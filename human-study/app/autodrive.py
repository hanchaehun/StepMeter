"""개발자 확인용 자동 진행 (--auto). 연습 모드(P00)로 진짜 창·진짜 Chromium을 띄우고 버튼을 대신 누른다.

참가자 역할은 하지 않는다(과업을 수행하지 않고 몇 초 뒤 [완료]). 정해진 한 차례는 버튼을 누르지 않아
3분(또는 --auto-limit) 자동 종료를 확인한다. 본 데이터 폴더에는 쓰지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .controller import Step


class AutoDriver:
    delay_ms = 1500  # 화면마다 잠깐 머문다 (스크린샷용)

    def __init__(self, timeout_page: int = 3, done_path: Path | None = None) -> None:
        self.timeout_page = timeout_page
        self.done_path = done_path
        self.finish_scheduled: set[int] = set()

    def _end(self, app: Any, result: dict[str, Any]) -> None:
        if self.done_path is not None:
            self.done_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        app.root.after(2000, app.root.destroy)

    def __call__(self, app: Any, key: Any) -> None:
        c = app.ctrl
        if app.rendered != key:
            return  # 그 사이 화면이 바뀌었다
        step = c.step
        try:
            if step == Step.SETUP:
                if not app.fac_var.get():
                    app.fac_var.set(c.facilitator_choices()[0])
                app.practice_var.set(True)
                c.choose(app.selected_github(), c.plan.practice_code, True)
            elif step == Step.PREFLIGHT:
                if app.preflight_running:
                    return
                if not app.mouse_var.get():
                    app.mouse_var.set(True)
                if not c.checks:
                    app.run_preflight()
                elif c.preflight_ok:
                    c.start()
                else:
                    self._end(app, {"ok": False, "stage": "preflight",
                                    "checks": [(x.name, x.ok, x.detail) for x in c.checks]})
            elif step == Step.C1:
                c.c1_pass()
            elif step == Step.C2:
                c.c2_signed()
            elif step == Step.RESUME:
                c.resume_continue()
            elif step == Step.HANDOVER:
                c.handed_over()
            elif step == Step.P_INTRO:
                c.participant_begin("6")
            elif step == Step.P_TASK:
                c.launch_page()
            elif step == Step.P_RUNNING:
                order = c.current_page.order
                if c.page_visible and order != self.timeout_page and order not in self.finish_scheduled:
                    self.finish_scheduled.add(order)
                    # ②는 [그만할게요], 나머지는 [다 했어요]
                    app.root.after(3000, lambda: c.report_participant(order != 2))
            elif step == Step.P_BETWEEN:
                c.between_next()
            elif step == Step.P_FINISHED:
                c.returned()
            elif step == Step.REVIEW:
                entries: dict[str, tuple[bool | None, list[int], str]] = {
                    r.page.page_id: (r.confirmed, [], "") for r in c.review_rows()}
                # ④: 참가자는 [다 했어요]였지만 진행자가 미완료로 확정 → 그 파일의 completed만 바뀐다
                p4 = c.plan.pages[3].page_id
                entries[p4] = (False, [5], "자동 확인: 진행자가 미완료로 확정")
                errors = c.submit_review(entries)
                if errors:
                    self._end(app, {"ok": False, "stage": "review", "errors": errors})
            elif step == Step.C5:
                c.finish_session()
            elif step == Step.DONE:
                rep = c.report
                self._end(app, {"ok": bool(rep and rep.ok), "stage": "done", "code": c.code,
                                "folder": str(c.out_dir), "check": rep.text if rep else None,
                                "zip": str(rep.zip_path) if rep else None, "zipped": rep.zipped if rep else []})
            elif step in (Step.P_ERROR, Step.ABORTED):
                self._end(app, {"ok": False, "stage": step.value, "error": c.error})
        except RuntimeError as e:
            self._end(app, {"ok": False, "stage": step.value, "error": str(e)})
