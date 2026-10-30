"""수집 JS 통합 테스트 (개발계획서 15.3 "Driver + 수집 JS").

기대값은 tests/fixtures/collect/page.html의 고정 위치(800×600 뷰포트)에서 손으로 계산했다.
실행 전 `npm run build:collect` 필요.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from playwright.async_api import async_playwright

from worker.collect.collector import observe, record_first_view, snapshot
from worker.schemas import BBox

HTML = Path(__file__).resolve().parent / "fixtures" / "collect" / "page.html"


class CollectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.browser = await self.playwright.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={"width": 800, "height": 600})
        await self.page.set_content(HTML.read_text(encoding="utf-8"))
        await record_first_view(self.page)
        self.items = await observe(self.page)

    def el_id(self, name):
        return next(i["el_id"] for i in self.items if i["name"] == name)

    async def snap(self, name):
        return await snapshot(self.page, self.el_id(name))

    async def test_observe_filters_hidden_and_offscreen(self):
        names = {i["name"] for i in self.items}
        self.assertLessEqual({"구매", "도움말", "결제", "그림자", "프레임", "여기", ""}, names)
        self.assertFalse({"숨김1", "숨김2", "숨김3", "숨김4", "더보기"} & names)
        self.assertEqual([i["el_id"] for i in self.items], list(range(1, len(self.items) + 1)))

    async def test_plain_button(self):
        s = await self.snap("구매")
        self.assertEqual((s.tag, s.role, s.landmark, s.context), ("button", "button", "main", "document"))
        self.assertEqual(s.bbox, BBox(x=100, y=100, width=120, height=40))
        self.assertEqual((s.viewport.width, s.viewport.height), (800, 600))
        self.assertEqual(s.style.color, "rgb(119, 119, 119)")
        self.assertEqual(s.style.background_color, "rgb(255, 255, 255)")
        self.assertEqual((s.style.font_size, s.style.font_weight, s.style.opacity), (16, 700, 1))
        self.assertEqual([layer.tag for layer in s.bg_chain], ["button", "main", "body", "html"])
        self.assertEqual(s.bg_chain[2].background_color, "rgb(240, 240, 240)")
        self.assertFalse(s.occluded)
        self.assertIsNone(s.occluder)
        self.assertIsNone(s.label_text)
        self.assertFalse(s.inline_in_text)
        self.assertEqual((s.in_first_view, s.first_view_scroll_px), (True, 0))

    async def test_nearby_targets_within_48px(self):
        # 중심 (160, 120). 도움말 x=200 → 40px, 멀리 x=300 → 140px, 메뉴 y=0..20 → 100px
        s = await self.snap("구매")
        self.assertEqual([(t.role, t.name) for t in s.nearby_targets], [("link", "도움말")])
        self.assertEqual(s.nearby_targets[0].bbox, BBox(x=200, y=100, width=50, height=20))

    async def test_landmarks(self):
        self.assertEqual((await self.snap("홈")).landmark, "banner")
        self.assertEqual((await self.snap("메뉴")).landmark, "navigation")
        self.assertEqual((await self.snap("제출")).landmark, "main")  # 이름 없는 form은 랜드마크 아님

    async def test_unnamed_button_gets_label_text(self):
        s = await self.snap("")
        self.assertEqual((s.name, s.label_text), ("", "수량"))

    async def test_inline_link_in_sentence(self):
        self.assertTrue((await self.snap("여기")).inline_in_text)
        self.assertFalse((await self.snap("도움말")).inline_in_text)

    async def test_occluded_by_cookie_banner(self):
        s = await self.snap("결제")  # 중심 (150, 520), 배너 y=480..600
        self.assertTrue(s.occluded)
        self.assertEqual((s.occluder.tag, s.occluder.role, s.occluder.name), ("div", "dialog", "쿠키 동의"))
        self.assertEqual(s.occluder.bbox, BBox(x=0, y=480, width=800, height=120))

    async def test_open_shadow(self):
        s = await self.snap("그림자")
        self.assertEqual((s.context, s.landmark), ("open_shadow", "main"))
        self.assertEqual(s.bbox, BBox(x=500, y=300, width=60, height=30))
        self.assertFalse(s.occluded)

    async def test_same_origin_iframe_uses_top_coordinates(self):
        s = await self.snap("프레임")  # iframe (400, 100) + 버튼 (10, 20)
        self.assertEqual(s.context, "same_origin_iframe")
        self.assertEqual(s.bbox, BBox(x=410, y=120, width=80, height=30))
        self.assertEqual(
            [layer.tag for layer in s.bg_chain], ["button", "body", "html", "iframe", "main", "body", "html"]
        )
        self.assertFalse(s.occluded)

    async def test_below_fold_after_scroll(self):
        await self.page.evaluate("() => window.scrollTo(0, 600)")
        self.items = await observe(self.page)
        s = await self.snap("더보기")  # 문서 기준 중심 y = 1020
        self.assertEqual(s.bbox, BBox(x=100, y=400, width=100, height=40))
        self.assertEqual((s.scroll.x, s.scroll.y), (0, 600))
        self.assertEqual((s.in_first_view, s.first_view_scroll_px), (False, 420))  # 1020 − 600

    async def test_element_added_after_load(self):
        await self.page.evaluate(
            """() => document.body.insertAdjacentHTML('beforeend',
            '<button style="position:absolute; left:600px; top:400px; width:50px; height:20px">새 버튼</button>')"""
        )
        self.items = await observe(self.page)
        s = await self.snap("새 버튼")
        self.assertEqual((s.in_first_view, s.first_view_scroll_px), (False, None))

    async def test_stale_el_id_raises(self):
        with self.assertRaises(Exception):
            await snapshot(self.page, len(self.items) + 1)


if __name__ == "__main__":
    unittest.main()
