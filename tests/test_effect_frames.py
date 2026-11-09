import unittest
from playwright.async_api import async_playwright
from worker.driver.effects import EffectObserver, EffectObservationError


class FrameEffectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 800, 'height': 600})
        self.observer = EffectObserver(self.page, window_ms=160)
        self.addAsyncCleanup(self.observer.aclose)

    async def prepare(self, style='top:550px'):
        await self.page.set_content('<iframe style="position:fixed;left:0;width:300px;height:300px;border:0;'+style+'" srcdoc="<p style=\'margin:0\' id=\'visible\'>old</p><p style=\'position:absolute;top:150px\' id=\'clipped\'>old</p>"></iframe>')
        self.frame = self.page.frames[1]
        await self.frame.locator('#clipped').wait_for(state='attached')

    async def test_partially_visible_frame_clips_child(self):
        await self.prepare()
        result = await self.observer.observe(lambda: self.frame.evaluate('clipped.textContent="new"'))
        self.assertEqual(result.effect_type, 'no_change')
        result = await self.observer.observe(lambda: self.frame.evaluate('visible.textContent="new"'))
        self.assertEqual(result.effect_type, 'dom_mutation')

    async def test_current_frame_geometry_not_initial_geometry(self):
        await self.prepare('top:0px')
        async def move_then_change():
            await self.page.locator('iframe').evaluate('(e)=>e.style.top="900px"')
            await self.frame.evaluate('visible.textContent="hidden now"')
        self.assertEqual((await self.observer.observe(move_then_change)).effect_type, 'no_change')
        async def show_then_change():
            await self.page.locator('iframe').evaluate('(e)=>e.style.top="0px"')
            await self.frame.evaluate('visible.textContent="visible now"')
        self.assertEqual((await self.observer.observe(show_then_change)).effect_type, 'dom_mutation')

    async def test_hidden_frame_becomes_visible_then_changes(self):
        await self.prepare('top:0px;display:none')
        async def action():
            await self.page.locator('iframe').evaluate('(e)=>e.style.display="block"')
            await self.frame.evaluate('visible.textContent="shown"')
        self.assertEqual((await self.observer.observe(action)).effect_type, 'dom_mutation')

    async def test_new_frame_with_modal_is_explicitly_incomplete(self):
        await self.page.set_content('<main>stable</main>')
        async def action():
            await self.page.evaluate('const f=document.createElement("iframe"); f.srcdoc="<dialog open>new modal</dialog>"; document.body.append(f)')
        with self.assertRaisesRegex(EffectObservationError, 'Frame attached'):
            await self.observer.observe(action)

    async def test_moving_frame_offscreen_then_removing_child_is_noise(self):
        await self.prepare('top:0px')
        async def action():
            await self.page.evaluate('document.querySelector("iframe").style.top="900px";document.querySelector("iframe").contentDocument.getElementById("visible").remove()')
        self.assertEqual((await self.observer.observe(action)).effect_type, 'no_change')

    async def test_cross_origin_visibility_is_explicitly_incomplete(self):
        await self.page.route('https://frame.test/**', lambda route: route.fulfill(status=200, content_type='text/html', body='<p id="value">old</p>'))
        await self.page.set_content('<iframe src="https://frame.test/"></iframe>')
        frame = self.page.frames[1]
        await frame.locator('#value').wait_for()
        with self.assertRaisesRegex(EffectObservationError, 'visibility incomplete'):
            await self.observer.observe(lambda: frame.evaluate('document.getElementById("value").textContent="changed"'))
