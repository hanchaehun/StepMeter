"""Enter 제출(type submit=true)도 click과 같은 "되돌릴 수 없는 버튼" 안전 검사를 거친다.

기대값 근거(2026-11-23 PM 지시, ADR 0011 10번): guard_target(..., submit=True)는 Enter가 일으킬 동작의 후보에
click과 같은 판정을 적용하고, 하나라도 걸리면 SafetyStop('Irreversible submit')이다.
1. 입력칸에 폼(el.form, form= 속성 포함)이 있으면 폼의 기본 제출 버튼: [...form.elements]에서 문서 순서로
   첫 번째 type=submit 버튼(type 없는 button 포함)·input[type=submit]·input[type=image].
   없으면 폼의 aria-label·name·title.
2. 폼이 없으면(textarea·contenteditable 포함) 조상 3단계 안의 button·[role=button]·input[type=submit].
3. 후보가 없거나 걸리지 않으면 지금처럼 Enter.
"""
import unittest
from unittest.mock import patch

from playwright.async_api import async_playwright

import worker.driver.playwright_driver as driver_module
from worker.agent.safety import SafetyStop, guard_target, is_irreversible_label
from worker.collect.collector import observe, resolve_element
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import TypeAction

# 제출 이벤트와 Enter 키를 센다. 제출은 막아 페이지가 바뀌지 않게 한다.
COUNTERS = '''<p id="out"></p><script>
window.__submits = 0; window.__enters = 0;
document.addEventListener('submit', e => { e.preventDefault(); window.__submits++;
  document.querySelector('#out').textContent = '제출됨'; }, true);
document.addEventListener('keydown', e => { if (e.key === 'Enter') window.__enters++; }, true);
</script>'''


def form(controls, attrs=''):
    return f'<form id="f" {attrs}><input aria-label="메모" name="q">{controls}</form>{COUNTERS}'


class SubmitSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 1280, 'height': 800})
        self.driver = PlaywrightDriver(self.page, task_description='메모에 테스트를 적는다', window_ms=500)
        self.addAsyncCleanup(self.driver.aclose)

    async def type_into(self, html, submit, name='메모'):
        await self.page.set_content(html)
        rows = await observe(self.page)
        target = next(r['el_id'] for r in rows if r['name'] == name)
        return await self.driver.perform(TypeAction(action='type', target=target, text='테스트', submit=submit,
                                                    thought='적는다', expectation='들어간다'))

    async def counts(self):
        return await self.page.evaluate('[window.__submits, window.__enters]')

    async def assert_blocked(self, html, name='메모'):
        with self.assertRaises(SafetyStop) as raised:
            await self.type_into(html, submit=True, name=name)
        self.assertEqual(str(raised.exception), 'Irreversible submit')
        self.assertEqual(await self.counts(), [0, 0])  # 제출 이벤트도 Enter도 없음

    async def test_form_default_button_order_blocks(self):
        await self.assert_blocked(form('<button type="submit">주문하기</button>'))

    async def test_first_submit_button_is_the_default(self):
        # 첫 번째 제출 버튼 "메시지 전송"이 기본 버튼이다. 두 번째 "검색"은 보지 않는다.
        await self.assert_blocked(form('<button type="submit">메시지 전송</button><button type="submit">검색</button>'))

    async def test_button_outside_form_linked_by_form_attribute_blocks(self):
        await self.assert_blocked(form('') + '<button type="submit" form="f">Place order</button>')

    async def test_form_default_button_search_submits(self):
        await self.type_into(form('<button type="submit">검색</button>'), submit=True)
        self.assertEqual(await self.counts(), [1, 1])
        self.assertEqual(await self.page.locator('#out').text_content(), '제출됨')

    async def test_textarea_without_form_next_to_send_blocks(self):
        await self.assert_blocked(f'<div><textarea aria-label="메시지"></textarea><button>Send</button></div>{COUNTERS}',
                                  name='메시지')

    async def test_search_input_without_form_still_presses_enter(self):
        for button in ('<button>검색</button>', '<button aria-label="검색"><svg width="16" height="16"></svg></button>'):
            with self.subTest(button=button):
                await self.type_into(f'<div><input type="search" aria-label="검색어">{button}</div>{COUNTERS}',
                                     submit=True, name='검색어')
                self.assertEqual(await self.counts(), [0, 1])
                self.assertEqual(await self.page.locator('input').input_value(), '테스트')

    async def test_order_form_with_submit_false_only_types(self):
        await self.type_into(form('<button type="submit">주문하기</button>'), submit=False)
        self.assertEqual(await self.counts(), [0, 0])
        self.assertEqual(await self.page.locator('input').input_value(), '테스트')

    async def test_type_button_is_not_a_submit_button(self):
        # type=button은 제출 버튼이 아니다. 기본 제출 버튼은 type 없는 "검색"이다.
        await self.type_into(form('<button type="button">주문하기</button><button>검색</button>'), submit=True)
        self.assertEqual(await self.counts(), [1, 1])

    async def test_form_without_submit_button_checks_form_name(self):
        await self.assert_blocked(form('', attrs='aria-label="결제"'))

    async def test_guard_runs_before_and_right_before_enter(self):
        # 드라이버는 행동 전과 실행 직전(checked_action) 두 번 guard_target(submit=True)을 부른다
        with patch.object(driver_module, 'guard_target', wraps=driver_module.guard_target) as spy:
            await self.type_into(form('<button type="submit">검색</button>'), submit=True)
        self.assertEqual([call.kwargs.get('submit') for call in spy.await_args_list], [True, True])

    async def test_click_judgement_is_unchanged(self):
        # click과 Enter 제출은 같은 판정을 쓴다. click 경로는 지금처럼 SafetyStop('Irreversible control').
        for label in ('주문하기', '메시지 전송', '결제', 'Place order', 'Send message'):
            self.assertTrue(is_irreversible_label(label), label)
        for label in ('검색', '주문 내역 보기', '', None):
            self.assertFalse(is_irreversible_label(label), label)
        await self.page.set_content('<button>주문하기</button>')
        await observe(self.page)
        handle = await resolve_element(self.page, 1)
        try:
            with self.assertRaises(SafetyStop) as raised:
                await guard_target(handle, 'click')
            self.assertEqual(str(raised.exception), 'Irreversible control')
        finally:
            await handle.dispose()


if __name__ == '__main__':
    unittest.main()
