"""진행 로직 (화면 없음). gui.py가 이 클래스의 상태(step)를 그리고 버튼을 이 메서드에 잇는다.

참가자가 노트북을 직접 쓰고 진행자는 옆에서 보는 방식(procedure_version self_guided_v1, session-procedure.md):
  진행자 화면: SETUP → PREFLIGHT → C1 조건 확인 → C2 동의서 → HANDOVER "노트북을 건네주세요"
  참가자 화면: P_INTRO 시작 안내·사용 시간 → (과업마다 P_TASK 과업 문장 → [시작] → P_RUNNING 오른쪽 패널
              → 3분·창 닫힘이면 P_BETWEEN) → P_FINISHED "노트북을 진행자에게 돌려주세요"
  진행자 화면: REVIEW 페이지별 완료 확정·진행 이상 메모 → C5 마지막 안내 → DONE 검사·zip

수집·저장은 session.run_session_async / save_session_or_dump / save_session / SessionMeta, 검사는
check_sessions.main을 그대로 부른다. 페이지가 끝나면 참가자 답으로 먼저 저장하고, 진행자가 확인표에서 완료 여부를
바꾸면 그 파일의 completed만 고쳐 session.save_session으로 다시 저장한다(같은 파일 이름, 다른 칸은 그대로).
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import threading
import time
import zipfile
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from . import notes as notes_mod
from .plan import Plan, PlanPage, code_number
from .sites import Check, folder_writable

GITHUB_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
HOURS = re.compile(r"^\d{1,2}(?:\.\d{1,2})?$")
OTHER_FACILITATOR = "기타"
LOCKED_INCOMPLETE = ("timeout", "closed", "crashed")  # 진행자가 바꿀 수 없는 미완료 (3분, 창 닫힘 = session.py 규칙)


class Step(str, Enum):
    SETUP = "setup"
    PREFLIGHT = "preflight"
    C1 = "c1"
    C2 = "c2"
    RESUME = "resume"
    HANDOVER = "handover"
    P_INTRO = "p_intro"
    P_TASK = "p_task"
    P_RUNNING = "p_running"
    P_BETWEEN = "p_between"
    P_ERROR = "p_error"
    P_FINISHED = "p_finished"
    REVIEW = "review"
    C5 = "c5"
    DONE = "done"
    ABORTED = "aborted"
    WITHDRAWN = "withdrawn"


PARTICIPANT_STEPS = (Step.P_INTRO, Step.P_TASK, Step.P_RUNNING, Step.P_BETWEEN, Step.P_FINISHED)
# 참가 철회(동의서 6절)를 받을 수 있는 단계. C-1·C-2는 [중단](데이터 없음), 진행 중 페이지는 먼저 끝낸다
WITHDRAW_STEPS = (Step.PREFLIGHT, Step.RESUME, Step.HANDOVER, Step.P_INTRO, Step.P_TASK, Step.P_BETWEEN,
                  Step.P_ERROR, Step.P_FINISHED, Step.REVIEW, Step.C5, Step.DONE)


def withdrawn_path(folder: Path, code: str) -> Path:
    """철회 표시 파일. 기록은 지우고 이 파일만 남겨 같은 코드를 다른 참가자에게 다시 주지 않게 한다(내용: 날짜뿐)."""
    return folder / f"withdrawn-{code}.txt"


@dataclass
class CodeInfo:
    code: str
    error: str | None = None
    warning: str | None = None  # 진행자 범위 밖: 확인을 받고 진행
    saved: list[str] = field(default_factory=list)  # 이미 저장된 page_id
    interrupted: list[str] = field(default_factory=list)  # 시작했지만 저장 전에 프로그램이 끝난 page_id
    noted: list[str] = field(default_factory=list)  # 파일 없이 notes에만 있는 page_id (오류로 건너뜀)

    @property
    def attempted(self) -> set[str]:
        return set(self.saved) | set(self.interrupted) | set(self.noted)


@dataclass
class PageResult:
    page: PlanPage
    completed: bool
    reported: str  # done | gave_up | timeout | closed | crashed
    path: Path
    invalid: bool = False
    events: int = 0


@dataclass
class ReviewRow:
    page: PlanPage
    reported: str | None
    completed: bool | None  # 처음 저장한 값
    confirmed: bool | None  # 확인표 기본값(이미 확인했으면 그 값)
    locked: bool  # 진행자가 바꿀 수 없음
    path: Path | None
    invalid: bool
    issue_codes: list[int]
    note: str

    @property
    def reported_text(self) -> str:
        return {"done": "다 했어요", "gave_up": "그만할게요", "timeout": "3분 자동 종료", "closed": "브라우저 창 닫힘",
                "crashed": "브라우저 오류"}.get(self.reported or "", "저장되지 않음")


@dataclass
class Report:
    text: str
    ok: bool
    check_path: Path
    zip_path: Path
    zipped: list[str]
    unsaved: list[str] = field(default_factory=list)  # 세션 파일이 없는 page_id (오류로 건너뜀·중간에 꺼짐)


@dataclass
class Deps:
    plan: Plan
    session: ModuleType  # human-study/session.py
    check: ModuleType  # human-study/check_sessions.py
    data_dir: Path
    practice_dir: Path
    settings_path: Path
    url_for: Callable[[str], str]
    env_checks: Callable[[], list[Check]]  # 사이트 서버·빌드·수집 번들
    screen_size: Callable[[], tuple[int, int]]  # (availWidth, availHeight)
    session_info: dict[str, Any]  # app_version, repo_commit, site_manifest_hashes, os, run_mode
    headless: bool = False
    page_limit_s: float | None = None  # 테스트에서 3분 대신 짧게
    on_page_open: Callable[[Any, asyncio.AbstractEventLoop], None] | None = None  # 테스트용


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Controller:
    def __init__(self, deps: Deps) -> None:
        self.d = deps
        self.plan = deps.plan
        self.version_name = self.plan.procedure_version
        self.limit_s = deps.page_limit_s if deps.page_limit_s is not None else self.plan.page_limit_seconds
        self._lock = threading.RLock()
        self.version = 0  # 상태가 바뀔 때마다 1씩 오른다 (GUI가 다시 그릴 때를 안다)
        self._reset()

    # ------------------------------------------------------------ 상태

    def _reset(self) -> None:
        self.step = Step.SETUP
        self.facilitator: str | None = None
        self.code: str | None = None
        self.practice = False
        self.info: CodeInfo | None = None
        self.checks: list[Check] = []
        self.preflight_ok = False
        self.screen_avail_height: int | None = None
        self.screen_avail_width: int | None = None
        self.hours: float | None = None
        self.started_at: str | None = None
        self.page_index = 0
        self.result: PageResult | None = None
        self.error: str | None = None
        self.retry_allowed = False
        self.report: Report | None = None
        self.aborted_at: Step | None = None
        self.withdrawn_removed: list[str] = []
        self._run_started: float | None = None
        self._decide: Callable[[str], None] | None = None
        self._pending_reason: str | None = None
        self._thread: threading.Thread | None = None
        self._partial: Path | None = None
        self._reason = "error"

    def _go(self, step: Step) -> None:
        with self._lock:
            self.step = step
            self.version += 1

    def _expect(self, step: Step) -> None:
        if self.step != step:
            raise RuntimeError(f"지금 단계는 {self.step.value}이다 (기대 {step.value})")

    @property
    def out_dir(self) -> Path:
        return self.d.practice_dir if self.practice else self.d.data_dir

    @property
    def current_page(self) -> PlanPage:
        return self.plan.pages[self.page_index]

    @property
    def participant_facing(self) -> bool:
        return self.step in PARTICIPANT_STEPS

    # ------------------------------------------------------------ 처음 화면

    def facilitator_choices(self) -> list[str]:
        return [f.github for f in self.plan.facilitators] + [OTHER_FACILITATOR]

    def remembered_facilitator(self) -> str | None:
        try:
            data = json.loads(self.d.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = data.get("facilitator") if isinstance(data, dict) else None
        return value if isinstance(value, str) and GITHUB_ID.match(value) else None

    def remember_facilitator(self, github: str) -> None:
        try:
            self.d.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.d.settings_path.write_text(json.dumps({"facilitator": github}) + "\n", encoding="utf-8")
        except OSError:
            pass  # 기억하지 못해도 진행에는 지장 없다

    def check_github(self, github: str) -> str | None:
        return None if GITHUB_ID.match(github or "") else "GitHub 아이디를 적어 주세요(영문·숫자·하이픈). 이름은 적지 않습니다"

    def _scan(self, folder: Path, code: str) -> tuple[dict[str, list[Path]], set[str]]:
        """(page_id → 저장된 파일들, 저장 없이 .partial만 남은 page_id). 파일은 읽기만 한다."""
        safe = self.d.session._safe
        saved: dict[str, list[Path]] = {}
        for f in sorted(folder.glob(f"human-session-{code}-*.json")):
            page_id = None
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("participant_code") == code:
                    page_id = data.get("page_id")
            except (OSError, json.JSONDecodeError):
                data = None
            if page_id is None and f.name.endswith(".invalid.json"):
                for p in self.plan.pages:  # 검증 실패 파일은 이름(참가자-page_id)으로 찾는다
                    if f.name.startswith(f"human-session-{safe(code + '-' + p.page_id)}-"):
                        page_id = p.page_id
            if isinstance(page_id, str):
                saved.setdefault(page_id, []).append(f)
        interrupted = set()
        for p in self.plan.pages:
            # 빈 .partial은 이벤트가 하나도 없다(페이지가 뜨기 전에 멈춤) → 참가자는 페이지를 못 봤다
            partials = folder.glob(f".partial-{safe(code)}-{safe(p.page_id)}-*.jsonl")
            if p.page_id not in saved and any(f.stat().st_size > 0 for f in partials):
                interrupted.add(p.page_id)
        return saved, interrupted

    def attempted(self, code: str, practice: bool = False) -> set[str]:
        """이미 한 페이지: 저장 파일, 저장 전에 끝난 .partial, notes에 적힌 페이지. 다시 하지 않는다."""
        folder = self.d.practice_dir if practice else self.d.data_dir
        saved, interrupted = self._scan(folder, code)
        data = notes_mod.load(folder, code)
        noted = {p.get("page_id") for p in data.get("pages", [])} if data else set()
        return set(saved) | interrupted | {x for x in noted if isinstance(x, str)}

    def suggest_code(self, github: str | None) -> str | None:
        """그 진행자 범위에서 아직 아무 페이지도 없고 철회되지 않은 가장 작은 번호."""
        f = self.plan.facilitator(github or "")
        if f is None:
            return None
        for c in f.codes():
            if not self.attempted(c) and not withdrawn_path(self.d.data_dir, c).exists():
                return c
        return None

    def inspect_code(self, github: str, code: str, practice: bool) -> CodeInfo:
        code = (code or "").strip().upper()
        if practice:
            code = self.plan.practice_code
        info = CodeInfo(code)
        try:
            code_number(code)
        except ValueError:
            info.error = "참가자 코드는 P01 같은 형식입니다"
            return info
        if not practice and code == self.plan.practice_code:
            info.error = f"{code}은 연습 전용입니다. 연습이면 '연습 모드'를 켜세요"
            return info
        if withdrawn_path(self.d.practice_dir if practice else self.d.data_dir, code).exists():
            info.error = (f"{code}는 참가 철회로 기록을 지운 코드입니다. 다른 참가자에게 다시 주지 않습니다"
                          + (". '연습 기록 지우기'로 지운 뒤 쓰세요" if practice else ". 다음 번호를 쓰세요"))
            return info
        if not practice:
            f = self.plan.facilitator(github)
            if f is None or code not in f.codes():
                where = f"{github}님의 범위({f.range_text})" if f else "진행자 범위 표(session-procedure.md C-2)"
                info.warning = (f"{code}는 {where} 밖입니다. 다른 진행자와 겹치지 않게 "
                                "세션 운영 담당에게 받은 번호인지 확인하세요.")
        saved, interrupted = self._scan(self.d.practice_dir if practice else self.d.data_dir, code)
        info.saved = [p.page_id for p in self.plan.pages if p.page_id in saved]
        info.interrupted = [p.page_id for p in self.plan.pages if p.page_id in interrupted]
        attempted = self.attempted(code, practice)
        info.noted = [p.page_id for p in self.plan.pages
                      if p.page_id in attempted and p.page_id not in saved and p.page_id not in interrupted]
        return info

    def choose(self, github: str, code: str, practice: bool, *, confirm_out_of_range: bool = False) -> CodeInfo:
        """처음 화면의 [다음]. 오류가 있거나 범위 밖인데 확인이 없으면 그대로 SETUP에 머문다."""
        err = self.check_github(github)
        if err:
            return CodeInfo(code, error=err)
        info = self.inspect_code(github, code, practice)
        if info.error or (info.warning and not confirm_out_of_range):
            return info
        self.facilitator, self.code, self.practice, self.info = github, info.code, practice, info
        self.remember_facilitator(github)
        self.preflight_ok = False
        self.checks = []
        self._go(Step.PREFLIGHT)
        return info

    def reset_practice(self) -> list[str]:
        """연습 폴더의 P00 기록만 지운다. 본 데이터 폴더는 건드리지 않는다."""
        code = self.plan.practice_code
        folder = self.d.practice_dir
        removed = []
        for f in self._code_files(folder, code) + [withdrawn_path(folder, code)]:
            if f.exists():
                f.unlink()
                removed.append(f.name)
        return removed

    def _code_files(self, folder: Path, code: str) -> list[Path]:
        """그 코드의 모든 기록: 세션 json(검증 실패 포함)·.partial·notes·검사 결과·zip과 쓰다 남은 .tmp."""
        safe = self.d.session._safe(code)
        patterns = (f"human-session-{code}-*.json", f".partial-{safe}-*.jsonl", f"notes-{code}.json",
                    f"notes-{code}.json.tmp", f"check-{code}.txt", f"upload-{code}.zip", f"upload-{code}.zip.tmp")
        return sorted({f for pattern in patterns for f in folder.glob(pattern) if f.is_file()})

    def withdraw(self) -> list[str]:
        """참가 철회(동의서 6절 "그만두시면 그때까지의 기록을 지웁니다"): 이 코드의 기록을 모두 지우고
        철회 표시만 남긴다. 표시가 있으면 코드 제안·입력에서 이 코드를 다시 쓰지 않는다. 지운 파일 이름을 돌려준다."""
        if self.step not in WITHDRAW_STEPS:
            raise RuntimeError(f"{self.step.value}에서는 철회를 받을 수 없다 (진행 중이면 먼저 [그만할게요])")
        code, folder = self.code or "", self.out_dir
        code_number(code)
        removed = []
        for f in self._code_files(folder, code):
            f.unlink()
            removed.append(f.name)
        folder.mkdir(parents=True, exist_ok=True)
        withdrawn_path(folder, code).write_text(
            f"참가 철회로 이 코드의 기록을 지웠다 ({datetime.now(timezone.utc):%Y-%m-%d}). 이 코드는 다시 쓰지 않는다.\n",
            encoding="utf-8")
        self.withdrawn_removed = removed
        self._go(Step.WITHDRAWN)
        return removed

    def back_to_setup(self) -> None:
        if self.step == Step.P_RUNNING:
            raise RuntimeError("페이지 진행 중에는 처음으로 돌아갈 수 없다")
        self._reset()
        self._go(Step.SETUP)

    # ------------------------------------------------------------ 시작 전 점검

    def run_preflight(self, mouse_ok: bool) -> list[Check]:
        checks = list(self.d.env_checks())
        hint = "Windows: 설정 → 디스플레이 → 배율을 100%로 / Mac: 시스템 설정 → 디스플레이 → '더 넓게'. 바꾼 뒤 [다시 점검]"
        try:
            w, h = (int(x) for x in self.d.screen_size())
            self.screen_avail_width, self.screen_avail_height = w, h
            need_h, need_w = self.plan.min_screen_avail_height, self.plan.min_screen_avail_width
            checks.append(Check("화면 높이", h >= need_h, f"{h}px (기준 {need_h}px 이상)" if h >= need_h
                                else f"{h}px로 {need_h}px보다 작습니다. {hint}"))
            checks.append(Check("화면 너비", w >= need_w,
                                f"{w}px (기준 {need_w}px 이상: 브라우저 1280 + 참가자 패널 {self.plan.panel_width})"
                                if w >= need_w else
                                f"{w}px로 {need_w}px(브라우저 1280 + 참가자 패널 {self.plan.panel_width})보다 작습니다. {hint}"))
        except Exception as e:  # noqa: BLE001  Chromium을 못 띄우면 이유를 보여 준다
            checks.append(Check("화면 크기", False, f"Chromium 창을 띄우지 못했습니다: {str(e)[:300]}"))
        err = folder_writable(self.out_dir)
        checks.append(Check("저장 폴더", err is None, str(self.out_dir) if err is None else f"{self.out_dir}: {err}"))
        checks.append(Check("외장 마우스", bool(mouse_ok),
                            "연결 확인함 (장치는 mouse로 기록)" if mouse_ok else "마우스를 연결하고 체크하세요"))
        with self._lock:
            self.checks = checks
            self.preflight_ok = all(c.ok for c in checks)
            self.version += 1
        return checks

    def invalidate_preflight(self) -> None:
        """점검 뒤 체크박스를 바꾸면 다시 점검해야 시작할 수 있다."""
        with self._lock:
            self.preflight_ok = False
            self.version += 1

    def start(self) -> None:
        if self.step != Step.PREFLIGHT or not self.preflight_ok:
            raise RuntimeError("시작 전 점검을 통과해야 시작할 수 있다")
        assert self.info is not None
        existing = notes_mod.load(self.out_dir, self.code or "")
        if existing and existing.get("session", {}).get("started_at"):
            self.started_at = existing["session"]["started_at"]
        else:
            self.started_at = _iso_z(datetime.now(timezone.utc))
        if self.info.attempted:
            self.hours = self._saved_hours()
            self._go(Step.RESUME)
        else:
            self._go(Step.C1)

    def _saved_hours(self) -> float | None:
        saved, _ = self._scan(self.out_dir, self.code or "")
        for files in saved.values():
            for f in files:
                try:
                    h = json.loads(f.read_text(encoding="utf-8")).get("daily_computer_hours")
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue
                if isinstance(h, (int, float)) and 0 <= h <= 24:
                    return float(h)
        return None

    # ------------------------------------------------------------ 진행자: C-1 · C-2 · 건네기

    def c1_pass(self) -> None:
        self._expect(Step.C1)
        self._go(Step.C2)

    def c2_signed(self) -> None:
        self._expect(Step.C2)
        self._go(Step.HANDOVER)

    def abort(self) -> None:
        """C-1·C-2에서 중단. 데이터 없이 끝나고 코드도 쓰지 않는다(파일을 만들지 않았다)."""
        if self.step not in (Step.C1, Step.C2):
            raise RuntimeError(f"{self.step}에서는 중단할 수 없다")
        self.aborted_at = self.step
        self._go(Step.ABORTED)

    def remaining_pages(self) -> list[PlanPage]:
        done = self.attempted(self.code or "", self.practice)
        return [p for p in self.plan.pages if p.page_id not in done]

    def resume_continue(self) -> None:
        """이어 하기: 남은 과업이 있으면 노트북을 건네고, 없으면 확인표로."""
        self._expect(Step.RESUME)
        self._go(Step.HANDOVER if self.remaining_pages() else Step.REVIEW)

    def handed_over(self) -> None:
        """[건넸어요]."""
        self._expect(Step.HANDOVER)
        self._go(Step.P_INTRO)

    # ------------------------------------------------------------ 참가자

    @staticmethod
    def parse_hours(text: str) -> float | str:
        t = (text or "").strip()
        if not HOURS.match(t):
            return "0~24 사이 숫자만 넣어 주세요"
        h = float(t)
        if not 0 <= h <= 24:
            return "0~24 사이 숫자만 넣어 주세요"
        return h

    @property
    def needs_hours(self) -> bool:
        return self.hours is None

    def participant_begin(self, hours_text: str | None = None) -> str | None:
        """시작 안내의 [시작하기]. 사용 시간을 아직 받지 않았으면 받는다. 오류 문장 또는 None."""
        self._expect(Step.P_INTRO)
        if self.hours is None:
            h = self.parse_hours(hours_text or "")
            if isinstance(h, str):
                return h
            self.hours = h
        self._next_task()
        return None

    def _next_task(self) -> None:
        remaining = self.remaining_pages()
        if remaining:
            self.page_index = self.plan.pages.index(remaining[0])  # self.result는 직전 페이지 결과로 남긴다
            self._go(Step.P_TASK)
        else:
            self._go(Step.P_FINISHED)

    def launch_page(self) -> None:
        """참가자의 [시작]. 과업 문장을 읽은 뒤에 창이 열린다."""
        self._expect(Step.P_TASK)
        page = self.current_page
        if page.page_id in self.attempted(self.code or "", self.practice):
            raise RuntimeError(f"{page.page_id}는 이미 했다 (같은 페이지 두 번 금지)")
        s = self.d.session
        assert self.code is not None and self.hours is not None
        meta = s.SessionMeta(self.code, page.page_id, self.plan.device, self.hours)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self._partial = self.out_dir / f".partial-{s._safe(self.code)}-{s._safe(page.page_id)}-{stamp}.jsonl"
        self._run_started = None
        self._decide = None
        self._pending_reason = None
        self.error = None
        url = self.d.url_for(page.page_id)
        self._go(Step.P_RUNNING)
        self._thread = threading.Thread(target=self._run, args=(meta, url, page, self._partial), daemon=True,
                                        name=f"session-{page.order}")
        self._thread.start()

    @property
    def page_visible(self) -> bool:
        """Chromium에 페이지가 떠서 3분 제한이 도는 중 (남은 시간은 화면에 보이지 않는다)."""
        return self._run_started is not None

    def remaining_seconds(self) -> float | None:
        if self._run_started is None:
            return None
        return max(0.0, self.limit_s - (time.monotonic() - self._run_started))

    def report_participant(self, done: bool) -> None:
        """참가자 패널의 [다 했어요](done) · [그만할게요](gave_up)."""
        if self.step != Step.P_RUNNING:
            return
        reason = "done" if done else "gave_up"
        with self._lock:
            if self._decide is None:
                self._pending_reason = reason
            else:
                try:
                    self._decide(reason)
                except RuntimeError:
                    pass  # 세션이 막 끝나 루프가 닫혔다

    def wait_page(self, timeout: float | None = None) -> bool:
        """테스트용: 진행 중인 페이지가 끝날 때까지 기다린다."""
        t = self._thread
        if t is not None:
            t.join(timeout)
            return not t.is_alive()
        return True

    async def _place_window(self, page: Any) -> None:
        """Chromium 창을 화면 왼쪽 위로 옮긴다. 오른쪽은 참가자 패널 자리다(창 크기는 바꾸지 않는다)."""
        if self.d.headless:
            return
        try:
            cdp = await page.context.new_cdp_session(page)
            win = await cdp.send("Browser.getWindowForTarget")
            await cdp.send("Browser.setWindowBounds", {"windowId": win["windowId"], "bounds": {"left": 0, "top": 0}})
            await cdp.detach()
        except Exception:  # noqa: BLE001  못 옮겨도 진행은 된다
            pass

    async def _interact(self, page: Any) -> bool:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()

        def resolve(reason: str) -> None:
            if not fut.done():
                fut.set_result(reason)

        page.on("close", lambda _: resolve("closed"))
        page.on("crash", lambda _: resolve("crashed"))
        await self._place_window(page)
        with self._lock:
            def decide(reason: str) -> None:
                loop.call_soon_threadsafe(resolve, reason)

            self._decide = decide
            if self._pending_reason:
                resolve(self._pending_reason)
            self._run_started = time.monotonic()
            self.version += 1
        if page.is_closed():
            resolve("closed")
        if self.d.on_page_open is not None:
            self.d.on_page_open(page, loop)
        try:
            reason = await asyncio.wait_for(asyncio.shield(fut), timeout=self.limit_s)
        except asyncio.TimeoutError:
            reason = "timeout"
        self._reason = reason
        return reason == "done"

    def _run(self, meta: Any, url: str, page: PlanPage, partial: Path) -> None:
        s = self.d.session
        self._reason = "error"
        try:
            data = asyncio.run(s.run_session_async(meta, url, headless=self.d.headless, interact=self._interact,
                                                   partial_path=partial))
        except (Exception, SystemExit) as e:  # noqa: BLE001  Chromium·서버 문제를 화면에 보여 준다
            lines = partial.read_text(encoding="utf-8").splitlines() if partial.exists() else []
            with self._lock:
                self.error = self._explain(e)
                self.retry_allowed = not lines  # 이벤트가 하나도 없으면 참가자는 페이지를 못 봤다
                self._run_started = None
                self._decide = None
            self._go(Step.P_ERROR)
            return
        path = s.save_session_or_dump(data, self.out_dir, f"{meta.participant_code}-{meta.page_id}")
        invalid = path.name.endswith(".invalid.json")
        if not invalid:
            partial.unlink(missing_ok=True)
        reason = self._reason
        result = PageResult(page, bool(data["completed"]), reason, path=path, invalid=invalid,
                            events=len(data["events"]))
        self._record_result(result)
        with self._lock:
            self.result = result
            self._run_started = None
            self._decide = None
        if reason in LOCKED_INCOMPLETE:
            self._go(Step.P_BETWEEN)  # "여기까지 하셔도 됩니다" / "창이 닫혔습니다"
        else:
            self._next_task()

    def between_next(self) -> None:
        self._expect(Step.P_BETWEEN)
        self._next_task()

    @staticmethod
    def _explain(e: BaseException) -> str:
        text = str(e) or type(e).__name__
        if "Executable doesn't exist" in text:
            return "Chromium을 찾지 못했습니다. 소스 방식이면 python -m playwright install chromium을 다시 하세요.\n" + text[:400]
        if "ERR_CONNECTION_REFUSED" in text:
            return "사이트 서버에 연결하지 못했습니다. 프로그램을 다시 여세요.\n" + text[:400]
        return text[:600]

    def _notes(self) -> dict[str, Any]:
        code = self.code or ""
        data = notes_mod.load(self.out_dir, code)
        if data is None:
            data = notes_mod.new({
                **self.d.session_info,
                "participant_code": code,
                "facilitator": self.facilitator,
                "screen_avail_height": self.screen_avail_height,
                "started_at": self.started_at,
                "procedure_version": self.version_name,
            })
        return data

    def _record_result(self, r: PageResult) -> None:
        """저장 직후 notes에 페이지 결과를 먼저 적는다(진행자 확인 전이라 issue=null)."""
        data = self._notes()
        notes_mod.upsert_page(data, {
            "order": r.page.order, "page_id": r.page.page_id, "participant_reported": r.reported,
            "completed": r.completed, "completed_confirmed": None, "confirmation_changed": None,
            "auto_stopped_3min": r.reported == "timeout", "issue": None, "issue_codes": [], "note": "",
        })
        notes_mod.save(self.out_dir, self.code or "", data)

    def retry_page(self) -> None:
        """Chromium·서버 오류로 페이지가 아예 뜨지 않았을 때만 다시 띄운다."""
        self._expect(Step.P_ERROR)
        if not self.retry_allowed:
            raise RuntimeError("참가자가 이미 페이지를 봤으면 다시 하지 않는다")
        if self._partial is not None:
            self._partial.unlink(missing_ok=True)
        self.error = None
        self._go(Step.P_TASK)

    def skip_page(self) -> None:
        """오류 난 페이지를 다시 하지 않고 넘어간다(확인표에서 기술 문제로 메모)."""
        self._expect(Step.P_ERROR)
        if self._partial is not None and self.retry_allowed:
            self._partial.unlink(missing_ok=True)  # 빈 기록. 아래 notes가 이 페이지를 했다고 남긴다
        data = self._notes()
        p = self.current_page
        notes_mod.upsert_page(data, {
            "order": p.order, "page_id": p.page_id, "participant_reported": None, "completed": None,
            "completed_confirmed": None, "confirmation_changed": None, "auto_stopped_3min": None,
            "issue": None, "issue_codes": [notes_mod.TECHNICAL[self.version_name]],
            "note": f"오류로 진행 못 함: {(self.error or '')[:120]}".replace("\n", " "),
        })
        notes_mod.save(self.out_dir, self.code or "", data)
        self.error = None
        self._next_task()

    def returned(self) -> None:
        """[돌려줬어요] (진행자가 누른다)."""
        self._expect(Step.P_FINISHED)
        self._go(Step.REVIEW)

    # ------------------------------------------------------------ 진행자: 확인표

    def review_rows(self) -> list[ReviewRow]:
        saved, interrupted = self._scan(self.out_dir, self.code or "")
        data = notes_mod.load(self.out_dir, self.code or "") or {"pages": []}
        rows = []
        for p in self.plan.pages:
            entry = notes_mod.page_entry(data, p.page_id) or {}
            files = saved.get(p.page_id) or []
            path = files[-1] if files else None
            invalid = bool(path and path.name.endswith(".invalid.json"))
            completed = entry.get("completed")
            if completed is None and path is not None and not invalid:
                completed = self._file_completed(path)
            reported = entry.get("participant_reported")
            codes = list(entry.get("issue_codes") or [])
            note = entry.get("note") or ""
            if path is None and not entry and p.page_id in interrupted:
                codes, note = [notes_mod.TECHNICAL[self.version_name]], "프로그램이 중간에 끝나 이 페이지가 저장되지 않음"
            confirmed = entry.get("completed_confirmed")
            if confirmed is None:
                confirmed = completed
            locked = path is None or invalid or reported in LOCKED_INCOMPLETE
            if reported in LOCKED_INCOMPLETE:
                confirmed = False
            rows.append(ReviewRow(p, reported, completed, confirmed, locked, path, invalid, codes, note))
        return rows

    @staticmethod
    def _file_completed(path: Path) -> bool | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("completed")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None
        return value if isinstance(value, bool) else None

    def _rewrite_completed(self, path: Path, value: bool) -> None:
        """세션 파일의 completed만 바꿔 session.save_session으로 같은 이름에 다시 저장한다(다른 칸은 그대로)."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("completed") == value:
            return
        data["completed"] = value
        new_path = self.d.session.save_session(data, path.parent)  # 스키마 검증 포함
        if Path(new_path).resolve() != path.resolve():
            Path(new_path).unlink(missing_ok=True)
            raise RuntimeError(f"{path.name}: 다시 저장한 파일 이름이 다르다 ({Path(new_path).name})")

    def submit_review(self, entries: dict[str, tuple[bool | None, list[int], str]]) -> dict[str, str]:
        """확인표 저장. entries: page_id → (완료 확정, 이상 항목, 한 줄 메모). 오류가 있으면 {page_id: 오류}."""
        self._expect(Step.REVIEW)
        rows = self.review_rows()
        errors: dict[str, str] = {}
        for r in rows:
            confirmed, codes, note = entries.get(r.page.page_id, (r.confirmed, [], ""))
            err = notes_mod.check_note(codes, note, self.version_name)
            if err:
                errors[r.page.page_id] = err
            elif not r.locked and confirmed is None:
                errors[r.page.page_id] = "완료 여부를 골라 주세요"
        if errors:
            return errors
        data = self._notes()
        rewrites: list[tuple[Path, bool]] = []
        for r in rows:
            confirmed, codes, note = entries.get(r.page.page_id, (r.confirmed, [], ""))
            if r.locked:
                confirmed = r.confirmed
            if r.path is not None and not r.invalid and confirmed is not None:
                rewrites.append((r.path, confirmed))
            changed = None if confirmed is None or r.completed is None else confirmed != r.completed
            entry = notes_mod.page_entry(data, r.page.page_id) or {
                "order": r.page.order, "page_id": r.page.page_id, "participant_reported": r.reported,
                "completed": r.completed, "auto_stopped_3min": r.reported == "timeout" if r.reported else None}
            entry = {**entry, "completed_confirmed": confirmed, "confirmation_changed": changed}
            notes_mod.upsert_page(data, notes_mod.apply_note(entry, codes, note))
        # notes(확정값)를 먼저 저장한 뒤 세션 파일을 고친다. 사이에 프로그램이 꺼져도 다시 열면 확인표 기본값이
        # notes의 확정값이라, 저장하면 세션 파일이 그 값으로 맞춰진다(반대 순서면 기본값이 원래 값으로 돌아간다)
        notes_mod.save(self.out_dir, self.code or "", data)
        for path, value in rewrites:
            self._rewrite_completed(path, value)
        self._go(Step.C5)
        return {}

    # ------------------------------------------------------------ C-5 · 검사

    def finish_session(self) -> Report:
        """check_sessions를 돌려 check-<코드>.txt를 쓰고 upload-<코드>.zip을 만든다."""
        self._expect(Step.C5)
        code, folder = self.code or "", self.out_dir
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.d.check.main([code, "--dir", str(folder)])
        text = buf.getvalue()
        check_path = folder / f"check-{code}.txt"
        check_path.write_text(text, encoding="utf-8")
        files = self.session_files(folder, code)
        notes_file = notes_mod.notes_path(folder, code)
        zip_path = folder / f"upload-{code}.zip"
        tmp = zip_path.with_name(zip_path.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in [*files, notes_file, check_path]:
                if f.exists():
                    z.write(f, f.name)
        tmp.replace(zip_path)
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        saved, _ = self._scan(folder, code)
        unsaved = [p.page_id for p in self.plan.pages if p.page_id not in saved]
        self.report = Report(text=text, ok=rc == 0, check_path=check_path, zip_path=zip_path, zipped=names,
                             unsaved=unsaved)
        self._go(Step.DONE)
        return self.report

    @staticmethod
    def session_files(folder: Path, code: str) -> list[Path]:
        """그 참가자의 세션 json(검증 실패 *.invalid.json 포함). .partial은 넣지 않는다."""
        out = []
        for f in sorted(folder.glob(f"human-session-{code}-*.json")):
            if f.name.endswith(".invalid.json"):
                out.append(f)
                continue
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("participant_code") == code:
                    out.append(f)
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
        return out

    # ------------------------------------------------------------ 이미 끝난 세션 메모 (진행자가 읽어 주던 방식)

    def before_app_pages(self, folder: Path, code: str) -> tuple[list[dict[str, Any]], str | None]:
        """(페이지 목록, 오류). 세션 파일은 읽기만 한다."""
        try:
            code_number(code)
        except ValueError:
            return [], "참가자 코드는 P01 같은 형식입니다"
        existing = notes_mod.load(folder, code)
        if existing and existing.get("session", {}).get("app_version") != notes_mod.BEFORE_APP:
            return [], f"notes-{code}.json이 진행 프로그램으로 이미 만들어져 있습니다. 덮어쓰지 않습니다"
        saved, _ = self._scan(folder, code)
        rows = []
        for p in self.plan.pages:
            entry = notes_mod.page_entry(existing, p.page_id) if existing else None
            rows.append({"page": p, "saved": p.page_id in saved,
                         "completed": self._file_completed(saved[p.page_id][-1]) if p.page_id in saved else None,
                         "issue_codes": list((entry or {}).get("issue_codes") or []),
                         "note": (entry or {}).get("note") or ""})
        if not saved:
            return rows, f"{folder}에 {code}의 세션 파일이 없습니다"
        return rows, None

    def save_before_app_notes(self, folder: Path, code: str, facilitator: str,
                              entries: dict[str, tuple[list[int], str]]) -> Path:
        """세션 파일은 건드리지 않고 notes-<코드>.json만 쓴다. app_version 등은 'before-app', 항목은 읽어 주던 방식."""
        version = notes_mod.READ_ALOUD
        err = self.check_github(facilitator)
        if err:
            raise ValueError(err)
        rows, err = self.before_app_pages(folder, code)
        if err:
            raise ValueError(err)
        for codes, note in entries.values():
            e = notes_mod.check_note(codes, note, version)
            if e:
                raise ValueError(e)
        saved, _ = self._scan(folder, code)
        starts = []
        for files in saved.values():
            for f in files:
                try:
                    starts.append(json.loads(f.read_text(encoding="utf-8"))["started_at"])
                except (OSError, json.JSONDecodeError, KeyError, TypeError):
                    continue
        b = notes_mod.BEFORE_APP
        data = notes_mod.new({"participant_code": code, "facilitator": facilitator, "app_version": b,
                              "repo_commit": b, "site_manifest_hashes": b, "os": b, "screen_avail_height": b,
                              "started_at": min(starts) if starts else None, "run_mode": b,
                              "procedure_version": version})
        for row in rows:
            p = row["page"]
            codes, note = entries.get(p.page_id, ([], ""))
            notes_mod.upsert_page(data, notes_mod.apply_note(
                {"order": p.order, "page_id": p.page_id, "participant_reported": None, "completed": row["completed"],
                 "completed_confirmed": row["completed"], "confirmation_changed": False if row["saved"] else None,
                 "auto_stopped_3min": False if row["saved"] else None}, codes, note))
        return notes_mod.save(folder, code, data)
