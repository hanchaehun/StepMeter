"""참가자 화면 내용. gui.py가 그리고 테스트가 문구를 검사한다.

참가자 화면에는 과업 문장, ④의 데모 안내, ①의 입력할 값, 버튼만 나온다.
진행자용 말("읽어 주세요" 등), 결함, 끝난 시점, 남은 시간, page_id는 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .controller import Controller, Step


@dataclass
class Screen:
    heading: str
    texts: list[tuple[str, str]] = field(default_factory=list)  # (모양, 문장) 모양: big | normal | values | alert
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (동작, 글자)
    hours_input: bool = False
    panel: bool = False  # 진행 중: 화면 오른쪽 작은 패널

    def all_text(self) -> str:
        return "\n".join([self.heading, *(t for _, t in self.texts), *(b for _, b in self.buttons)])


def window_title(version: str) -> str:
    return f"StepMeter 사람 실험 {version}"


def version_line(version: str, run_mode: str) -> str:
    """진행자 시작 화면 아래쪽 한 줄. run_mode는 notes의 값(exe-windows, source-mac 등)."""
    how = "exe" if run_mode.startswith("exe") else "소스"
    return f"버전 {version} · 실행 방식 {how}"


def _task_texts(c: Controller) -> list[tuple[str, str]]:
    p = c.current_page
    out: list[tuple[str, str]] = []
    if p.preface_say:
        out.append(("normal", p.preface_say))
    out.append(("big", p.task_say))
    if p.show_values:
        out.append(("label", c.plan.p("values_label")))
        out += [("values", v) for v in p.show_values]
    return out


def participant_screen(c: Controller) -> Screen:
    plan = c.plan
    step = c.step
    if step == Step.P_INTRO:
        s = Screen("안내", [("big", plan.p("intro"))], [("begin", plan.p("intro_button"))])
        if c.needs_hours:
            s.texts.append(("normal", plan.p("hours_question")))
            s.hours_input = True
        return s
    if step == Step.P_TASK:
        p = c.current_page
        heading = plan.p("task_heading").format(n=p.order, total=len(plan.pages))
        return Screen(heading, [*_task_texts(c), ("normal", plan.p("task_prompt"))],
                      [("start", plan.p("start_button"))])
    if step == Step.P_RUNNING:
        p = c.current_page
        heading = plan.p("task_heading").format(n=p.order, total=len(plan.pages))
        s = Screen(heading, [*_task_texts(c), ("small", plan.p("panel_note"))],
                   [("done", plan.p("done_button")), ("give_up", plan.p("give_up_button"))], panel=True)
        return s
    if step == Step.P_BETWEEN:
        r = c.result
        text = plan.p("time_up") if r is not None and r.reported == "timeout" else plan.p("window_closed")
        return Screen("", [("alert", text)], [("next", plan.p("next_button"))])
    if step == Step.P_FINISHED:
        return Screen("", [("big", plan.p("finished"))], [("returned", plan.p("returned_button"))])
    raise ValueError(f"참가자 화면이 아니다: {step}")
