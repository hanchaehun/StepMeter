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

    async def click_script(self, script):
        await self.page.locator('button').evaluate('(el,script)=>{el.onclick=()=>{eval(script)}}',script)
        return await self.observer.click(self.page.locator('button'))

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
                result=await self.click_script('panel.'+change)
                self.assertEqual(result.effect_type,'dom_mutation')
        await self.page.set_content('<button>Open</button><section hidden id="panel"><p>Response</p></section>')
        result=await self.click_script('panel.hidden=false')
        self.assertEqual(result.effect_type,'dom_mutation')

    async def test_css_transition_after_mutation_is_observed(self):
        await self.page.set_content('<style>#panel{opacity:0;transition:opacity .08s}#panel.active{opacity:1}</style><button>Open</button><section id="panel">Response</section>')
        await self.page.wait_for_timeout(50)
        result=await self.click_script("panel.classList.add('active')")
        self.assertEqual(result.effect_type,'dom_mutation')

    async def test_shadow_descendant_and_stylesheet_on_ancestor(self):
        await self.page.set_content('<button>Open</button><div id="host" hidden></div>')
        await self.page.evaluate("host.attachShadow({mode:'open'}).innerHTML='<p>Response</p>'")
        result=await self.click_script('host.hidden=false')
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
                result=await self.click_script(script)
                self.assertEqual(result.effect_type,'no_change')

    async def test_same_state_assignment_and_inert_button_stay_no_change(self):
        await self.page.set_content('<button>Inert</button><p id="panel">Other</p>')
        self.assertEqual((await self.observer.click(self.page.locator('button'))).effect_type,'no_change')
        result=await self.observer.observe(lambda:self.page.evaluate('panel.hidden=false'))
        self.assertEqual(result.effect_type,'no_change')

    async def assert_periodic_no_change(self, interval, script, *, arm=False):
        # Ordinary names/roles: semantic timer/carousel exclusions cannot hide a regression.
        await self.page.set_content('''<style>#panel{display:block}#panel.is-active{display:none}</style>
            <button>Inert</button><main><section id="panel">Background content</section></main>''')
        await self.page.evaluate('''({interval,script,arm})=>{
            const panel=document.querySelector('#panel');
            panel.hidden=false;
            globalThis.ticks=0;
            if(arm)document.querySelector('button').onclick=()=>document.querySelector('main').classList.add('armed');
            globalThis.tickTimer=setInterval(()=>{eval(script);globalThis.ticks++},interval);
        }''',dict(interval=interval,script=script,arm=arm))
        observer=EffectObserver(self.page,window_ms=3000)
        self.addAsyncCleanup(observer.aclose)
        result=await observer.click(self.page.locator('button'))
        self.assertGreaterEqual(await self.page.evaluate('globalThis.ticks'),1)
        await self.page.evaluate('clearInterval(globalThis.tickTimer)')
        self.assertEqual(result.effect_type,'no_change')

    async def test_periodic_banner_class_is_not_click_response(self):
        await self.assert_periodic_no_change(1000,"panel.classList.toggle('is-active')")

    async def test_periodic_notification_display_is_not_click_response(self):
        await self.assert_periodic_no_change(1500,"panel.style.display=panel.style.display==='none'?'block':'none'")

    async def test_periodic_loading_hidden_is_not_click_response(self):
        await self.assert_periodic_no_change(800,'panel.hidden=!panel.hidden')

    async def test_later_timer_revokes_earlier_ancestor_authorization(self):
        await self.assert_periodic_no_change(800,'panel.hidden=!panel.hidden',arm=True)

    async def test_observation_start_without_action_does_not_authorize_visibility(self):
        await self.page.set_content('<button>Inert</button><p id="panel" hidden>Other</p>')
        result=await self.observer.observe(lambda:self.page.evaluate('panel.hidden=false'))
        self.assertEqual(result.effect_type,'no_change')

    async def test_keyboard_action_can_show_unlinked_panel(self):
        await self.page.set_content('<button onkeydown="panel.hidden=false">Open</button><p id="panel" hidden>Other</p>')
        await self.page.locator('button').focus()
        result=await self.observer.observe(lambda:self.page.keyboard.press('ArrowRight'))
        self.assertEqual(result.effect_type,'dom_mutation')

    async def test_authorization_does_not_include_unrelated_sibling(self):
        await self.page.set_content('''<style>#panel.active + aside{display:block}aside{display:none}</style>
            <button>Open</button><section id="panel"></section><aside>Unrelated</aside>''')
        result=await self.click_script("panel.classList.add('active')")
        self.assertTrue(await self.page.locator('aside').is_visible())
        self.assertEqual(result.effect_type,'no_change')

    async def test_large_dom_with_js_style_animation_does_not_time_out(self):
        # 요소 약 3,100개 + 매 프레임 100개 요소의 style 변경(움직이는 배경 등). 장바구니 패널 표시는 반응이다(#77).
        await self.page.set_content('''<style>.panel{display:none}.panel.on{display:block}</style>
            <button onclick="document.querySelector('.panel').classList.add('on')">Cart</button>
            <section class="panel">Cart contents</section><div id="big"></div><div id="anim"></div>
            <script>
            const big=document.getElementById('big');
            for(let i=0;i<300;i++){let d=big;for(let k=0;k<10;k++){const c=document.createElement('div');d.appendChild(c);d=c;}d.textContent='row '+i;}
            const a=document.getElementById('anim');const els=[];
            for(let i=0;i<100;i++){const e=document.createElement('span');e.textContent='*';e.style.display='inline-block';a.appendChild(e);els.push(e);}
            let t=0;(function f(){t++;els.forEach((e,i)=>e.style.transform='translateX('+((t+i)%20)+'px)');requestAnimationFrame(f)})();
            </script>''')
        observer = EffectObserver(self.page)
        self.addAsyncCleanup(observer.aclose)
        result = await observer.click(self.page.locator('button'))
        self.assertEqual(result.effect_type, 'dom_mutation')
