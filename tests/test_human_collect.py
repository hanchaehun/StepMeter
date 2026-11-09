"""사람 데이터 수집 JS 테스트 (개발계획서 9.1 "수집", 동의서 3·4절).

tests/fixtures/human-study/page.html의 고정 좌표(800×600 뷰포트)에서 기대값을 손으로 계산했다.
실행 전 `npm run build:collect` 필요 (요소 지문은 이원준 님 수집 번들의 observe()를 쓴다).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "worker" / "collect" / "dist" / "collect.js"
COLLECT = ROOT / "human-study" / "collect.js"
HTML = ROOT / "tests" / "fixtures" / "human-study" / "page.html"

# 테스트용 __hsPush: 이벤트를 배열에 쌓는다. 실제 세션에서는 Python expose_function이 대신한다.
FAKE_PUSH = "window.__hsEvents = []; window.__hsPush = (ev) => { window.__hsEvents.push(ev); };"


class HumanCollectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.browser = await self.playwright.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context(viewport={"width": 800, "height": 600})
        self.start_ms = 1_700_000_000_000
        await self.context.add_init_script(
            FAKE_PUSH + f"window.__hsStart = {self.start_ms}; window.__hsOrigin = 'file://';" + BUNDLE.read_text(encoding="utf-8") + COLLECT.read_text(encoding="utf-8")
        )
        self.page = await self.context.new_page()
        # set_content는 document.open()으로 문서를 다시 써서 리스너가 지워진다. 실제 세션처럼 goto로 연다.
        await self.page.goto(HTML.as_uri())
        await self.page.wait_for_timeout(450)  # load 뒤 300ms 안정 → stable

    async def events(self):
        return await self.page.evaluate("() => window.__hsEvents")

    async def test_first_event_is_stable(self):
        ev = await self.events()
        self.assertEqual(ev[0]["type"], "stable")
        self.assertEqual((ev[0]["x"], ev[0]["y"], ev[0]["target_key"]), (None, None, None))

    async def test_every_event_has_exactly_the_five_fields(self):
        await self.page.mouse.click(160, 120)
        for e in await self.events():
            self.assertEqual(set(e), {"t_ms", "type", "x", "y", "target_key"}, e)
            self.assertIsInstance(e["t_ms"], int)
            self.assertGreaterEqual(e["t_ms"], 0)

    async def test_click_records_down_up_click_with_fingerprint(self):
        await self.page.mouse.click(160, 120)  # 구매 버튼 중심 (100+60, 100+20)
        ev = [e for e in await self.events() if e["type"] in ("down", "up", "click")]
        self.assertEqual([e["type"] for e in ev], ["down", "up", "click"])
        for e in ev:
            self.assertEqual(e["target_key"], "button|button|구매||main")
            self.assertEqual((e["x"], e["y"]), (160, 120))

    async def test_click_on_plain_text_has_null_target(self):
        await self.page.mouse.click(120, 310)  # <p> 본문 글 위
        clicks = [e for e in await self.events() if e["type"] == "click"]
        self.assertEqual(len(clicks), 1)
        self.assertIsNone(clicks[0]["target_key"])

    async def test_key_events_have_no_text(self):
        await self.page.mouse.click(200, 176)  # 입력칸 중심
        await self.page.keyboard.type("abc")
        keys = [e for e in await self.events() if e["type"] == "key"]
        self.assertEqual(len(keys), 3)  # 글자 수 = 키 이벤트 수
        self.assertEqual(keys[0]["target_key"], "input|textbox|이메일||main")
        self.assertEqual((keys[0]["x"], keys[0]["y"]), (None, None))
        self.assertNotIn("abc", json.dumps(await self.events(), ensure_ascii=False))

    async def test_move_is_throttled_to_about_60hz(self):
        # 100번 이동(2ms 간격)을 16ms 묶음으로 → 개수 ≤ 경과시간/16 + 1, 최소 1개
        elapsed = await self.page.evaluate(
            """async () => {
              const t0 = performance.now();
              for (let i = 0; i < 100; i++) {
                document.dispatchEvent(new PointerEvent('pointermove', { clientX: 300 + i, clientY: 300, bubbles: true }));
                await new Promise(r => setTimeout(r, 2));
              }
              return performance.now() - t0;
            }"""
        )
        moves = [e for e in await self.events() if e["type"] == "move"]
        self.assertGreaterEqual(len(moves), 1)
        self.assertLessEqual(len(moves), int(elapsed // 16) + 1, f"elapsed={elapsed:.0f}ms")
        self.assertLess(len(moves), 100)  # 100개 전부 기록되면 묶음이 안 된 것
        self.assertTrue(all(isinstance(e["x"], (int, float)) and isinstance(e["y"], (int, float)) for e in moves))

    async def test_scroll_records_last_pointer_position(self):
        await self.page.mouse.move(400, 300)
        await self.page.mouse.wheel(0, 500)
        await self.page.wait_for_timeout(100)
        scrolls = [e for e in await self.events() if e["type"] == "scroll"]
        self.assertGreaterEqual(len(scrolls), 1)
        self.assertEqual((scrolls[0]["x"], scrolls[0]["y"]), (400, 300))
        self.assertIsNone(scrolls[0]["target_key"])

    async def test_stable_after_dom_change(self):
        before = len([e for e in await self.events() if e["type"] == "stable"])
        await self.page.evaluate("() => document.body.append(document.createElement('p'))")
        await self.page.wait_for_timeout(450)
        after = [e for e in await self.events() if e["type"] == "stable"]
        self.assertEqual(len(after), before + 1)

    async def test_t_ms_is_relative_to_start(self):
        # __hsStart는 1.7e12 (과거 시각). Date.now() − start 는 양수이고 1초 이상 차이가 난다
        ev = await self.events()
        self.assertGreater(ev[0]["t_ms"], 1000)
        later = await self.page.evaluate("() => Date.now()") - self.start_ms
        self.assertLessEqual(ev[-1]["t_ms"], later)

    # ---- 리뷰 수정 패스 ----
    async def test_keyboard_submit_does_not_record_fake_click(self):
        # Enter로 폼 제출 → Chromium이 detail=0, (0,0)인 합성 click을 submit 버튼에 보낸다. 기록하지 않는다
        await self.page.mouse.click(200, 176)      # 입력칸
        await self.page.keyboard.press("Enter")
        ev = await self.events()
        clicks = [e for e in ev if e["type"] == "click"]
        self.assertEqual(len(clicks), 1, clicks)   # 입력칸을 누른 진짜 클릭만
        self.assertEqual((clicks[0]["x"], clicks[0]["y"]), (200, 176))
        self.assertEqual(len([e for e in ev if e["type"] == "key"]), 1)  # Enter는 key 1건

    async def test_label_click_records_one_click(self):
        # label을 누르면 브라우저가 input에 합성 click(detail=0)을 한 번 더 보낸다 → 1건만 남긴다
        await self.page.mouse.click(440, 112)      # "동의합니다" label 중심 (400+40, 100+12)
        clicks = [e for e in await self.events() if e["type"] == "click"]
        self.assertEqual(len(clicks), 1, clicks)
        self.assertEqual((clicks[0]["x"], clicks[0]["y"]), (440, 112))

    async def test_repeat_keydown_is_ignored(self):
        await self.page.mouse.click(200, 176)
        await self.page.evaluate(
            """() => { for (let i = 0; i < 5; i++) document.activeElement.dispatchEvent(
                 new KeyboardEvent('keydown', { key: 'Backspace', repeat: i > 0, bubbles: true })); }"""
        )
        keys = [e for e in await self.events() if e["type"] == "key"]
        self.assertEqual(len(keys), 1)  # 자동 반복(repeat=true) 4건은 세지 않는다

    async def test_t_ms_is_taken_before_fingerprint_work(self):
        # down/up/click의 t_ms 차이는 60ms 안 (observe() 시간이 더해지면 벌어진다)
        await self.page.mouse.click(160, 120)
        ev = [e for e in await self.events() if e["type"] in ("down", "up", "click")]
        self.assertLessEqual(ev[-1]["t_ms"] - ev[0]["t_ms"], 60)

    async def test_not_installed_in_iframe(self):
        # 프레임 안에서는 설치되지 않는다 (프레임 좌표·stable이 섞이지 않게)
        installed = await self.page.evaluate(
            """async () => {
              const f = document.createElement('iframe');
              f.srcdoc = '<button id=b>안</button>';
              document.body.append(f);
              await new Promise(r => f.onload = r);
              return !!f.contentWindow.__hsInstalled;
            }"""
        )
        self.assertFalse(installed)


if __name__ == "__main__":
    unittest.main()
