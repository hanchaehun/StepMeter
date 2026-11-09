"""Synthetic browser checks for ADR 0010's no-op and screenshot contracts."""
import unittest

from playwright.async_api import async_playwright

from worker.collect.collector import observe
from worker.driver.effects import EffectObservationError
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import ClickAction, SelectAction, TypeAction, ScrollAction, BackAction, WaitAction


class DriverADRTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 800, 'height': 600})
        self.driver = PlaywrightDriver(self.page, window_ms=1500)
        self.addAsyncCleanup(self.driver.aclose)

    async def test_occluded_actions_are_real_snapshot_noops(self):
        for action_type, html, extra in [
            (ClickAction, '<button onclick="window.changed=true">Target</button>', {}),
            (TypeAction, '<input aria-label="Target" value="original">', {'text': 'new'}),
            (SelectAction, '<select aria-label="Target"><option>A</option><option>B</option></select>', {'option': 2}),
        ]:
            with self.subTest(action=action_type):
                await self.page.set_content(html + '<div style="position:fixed;inset:0;background:#ffffff80;z-index:10"></div>')
                rows = await observe(self.page)
                action = action_type(action={ClickAction:'click', TypeAction:'type', SelectAction:'select'}[action_type],
                                     target=rows[0]['el_id'], thought='Try target', expectation='Changed', **extra)
                before = await self.page.locator('body').inner_html()
                # A trial click on this covered target would otherwise time out.
                self.page.set_default_timeout(300)
                result = await self.driver.perform(action)
                self.assertTrue(result.element.occluded)
                self.assertIsNotNone(result.element.occluder)
                self.assertEqual(result.effect.as_step_effect(), {'effect_type': 'no_change', 'changed': False})
                self.assertEqual(before, await self.page.locator('body').inner_html())
                self.assertFalse(await self.page.evaluate('!!window.changed'))
                self.assertTrue(result.screenshot.startswith(b'\xff\xd8'))
                if action.action == 'type':
                    self.assertEqual(await self.page.locator('input').input_value(), 'original')
                if action.action == 'select':
                    self.assertEqual(await self.page.locator('select').input_value(), 'A')

    async def test_enabled_option_numbers_skip_disabled_options_and_groups(self):
        await self.page.set_content('''<select aria-label="Target"><option disabled>Placeholder</option>
            <option>A</option><optgroup disabled label="Unavailable"><option>B</option></optgroup>
            <option disabled>C</option><option>D</option></select>''')
        await observe(self.page)
        options = await self.driver.select_options(1)
        self.assertEqual(options, [{'index': 1, 'label': 'A', 'value': 'A'}, {'index': 4, 'label': 'D', 'value': 'D'}])
        result = await self.driver.perform(SelectAction(action='select', target=1, option=2, thought='Choose', expectation='D'))
        self.assertEqual(await self.page.locator('select').input_value(), 'D')
        self.assertTrue(result.screenshot.startswith(b'\xff\xd8'))

    async def test_changed_observed_option_mapping_rejected(self):
        await self.page.set_content('<select aria-label="Target"><option>A</option><optgroup label="Group"><option>B</option></optgroup></select>')
        await observe(self.page)
        await self.driver.select_options(1)
        await self.page.locator('optgroup').evaluate('(e)=>e.disabled=true')
        with self.assertRaises(EffectObservationError):
            await self.driver.perform(SelectAction(action='select', target=1, option=1, thought='Choose', expectation='A'))
        self.assertEqual(await self.page.locator('select').input_value(), 'A')

    async def test_option_mapping_changed_during_setup_is_rejected(self):
        await self.page.set_content('<select aria-label="Target"><option>A</option><optgroup label="Group"><option>B</option></optgroup></select>')
        await observe(self.page)
        await self.driver.select_options(1)
        original = self.driver.effects.observe
        async def changed_setup(callback, **kwargs):
            await self.page.locator('optgroup').evaluate('(e)=>e.disabled=true')
            return await original(callback, **kwargs)
        self.driver.effects.observe = changed_setup
        with self.assertRaises(EffectObservationError):
            await self.driver.perform(SelectAction(action='select', target=1, option=2, thought='Choose', expectation='B'))
        self.assertEqual(await self.page.locator('select').input_value(), 'A')

    async def test_screenshot_is_after_scroll_before_mutation(self):
        await self.page.set_content('<button onclick="this.textContent=\'After\'">Before</button>')
        await observe(self.page)
        await self.page.locator('button').evaluate('(e)=>e.style.marginTop="1200px"')
        calls = []
        original = self.page.screenshot
        async def capture(**kwargs):
            calls.append((kwargs, await self.page.evaluate('scrollY'), await self.page.locator('button').inner_text()))
            return await original(**kwargs)
        self.page.screenshot = capture
        result = await self.driver.perform(ClickAction(action='click', target=1, thought='Click', expectation='After'))
        self.assertEqual(calls[0][0], {'type': 'jpeg', 'quality': 70, 'caret': 'initial'})
        self.assertGreater(calls[0][1], 0)
        self.assertEqual(calls[0][1], result.element.scroll.y)
        self.assertEqual(calls[0][2], 'Before')
        self.assertEqual(await self.page.locator('button').inner_text(), 'After')

    async def test_nontarget_actions_capture_pre_action_screenshots(self):
        await self.page.set_content('<div style="height:2000px">Page</div>')
        for action in [ScrollAction(action='scroll', direction='down', thought='Scroll', expectation='Below'),
                       WaitAction(action='wait', thought='Wait', expectation='Ready'),
                       BackAction(action='back', thought='Back', expectation='Previous')]:
            result = await self.driver.perform(action)
            self.assertIsNone(result.element)
            self.assertTrue(result.screenshot.startswith(b'\xff\xd8'))
