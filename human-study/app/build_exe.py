"""진행 프로그램 Windows exe 빌드 (진행자 PC에 설치가 필요 없게 Chromium까지 넣는다).

저장소 루트에서, infra/README.md "W1 실행 환경"의 가상환경으로 실행한다:
    .venv\\Scripts\\python.exe human-study\\app\\build_exe.py
또는 human-study\\app\\build_exe.ps1

순서:
  1. npm run build:collect                     수집 번들을 최신 코드로
  2. python -m benchmark.serve_variants check  결함판·기준선 확인 (실패하면 멈춘다. 사이트를 다시 빌드하지 않는다)
  3. 내장 폴더 준비: 저장소와 같은 상대 경로로 기존 모듈·사이트 빌드 결과·manifest·check 결과를 복사하고
     복사한 사이트가 manifest 해시와 같은지 확인한다
  4. PyInstaller onedir (requirements-build.txt의 고정 버전)
  5. Playwright Chromium을 exe 폴더 안(playwright/driver/package/.local-browsers)에 넣는다
결과: dist\\StepMeter-human-<날짜-커밋7>\\StepMeter-human.exe 와 dist\\StepMeter-human-<버전>.zip
dist/, build/, *.zip은 git 제외다. 커밋하지 않는다.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parents[1]
BUILD = ROOT / "build" / "stepmeter-human"
DIST = ROOT / "dist"
NAME = "StepMeter-human"
FIRST_RUN = APP / "first_run.txt"
FIRST_RUN_NAME = "처음 실행할 때 읽기.txt"

# 기존 모듈은 고치지 않고 그대로 넣는다 (resources.py가 파일 경로로 불러온다)
REPO_FILES = [
    "human-study/session.py",
    "human-study/schema.py",
    "human-study/check_sessions.py",
    "human-study/collect.js",
    "human-study/session_plan.json",
    "worker/collect/dist/collect.js",
    "apps/api/openapi.yaml",
    "benchmark/serve_variants.py",
    "benchmark/mutate.py",
    "benchmark/variants.json",
    "benchmark/apps.json",
]
LOCAL_MODULES = {"benchmark", "schema", "session", "check_sessions", "upload"}


def version_string(when: datetime, commit: str) -> str:
    """버전 = 날짜 + 커밋 앞 7자리."""
    return f"{when:%Y%m%d}-{commit[:7]}"


def run(cmd: list[str], **kw: object) -> None:
    print("$", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)  # type: ignore[call-overload]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def _serve_variants():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from benchmark import serve_variants

    return serve_variants


def stage_resources(dest: Path, *, include_sites: bool = True) -> dict[str, str]:
    """dest에 저장소와 같은 상대 경로로 내장 파일을 둔다. 반환: 빌드별 결과 sha256."""
    if dest.exists():
        shutil.rmtree(dest)
    for rel in REPO_FILES:
        src = ROOT / rel
        if not src.is_file():
            raise SystemExit(f"{rel} 없음" + (" — 저장소 루트에서 npm run build:collect" if "collect/dist" in rel else ""))
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    sv = _serve_variants()
    config = sv.load_config()
    # load_config가 확인하는 패치 파일 (빌드 입력 해시 비교에도 쓴다). 패치를 적용하지는 않는다
    for b in config.builds:
        for _kind, rel, path in sv.patch_files(b):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest / rel)
    hashes: dict[str, str] = {}
    if not include_sites:
        return hashes
    builds = config.page_builds()
    problems = sv.stale_builds(config, builds)
    if problems:
        raise SystemExit("사이트 빌드가 없거나 최신이 아니다 (python -m benchmark.serve_variants build):\n  "
                         + "\n  ".join(problems))
    for b in builds:
        manifest = sv.read_json(b.manifest_path) or {}
        src_root = config.serve_root(b)
        rel_root = src_root.relative_to(ROOT)
        for rel, path in sv._visible_files(src_root):  # serve가 내보내는 파일만 (.git 등 숨김 경로 제외)
            target = dest / rel_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        rel_manifest = b.manifest_path.relative_to(ROOT)
        (dest / rel_manifest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b.manifest_path, dest / rel_manifest)
        got = sv.tree_digest(dest / rel_root)["sha256"]
        want = (manifest.get("output") or {}).get("sha256")
        if got != want:
            raise SystemExit(f"{b.id}: 복사한 사이트 해시 {got[:12]}가 manifest {str(want)[:12]}와 다르다")
        hashes[b.id] = got
    evidence = ROOT / "benchmark" / "evidence" / "variants-check.json"
    summary = json.loads(evidence.read_text(encoding="utf-8"))
    if not summary.get("ok"):
        raise SystemExit("serve_variants check 결과가 실패다")
    for bid, sha in hashes.items():
        if ((summary.get("builds", {}).get(bid) or {}).get("output") or {}).get("sha256") != sha:
            raise SystemExit(f"{bid}: check한 빌드와 넣을 빌드가 다르다. serve_variants check를 다시 하라")
    (dest / "benchmark" / "evidence").mkdir(parents=True, exist_ok=True)
    shutil.copy2(evidence, dest / "benchmark" / "evidence" / "variants-check.json")
    return hashes


def hidden_imports(dest: Path) -> list[str]:
    """내장한 .py가 import하는 바깥 모듈 (PyInstaller가 파일 경로로 불러오는 모듈은 분석하지 못한다)."""
    names: set[str] = set()
    for py in dest.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
    return sorted(n for n in names if n.split(".")[0] not in LOCAL_MODULES and n != "__future__")


def chromium_dirs() -> list[tuple[Path, str]]:
    """(설치된 Chromium 폴더, 내장 위치). 이 playwright 버전이 쓰는 리비전만 넣는다."""
    import playwright

    pkg = Path(playwright.__file__).parent / "driver" / "package"
    browsers = json.loads((pkg / "browsers.json").read_text(encoding="utf-8"))["browsers"]
    revs = {b["name"]: b["revision"] for b in browsers}
    wanted = [f"chromium-{revs['chromium']}"]
    if os.name == "nt" and "winldd" in revs:
        wanted.append(f"winldd-{revs['winldd']}")
    candidates = [Path(p) for p in (os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),) if p and p != "0"]
    candidates += [ROOT / ".venv" / "ms-playwright", Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"]
    out = []
    for name in wanted:
        for base in candidates:
            if (base / name / "INSTALLATION_COMPLETE").exists():
                out.append((base / name, f"playwright/driver/package/.local-browsers/{name}"))
                break
        else:
            raise SystemExit(f"{name} 없음. $env:PLAYWRIGHT_BROWSERS_PATH=\"$PWD\\.venv\\ms-playwright\" 후 "
                             "python -m playwright install chromium")
    return out


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-check", action="store_true", help="개발용: serve_variants check를 건너뛴다(직전 결과 사용)")
    args = parser.parse_args(argv)
    if os.name != "nt":
        raise SystemExit("exe 빌드는 Windows에서 한다. Mac은 run_mac.command(소스 방식)를 쓴다")

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise SystemExit("npm을 찾지 못했다 (Node 22)")
    run([npm, "run", "build:collect"])
    if not args.skip_check:
        run([sys.executable, "-m", "benchmark.serve_variants", "check"])
    run([sys.executable, "-m", "pip", "install", "-q", "-r", str(APP / "requirements-build.txt")])

    commit = git("rev-parse", "HEAD")
    bundled = (*REPO_FILES, "human-study/app/", "benchmark/baselines/", "benchmark/mutations/")
    dirty = [line[3:] for line in git("status", "--porcelain").splitlines() if line[3:].startswith(bundled)]
    if dirty:
        print("주의: 커밋하지 않은 변경이 exe에 들어간다: " + ", ".join(dirty), flush=True)
    version = version_string(datetime.now(), commit)
    res = BUILD / "res"
    hashes = stage_resources(res)
    (res / "app_build.json").write_text(json.dumps({
        "version": version, "commit": commit, "dirty_paths": dirty,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "site_manifest_hashes": hashes,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pyi_args = ["--noconfirm", "--clean", "--onedir", "--windowed", "--name", NAME,
                "--distpath", str(BUILD / "pyi-dist"), "--workpath", str(BUILD / "pyi-work"),
                "--specpath", str(BUILD / "pyi-spec"), "--paths", str(ROOT / "human-study"),
                "--add-data", f"{res}{os.pathsep}."]
    for src, target in chromium_dirs():
        pyi_args += ["--add-data", f"{src}{os.pathsep}{target}"]
    for mod in hidden_imports(res):
        pyi_args += ["--hidden-import", mod]
    pyi_args.append(str(APP / "__main__.py"))
    run([sys.executable, "-m", "PyInstaller", *pyi_args])

    out = DIST / f"{NAME}-{version}"
    if out.exists():
        shutil.rmtree(out)
    DIST.mkdir(exist_ok=True)
    shutil.move(str(BUILD / "pyi-dist" / NAME), out)
    shutil.copy2(FIRST_RUN, out / FIRST_RUN_NAME)
    zip_path = DIST / f"{NAME}-{version}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, Path(out.name) / f.relative_to(out))
    print(f"\nexe: {out / (NAME + '.exe')}")
    print(f"폴더 크기: {dir_size(out) / 2**20:.0f} MB, zip: {zip_path} {zip_path.stat().st_size / 2**20:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
