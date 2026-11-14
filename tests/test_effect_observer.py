"""Independent expectations from development plan 5.1, not collector output."""
import asyncio
import os

import unittest
from playwright.async_api import async_playwright
from worker.driver.effects import EffectObserver, EffectResult, NetworkFilter, url_identity


def test_network_noise_contract():
    f = NetworkFilter(['analytics.example'])
    assert f.classify('https://app.test/api?seq=1', 'GET', 'fetch', 1)
    assert not f.classify('https://app.test/api?seq=2', 'GET', 'xhr', 2)
    assert f.classify('https://app.test/api', 'POST', 'xhr', 2)
    assert not f.classify('https://sub.analytics.example/x', 'POST', 'fetch', 2)
    assert not f.classify('https://app.test/api', 'POST', 'ping', 2)
    assert f.classify('https://app.test/api', 'GET', 'fetch', 6)


def test_contract_does_not_invent_network_enum():
    assert EffectResult('no_change', 1).as_step_effect() == {'effect_type': 'dom_mutation', 'changed': True}
    assert EffectResult('no_change', 0).as_step_effect() == {'effect_type': 'no_change', 'changed': False}
    assert EffectResult('dom_mutation', 1).as_step_effect() == {'effect_type': 'dom_mutation', 'changed': True}
    assert url_identity('https://a/x?b=2&a=1') == url_identity('https://a/x?a=1&b=2')
    assert url_identity('https://a/#a') == url_identity('https://a/#b')
    assert url_identity('https://a/#a', hash_routes=True) != url_identity('https://a/#b', hash_routes=True)


def test_real_browser_effects():
    asyncio.run(_browser_cases())


async def _browser_cases():
    async with async_playwright() as p:
        launch = {'headless': True}
        if os.environ.get('STEPMETER_CHROMIUM_EXECUTABLE'):
            launch['executable_path'] = os.environ['STEPMETER_CHROMIUM_EXECUTABLE']
        browser = await p.chromium.launch(**launch)
        page = await browser.new_page()
        try:
            cases = [
                ('<div class="carousel" id="n">Slide A</div><button>inert</button><script>setInterval(()=>n.textContent=Math.random().toString(36),20)</script>', 'no_change'),
                ('<button aria-expanded="false" onclick="this.setAttribute(\'aria-expanded\',\'true\')">accordion</button>', 'dom_mutation'),
                ('<button onclick="d.showModal()">open</button><dialog id="d">modal</dialog>', 'modal_change'),
                ('<div role="timer" id="n">Time 1</div><button>inert</button><script>setInterval(()=>n.textContent=\'Time \'+Date.now(),20)</script>', 'no_change'),
                ('<button onclick="n.remove()">remove</button><p id="n">visible content</p>', 'dom_mutation'),
                ('<button onclick="n.textContent=\'new\'">change</button><p id="n" hidden>old</p>', 'no_change'),
                ('<button onclick="n.textContent=\'new\'">change</button><p id="n" style="position:absolute;top:3000px">old</p>', 'no_change'),
                ('<div class="carousel"><button onclick="n.textContent=\'next\'">next</button><p id="n">old</p></div>', 'dom_mutation'),
                ('<button onclick="n.textContent=\'new\'">change</button><p class="address" id="n">old</p>', 'dom_mutation'),
                ('<button onclick="n.focus()">focus</button><input id="n">', 'dom_mutation'),
                ('<button onclick="n.textContent=\'12:45\'">clock</button><p id="n">12:44</p>', 'no_change'),
            ]
            for html, expected in cases:
                await page.close()
                page = await browser.new_page()
                await page.set_content(html)
                observer = EffectObserver(page, window_ms=150)
                try:
                    result = await observer.click(page.locator('button'))
                    assert result.effect_type == expected, html
                    assert result.as_step_effect()['changed'] == (expected != 'no_change')
                    assert await page.evaluate('Object.keys(globalThis).filter(k=>k.startsWith("__stepmeter_effect_")).length') == 0
                finally:
                    await observer.aclose()
            # Prior background GET polling is suppressed even when query values vary.
            await page.route('**/api*', lambda route: route.fulfill(status=200, body='{}'))
            await page.goto('https://test.example/api')
            await page.set_content('<button>inert</button>')
            observer = EffectObserver(page, window_ms=150)
            await page.evaluate('fetch("/api?before=1")')
            result = await observer.observe(lambda: page.evaluate('fetch("/api?after=2")'))
            assert result.effect_type == 'no_change' and result.meaningful_network_count == 0
            result = await observer.observe(lambda: page.evaluate('fetch("/api", {method:"POST"})'))
            assert result.meaningful_network_count == 1
            assert result.as_step_effect() == {'effect_type': 'dom_mutation', 'changed': True}
            # Priority survives lower-priority changes earlier in the window.
            result = await observer.observe(lambda: page.evaluate('document.body.append("changed");history.pushState({},"","/next")'))
            assert result.effect_type == 'url_change'
            # Short-window timing boundaries and priority: DOM is not an early exit.
            await page.set_content('<button>inert</button><p id="label">old</p><dialog id="dialog">modal</dialog>')
            result = await observer.observe(lambda: page.evaluate('label.textContent="new";setTimeout(()=>dialog.showModal(),70)'))
            assert result.effect_type == 'modal_change'
            await page.locator('dialog').evaluate('(d)=>d.close()')
            result = await observer.observe(lambda: page.evaluate('setTimeout(()=>label.textContent="late",250)'))
            assert result.effect_type == 'no_change'
            await page.wait_for_timeout(150)
            # Already-focused form edits must still be visible responses.
            await page.set_content('<input value="old">')
            await page.locator('input').focus()
            handle = await page.locator('input').element_handle()
            result = await observer.observe(lambda: handle.fill('new'), target=handle)
            assert result.effect_type == 'dom_mutation'
            await handle.dispose()
            # Cancellation removes injected state and allows reuse.
            task = asyncio.create_task(observer.observe(lambda: asyncio.sleep(10)))
            await asyncio.sleep(.05)
            task.cancel()
            with unittest.TestCase().assertRaises(asyncio.CancelledError):
                await task
            assert await page.evaluate('Object.keys(globalThis).filter(k=>k.startsWith("__stepmeter_effect_")).length') == 0
            assert (await observer.observe(lambda: asyncio.sleep(0))).effect_type == 'no_change'
            await observer.aclose()
            # Nested open-shadow target and hidden-frame noise.
            await page.set_content('<div id="host"></div><iframe style="display:none" srcdoc="<p>old</p>"></iframe>')
            await page.evaluate('host.attachShadow({mode:"open"}).innerHTML=`<section></section>`;host.shadowRoot.querySelector("section").attachShadow({mode:"open"}).innerHTML=`<button onclick="this.setAttribute(\'aria-expanded\',\'true\')" aria-expanded="false">expand</button>`')
            observer = EffectObserver(page, window_ms=150)
            assert (await observer.click(page.locator('button'))).effect_type == 'dom_mutation'
            async def hidden_frame_change():
                await page.frames[1].evaluate('document.body.textContent="new"')
            assert (await observer.observe(hidden_frame_change)).effect_type == 'no_change'
            await observer.aclose()
            # Mandatory one-second GET poll fixture with the production 3s window.
            await page.set_content('<button>inert</button>')
            observer = EffectObserver(page)
            await page.evaluate('fetch("/api?tick=0");globalThis.poll=setInterval(()=>fetch("/api?tick="+Date.now()),1000)')
            await page.wait_for_timeout(50)
            result = await observer.click(page.locator('button'))
            assert result.effect_type == 'no_change' and result.meaningful_network_count == 0
            await page.evaluate('clearInterval(globalThis.poll)')
            await observer.aclose()
        finally:
            await browser.close()


class EffectTests(unittest.TestCase):
    def test_network_noise_contract(self):
        test_network_noise_contract()

    def test_contract_does_not_invent_network_enum(self):
        test_contract_does_not_invent_network_enum()

    def test_real_browser_effects(self):
        test_real_browser_effects()
