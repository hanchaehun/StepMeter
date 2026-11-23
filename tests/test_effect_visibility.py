"""Visual state changes independent of action target, with noise controls."""
import unittest
from playwright.async_api import async_playwright
from worker.driver.effects import EffectObserver
from worker.rules.r03 import evaluate

class VisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pw=await async_playwright().start(); self.addAsyncCleanup(pw.stop)
        browser=await pw.chromium.launch();self.addAsyncCleanup(browser.close)
        self.page=await browser.new_page();await self.page.route('**/*',lambda route:route.abort())
        self.observer=EffectObserver(self.page,window_ms=250);self.addAsyncCleanup(self.observer.aclose)

    async def test_unlinked_cart_show_and_hide_do_not_emit_r03(self):
        await self.page.set_content('''<style>.panel{display:none}.panel.active{display:block}</style>
            <button onclick="document.querySelector('.panel').classList.toggle('active')">Cart</button>
            <section class="panel">Cart contents</section>''')
        for shown in [True,False]:
            result=await self.observer.click(self.page.locator('button'))
            self.assertEqual(await self.page.locator('section').is_visible(),shown)
            self.assertEqual(result.effect_type,'dom_mutation')
            self.assertIsNone(evaluate('click',result.effect_type))

    async def test_parent_hidden_and_visibility_opacity_transitions(self):
        for declaration,change in [('display:none',"style.display='block'"),
                ('visibility:hidden',"style.visibility='visible'"),('opacity:0',"style.opacity='1'")]:
            with self.subTest(css=declaration):
                await self.page.set_content(f'<button>Open</button><section id="panel" style="{declaration}"><div>Response</div></section>')
                result=await self.observer.observe(lambda:self.page.evaluate('panel.'+change))
                self.assertEqual(result.effect_type,'dom_mutation')
        await self.page.set_content('<button>Open</button><section hidden id="panel"><p>Response</p></section>')
        result=await self.observer.observe(lambda:self.page.evaluate('panel.hidden=false'))
        self.assertEqual(result.effect_type,'dom_mutation')

    async def test_css_transition_after_mutation_is_observed(self):
        await self.page.set_content('<style>#panel{opacity:0;transition:opacity .08s}#panel.active{opacity:1}</style><button>Open</button><section id="panel">Response</section>')
        await self.page.wait_for_timeout(50)
        result=await self.observer.observe(lambda:self.page.evaluate("panel.classList.add('active')"))
        self.assertEqual(result.effect_type,'dom_mutation')

    async def test_shadow_descendant_and_stylesheet_on_ancestor(self):
        await self.page.set_content('<button>Open</button><div id="host" hidden></div>')
        await self.page.evaluate("host.attachShadow({mode:'open'}).innerHTML='<p>Response</p>'")
        result=await self.observer.observe(lambda:self.page.evaluate('host.hidden=false'))
        self.assertEqual(result.effect_type,'dom_mutation')

    async def test_background_color_motion_and_noise_toggles_are_ignored(self):
        for kind in ['color','motion','timer','offscreen','hidden-frame']:
            with self.subTest(kind=kind):
                await self.page.set_content('<button>Inert</button><section id="panel">Other</section>')
                if kind=='color': script="panel.style.color='red'"
                elif kind=='motion': script="panel.style.transform='translateX(10px)'"
                elif kind=='timer':
                    await self.page.locator('#panel').evaluate("e=>{e.setAttribute('role','timer');e.hidden=true}")
                    script='panel.hidden=false'
                elif kind=='offscreen':
                    await self.page.locator('#panel').evaluate("e=>{e.style.position='absolute';e.style.top='2000px';e.hidden=true}")
                    script='panel.hidden=false'
                else:
                    await self.page.set_content('<button>Inert</button><iframe style="display:none" srcdoc="<p hidden id=p>Other</p>"></iframe>')
                    result=await self.observer.observe(lambda:self.page.frames[1].evaluate('p.hidden=false'))
                    self.assertEqual(result.effect_type,'no_change');continue
                result=await self.observer.observe(lambda:self.page.evaluate(script))
                self.assertEqual(result.effect_type,'no_change')

    async def test_same_state_assignment_and_inert_button_stay_no_change(self):
        await self.page.set_content('<button>Inert</button><p id="panel">Other</p>')
        self.assertEqual((await self.observer.click(self.page.locator('button'))).effect_type,'no_change')
        result=await self.observer.observe(lambda:self.page.evaluate('panel.hidden=false'))
        self.assertEqual(result.effect_type,'no_change')
