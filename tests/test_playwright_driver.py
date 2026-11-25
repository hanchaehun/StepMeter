import unittest
from playwright.async_api import async_playwright
from worker.collect.collector import observe
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import ClickAction, SelectAction, TypeAction


class DriverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        self.driver = PlaywrightDriver(self.page, window_ms=500)
        self.addAsyncCleanup(self.driver.aclose)

    async def test_numbered_click_and_effect(self):
        await self.page.set_content('<button onclick="this.setAttribute(\'aria-expanded\',\'true\')">Expand</button>')
        rows = await observe(self.page)
        result = await self.driver.perform(ClickAction(action='click', target=rows[0]['el_id'], thought='Expand', expectation='Open'))
        self.assertEqual(result.element.name, 'Expand')
        self.assertEqual(result.effect.as_step_effect(), {'changed': True, 'effect_type': 'dom_mutation'})

    async def test_stale_number_rejected(self):
        await self.page.set_content('<button>First</button>')
        await observe(self.page)
        await self.page.locator('button').evaluate('(e)=>e.textContent="Recycled"')
        with self.assertRaises(Exception):
            await self.driver.perform(ClickAction(action='click', target=1, thought='Click', expectation='Open'))

    async def test_type_and_select(self):
        await self.page.set_content('<input aria-label="Name"><select aria-label="Choice"><option>A</option><option>B</option></select>')
        await observe(self.page)
        await self.driver.perform(TypeAction(action='type', target=1, text='test', thought='Fill', expectation='Filled'))
        self.assertEqual(await self.page.locator('input').input_value(), 'test')
        await observe(self.page)
        await self.driver.perform(SelectAction(action='select', target=2, option=2, thought='Choose', expectation='Chosen'))
        self.assertEqual(await self.page.locator('select').input_value(), 'B')

    async def test_select_same_value_different_option_is_effect(self):
        await self.page.set_content('<select aria-label="Choice"><option value="x">Alpha</option><option value="x">Beta</option></select>')
        await self.page.locator('select').focus()
        await observe(self.page)
        result = await self.driver.perform(SelectAction(action='select', target=1, option=2, thought='Choose', expectation='Beta'))
        self.assertEqual(await self.page.locator('select').evaluate('(e)=>e.selectedIndex'), 1)
        self.assertEqual(result.effect.effect_type, 'dom_mutation')

    async def test_concurrent_action_does_not_prepare(self):
        import asyncio
        from worker.driver.effects import EffectObservationError
        await self.page.set_content('<button>First</button><input aria-label="Name">')
        await observe(self.page)
        first = asyncio.create_task(self.driver.perform(ClickAction(action='click', target=1, thought='Click', expectation='Effect')))
        await asyncio.sleep(.01)
        with self.assertRaises(EffectObservationError):
            await self.driver.perform(TypeAction(action='type', target=2, text='wrong', thought='Fill', expectation='Filled'))
        await first
        self.assertEqual(await self.page.locator('input').input_value(), '')

    async def test_readonly_input_and_disabled_optgroup_rejected(self):
        from worker.driver.effects import EffectObservationError
        await self.page.set_content('<input readonly aria-label="Name"><select aria-label="Choice"><option>A</option><optgroup label="Unavailable" disabled><option>B</option></optgroup></select>')
        await observe(self.page)
        with self.assertRaises(EffectObservationError):
            await self.driver.perform(TypeAction(action='type', target=1, text='wrong', thought='Fill', expectation='Filled'))
        with self.assertRaises(EffectObservationError):
            await self.driver.perform(SelectAction(action='select', target=2, option=2, thought='Choose', expectation='Chosen'))

    async def test_target_recycled_during_observer_setup_rejected(self):
        await self.page.set_content('<button data-id="first" onclick="globalThis.clicked=true">Row</button>')
        await observe(self.page)
        original = self.driver.effects.observe
        async def changed_setup(callback, **kwargs):
            await self.page.locator('button').evaluate('(e)=>e.dataset.id="second"')
            return await original(callback, **kwargs)
        self.driver.effects.observe = changed_setup
        with self.assertRaises(Exception):
            await self.driver.perform(ClickAction(action='click', target=1, thought='Click', expectation='Open'))
        self.assertFalse(await self.page.evaluate('!!globalThis.clicked'))

    async def test_observed_effect_feeds_existing_step_rules_and_metrics(self):
        from apps.api.db.models import Step
        from worker.rules import r03
        from worker.metrics.interactions import count_no_response_clicks
        await self.page.set_content('''<div class="carousel" id="ticker">Slide</div>
            <button id="inert">Inert</button><button id="expand" aria-expanded="false"
            onclick="this.setAttribute('aria-expanded','true')">Expand</button>
            <script>setInterval(()=>ticker.textContent='Slide '+Math.random(),20)</script>''')
        actions, effects = [], []
        for name, expected in [('Inert', 'no_change'), ('Expand', 'dom_mutation')]:
            rows = await observe(self.page)
            number = next(row['el_id'] for row in rows if row['name'] == name)
            action = ClickAction(action='click', target=number, thought='Test', expectation='Observe')
            result = await self.driver.perform(action)
            # Frozen DB fields accept measured output without schema changes.
            step = Step(attempt_id=1, idx=len(actions), action=action.model_dump(),
                        thought=action.thought, url='about:blank', state_hash='0'*64,
                        **result.effect.as_step_effect())
            self.assertEqual(step.effect_type, expected)
            self.assertEqual(r03.evaluate(action.action, step.effect_type) is not None,
                             name == 'Inert')
            actions.append(action.action)
            effects.append(step.effect_type)
        self.assertEqual(count_no_response_clicks(actions, effects), 1)

    async def test_slow_preparation_is_outside_the_observation_window(self):
        # PM 결정: 재확인·옵션 확인·안전 검사(준비)는 3초 관찰 창에 들어가지 않는다.
        # 준비가 3.5초 걸려도 시간 초과가 아니고, 누르면 글자가 나타나므로 dom_mutation이다.
        import asyncio
        from unittest.mock import patch
        from worker.driver import playwright_driver
        real_guard = playwright_driver.guard_target
        async def slow_guard(*args, **kwargs):
            await asyncio.sleep(3.5)
            return await real_guard(*args, **kwargs)
        driver = PlaywrightDriver(self.page)  # 기본 관찰 창 3000ms
        self.addAsyncCleanup(driver.aclose)
        await self.page.set_content('<button onclick="document.body.insertAdjacentHTML(\'beforeend\',\'<p>Shown</p>\')">Show</button>')
        rows = await observe(self.page)
        with patch('worker.driver.playwright_driver.guard_target', slow_guard):
            result = await driver.perform(ClickAction(action='click', target=rows[0]['el_id'],
                                                      thought='Show', expectation='Text appears'))
        self.assertEqual(result.effect.effect_type, 'dom_mutation')
        self.assertEqual(await self.page.locator('p').text_content(), 'Shown')

    async def test_type_submit_fill_and_enter_share_one_deadline(self):
        # PM 결정: fill과 press('Enter')는 하나의 마감(2500ms)을 나눠 쓴다. press에는 남은 시간(최소 100ms)만 준다.
        # fill이 2.0초 걸리면 press의 timeout은 600ms 이하다(바깥 3초 안전망을 넘지 않는다).
        import asyncio
        from unittest.mock import patch
        from playwright.async_api import ElementHandle
        real_fill, real_press, seen = ElementHandle.fill, ElementHandle.press, []
        async def slow_fill(handle, value, **kwargs):
            await asyncio.sleep(2.0)
            return await real_fill(handle, value, **kwargs)
        async def recording_press(handle, key, **kwargs):
            seen.append(kwargs.get('timeout'))
            return await real_press(handle, key, **kwargs)
        driver = PlaywrightDriver(self.page)  # 기본 관찰 창 3000ms, 입력 시간 제한 2500ms
        self.addAsyncCleanup(driver.aclose)
        await self.page.set_content('<form onsubmit="event.preventDefault()"><input aria-label="Search"></form>')
        rows = await observe(self.page)
        with patch.object(ElementHandle, 'fill', slow_fill), patch.object(ElementHandle, 'press', recording_press):
            await driver.perform(TypeAction(action='type', target=rows[0]['el_id'], text='shoes', submit=True,
                                            thought='Search', expectation='Results'))
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(seen[0])
        self.assertLessEqual(seen[0], 600)
        self.assertGreaterEqual(seen[0], 100)

    async def test_automatic_preparation_scroll_is_reported(self):
        from worker.metrics.klm import estimate_step
        await self.page.set_content('<div style="height:1600px"></div><button>Far</button>')
        await self.page.locator('button').scroll_into_view_if_needed()
        rows=await observe(self.page)
        await self.page.evaluate('scrollTo(0,0)')
        result=await self.driver.perform(ClickAction(action='click',target=rows[0]['el_id'],thought='Click',expectation='Effect'))
        self.assertTrue(result.auto_scrolled)
        self.assertAlmostEqual(estimate_step(dict(action='click'),first_action=False,auto_scrolled=result.auto_scrolled),3.75)
