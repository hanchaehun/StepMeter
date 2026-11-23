"""#75: 수집 역할 추가, 30개 정렬, type submit(입력 후 Enter).

기대값은 #75 결정에서 정한다(구현을 보고 만들지 않았다).
- 수집 역할: option, menuitemcheckbox, menuitemradio, radio, switch, combobox, treeitem, slider,
  spinbutton, searchbox, textbox 역할 요소는 tabindex가 없거나 -1이어도 수집한다.
- 30개 정렬: 30개 이하면 문서 순서. 넘으면 ① 열린 겹침 층(가장 가까운 조상이 dialog[open],
  [role=dialog], [role=alertdialog], [aria-modal="true"], [role=listbox], [role=menu]) 안의 요소
  ② 가려지지 않은 요소 ③ 텍스트 입력칸 ④ main 안 → 화면 중심 거리 → 큰 순 → el_id.
  정렬 전용 필드는 LLM 항목에 넣지 않는다. 30개 안의 가려진 요소는 "(가려짐)"(ADR 0010).
- submit=true면 입력 후 같은 요소에서 Enter 한 번. 비밀번호 규칙(ADR 0011 1번)은 그대로 먼저 돈다.

모든 화면은 1280×800이고 아래 고정 CSS로 위치를 정했다.
"""
import unittest

from playwright.async_api import async_playwright

from worker.agent.observation import describe
from worker.agent.safety import LoginWall
from worker.collect.collector import observe
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import TypeAction

VIEWPORT = {'width': 1280, 'height': 800}
# 화면 키 전 이전 observe 행의 키 (ADR 0010 형식). #75 정렬 전용 필드는 LLM 항목에 없어야 한다.
OBSERVE_KEYS = {'el_id', 'tag', 'role', 'name', 'landmark', 'label_text', 'bbox', 'occluded'}

STYLE = '''<style>
body{margin:0;font:14px sans-serif}
main{position:absolute;left:0;top:100px;width:1280px}
main button{position:absolute;width:100px;height:40px;margin:0}
</style>'''


def main_buttons(count, columns=10, top=0):
    """main 안 버튼. 열 간격 120px, 행 간격 60px. 40개(10×4)는 y 100–320, 60개(10×6)는 y 100–440."""
    return ''.join(
        f'<button style="left:{20 + (i % columns) * 120}px;top:{top + (i // columns) * 60}px">B{i + 1}</button>'
        for i in range(count))


def page_html(body):
    return f'<!doctype html><html lang="ko"><head>{STYLE}</head><body>{body}</body></html>'


class ObservationOrderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport=VIEWPORT)
        self.driver = PlaywrightDriver(self.page, window_ms=500)
        self.addAsyncCleanup(self.driver.aclose)

    async def rows(self, body):
        await self.page.set_content(page_html(body))
        elements = await observe(self.page)
        return elements, await describe(elements, self.driver)

    def names(self, rows):
        return [row['name'] for row in rows]

    async def test_modal_email_and_invite_are_in_30_before_occluded_main_buttons(self):
        # 초대 창(aria-modal, landmark 없음) 뒤에 반투명 막이 main 버튼 40개를 덮는다 (#75 확인 사실 2).
        body = (f'<main>{main_buttons(40)}</main>'
                '<div style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:10"></div>'
                '<div role="dialog" aria-modal="true" aria-labelledby="t" style="position:fixed;left:440px;top:250px;'
                'width:400px;height:200px;background:#fff;z-index:11">'
                '<h2 id="t">Invite user</h2><label>Email <input type="email"></label><button>Invite</button></div>')
        elements, rows = await self.rows(body)
        self.assertEqual(len(elements), 42)
        self.assertEqual(len(rows), 30)
        self.assertIn('Email', self.names(rows))
        self.assertIn('Invite', self.names(rows))
        # 겹침 층 2개 다음은 가려진 main 버튼 28개. 30개 안의 가려진 요소는 "(가려짐)"이다 (ADR 0010).
        self.assertEqual(self.names(rows[:2]), ['Email', 'Invite'])
        hidden = [row for row in rows if row['occluded']]
        self.assertEqual(len(hidden), 28)
        self.assertTrue(all(row.get('visibility') == '(가려짐)' for row in hidden))
        self.assertTrue(all(set(row) <= OBSERVE_KEYS | {'visibility'} for row in rows))

    async def test_popover_options_without_tabindex_are_collected_and_in_30(self):
        # cmdk 팝오버 형태: role=dialog 안 listbox의 role=option 5개, tabindex 없음 (#75 확인 사실 1, /tasks Status).
        options = ''.join(f'<div role="option" style="height:32px">{n}</div>'
                          for n in ('Backlog', 'Todo', 'In Progress', 'Done', 'Canceled'))
        body = (f'<main>{main_buttons(40)}</main>'
                '<div role="dialog" style="position:fixed;left:20px;top:460px;width:220px;background:#fff">'
                f'<div role="listbox" aria-label="Status">{options}</div></div>')
        elements, rows = await self.rows(body)
        collected = [e for e in elements if e['role'] == 'option']
        self.assertEqual([e['name'] for e in collected], ['Backlog', 'Todo', 'In Progress', 'Done', 'Canceled'])
        self.assertEqual(len(elements), 45)
        self.assertEqual(self.names(rows[:5]), ['Backlog', 'Todo', 'In Progress', 'Done', 'Canceled'])

    async def test_body_end_listbox_options_with_negative_tabindex_are_collected_and_in_30(self):
        # Radix Select 포털 형태: body 끝 role=listbox 안 role=option 4개, tabindex=-1 (#75 확인 사실 1, Role 선택).
        options = ''.join(f'<div role="option" tabindex="-1" style="height:32px">{n}</div>'
                          for n in ('Superadmin', 'Admin', 'Manager', 'Cashier'))
        body = (f'<main>{main_buttons(40)}</main>'
                f'<div role="listbox" style="position:fixed;left:600px;top:460px;width:200px;background:#fff">'
                f'{options}</div>')
        elements, rows = await self.rows(body)
        self.assertEqual([e['name'] for e in elements if e['role'] == 'option'],
                         ['Superadmin', 'Admin', 'Manager', 'Cashier'])
        self.assertEqual(len(rows), 30)
        self.assertEqual(self.names(rows[:4]), ['Superadmin', 'Admin', 'Manager', 'Cashier'])

    async def test_header_search_input_is_in_30_with_60_main_buttons(self):
        # 미치 머리글 검색창 형태: header(banner)의 검색 input + main 버튼 60개, 가린 것 없음 (#75 확인 사실 2).
        body = ('<header style="position:absolute;left:0;top:0;width:1280px;height:80px">'
                '<input type="search" aria-label="Search places" style="position:absolute;left:900px;top:20px;width:300px;height:36px">'
                f'</header><main>{main_buttons(60)}</main>')
        elements, rows = await self.rows(body)
        self.assertEqual(len(elements), 61)
        search = next(e for e in elements if e['name'] == 'Search places')
        self.assertEqual((search['landmark'], search['occluded']), ('banner', False))
        # 겹침 층·가려진 요소가 없으니 텍스트 입력칸이 맨 앞이다.
        self.assertEqual(rows[0]['name'], 'Search places')
        self.assertEqual(len(rows), 30)

    async def test_30_or_fewer_elements_keep_document_order_and_fields(self):
        body = ('<header><a href="#home">Home</a></header>'
                '<main><button style="position:static">Go</button><input aria-label="Name"></main>')
        elements, rows = await self.rows(body)
        self.assertEqual([r['el_id'] for r in rows], [1, 2, 3])
        self.assertEqual(self.names(rows), ['Home', 'Go', 'Name'])
        self.assertEqual([set(r) for r in rows], [OBSERVE_KEYS] * 3)
        self.assertEqual(rows, [{k: v for k, v in e.items() if k in OBSERVE_KEYS} for e in elements])

    async def test_widget_roles_are_collected_without_tabindex(self):
        roles = ['option', 'menuitemcheckbox', 'menuitemradio', 'radio', 'switch', 'combobox',
                 'treeitem', 'slider', 'spinbutton', 'searchbox', 'textbox']
        body = '<main>' + ''.join(
            f'<div role="{role}" aria-label="w-{role}" style="height:20px;width:120px">{role}</div>'
            for role in roles) + '<div style="height:20px">plain text</div></main>'
        await self.page.set_content(page_html(body))
        elements = await observe(self.page)
        self.assertEqual([e['name'] for e in elements], [f'w-{role}' for role in roles])
        self.assertEqual([e['role'] for e in elements], roles)


class SubmitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport=VIEWPORT)

    def driver(self, task=''):
        driver = PlaywrightDriver(self.page, task_description=task, window_ms=500)
        self.addAsyncCleanup(driver.aclose)
        return driver

    async def type_into(self, driver, text, submit):
        rows = await observe(self.page)
        target = next(r['el_id'] for r in rows if r['tag'] == 'input')
        return await driver.perform(TypeAction(action='type', target=target, text=text, submit=submit,
                                               thought='검색어를 넣는다', expectation='결과가 보인다'))

    # 실행 버튼이 없는 검색 폼: Enter(암묵적 제출)로만 실행된다. 미치 검색과 같은 경우 (#75 확인 사실 3).
    SEARCH = ('<form onsubmit="event.preventDefault();document.querySelector(\'#out\').textContent=\'결과: \'+this.q.value">'
              '<input name="q" type="search" aria-label="검색"></form><p id="out"></p>')

    async def test_submit_true_runs_enter_only_search_in_one_observation(self):
        await self.page.set_content(page_html(self.SEARCH))
        result = await self.type_into(self.driver(), '시부야', True)
        self.assertEqual(await self.page.locator('#out').text_content(), '결과: 시부야')
        self.assertEqual(await self.page.locator('input').input_value(), '시부야')
        self.assertEqual(result.effect.as_step_effect(), {'changed': True, 'effect_type': 'dom_mutation'})

    async def test_submit_false_does_not_run_search(self):
        await self.page.set_content(page_html(self.SEARCH))
        await self.type_into(self.driver(), '시부야', False)
        self.assertEqual(await self.page.locator('#out').text_content(), '')
        self.assertEqual(await self.page.locator('input').input_value(), '시부야')

    LOGIN = ('<form onsubmit="event.preventDefault();document.querySelector(\'#out\').textContent=\'제출됨\'">'
             '<input type="password" aria-label="비밀번호"></form><p id="out"></p>')

    async def test_password_with_submit_keeps_password_rule(self):
        # 과업에 없는 값: 입력도 Enter도 하지 않고 LoginWall (ADR 0011 1번)
        await self.page.set_content(page_html(self.LOGIN))
        with self.assertRaises(LoginWall):
            await self.type_into(self.driver('비밀번호 Study1234로 로그인한다'), 'Guess999', True)
        self.assertEqual(await self.page.locator('input').input_value(), '')
        self.assertEqual(await self.page.locator('#out').text_content(), '')

    async def test_password_from_task_with_submit_is_typed_and_submitted(self):
        await self.page.set_content(page_html(self.LOGIN))
        await self.type_into(self.driver('비밀번호 Study1234로 로그인한다'), 'Study1234', True)
        self.assertEqual(await self.page.locator('#out').text_content(), '제출됨')


if __name__ == '__main__':
    unittest.main()
