"""실행 방식(exe·소스)에 따라 사이트·수집 번들·기존 모듈의 위치를 고른다.

두 방식 모두 같은 폴더 구조를 쓴다. 소스 방식은 저장소 루트, exe 방식은 PyInstaller가 푼
내장 폴더(sys._MEIPASS)가 루트다. 내장 폴더에는 빌드 스크립트(build_exe.py)가 저장소와 같은
상대 경로로 파일을 넣는다. 그래서 session.py·schema.py·check_sessions.py·serve_variants.py가
자기 파일 위치로 계산하는 경로(collect.js, openapi.yaml, variants.json, 빌드 폴더)가 두 방식에서
모두 맞게 나온다. 이 모듈들은 고치지 않고 파일 경로로 불러온다.
"""
from __future__ import annotations

import ctypes
import importlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
BUILD_INFO = "app_build.json"  # exe 내장 폴더에만 있다 (build_exe.py가 쓴다)
HOME_ENV = "STEPMETER_HUMAN_HOME"  # 데이터 폴더의 부모를 바꾼다 (자동 확인·테스트용)


@dataclass(frozen=True)
class Resources:
    mode: str  # "exe" | "source"
    root: Path

    @property
    def human_study(self) -> Path:
        return self.root / "human-study"

    @property
    def plan_path(self) -> Path:
        return self.human_study / "session_plan.json"

    @property
    def variants_root(self) -> Path:
        """serve_variants의 VARIANTS_ROOT와 같은 곳 (사이트 빌드 결과·manifest)."""
        return self.root / "benchmark" / "apps" / "variants"

    @property
    def variants_config(self) -> Path:
        return self.root / "benchmark" / "variants.json"

    @property
    def collect_bundle(self) -> Path:
        """session.BUNDLE과 같은 곳 (npm run build:collect 결과)."""
        return self.root / "worker" / "collect" / "dist" / "collect.js"

    @property
    def collect_script(self) -> Path:
        return self.human_study / "collect.js"

    @property
    def check_evidence(self) -> Path:
        """serve_variants check 요약."""
        return self.root / "benchmark" / "evidence" / "variants-check.json"

    def _ensure_path(self) -> None:
        for p in (str(self.root), str(self.human_study)):
            if p not in sys.path:
                sys.path.insert(0, p)

    def load(self, name: str) -> ModuleType:
        """human-study/<name>.py를 파일 경로로 불러온다. 테스트(tests/test_human_session.py)와 같은 이름을 쓴다."""
        modname = f"human_study_{name}"
        path = (self.human_study / f"{name}.py").resolve()
        mod = sys.modules.get(modname)
        if mod is not None and Path(getattr(mod, "__file__", "")).resolve() == path:
            return mod
        self._ensure_path()
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"{path}를 불러오지 못했다")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        return mod

    def serve_variants(self) -> ModuleType:
        self._ensure_path()
        return importlib.import_module("benchmark.serve_variants")

    def build_info(self) -> dict[str, Any]:
        """{"version", "commit", "built_at"}. 소스 방식은 git에서 읽는다."""
        if self.mode == "exe":
            try:
                return json.loads((self.root / BUILD_INFO).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"version": "exe-unknown", "commit": None, "built_at": None}
        commit = git_commit(self.root)
        return {"version": source_version(commit, git_dirty(self.root), date.today()), "commit": commit,
                "built_at": None}


def source_version(commit: str | None, dirty: bool, today: date) -> str:
    """소스 방식 버전: 실행한 날짜 + 커밋 앞 7자리(exe와 같은 모양). 커밋 안 된 변경이 있으면 -dirty."""
    base = f"{today:%Y%m%d}-{commit[:7]}" if commit else f"{today:%Y%m%d}-nogit"
    return base + ("-dirty" if dirty else "")


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                             check=True, stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def git_commit(root: Path) -> str | None:
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() or None if out else None


def git_dirty(root: Path) -> bool:
    """작업 트리에 커밋 안 된 변경(새 파일 포함, .gitignore 제외)이 있는지."""
    out = _git(root, "status", "--porcelain")
    return bool(out and out.strip())


def detect(frozen: bool | None = None, meipass: str | None = None) -> Resources:
    """exe(PyInstaller)면 내장 폴더, 아니면 저장소 루트."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        base = meipass if meipass is not None else getattr(sys, "_MEIPASS", None)
        if base is None:
            raise RuntimeError("exe 방식인데 내장 폴더(sys._MEIPASS)를 찾지 못했다")
        return Resources("exe", Path(base))
    return Resources("source", REPO_ROOT)


def run_mode(res: Resources) -> str:
    """notes에 남기는 실행 방식: exe-windows, source-windows, source-mac 등."""
    system = {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), platform.system().lower())
    return f"{res.mode}-{system}"


# ---------------------------------------------------------------- 이 PC의 폴더

def documents_dir() -> Path:
    """문서 폴더. Windows는 OneDrive로 옮겨진 경우도 따른다."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        try:
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            windll = getattr(ctypes, "windll")
            if windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
                path = Path(out.value or "")
                windll.ole32.CoTaskMemFree(out)
                if path.parts:
                    return path
        except (OSError, AttributeError):
            pass
    return Path.home() / "Documents"


def data_dirs() -> tuple[Path, Path]:
    """(본 데이터, 연습 데이터). exe 폴더에는 쓰지 않는다."""
    docs = documents_dir()
    return docs / "StepMeter-human", docs / "StepMeter-human-practice"


def settings_dir() -> Path:
    """진행자 선택·로그. 참가자 데이터는 두지 않는다."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override) / ".stepmeter-human-settings"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "StepMeter-human"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "StepMeter-human"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "StepMeter-human"
