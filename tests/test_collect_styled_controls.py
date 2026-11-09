"""Visible native indicator expectations authored from the MUI DOM pattern.

The input is the actual target and retains native role, name and 38px geometry.
Opaque/display-hidden/offscreen controls are negative fixtures, not relabeled truth.
"""
import unittest
from playwright.async_api import async_playwright
from worker.collect.collector import observe, resolve_element, snapshot

STYLE = '''<style>
label {display:block;position:relative;width:150px;height:40px}
.control {display:inline-block;position:relative;width:38px;height:38px}
input {position:absolute;inset:0;margin:0;width:38px;height:38px;opacity:0;z-index:1}
svg {position:absolute;left:9px;top:9px;width:20px;height:20px}
</style>'''
INDICATOR = '<svg aria-hidden="true"><rect width="20" height="20" fill="blue"/></svg>'


def control(name, attrs='', wrapper=''):
    return f'<label style="{wrapper}"><span class="control"><input type="checkbox" {attrs}>{INDICATOR}</span>{name}</label>'


class StyledControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 800, 'height': 600})

    async def test_visible_native_target_keeps_semantics_and_clicks(self):
        await self.page.set_content(STYLE + control('Women'))
        rows = await observe(self.page)
        self.assertEqual([(r['name'], r['role']) for r in rows], [('Women', 'checkbox')])
        snap = await snapshot(self.page, rows[0]['el_id'])
        self.assertEqual(snap.tag, 'input')
        self.assertEqual(snap.style.opacity, 0)
        self.assertEqual(snap.bbox.width, 38)
        self.assertFalse(snap.occluded)
        handle = await resolve_element(self.page, rows[0]['el_id'])
        try:
            await handle.click()
        finally:
            await handle.dispose()
        self.assertTrue(await self.page.locator('input').is_checked())

    async def test_hidden_or_unrepresented_controls_stay_excluded(self):
        html = STYLE + control('Visible') + control('Hidden parent', wrapper='opacity:0')
        html += control('Hidden visibility', attrs='style="visibility:hidden"')
        html += control('Hidden display', attrs='style="display:none"')
        html += control('Offscreen', wrapper='position:absolute;top:3000px')
        html += control('No pointer', attrs='style="pointer-events:none"')
        html += '<label><span class="control"><input type="checkbox"></span>No indicator</label>'
        html += '<label><span class="control"><input type="text">'+INDICATOR+'</span>Text input</label>'
        await self.page.set_content(html)
        self.assertEqual([r['name'] for r in await observe(self.page)], ['Visible'])

    async def test_raw_collection_preserves_occluded_styled_target(self):
        await self.page.set_content(STYLE + control('Covered') +
                                    '<div style="position:absolute;left:0;top:0;width:200px;height:60px;background:red;z-index:10"></div>')
        rows = await observe(self.page)
        self.assertEqual([r['name'] for r in rows], ['Covered'])
        self.assertTrue(rows[0]['occluded'])

    async def test_radio_supported_but_unrelated_indicator_does_not_qualify(self):
        radio = control('Choice').replace('type="checkbox"', 'type="radio"')
        outside = control('Unrelated').replace('class="control"', 'class="control" style="width:100px"').replace('<svg ', '<svg style="left:60px" ')
        await self.page.set_content(STYLE + radio + outside)
        rows = await observe(self.page)
        self.assertEqual([(r['name'], r['role']) for r in rows], [('Choice', 'radio')])

    async def test_driver_records_styled_native_checked_effect(self):
        from worker.driver.playwright_driver import PlaywrightDriver
        from worker.schemas import ClickAction
        await self.page.set_content(STYLE + control('Women'))
        rows = await observe(self.page)
        driver = PlaywrightDriver(self.page, window_ms=500)
        try:
            result = await driver.perform(ClickAction(action='click', target=rows[0]['el_id'],
                                                     thought='Toggle Women', expectation='Checkbox toggles'))
            self.assertTrue(await self.page.locator('input').is_checked())
            self.assertEqual(result.effect.as_step_effect(), {'effect_type': 'dom_mutation', 'changed': True})
        finally:
            await driver.aclose()
