import unittest
from playwright.async_api import async_playwright
from worker.driver.effects import EffectObserver


class NativeControlEffectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        self.observer = EffectObserver(self.page, window_ms=120)
        self.addAsyncCleanup(self.observer.aclose)

    async def test_focused_checkbox_second_click_is_effect(self):
        await self.page.set_content('<label><input type="checkbox">Accept</label>')
        checkbox = self.page.locator('input')
        await checkbox.focus()
        for expected in (True, False):
            result = await self.observer.click(checkbox)
            self.assertEqual(await checkbox.is_checked(), expected)
            self.assertEqual(result.effect_type, 'dom_mutation')

    async def test_focused_styled_checkbox_second_click_is_effect(self):
        await self.page.set_content('<label><span style="position:relative;display:inline-block;width:24px;height:24px"><input type="checkbox" style="position:absolute;inset:0;width:24px;height:24px;margin:0;opacity:0;z-index:1"><svg width="24" height="24"><rect width="20" height="20"/></svg></span>Accept</label>')
        checkbox = self.page.locator('input')
        await checkbox.focus()
        for expected in (True, False):
            result = await self.observer.click(checkbox)
            self.assertEqual(await checkbox.is_checked(), expected)
            self.assertEqual(result.effect_type, 'dom_mutation')

    async def test_invisible_checkbox_without_indicator_is_not_effect(self):
        await self.page.set_content('<label><input type="checkbox" style="opacity:0">Accept</label>')
        handle = await self.page.locator('input').element_handle()
        self.addAsyncCleanup(handle.dispose)
        async def action():
            await handle.evaluate('(e)=>{e.checked=!e.checked;e.dispatchEvent(new Event("input",{bubbles:true}));}')
        result = await self.observer.observe(action, target=handle)
        self.assertEqual(result.effect_type, 'no_change')

    async def test_hidden_indicator_container_is_not_effect(self):
        await self.page.set_content('<label style="opacity:0"><span><input type="checkbox" style="opacity:0;width:24px;height:24px"><svg width="20" height="20"></svg></span>Hidden</label>')
        handle = await self.page.locator('input').element_handle()
        self.addAsyncCleanup(handle.dispose)
        result = await self.observer.observe(lambda: handle.evaluate('(e)=>{e.checked=true;e.dispatchEvent(new Event("change",{bubbles:true}));}'), target=handle)
        self.assertEqual(result.effect_type, 'no_change')
