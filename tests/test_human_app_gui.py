"""진행 프로그램 화면(tkinter) 테스트: 버전 표시와 창 위치 복원.

화면이 없는 환경(CI 등)에서는 건너뛴다. 페이지는 합성 HTML, Chromium은 헤드리스, 저장은 임시 폴더, 코드는 P05 범위의
가짜 세션만 쓴다(참가자 데이터 없음). 기대값: 창이 화면 안(0 ≤ x, x + 너비 ≤ 화면 너비 …)에 있고 패널 모드가 아니다.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = ROOT / "human-study"
if str(HS) not in sys.path:
    sys.path.insert(0, str(HS))

try:
    import tkinter as tk

    _root_probe = tk.Tk()
    _root_probe.destroy()
    HAVE_DISPLAY = True
except Exception:  # noqa: BLE001  화면 없음(CI)
    HAVE_DISPLAY = False

from tests.test_human_app import CHECK, PLAN, SESSION, STABLE, _serve_fixture  # noqa: E402

if HAVE_DISPLAY:
    from app.controller import Controller, Deps, Step  # noqa: E402
    from app.gui import App  # noqa: E402
    from app.sites import Check  # noqa: E402

VERSION = "20261114-3ef3886"


@unittest.skipUnless(HAVE_DISPLAY, "화면(디스플레이)이 없다")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _serve_fixture()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/page.html"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.data = base / "StepMeter-human"
        self.opened: list = []
        self.ctrl = Controller(Deps(
            plan=PLAN, session=SESSION, check=CHECK, data_dir=self.data, practice_dir=base / "practice",
            settings_path=base / "settings.json", url_for=lambda pid: self.url,
            env_checks=lambda: [Check("사이트 서버", True, "fake")], screen_size=lambda: (1920, 1032),
            session_info={"app_version": VERSION, "repo_commit": "0" * 40, "site_manifest_hashes": {},
                          "os": "test", "run_mode": "exe-windows"},
            headless=True, page_limit_s=1.0, on_page_open=lambda page, loop: self.opened.append((page, loop))))
        import app.gui as gui_mod
        orig_open = gui_mod.open_folder
        gui_mod.open_folder = lambda path: None  # 검사 화면에서 탐색기를 열지 않는다
        self.addCleanup(setattr, gui_mod, "open_folder", orig_open)
        self.root = tk.Tk()
        self.addCleanup(self._close_root)
        self.app = App(self.root, self.ctrl, None, None)
        self.pump(0.8)  # 시작 직후 위치 확인(0.15·0.6초 뒤)까지

    def _close_root(self):
        for after_id in self.root.tk.call("after", "info"):
            self.root.after_cancel(after_id)
        self.root.destroy()

    def pump(self, seconds: float, until=None) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            if until is not None and until():
                return
            time.sleep(0.02)

    def assert_on_screen(self, where: str) -> None:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y, w, h = self.app.window_rect()
        self.assertFalse(self.app.docked, where)
        self.assertGreaterEqual(x, 0, where)
        self.assertGreaterEqual(y, 0, where)
        self.assertLessEqual(x + w, sw, f"{where}: {w}x{h}+{x}+{y}")
        self.assertLessEqual(y + h, sh, f"{where}: {w}x{h}+{x}+{y}")
        self.assertGreater(w, 600, where)  # 패널 크기가 아니다

    def test_title_and_start_screen_show_version(self):
        self.assertEqual(self.root.title(), f"StepMeter 사람 실험 {VERSION}")
        self.assertEqual(self.app.version_label.cget("text"), f"버전 {VERSION} · 실행 방식 exe")
        self.assert_on_screen("시작 화면")

    def test_off_screen_window_is_put_back(self):
        sw = self.root.winfo_screenwidth()
        # 패널 자리에 남은 일반 크기 창 (exe에서 본 증상)
        self.root.geometry(f"1200x900+{sw - 300}+0")
        self.assertTrue(self.app.off_screen())
        self.assertTrue(self.app.ensure_on_screen())
        self.assert_on_screen("안전장치를 직접 부른 뒤")
        self.root.geometry(f"1200x900+{sw - 300}+0")
        self.assertTrue(self.app.off_screen())
        self.pump(1.5, until=lambda: not self.app.off_screen())  # 1초마다 도는 안전장치
        self.assert_on_screen("1초 안전장치 뒤")
        self.assertTrue(any("화면 밖" in line for line in self.app.place_log))

    def _to_last_task(self):
        for i, p in enumerate(PLAN.pages[:5]):  # ①~⑤는 이미 했다고 친다(합성 파일)
            meta = SESSION.SessionMeta("P05", p.page_id, "mouse", 6)
            SESSION.save_session(SESSION.build_session(meta, STABLE, True,
                                                       datetime(2026, 11, 14, 1, i, tzinfo=timezone.utc)), self.data)
        c = self.ctrl
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.resume_continue()
        c.handed_over()
        c.participant_begin(None)
        self.pump(0.5)
        self.assertEqual(c.current_page.order, 6)

    def _finish_last_task(self, how: str) -> None:
        c = self.ctrl
        self._to_last_task()
        c.launch_page()
        self.pump(30, until=lambda: c.page_visible or c.step != Step.P_RUNNING)
        self.pump(0.5)
        self.assertTrue(self.app.docked, "진행 중에는 패널")
        if how == "done":
            c.report_participant(True)
        elif how == "gave_up":
            c.report_participant(False)
        elif how == "close":
            page, loop = self.opened[-1]
            asyncio.run_coroutine_threadsafe(page.close(), loop)
        # timeout: 1초 제한
        self.pump(30, until=lambda: c.step in (Step.P_BETWEEN, Step.P_FINISHED, Step.P_ERROR))
        self.assertNotEqual(c.step, Step.P_ERROR, c.error)
        self.pump(0.8)
        self.assert_on_screen(f"{how}: 패널이 끝난 뒤")
        if c.step == Step.P_BETWEEN:
            c.between_next()
            self.pump(0.8)
        self.assertEqual(c.step, Step.P_FINISHED)
        c.returned()  # [돌려줬어요] → 진행자 확인표
        self.pump(1.0)
        self.assertEqual(c.step, Step.REVIEW)
        self.assert_on_screen(f"{how}: 확인표")
        self.assertTrue(any("일반" in line for line in self.app.place_log))

    def test_window_back_on_screen_after_done(self):
        self._finish_last_task("done")

    def test_window_back_on_screen_after_gave_up(self):
        self._finish_last_task("gave_up")

    def test_window_back_on_screen_after_timeout(self):
        self._finish_last_task("timeout")

    def test_window_back_on_screen_after_window_closed(self):
        self._finish_last_task("close")

    def test_full_six_tasks_then_review_c5_done(self):
        c = self.ctrl
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.c1_pass()
        c.c2_signed()
        c.handed_over()
        c.participant_begin("6")
        self.pump(0.3)
        for _ in range(6):
            c.launch_page()
            self.pump(30, until=lambda: c.page_visible)
            self.pump(0.6)
            c.report_participant(True)
            self.pump(30, until=lambda: c.step != Step.P_RUNNING)
            self.pump(0.5)
            self.assert_on_screen(f"과업 뒤 {c.step.value}")
        c.returned()
        self.pump(0.8)
        self.assert_on_screen("확인표")
        self.assertEqual(c.submit_review({r.page.page_id: (r.confirmed, [], "") for r in c.review_rows()}), {})
        self.pump(0.8)
        self.assert_on_screen("마지막 안내")
        c.finish_session()
        self.pump(0.8)
        self.assert_on_screen("검사")
        notes = json.loads((self.data / "notes-P05.json").read_text(encoding="utf-8"))
        self.assertEqual(notes["session"]["app_version"], VERSION)


if __name__ == "__main__":
    unittest.main()
