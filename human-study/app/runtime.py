"""실제 실행용 Deps 만들기 (exe·소스 공통). 테스트는 이 파일 대신 가짜 Deps를 쓴다."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any, TextIO

from .controller import Controller, Deps
from .plan import load_plan
from .resources import Resources, data_dirs, detect, legacy_data_dir, legacy_data_problem, run_mode, settings_dir
from .sites import Check, SiteServers, screen_avail_size


def prepare_process(res: Resources) -> Path:
    """exe에서 필요한 환경: 표준 출력 대신 로그 파일, 내장 Chromium, exe 폴더에 .pyc를 쓰지 않음."""
    log_dir = settings_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"
    if res.mode == "exe":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"  # Chromium은 exe 안(playwright 패키지 폴더)에 있다
        sys.dont_write_bytecode = True
    if sys.stdout is None or sys.stderr is None:  # --windowed exe: 서버 요청 기록·print가 갈 곳
        log: TextIO = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    return log_path


def build(res: Resources | None = None) -> tuple[Controller, SiteServers | None, str | None]:
    """(controller, 사이트 서버, 서버를 못 띄운 이유)."""
    res = res or detect()
    plan = load_plan(res.plan_path)
    session = res.load("session")
    check = res.load("check_sessions")
    real, practice = data_dirs()
    sites: SiteServers | None = None
    server_error: str | None = None
    try:
        sites = SiteServers(res)
        server_error = sites.start()
    except Exception as e:  # noqa: BLE001  variants.json·빌드가 없으면 점검 화면에서 보여 준다
        server_error = f"사이트 설정을 읽지 못했습니다: {e}"

    def env_checks() -> list[Check]:
        checks: list[Check] = []
        if sites is None or server_error:
            checks.append(Check("사이트 서버", False, server_error or "사이트 서버 없음"))
        else:
            status = sites.probe_all()
            bad = {pid: code for pid, code in status.items() if code != 200}
            checks.append(Check("사이트 서버", not bad,
                                f"6개 주소 200 ({', '.join(str(b.port) for b in sites.builds)})" if not bad
                                else "200이 아닌 주소: " + ", ".join(f"{p} → {c}" for p, c in bad.items())))
            problems = sites.integrity_problems()
            checks.append(Check("사이트 빌드", not problems,
                                "check를 통과한 빌드와 같음 (manifest 해시 일치)" if not problems else "; ".join(problems)))
        missing = [p for p in (res.collect_bundle, res.collect_script) if not p.is_file()]
        hint = " (저장소 루트에서 npm run build:collect)" if res.mode == "source" else ""
        checks.append(Check("수집 번들", not missing,
                            "collect.js 2개 있음" if not missing else "없음: " + ", ".join(str(p) for p in missing) + hint))
        legacy = legacy_data_problem(legacy_data_dir(), real)
        if legacy:
            checks.append(Check("예전 저장 위치", False, legacy))
        return checks

    info = res.build_info()
    session_info: dict[str, Any] = {
        "app_version": info.get("version"),
        "repo_commit": info.get("commit"),
        "site_manifest_hashes": sites.manifest_hashes() if sites else {},
        "os": platform.platform(),
        "run_mode": run_mode(res),
    }
    deps = Deps(
        plan=plan, session=session, check=check, data_dir=real, practice_dir=practice,
        settings_path=settings_dir() / "settings.json",
        url_for=(sites.url_for if sites else (lambda pid: "about:blank")),
        env_checks=env_checks, screen_size=screen_avail_size, session_info=session_info,
    )
    return Controller(deps), sites, server_error


def startup_message(err: BaseException, exe: bool, log_path: Path | None) -> str:
    """프로그램을 시작하지 못했을 때 진행자에게 보여 줄 글. 창 모드 exe는 오류가 화면에 나오지 않으므로 알림 창으로 띄운다."""
    detail = (str(err) or type(err).__name__).strip()[:300]
    if exe:
        fix = ("zip을 새 폴더에 처음부터 다시 풀고, 그 폴더 안의 StepMeter-human.exe를 실행하세요. "
               "exe만 다른 곳으로 옮기거나 압축 파일 안에서 바로 실행하면 이렇게 됩니다.")
    else:
        fix = "저장소 루트에서 git pull origin main 후 다시 실행하세요."
    where = f"\n\n그래도 안 되면 이 로그 파일을 세션 운영 담당에게 보내 주세요:\n{log_path}" if log_path else ""
    return f"프로그램을 시작하지 못했습니다.\n\n{detail}\n\n{fix}{where}"
