"""Real-browser SPA and numeric mapping regressions on a local synthetic fixture.

These authored fixture checks do not certify the three real SPA acceptance run.
"""
from pathlib import Path
import unittest

from playwright.async_api import async_playwright
from worker.collect.collector import observe, record_first_view, resolve_element, snapshot
from benchmark.spa_eval import evaluate_state, numeric_click, resolve_truth

FIXTURE = Path(__file__).parent / "fixtures/collect/spa/index.html"


class SpaBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={"width": 800, "height": 600})
        await self.page.set_content(FIXTURE.read_text(encoding="utf-8"), wait_until="load")
        await record_first_view(self.page)

    async def numbered(self, name):
        items = await observe(self.page)
        return next(o["el_id"] for o in items if o["name"] == name)

    async def test_cookie_modal_hides_target_without_raw_omission(self):
        number = await self.numbered("Covered action")
        self.assertTrue((await snapshot(self.page, number)).occluded)
        await self.page.locator("#accept").click()
        number = await self.numbered("Covered action")
        self.assertFalse((await snapshot(self.page, number)).occluded)

    async def test_recycled_node_rejects_old_number_then_reobserve_resolves(self):
        number = await self.numbered("Row 0")
        await self.page.locator("#list").evaluate("el => el.scrollTop = 1500")
        await self.page.wait_for_function("document.querySelector('#row').textContent === 'Row 50'")
        with self.assertRaises(Exception):
            await resolve_element(self.page, number)
        number = await self.numbered("Row 50")
        handle = await resolve_element(self.page, number)
        self.addAsyncCleanup(handle.dispose)
        self.assertEqual(await handle.inner_text(), "Row 50")

    async def test_removed_target_never_remaps_to_next_number(self):
        number = await self.numbered("Open dialog")
        await self.page.locator("#open-dialog").evaluate("el => el.remove()")
        with self.assertRaises(Exception):
            await resolve_element(self.page, number)

    async def test_numbered_click_works_in_open_shadow_and_frame(self):
        for key, selector, frame, name in (("shadow", "#shadow-button", None, "Shadow action"),
                                            ("frame", "#frame-button", "#frame", "Frame action")):
            spec = {"key": key, "selector": selector, "name": name, "role": "button", "occluded": False}
            if frame:
                spec["frame"] = frame
            truth = await resolve_truth(self.page, [spec])
            items = await observe(self.page)
            matches = evaluate_state(truth, items)["matches"]
            result = await numeric_click(self.page, key, truth, items, matches)
            self.assertEqual(result["status"], "matched")

    async def test_repeated_open_close_and_route_reobserve(self):
        await self.page.locator("#accept").click()
        for _ in range(3):
            handle = await resolve_element(self.page, await self.numbered("Open dialog"))
            await handle.click()
            await handle.dispose()
            handle = await resolve_element(self.page, await self.numbered("Close dialog"))
            await handle.click()
            await handle.dispose()
            self.assertFalse(await self.page.locator("#modal").is_visible())
        number = await self.numbered("Overview action")
        await self.page.locator("#route").click()
        await self.page.wait_for_function("document.querySelector('#route-target').textContent === 'Details action'")
        with self.assertRaises(Exception):
            await resolve_element(self.page, number)
        handle = await resolve_element(self.page, await self.numbered("Details action"))
        await handle.dispose()

    async def test_select_option_reorder_rejects_old_number(self):
        await self.page.evaluate("""() => {
            const el=document.createElement('select'); el.setAttribute('aria-label','Choice');
            el.innerHTML='<option value="a">A</option><option value="b">B</option>';
            el.style='position:absolute;top:300px';document.body.append(el);
        }""")
        number = await self.numbered("Choice")
        await self.page.locator("select").evaluate("el => el.prepend(el.lastElementChild)")
        with self.assertRaises(Exception):
            await resolve_element(self.page, number)

    async def test_id_validation_does_not_accept_boolean_or_out_of_range(self):
        await observe(self.page)
        for value in (True, 0, -1, 1.0):
            with self.assertRaises(ValueError):
                await resolve_element(self.page, value)
        with self.assertRaises(Exception):
            await resolve_element(self.page, 10000)
