"""사람 실험·벤치마크 측정에 쓰는 결함판 빌드·실행 도구.

benchmark/variants.json의 (앱, 변이)마다 별도 폴더에 apps.json의 고정 커밋을 받고
기준선 패치 → 결함 패치(baseline이면 생략) → lockfile대로 설치 → 프로덕션 빌드를 한 뒤,
고정 포트의 정적 서버로 띄운다. 사람 실험(human-study/session.py --url)과 에이전트 측정이
같은 빌드와 같은 page_id → URL 표를 쓰게 하려는 것이다. 홀드아웃 앱은 다루지 않는다(ADR 0003).

    python -m benchmark.serve_variants build [<앱>/<변이> ...] [--force]   패치 해시가 같으면 건너뛴다
    python -m benchmark.serve_variants check     verify 스크립트로 결함판=결함 있음, 기준선=깨끗 확인
                                                 (purpose가 human-study-only인 변이는 builds[].check 값만 확인)
    python -m benchmark.serve_variants serve [<앱>/<변이> ...] [--all] [--foreground] [--host 0.0.0.0]
    python -m benchmark.serve_variants urls [--json]
    python -m benchmark.serve_variants stop

serve는 참가자 페이지가 있는 빌드만 띄운다(--all이면 check 전용 기준선까지). 백그라운드로 띄우고
바로 돌아오며, 끌 때는 stop을 쓴다. --foreground는 이 창에서 띄우고 Ctrl+C로 끈다.
--host 기본값은 127.0.0.1(이 PC에서만 열림)이다. 컨테이너·다른 기기에서 열어야 할 때만 0.0.0.0을 준다.

산출물은 모두 git 제외다(.gitignore의 benchmark/apps/*/, benchmark/evidence/).
    benchmark/apps/variants/<앱>/<변이>/                고정 커밋 + 패치 + 빌드 결과
    benchmark/apps/variants/<앱>/<변이>.manifest.json   앱·커밋·패치 sha256·빌드 시각·결과 해시
    benchmark/apps/variants/<앱>/<변이>.build.log       체크아웃·설치·빌드 출력
    benchmark/apps/variants/serve-state.json            지금 띄운 서버 (stop이 지운다)
    benchmark/apps/variants/serve-history.jsonl         언제 어떤 빌드(결과 해시)를 띄우고 내렸는지
    benchmark/evidence/variants-check.json              check 요약
    benchmark/evidence/<앱>/variants-check/             check의 verify·axe 결과와 스크린샷
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlsplit

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
CONFIG = BENCH / "variants.json"
APPS = BENCH / "apps.json"  # 공개 개발 앱만. benchmark/holdout/은 읽지 않는다
VARIANTS_ROOT = BENCH / "apps" / "variants"
STATE = VARIANTS_ROOT / "serve-state.json"
HISTORY = VARIANTS_ROOT / "serve-history.jsonl"
SERVE_LOG = VARIANTS_ROOT / "serve.log"
EVIDENCE = BENCH / "evidence"
CHECK_PHASE = "variants-check"

BASELINE = "baseline"
# 사람 실험 전용 변이: 정답(labels/)에 넣지 않으므로 check가 결함 발현 대신 builds[].check의 측정값만 본다
HUMAN_STUDY_ONLY = "human-study-only"
SIZE_TOLERANCE_PX = 0.5  # 소수점 레이아웃 오차
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NODE_SHIMS = {"npm", "npx", "pnpm", "corepack"}  # Windows에서는 .cmd 배치 파일이다
KEY_FIELDS = ("app", "variant", "repository", "revision", "patches", "recipe")  # 같으면 다시 빌드하지 않는다
# 결함판을 기준선과 같은 방법으로 재는 verify 스크립트 (selection.md "shadcn-admin 결함 변이")
VERIFY_MODULES = {"sb-admin-2": "benchmark.verify_sb_admin_2", "shadcn-admin": "benchmark.verify_shadcn_admin"}
# audit.py가 기준선 페이지 axe violations 0을 확인하는 앱 (selection.md "기존 결함 클리닝")
AUDIT_APPS = ("sb-admin-2", "material-kit-react")

# Windows 레지스트리에 따라 mimetypes가 .js를 text/plain으로 주면 모듈 스크립트가 막히므로 직접 정한다
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".map": "application/json",
    ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject", ".wasm": "application/wasm", ".mp4": "video/mp4", ".webm": "video/webm",
}


class ConfigError(Exception):
    """variants.json이 규칙에 맞지 않는다."""


class BuildError(Exception):
    """체크아웃·패치·설치·빌드 실패."""


class ServeError(Exception):
    """서버를 띄우지 못했다."""


# ---------------------------------------------------------------- 설정

@dataclass(frozen=True)
class Recipe:
    install: tuple[str, ...] | None
    build: tuple[str, ...] | None
    serve_root: str
    spa: bool

    def as_json(self) -> dict[str, Any]:
        return {"install": list(self.install) if self.install else None,
                "build": list(self.build) if self.build else None,
                "serve_root": self.serve_root, "spa": self.spa}


@dataclass(frozen=True)
class SizeCheck:
    """사람 실험 전용 변이의 check: verify 스크립트가 잰 size_px가 기준선→결함판에서 이 값이어야 한다."""
    baseline: float
    variant: float

    def passes(self, baseline_px: float | None, variant_px: float | None) -> bool:
        return (baseline_px is not None and variant_px is not None
                and abs(baseline_px - self.baseline) <= SIZE_TOLERANCE_PX
                and abs(variant_px - self.variant) <= SIZE_TOLERANCE_PX)


@dataclass(frozen=True)
class Build:
    app: str
    variant: str
    port: int
    purpose: str | None = None
    size_check: SizeCheck | None = None

    @property
    def id(self) -> str:
        return f"{self.app}/{self.variant}"

    @property
    def checkout(self) -> Path:
        return VARIANTS_ROOT / self.app / self.variant

    @property
    def manifest_path(self) -> Path:
        return VARIANTS_ROOT / self.app / f"{self.variant}.manifest.json"

    @property
    def log_path(self) -> Path:
        return VARIANTS_ROOT / self.app / f"{self.variant}.build.log"


@dataclass(frozen=True)
class Page:
    page_id: str  # <앱 id>/<페이지>/<변이> (human-study/pages.md)
    path: str

    @property
    def build_id(self) -> str:
        app, _, variant = self.page_id.split("/")
        return f"{app}/{variant}"


@dataclass(frozen=True)
class Config:
    host: str
    recipes: dict[str, Recipe]
    builds: tuple[Build, ...]
    pages: tuple[Page, ...]
    apps: dict[str, dict[str, Any]]

    def build(self, build_id: str) -> Build:
        for b in self.builds:
            if b.id == build_id:
                return b
        raise ConfigError(f"variants.json에 없는 빌드: {build_id}")

    def serve_root(self, build: Build) -> Path:
        return build.checkout / self.recipes[build.app].serve_root

    def pages_of(self, build: Build) -> list[Page]:
        return [p for p in self.pages if p.build_id == build.id]

    def page_builds(self) -> list[Build]:
        """참가자 페이지가 있는 빌드 (serve 기본값)."""
        used = {p.build_id for p in self.pages}
        return [b for b in self.builds if b.id in used]

    def url(self, page: Page, host: str | None = None) -> str:
        return f"http://{host or self.host}:{self.build(page.build_id).port}{page.path}"

    def url_for(self, page_id: str, host: str | None = None) -> str:
        """에이전트 측정용: page_id → 사람 실험과 같은 URL."""
        for p in self.pages:
            if p.page_id == page_id:
                return self.url(p, host)
        raise ConfigError(f"variants.json에 없는 page_id: {page_id}")


def load_apps(path: Path = APPS) -> dict[str, dict[str, Any]]:
    """apps.json의 개발 앱. 홀드아웃 항목은 이 파일에 없고, 있어도 받지 않는다."""
    apps = json.loads(path.read_text(encoding="utf-8"))["apps"]
    return {a["id"]: a for a in apps if a.get("split") == "development"}


def _safe_relative(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return not path.startswith(("/", "\\")) and ":" not in path and ".." not in parts


def _command_ok(value: Any) -> bool:
    return value is None or (isinstance(value, list) and bool(value) and all(isinstance(x, str) and x for x in value))


def _size_check_ok(value: Any) -> bool:
    def number(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0

    return (isinstance(value, dict) and value.get("measure") == "size_px"
            and number(value.get("baseline")) and number(value.get("variant"))
            and value["variant"] < value["baseline"])


def validate(raw: dict[str, Any], apps: dict[str, dict[str, Any]], bench: Path = BENCH) -> list[str]:
    """variants.json 검사. 오류 문장 목록을 돌려준다 (비면 통과)."""
    errors: list[str] = []
    if raw.get("version") != 1:
        errors.append("version은 1이어야 한다")
    if not isinstance(raw.get("host"), str) or not raw["host"]:
        errors.append("host가 없다")

    recipes = raw.get("recipes")
    if not isinstance(recipes, dict) or not recipes:
        errors.append("recipes가 없다")
        recipes = {}
    for app, r in recipes.items():
        where = f"recipes.{app}"
        if app not in apps:
            errors.append(f"{where}: benchmark/apps.json의 개발 앱이 아니다")
        if not isinstance(r, dict):
            errors.append(f"{where}: 객체여야 한다")
            continue
        for step in ("install", "build"):
            if not _command_ok(r.get(step)):
                errors.append(f"{where}.{step}: null 또는 비지 않은 문자열 목록이어야 한다")
        if not isinstance(r.get("serve_root"), str) or not _safe_relative(r["serve_root"]):
            errors.append(f"{where}.serve_root: 체크아웃 안의 상대 경로여야 한다")
        if not isinstance(r.get("spa"), bool):
            errors.append(f"{where}.spa: true/false여야 한다")
        if not (bench / "baselines" / f"{app}.patch").is_file():
            errors.append(f"{where}: 기준선 패치 benchmark/baselines/{app}.patch가 없다")

    builds = raw.get("builds")
    if not isinstance(builds, list) or not builds:
        errors.append("builds가 없다")
        builds = []
    build_ids: set[str] = set()
    ports: dict[int, str] = {}
    for i, b in enumerate(builds):
        where = f"builds[{i}]"
        if not isinstance(b, dict):
            errors.append(f"{where}: 객체여야 한다")
            continue
        app, variant, port = b.get("app"), b.get("variant"), b.get("port")
        build_id = f"{app}/{variant}"
        if app not in recipes:
            errors.append(f"{where}: recipes에 없는 앱 {app!r}")
        if not isinstance(variant, str) or not NAME.match(variant):
            errors.append(f"{where}: variant {variant!r}는 소문자·숫자·하이픈이어야 한다")
        elif variant != BASELINE and not (bench / "mutations" / str(app) / f"{variant}.patch").is_file():
            errors.append(f"{where}: 결함 패치 benchmark/mutations/{app}/{variant}.patch가 없다")
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            errors.append(f"{where}: port {port!r}는 1024~65535 정수여야 한다")
        elif port in ports:
            errors.append(f"{where}: 포트 {port}가 {ports[port]}와 겹친다")
        else:
            ports[port] = build_id
        if build_id in build_ids:
            errors.append(f"{where}: {build_id} 빌드가 두 번 있다")
        build_ids.add(build_id)
        purpose, check = b.get("purpose"), b.get("check")
        if purpose not in (None, HUMAN_STUDY_ONLY):
            errors.append(f"{where}: purpose {purpose!r}는 없거나 {HUMAN_STUDY_ONLY!r}여야 한다")
        elif purpose == HUMAN_STUDY_ONLY:
            if variant == BASELINE:
                errors.append(f"{where}: 기준선은 {HUMAN_STUDY_ONLY}일 수 없다")
            if not _size_check_ok(check):
                errors.append(f'{where}.check: {{"measure": "size_px", "baseline": 숫자, "variant": 더 작은 숫자}}가 필요하다')
        elif check is not None:
            errors.append(f"{where}.check: purpose가 {HUMAN_STUDY_ONLY}인 빌드에만 쓴다")

    pages = raw.get("pages")
    if not isinstance(pages, list) or not pages:
        errors.append("pages가 없다")
        pages = []
    page_ids: set[str] = set()
    for i, p in enumerate(pages):
        where = f"pages[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{where}: 객체여야 한다")
            continue
        page_id, path = p.get("page_id"), p.get("path")
        parts = page_id.split("/") if isinstance(page_id, str) else []
        if len(parts) != 3 or not all(NAME.match(x) for x in parts):
            errors.append(f"{where}: page_id {page_id!r}는 '<앱 id>/<페이지>/<변이>' 형식이어야 한다")
        elif f"{parts[0]}/{parts[2]}" not in build_ids:
            errors.append(f"{where}: {page_id}를 띄울 빌드 {parts[0]}/{parts[2]}가 builds에 없다")
        if page_id in page_ids:
            errors.append(f"{where}: page_id {page_id}가 두 번 있다")
        page_ids.add(str(page_id))
        if not isinstance(path, str) or not path.startswith("/") or not _safe_relative(path.lstrip("/")):
            errors.append(f"{where}: path {path!r}는 '/'로 시작하는 서버 안 경로여야 한다")
    return errors


def load_config(path: Path = CONFIG, apps_path: Path = APPS) -> Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    apps = load_apps(apps_path)
    errors = validate(raw, apps)
    if errors:
        raise ConfigError("variants.json 오류:\n  " + "\n  ".join(errors))
    recipes = {
        app: Recipe(install=tuple(r["install"]) if r["install"] else None,
                    build=tuple(r["build"]) if r["build"] else None,
                    serve_root=r["serve_root"], spa=r["spa"])
        for app, r in raw["recipes"].items()
    }
    return Config(
        host=raw["host"], recipes=recipes,
        builds=tuple(Build(b["app"], b["variant"], b["port"], purpose=b.get("purpose"),
                           size_check=SizeCheck(b["check"]["baseline"], b["check"]["variant"]) if b.get("check") else None)
                     for b in raw["builds"]),
        pages=tuple(Page(p["page_id"], p["path"]) for p in raw["pages"]),
        apps={app: apps[app] for app in recipes},
    )


def select_builds(config: Config, ids: Iterable[str], default: list[Build]) -> list[Build]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return default
    known = {b.id: b for b in config.builds}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ConfigError(f"variants.json에 없는 빌드: {', '.join(unknown)} (있는 것: {', '.join(known)})")
    return [known[i] for i in ids]


def page_table(config: Config, host: str | None = None) -> list[dict[str, Any]]:
    """page_id → URL 표. 사람 실험(session.py --url)과 에이전트 측정이 같은 표를 쓴다."""
    return [{"page_id": p.page_id, "url": config.url(p, host), "build": p.build_id,
             "port": config.build(p.build_id).port} for p in config.pages]


def parse_host(value: str) -> str:
    """serve --host: 서버를 띄울 IPv4 주소."""
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        raise argparse.ArgumentTypeError(f"IPv4 주소여야 한다 (예: 127.0.0.1, 0.0.0.0): {value!r}") from None


def url_host(bind: str) -> str:
    """접속 주소. 모든 인터페이스(0.0.0.0)에 띄우면 이 PC에서는 127.0.0.1로 연다."""
    return "127.0.0.1" if bind == "0.0.0.0" else bind


# ---------------------------------------------------------------- 해시·재빌드 판단

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _visible_files(root: Path) -> list[tuple[str, Path]]:
    """서버가 내보낼 수 있는 파일. 숨김 경로(.git 등)는 serve하지 않으므로 뺀다."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.startswith("."):
                path = Path(dirpath) / name
                found.append((path.relative_to(root).as_posix(), path))
    return sorted(found)


def tree_digest(root: Path) -> dict[str, Any]:
    """빌드 결과 전체의 해시: 정렬한 '상대 경로 NUL 파일 sha256 줄바꿈'들의 sha256."""
    h = hashlib.sha256()
    files = _visible_files(root)
    for rel, path in files:
        h.update(f"{rel}\0{sha256_file(path)}\n".encode("utf-8"))
    return {"sha256": h.hexdigest(), "files": len(files)}


def patch_files(build: Build, bench: Path = BENCH) -> list[tuple[str, str, Path]]:
    """(종류, 저장소 기준 경로, 실제 파일). 기준선 다음에 결함 패치를 적용한다."""
    items = [("baseline", f"benchmark/baselines/{build.app}.patch", bench / "baselines" / f"{build.app}.patch")]
    if build.variant != BASELINE:
        items.append(("mutation", f"benchmark/mutations/{build.app}/{build.variant}.patch",
                      bench / "mutations" / build.app / f"{build.variant}.patch"))
    return items


def source_key(app: dict[str, Any], recipe: Recipe, build: Build, bench: Path = BENCH) -> dict[str, Any]:
    """빌드 결과를 정하는 입력. manifest에 그대로 들어가고, 같으면 다시 빌드하지 않는다."""
    return {
        "app": build.app, "variant": build.variant,
        "repository": app["repository"], "revision": app["revision"],
        "patches": [{"kind": kind, "path": rel, "sha256": sha256_file(path)}
                    for kind, rel, path in patch_files(build, bench)],
        "recipe": recipe.as_json(),
    }


def rebuild_reason(manifest: dict[str, Any] | None, key: dict[str, Any], output_sha256: str | None,
                   *, force: bool = False) -> str | None:
    """다시 빌드해야 하는 이유. None이면 지금 빌드를 그대로 쓴다."""
    if force:
        return "--force"
    if manifest is None:
        return "manifest 없음"
    if manifest.get("patches") != key["patches"]:
        old = {p.get("path"): p.get("sha256") for p in manifest.get("patches") or []}
        changed = [p["path"] for p in key["patches"] if old.get(p["path"]) != p["sha256"]]
        return "패치 해시가 바뀜: " + ", ".join(changed or ["패치 목록"])
    for field in KEY_FIELDS:
        if manifest.get(field) != key[field]:
            return {"revision": "고정 커밋이 바뀜", "recipe": "설치·빌드 방법이 바뀜"}.get(field, f"{field}가 바뀜")
    if output_sha256 is None:
        return "빌드 결과 없음"
    if output_sha256 != (manifest.get("output") or {}).get("sha256"):
        return "빌드 결과가 manifest의 해시와 다름 (빌드 뒤 파일이 바뀜)"
    return None


def build_status(config: Config, build: Build) -> tuple[str | None, dict[str, Any] | None]:
    """(다시 빌드할 이유 또는 None, 현재 manifest)."""
    key = source_key(config.apps[build.app], config.recipes[build.app], build)
    manifest = read_json(build.manifest_path)
    root = config.serve_root(build)
    digest = tree_digest(root)["sha256"] if root.is_dir() else None
    return rebuild_reason(manifest, key, digest), manifest


def stale_builds(config: Config, builds: Iterable[Build]) -> list[str]:
    problems = []
    for b in builds:
        reason, _ = build_status(config, b)
        if reason:
            problems.append(f"{b.id}: {reason}")
    return problems


# ---------------------------------------------------------------- 빌드

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def resolve_command(cmd: Iterable[str], *, os_name: str = os.name,
                    which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """명령 목록의 실행 파일을 전체 경로로 바꾼다. Windows의 npm·npx는 npm.cmd·npx.cmd다."""
    exe, *args = list(cmd)
    if os_name == "nt" and exe in NODE_SHIMS:
        exe += ".cmd"
    found = which(exe)
    if found is None:
        raise BuildError(f"{exe}를 PATH에서 찾지 못했다")
    return [found, *args]


def _capture(cmd: list[str], cwd: Path | None = None) -> str:
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, check=True, stdin=subprocess.DEVNULL)
    return out.stdout.decode("utf-8", errors="replace").strip()


def _run(cmd: list[str], logf: Any, cwd: Path | None = None) -> None:
    logf.write(f"\n$ {subprocess.list2cmdline(cmd)}\n".encode("utf-8"))
    logf.flush()
    proc = subprocess.run(cmd, cwd=cwd, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise BuildError(f"종료 코드 {proc.returncode}: {subprocess.list2cmdline(cmd)}")


def _tail(path: Path, lines: int = 30) -> str:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _remove_tree(path: Path) -> None:
    """이전 빌드 폴더를 지운다. benchmark/apps/variants/ 밖은 지우지 않는다."""
    if not path.exists():
        return
    base = VARIANTS_ROOT.resolve()
    target = path.resolve()
    if target == base or not target.is_relative_to(base):
        raise BuildError(f"{path}는 {VARIANTS_ROOT} 안이 아니라 지우지 않는다")

    def onexc(func: Callable[[str], Any], p: str, _exc: BaseException) -> None:
        os.chmod(p, stat.S_IWRITE)  # git pack 파일 등 읽기 전용 파일 (Windows)
        func(p)

    shutil.rmtree(target, onexc=onexc)


def tool_versions() -> dict[str, str | None]:
    found: dict[str, str | None] = {"python": platform.python_version(), "os": platform.platform()}
    for name, cmd in (("git", ["git", "--version"]), ("node", ["node", "--version"]), ("npm", ["npm", "--version"])):
        try:
            found[name] = _capture(resolve_command(cmd))
        except (BuildError, OSError, subprocess.CalledProcessError):
            found[name] = None
    return found


def _stepmeter_commit() -> str | None:
    try:
        return _capture(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    except (OSError, subprocess.CalledProcessError):
        return None


def _node_warning(versions: dict[str, str | None]) -> str | None:
    nvmrc = ROOT / ".nvmrc"
    node = versions.get("node")
    if not node or not nvmrc.is_file():
        return None
    want = nvmrc.read_text(encoding="utf-8").strip().lstrip("v").split(".")[0]
    have = node.lstrip("v").split(".")[0]
    return None if want == have else f"Node {node}로 빌드한다 (.nvmrc는 {want}). manifest에 기록한다"


def _served_build_ids() -> set[str]:
    state = read_json(STATE)
    if not state or not _live_ports(state):
        return set()
    return {s.get("id") for s in state.get("servers", [])}


def build_one(config: Config, build: Build, *, force: bool = False) -> bool:
    """빌드 하나. 다시 빌드했으면 True, 최신이라 건너뛰었으면 False."""
    recipe, app = config.recipes[build.app], config.apps[build.app]
    key = source_key(app, recipe, build)
    root = config.serve_root(build)
    manifest = read_json(build.manifest_path)
    digest = tree_digest(root)["sha256"] if root.is_dir() else None
    reason = rebuild_reason(manifest, key, digest, force=force)
    if reason is None:
        print(f"{build.id}: 최신이라 건너뜀 (패치 해시 같음, 결과 {digest[:12]})")
        return False
    if build.id in _served_build_ids():
        raise ServeError(f"{build.id}: serve 중이라 다시 빌드하지 않는다. 먼저 python -m benchmark.serve_variants stop")
    print(f"{build.id}: 빌드 ({reason})", flush=True)
    _remove_tree(build.checkout)
    build.manifest_path.unlink(missing_ok=True)
    build.checkout.mkdir(parents=True)
    git = [*resolve_command(["git"]), "-C", str(build.checkout)]
    with build.log_path.open("wb") as logf:
        print(f"  체크아웃 {app['repository']} @ {app['revision'][:12]}", flush=True)
        _run([*git, "init", "-q"], logf)
        # 줄바꿈을 원본 그대로 둔다. autocrlf가 켜진 Windows에서도 결과 해시가 다른 PC와 같게 나온다
        _run([*git, "config", "core.autocrlf", "false"], logf)
        _run([*git, "remote", "add", "origin", app["repository"] + ".git"], logf)
        _run([*git, "fetch", "-q", "--depth", "1", "origin", app["revision"]], logf)
        _run([*git, "checkout", "-q", "--detach", "FETCH_HEAD"], logf)
        head = _capture([*git, "rev-parse", "HEAD"])
        if head != app["revision"]:
            raise BuildError(f"받은 커밋 {head}가 apps.json의 {app['revision']}와 다르다")
        for _kind, rel, path in patch_files(build):
            print(f"  패치 {rel}", flush=True)
            _run([*git, "apply", "--check", str(path)], logf)
            _run([*git, "apply", str(path)], logf)
        for label, step in (("설치", recipe.install), ("빌드", recipe.build)):
            if step:
                print(f"  {label}: {' '.join(step)}", flush=True)
                _run(resolve_command(step), logf, cwd=build.checkout)
    if not root.is_dir():
        raise BuildError(f"빌드 결과 폴더 {root}가 없다 (recipes.{build.app}.serve_root 확인)")
    for page in config.pages_of(build):
        if resolve_path(root, page.path, recipe.spa) is None:
            raise BuildError(f"{page.page_id}의 시작 경로 {page.path}에 해당하는 파일이 빌드 결과에 없다")
    versions = tool_versions()
    warning = _node_warning(versions) if (recipe.install or recipe.build) else None
    if warning:
        print(f"  주의: {warning}")
    output = tree_digest(root)
    write_json(build.manifest_path, {
        "schema": "stepmeter-variant-build/1",
        "id": build.id,
        **key,
        "built_at": now_iso(),
        "output": {"root": root.relative_to(ROOT).as_posix(), **output},
        "tools": versions,
        "stepmeter_commit": _stepmeter_commit(),
    })
    print(f"  완료: 결과 sha256 {output['sha256'][:12]} ({output['files']}개 파일), "
          f"{build.manifest_path.relative_to(ROOT).as_posix()}", flush=True)
    return True


def cmd_build(config: Config, ids: list[str], force: bool) -> int:
    builds = select_builds(config, ids, list(config.builds))
    failed = []
    for b in builds:
        try:
            build_one(config, b, force=force)
        except ServeError as e:
            failed.append(b.id)
            print(e, file=sys.stderr)
        except BuildError as e:
            failed.append(b.id)
            print(f"{b.id}: 실패: {e}", file=sys.stderr)
            tail = _tail(b.log_path)
            if tail:
                print(f"--- {b.log_path.relative_to(ROOT).as_posix()} 끝부분 ---\n{tail}", file=sys.stderr)
    if failed:
        print(f"실패한 빌드: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- 정적 서버

def resolve_path(root: Path, url_path: str, spa: bool) -> Path | None:
    """요청 경로 → 내보낼 파일. 숨김·상위 경로는 막고, SPA는 확장자 없는 경로에 index.html을 준다."""
    path = unquote(urlsplit(url_path).path)
    parts = [p for p in path.split("/") if p]
    if any(p.startswith(".") or "\\" in p or ":" in p or "\0" in p for p in parts):
        return None
    base = root.resolve()
    target = base.joinpath(*parts)
    if target.is_dir():
        target = target / "index.html"
    if target.is_file() and target.resolve().is_relative_to(base):
        return target
    if spa and not (parts and "." in parts[-1]):
        index = base / "index.html"
        return index if index.is_file() else None
    return None


def content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def make_handler(root: Path, spa: bool, *, log_requests: bool = True) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "StepMeterVariants/1"

        def do_GET(self) -> None:
            self._send(body=True)

        def do_HEAD(self) -> None:
            self._send(body=False)

        def _send(self, body: bool) -> None:
            target = resolve_path(root, self.path, spa)
            if target is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = target.read_bytes()
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type(target))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if body:
                    self.wfile.write(data)
            except ConnectionError:
                pass  # 브라우저가 먼저 끊음

        def log_request(self, code: Any = "-", size: Any = "-") -> None:
            # 쿼리 문자열은 남기지 않는다. 폼이 GET으로 제출되면 입력값이 붙을 수 있다(동의서 4절)
            if log_requests:
                port = self.server.server_address[1]
                sys.stderr.write(f"{now_iso()} :{port} {self.command} {urlsplit(self.path).path} {code}\n")

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # 오류 응답도 log_request가 경로·코드로 남긴다

    return Handler


class StaticServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows의 SO_REUSEADDR는 다른 프로세스가 쓰는 포트에도 bind를 허락하므로 끄고 독점 bind한다
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind의 getfqdn()은 Windows에서 몇 초 걸릴 수 있어 건너뛴다
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), int(self.server_address[1])


@dataclass
class Running:
    build: Build
    server: StaticServer

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])


def start_servers(config: Config, builds: Iterable[Build], host: str, *, ephemeral: bool = False) -> list[Running]:
    """빌드마다 스레드 하나로 정적 서버를 띄운다. ephemeral이면 빈 포트에 요청 기록 없이(check용)."""
    running: list[Running] = []
    for b in builds:
        port = 0 if ephemeral else b.port
        handler = make_handler(config.serve_root(b), config.recipes[b.app].spa, log_requests=not ephemeral)
        try:
            server = StaticServer((host, port), handler)
        except OSError as e:
            stop_servers(running)
            raise ServeError(f"{b.id}: {host}:{port}에 서버를 띄우지 못했다 ({e})") from e
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name=b.id).start()
        running.append(Running(b, server))
    return running


def stop_servers(running: Iterable[Running]) -> None:
    for r in running:
        r.server.shutdown()
        r.server.server_close()


def port_in_use(host: str, port: int, timeout: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _live_ports(state: dict[str, Any]) -> list[int]:
    host = state.get("host", "127.0.0.1")
    return [s["port"] for s in state.get("servers", []) if port_in_use(host, s["port"])]


def _state_token() -> str | None:
    state = read_json(STATE)
    return state.get("token") if state else None


def _append_history(event: dict[str, Any]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _unlink_retry(path: Path, tries: int = 20) -> None:
    for _ in range(tries):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:  # Windows: serve 프로세스가 마침 읽는 중
            time.sleep(0.1)
    path.unlink(missing_ok=True)


def host_loop(config: Config, builds: list[Build], token: str, bind: str) -> int:
    """서버를 띄우고 serve-state.json이 사라질 때(stop)나 Ctrl+C까지 기다린다."""
    try:
        running = start_servers(config, builds, bind)
    except ServeError as e:
        print(e, file=sys.stderr, flush=True)
        return 1
    host = url_host(bind)
    manifests = {b.id: read_json(b.manifest_path) or {} for b in builds}
    servers = [{
        "id": b.id, "port": b.port, "url": f"http://{host}:{b.port}/",
        "revision": manifests[b.id].get("revision"), "patches": manifests[b.id].get("patches"),
        "built_at": manifests[b.id].get("built_at"), "output": manifests[b.id].get("output"),
    } for b in builds]
    served = {b.id for b in builds}
    pages = [row for row in page_table(config, host) if row["build"] in served]
    started = now_iso()
    write_json(STATE, {"pid": os.getpid(), "token": token, "host": host, "bind": bind, "started_at": started,
                       "servers": servers, "pages": pages})
    _append_history({"event": "start", "at": started, "pid": os.getpid(), "bind": bind, "servers": servers})
    print(f"{started} serve 시작 pid {os.getpid()}: " + ", ".join(f"{b.id}:{b.port}" for b in builds), flush=True)
    try:
        while _state_token() == token:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_servers(running)
        if _state_token() == token:
            _unlink_retry(STATE)
        _append_history({"event": "stop", "at": now_iso(), "pid": os.getpid()})
        print(f"{now_iso()} serve 끝", flush=True)
    return 0


def probe(url: str, timeout: float = 5.0) -> int | str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 프록시 설정을 타지 않게
    try:
        with opener.open(url, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except (urllib.error.URLError, OSError) as e:
        return f"오류 {e}"


def _print_rows(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


def print_tables(config: Config, builds: list[Build], status: dict[str, int | str] | None = None,
                 host: str | None = None) -> None:
    served = {b.id for b in builds}
    rows = [["page_id", "URL", "build"] + (["status"] if status is not None else [])]
    for row in page_table(config, host):
        if row["build"] in served:
            rows.append([row["page_id"], row["url"], row["build"]]
                        + ([str(status.get(row["page_id"]))] if status is not None else []))
    _print_rows(rows)
    print()
    rows = [["build", "port", "built_at", "output sha256"]]
    for b in builds:
        m = read_json(b.manifest_path) or {}
        rows.append([b.id, str(b.port), str(m.get("built_at")), str((m.get("output") or {}).get("sha256", ""))[:16]])
    _print_rows(rows)


def cmd_serve(config: Config, ids: list[str], *, all_builds: bool, foreground: bool, bind: str | None = None) -> int:
    builds = select_builds(config, ids, list(config.builds) if all_builds else config.page_builds())
    bind = bind or config.host
    host = url_host(bind)
    problems = stale_builds(config, builds)
    if problems:
        print("빌드가 없거나 최신이 아니다:\n  " + "\n  ".join(problems), file=sys.stderr)
        print("먼저: python -m benchmark.serve_variants build", file=sys.stderr)
        return 1
    state = read_json(STATE)
    if state and _live_ports(state):
        print(f"이미 serve 중이다 (pid {state.get('pid')}, {state.get('started_at')}). "
              "먼저 python -m benchmark.serve_variants stop", file=sys.stderr)
        return 1
    STATE.unlink(missing_ok=True)  # 정리 없이 끝난 지난 serve의 흔적
    busy = [f"{b.id}:{b.port}" for b in builds if port_in_use(host, b.port)]
    if busy:
        print(f"포트를 이미 다른 프로그램이 쓰고 있다: {', '.join(busy)}", file=sys.stderr)
        return 1
    if bind == "0.0.0.0":
        print("주의: 모든 네트워크 주소에 띄운다. 같은 네트워크의 다른 기기에서도 열리고, "
              "Windows 방화벽이 허용 여부를 물을 수 있다.", flush=True)
    token = secrets.token_hex(8)
    if foreground:
        print_tables(config, builds, host=host)
        print("\nCtrl+C로 끈다.", flush=True)
        return host_loop(config, builds, token, bind)

    VARIANTS_ROOT.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with SERVE_LOG.open("ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "benchmark.serve_variants", "_host", "--token", token, "--host", bind,
             *[b.id for b in builds]],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kwargs)
    deadline = time.monotonic() + 30
    while _state_token() != token:
        if proc.poll() is not None or time.monotonic() > deadline:
            print("serve 프로세스가 서버를 띄우지 못했다:", file=sys.stderr)
            print(_tail(SERVE_LOG, 15), file=sys.stderr)
            return 1
        time.sleep(0.2)
    served = {b.id for b in builds}
    status = {row["page_id"]: probe(row["url"]) for row in page_table(config, host) if row["build"] in served}
    pid = (read_json(STATE) or {}).get("pid", proc.pid)  # Windows venv의 python.exe는 실제 인터프리터를 자식으로 띄운다
    print(f"serve 중 (pid {pid}, 주소 {bind}, 로그 {SERVE_LOG.relative_to(ROOT).as_posix()})\n")
    print_tables(config, builds, status, host=host)
    print("\n끄기: python -m benchmark.serve_variants stop")
    if any(code != 200 for code in status.values()):
        print("200이 아닌 주소가 있다. 위 표와 serve.log를 확인한다.", file=sys.stderr)
        return 1
    return 0


def cmd_stop() -> int:
    state = read_json(STATE)
    if state is None:
        print("띄운 서버가 없다.")
        return 0
    host = state.get("host", "127.0.0.1")
    ports = [s["port"] for s in state.get("servers", [])]
    _unlink_retry(STATE)  # serve 프로세스는 이 파일이 사라지면 서버를 닫고 끝난다
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and any(port_in_use(host, p) for p in ports):
        time.sleep(0.2)
    still = [p for p in ports if port_in_use(host, p)]
    if still:
        kill = f"taskkill /PID {state.get('pid')} /F" if os.name == "nt" else f"kill {state.get('pid')}"
        print(f"포트 {still}가 아직 열려 있다. serve 프로세스가 맞는지 확인하고 직접 끝낸다: {kill}", file=sys.stderr)
        return 1
    print(f"정리함: pid {state.get('pid')}, 포트 {', '.join(map(str, ports))}")
    return 0


def cmd_urls(config: Config, as_json: bool) -> int:
    if as_json:
        print(json.dumps(page_table(config), ensure_ascii=False, indent=2))
    else:
        print_tables(config, config.page_builds())
    return 0


# ---------------------------------------------------------------- check

async def run_checks(config: Config, urls: dict[str, str]) -> list[dict[str, Any]]:
    """verify 스크립트(결함판=결함 있음, 기준선=결함 없음)와 audit.py(기준선 axe violations 0)."""
    results: list[dict[str, Any]] = []
    for app, module_name in VERIFY_MODULES.items():
        variants = [b for b in config.builds if b.app == app and b.variant != BASELINE]
        if not variants:
            continue
        baseline = urls.get(f"{app}/{BASELINE}")
        module = importlib.import_module(module_name)
        for b in variants:
            if b.variant not in module.CASES:
                results.append({"check": f"{b.id} 결함 발현", "ok": False,
                                "detail": f"{module_name}에 이 변이 측정이 없다"})
        variants = [b for b in variants if b.variant in module.CASES]
        if baseline is None:
            for b in variants:
                results.append({"check": f"{b.id} 결함 발현", "ok": False, "detail": f"{app}/baseline 빌드가 없다"})
            continue
        if not variants:
            continue
        # 수동 verify 결과(evidence/<앱>/verification.json)를 덮어쓰지 않게 출력 폴더만 바꾼다
        module.OUTPUT = EVIDENCE / app / CHECK_PHASE
        report = await module.verify(baseline, {b.variant: urls[b.id] for b in variants})
        for b in variants:
            case = report["cases"][b.variant]
            errors = case["baseline"]["page_errors"] + case["variant"]["page_errors"]
            if b.size_check:  # 사람 실험 전용: 결함 판정(defect) 대신 누름 영역 크기만 본다
                before, after = case["baseline"].get("size_px"), case["variant"].get("size_px")
                name, ok = f"{b.id} 누름 영역 축소", b.size_check.passes(before, after)
                detail = (f"사람 실험 전용(R01 정답 아님) 누름 영역 {before}→{after}px "
                          f"(기대 {b.size_check.baseline:g}→{b.size_check.variant:g}px)")
            else:
                name, ok = f"{b.id} 결함 발현", bool(case["manifested"])
                detail = (f"{case['rule']} 결함판 defect={case['variant']['defect']}, "
                          f"기준선 defect={case['baseline']['defect']}")
            if errors:
                detail += f", 페이지 오류 {len(errors)}건: {errors[0][:120]}"
            results.append({"check": name, "ok": ok and not errors, "detail": detail})
    audit = importlib.import_module("benchmark.audit")
    for app in AUDIT_APPS:
        bid = f"{app}/{BASELINE}"
        if bid not in urls:
            continue
        out = EVIDENCE / app / CHECK_PHASE / "axe"
        for old in out.glob("*.json"):
            old.unlink()
        try:
            await audit.audit(app, urls[bid], f"{CHECK_PHASE}/axe")
        except Exception as e:  # 페이지 로드 실패(RuntimeError)·브라우저 오류도 check 실패로 보고한다
            results.append({"check": f"{bid} axe", "ok": False, "detail": f"audit.py 실패: {e}"})
            continue
        for path in sorted(out.glob("*.json")):
            violations = sorted(v["id"] for v in json.loads(path.read_text(encoding="utf-8"))["violations"])
            results.append({"check": f"{bid} axe {path.name.removesuffix('.json')}", "ok": not violations,
                            "detail": "violations 0" if not violations else "violations: " + ", ".join(violations)})
    return results


def cmd_check(config: Config) -> int:
    builds = list(config.builds)
    problems = stale_builds(config, builds)
    if problems:
        print("빌드가 없거나 최신이 아니다:\n  " + "\n  ".join(problems), file=sys.stderr)
        print("먼저: python -m benchmark.serve_variants build", file=sys.stderr)
        return 1
    # serve 중인 고정 포트와 겹치지 않게 빈 포트에 같은 빌드 폴더를 띄워 잰다
    running = start_servers(config, builds, config.host, ephemeral=True)
    urls = {r.build.id: f"http://{config.host}:{r.port}" for r in running}
    try:
        results = asyncio.run(run_checks(config, urls))
    finally:
        stop_servers(running)
    ok = bool(results) and all(r["ok"] for r in results)
    summary = {
        "checked_at": now_iso(), "ok": ok,
        "builds": {b.id: {k: (read_json(b.manifest_path) or {}).get(k) for k in ("revision", "patches", "built_at", "output")}
                   for b in builds},
        "results": results,
    }
    write_json(EVIDENCE / "variants-check.json", summary)
    print()
    _print_rows([["check", "result", "detail"]]
                + [[r["check"], "pass" if r["ok"] else "FAIL", r["detail"]] for r in results])
    print(f"\n요약: {EVIDENCE.relative_to(ROOT).as_posix()}/variants-check.json", flush=True)
    if not ok:
        print("실패한 검사가 있다.", file=sys.stderr)
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")  # cp949 콘솔에서 출력 때문에 죽지 않게
    parser = argparse.ArgumentParser(prog="python -m benchmark.serve_variants", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, metavar="{build,check,serve,urls,stop}")
    p = sub.add_parser("build", help="고정 커밋 + 패치 + 설치 + 프로덕션 빌드 (패치 해시가 같으면 건너뜀)")
    p.add_argument("ids", nargs="*", metavar="앱/변이", help="기본: variants.json의 빌드 전부")
    p.add_argument("--force", action="store_true", help="해시가 같아도 다시 빌드")
    sub.add_parser("check", help="verify 스크립트로 결함판·기준선 확인. 실패하면 종료 코드 1")
    p = sub.add_parser("serve", help="고정 포트에 띄우고 page_id별 URL 표 출력")
    p.add_argument("ids", nargs="*", metavar="앱/변이", help="기본: 참가자 페이지가 있는 빌드")
    p.add_argument("--all", action="store_true", help="check 전용 기준선까지 띄운다")
    p.add_argument("--foreground", action="store_true", help="이 창에서 띄우고 Ctrl+C로 끈다")
    p.add_argument("--host", type=parse_host, help="서버를 띄울 IPv4 주소 (기본: variants.json의 host, 127.0.0.1). "
                   "0.0.0.0이면 다른 기기·컨테이너에서도 열린다")
    p = sub.add_parser("urls", help="page_id → URL 표 (서버는 띄우지 않음)")
    p.add_argument("--json", action="store_true")
    sub.add_parser("stop", help="serve로 띄운 서버 정리")
    p = sub.add_parser("_host")  # serve가 백그라운드로 띄우는 내부 명령
    p.add_argument("--token", required=True)
    p.add_argument("--host", type=parse_host)
    p.add_argument("ids", nargs="+")
    args = parser.parse_args(argv)

    if args.command == "stop":
        return cmd_stop()
    try:
        config = load_config()
        if args.command == "build":
            return cmd_build(config, args.ids, args.force)
        if args.command == "check":
            return cmd_check(config)
        if args.command == "serve":
            return cmd_serve(config, args.ids, all_builds=args.all, foreground=args.foreground, bind=args.host)
        if args.command == "urls":
            return cmd_urls(config, args.json)
        return host_loop(config, select_builds(config, args.ids, []), args.token, args.host or config.host)
    except (ConfigError, ServeError) as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
