"""ADR 0010 §9 expectations: native semantics, real label activation, no force.

Fixed CSS: input/indicator at (40,44), 16×16; label starts (64,40).
Cover rectangle is (32,32,180,48). Expectations are authored from these boxes.
"""
import unittest

from playwright.async_api import async_playwright

from tests.test_a11y_axe import AXE_SCRIPT
from worker.a11y.scan import scan_page
from worker.collect.collector import (observe, record_first_view, resolve_element,
                                      scroll_target_into_view, snapshot)
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import BBox, ClickAction
from worker.agent.observation import describe
from worker.rules.engine import axe_target_size_result, evaluate_step

HTML = '''<style>
body {margin:0} .custom {position:relative;margin:40px;padding-left:24px;height:24px}
input {position:absolute;left:0;top:4px;z-index:-1;width:16px;height:16px;margin:0;opacity:0}
label {position:relative;display:inline-block;line-height:24px}
label::before {position:absolute;left:-24px;top:4px;content:"";width:16px;height:16px;background:blue}
</style><div class="custom"><input type="checkbox" id="check"><label for="check">Remember Me</label></div>'''
# WCAG 2.5.8 spacing: indicator center (48,52); this 300px-wide link starts at
# y=61, 9px away (< 12px), like the SB Admin small variant's Forgot Password link.
BELOW_LINK = ('<a href="#forgot" style="position:absolute;left:40px;top:61px;'
              'width:300px;height:20px">Forgot Password?</a>')
# A plain 16×16 button at the indicator's box, with the same link 9px below.
SMALL_BUTTON = ('<button aria-label="Remember" style="position:absolute;left:40px;top:44px;'
                'width:16px;height:16px;padding:0;border:0"></button>' + BELOW_LINK)


class LabelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 800, 'height': 600})
        self.driver = PlaywrightDriver(self.page, window_ms=1000)
        self.addAsyncCleanup(self.driver.aclose)

    async def click(self, number):
        return await self.driver.perform(ClickAction(action='click', target=number,
            thought='Toggle the named checkbox', expectation='Checked state changes'))

    async def agent_r01(self, role):
        """worker/agent/loop.py order: observe, scroll, axe, click, evaluate_step."""
        await record_first_view(self.page)
        number = next(r['el_id'] for r in await observe(self.page) if r['role'] == role)
        handle = await resolve_element(self.page, number)
        try:
            await scroll_target_into_view(self.page, number)
            axe = await scan_page(self.page, AXE_SCRIPT, {0: handle})
        finally:
            await handle.dispose()
        result = await self.click(number)
        verdict = axe_target_size_result(axe, 0)
        r01 = [c for c in evaluate_step(result.element, step_id=1, action='click',
                                        effect_type=result.effect.effect_type,
                                        is_first_target=True, axe_target_size=verdict)
               if c.rule_id == 'R01']
        return result.element, verdict, r01

    async def test_label_checkbox_r01_uses_spacing_not_axe(self):
        # axe measures the transparent input, not the surface pressed (ADR 0010 §9).
        await self.page.set_content(HTML + BELOW_LINK)
        element, verdict, r01 = await self.agent_r01('checkbox')
        self.assertEqual((element.role, element.style.opacity), ('checkbox', 0))
        self.assertFalse(verdict)  # the regression: axe passes the invisible input
        self.assertEqual([(c.severity, c.measured, c.threshold) for c in r01], [('high', 16, 24)])

    async def test_label_checkbox_without_neighbor_has_no_r01(self):
        await self.page.set_content(HTML)
        element, _, r01 = await self.agent_r01('checkbox')
        self.assertEqual(element.nearby_targets, [])
        self.assertEqual(r01, [])

    async def test_plain_small_button_keeps_axe_precedence(self):
        await self.page.set_content(SMALL_BUTTON)
        element, verdict, r01 = await self.agent_r01('button')
        self.assertEqual(element.bbox, BBox(x=40, y=44, width=16, height=16))
        self.assertIsNotNone(verdict)
        self.assertEqual(bool(r01), verdict)
        # Same failing geometry, but a definitive axe pass still wins for a visible button.
        self.assertEqual([c for c in evaluate_step(element, step_id=1, action='click',
                          effect_type='dom_mutation', is_first_target=True, axe_target_size=False)
                          if c.rule_id == 'R01'], [])

    async def test_bootstrap_native_semantics_geometry_and_effect(self):
        await self.page.set_content(HTML)
        await record_first_view(self.page)
        rows = await observe(self.page)
        self.assertEqual([(r['tag'], r['role'], r['name']) for r in rows],
                         [('input', 'checkbox', 'Remember Me')])
        result = await self.click(rows[0]['el_id'])
        self.assertEqual(result.element.bbox, BBox(x=40, y=44, width=16, height=16))
        self.assertTrue(result.element.in_first_view)
        self.assertFalse(result.element.occluded)
        self.assertTrue(await self.page.locator('input').is_checked())
        self.assertEqual(result.effect.as_step_effect(), {'changed': True, 'effect_type': 'dom_mutation'})
        self.assertTrue(result.screenshot.startswith(b'\xff\xd8'))

    async def test_empty_label_with_pseudo_indicator_and_aria_name(self):
        await self.page.set_content(HTML.replace('id="check"', 'id="check" aria-label="Remember Me"')
                                    .replace('>Remember Me</label>', '></label>'))
        rows = await observe(self.page)
        self.assertEqual([r['name'] for r in rows], ['Remember Me'])
        await self.click(rows[0]['el_id'])
        self.assertTrue(await self.page.locator('input').is_checked())

    async def test_fully_hidden_native_uses_visible_label_surface(self):
        await self.page.set_content(HTML.replace('opacity:0}', 'opacity:0;display:none}'))
        rows = await observe(self.page)
        self.assertEqual([r['name'] for r in rows], ['Remember Me'])
        result = await self.click(rows[0]['el_id'])
        self.assertEqual(result.element.bbox.x, 64)
        self.assertTrue(await self.page.locator('input').is_checked())

    async def test_fully_hidden_native_with_empty_label_uses_pseudo_surface(self):
        html = HTML.replace('opacity:0}', 'opacity:0;display:none}')
        html = html.replace('id="check"', 'id="check" aria-label="Remember Me"')
        await self.page.set_content(html.replace('>Remember Me</label>', '></label>') +
                                    '<style>label{vertical-align:top}</style>')
        await observe(self.page)
        result = await self.click(1)
        self.assertEqual(result.element.bbox, BBox(x=40, y=44, width=16, height=16))
        self.assertTrue(await self.page.locator('input').is_checked())

    async def test_overlay_records_r04_without_toggling(self):
        await self.page.set_content(HTML + '<div role="dialog" aria-label="Cookie" style="position:absolute;left:32px;top:32px;width:180px;height:48px;background:red;z-index:10"></div>')
        rows = await observe(self.page)
        self.assertTrue(rows[0]['occluded'])
        self.assertEqual((await describe(rows, self.driver))[0]['visibility'], '(가려짐)')
        result = await self.click(1)
        self.assertTrue(result.element.occluded)
        self.assertEqual(result.element.occluder.name, 'Cookie')
        self.assertEqual(result.effect.effect_type, 'no_change')
        self.assertFalse(await self.page.locator('input').is_checked())
        rules = [c.rule_id for c in evaluate_step(result.element, step_id=1,
                    action='click', effect_type=result.effect.effect_type, is_first_target=True)]
        self.assertIn('R04', rules)
        self.assertNotIn('R03', rules)

    async def test_unrelated_control_embedded_in_label_is_not_proxy_activation(self):
        # Input (40,44) center (48,52) is occupied by an independent link.
        await self.page.set_content(HTML.replace('Remember Me</label>',
            'Remember Me<a href="#other" style="position:absolute;left:-24px;top:4px;width:16px;height:16px;z-index:2">?</a></label>'))
        rows = await observe(self.page)
        self.assertTrue(rows[0]['occluded'])
        result = await self.click(rows[0]['el_id'])
        self.assertEqual(result.effect.effect_type, 'no_change')
        self.assertFalse(await self.page.locator('input').is_checked())

    async def test_hidden_label_and_unassociated_transparent_input_excluded(self):
        for extra in ('label{opacity:0}', '.custom{visibility:hidden}', 'label{display:none}', 'label{pointer-events:none}'):
            with self.subTest(css=extra):
                await self.page.set_content(HTML + f'<style>{extra}</style>')
                self.assertEqual(await observe(self.page), [])
        await self.page.set_content('<input type="checkbox" style="opacity:0">')
        self.assertEqual(await observe(self.page), [])

    async def test_reassigned_label_rejects_stale_number(self):
        await self.page.set_content(HTML)
        await observe(self.page)
        await self.page.locator('label').evaluate('(el)=>el.htmlFor="other"')
        with self.assertRaises(Exception):
            await resolve_element(self.page, 1)
        self.assertFalse(await self.page.locator('input').is_checked())

    async def test_disabled_proxy_does_not_bypass_native_actionability(self):
        await self.page.set_content(HTML.replace('type="checkbox"', 'type="checkbox" disabled'))
        await observe(self.page)
        with self.assertRaises(Exception):
            await self.click(1)
        self.assertFalse(await self.page.locator('input').is_checked())

    async def test_same_origin_frame_and_frame_position_after_observe(self):
        await self.page.set_content('<iframe style="position:absolute;left:100px;top:100px;width:500px;height:300px;border:0"></iframe>')
        frame = self.page.frames[1]
        await frame.set_content(HTML.replace('type="checkbox"', 'type="radio"'))
        await record_first_view(self.page)
        rows = await observe(self.page)
        self.assertEqual(rows[0]['role'], 'radio')
        await self.page.locator('iframe').evaluate('(el)=>el.style.top="200px"')
        result = await self.click(1)
        self.assertEqual(result.element.context, 'same_origin_iframe')
        self.assertEqual(result.element.bbox, BBox(x=140, y=244, width=16, height=16))
        self.assertTrue(await frame.locator('input').is_checked())

    async def test_open_shadow_label(self):
        await self.page.set_content('<div id="host"></div>')
        await self.page.locator('#host').evaluate('(el, html)=>el.attachShadow({mode:"open"}).innerHTML=html', HTML)
        rows = await observe(self.page)
        result = await self.click(rows[0]['el_id'])
        self.assertEqual(result.element.context, 'open_shadow')
        self.assertTrue(await self.page.locator('input').is_checked())

    async def test_occlusion_updates_and_pointer_transparent_overlay(self):
        await self.page.set_content(HTML + '<div id="overlay" style="position:absolute;inset:0;background:#fff8;pointer-events:none"></div>')
        await observe(self.page)
        self.assertFalse((await snapshot(self.page, 1)).occluded)
        await self.page.locator('#overlay').evaluate('(el)=>el.style.pointerEvents="auto"')
        self.assertTrue((await snapshot(self.page, 1)).occluded)
        await self.page.locator('#overlay').evaluate('(el)=>el.remove()')
        self.assertFalse((await snapshot(self.page, 1)).occluded)
