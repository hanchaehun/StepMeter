"""관찰 보강 (action_v4): 요소 상태, LLM에 보내는 한 줄 형식, 60개 상한.

기대값은 PM 결정에서 가져왔다(구현을 보고 만들지 않았다).
- observe() 행의 state: filled(텍스트 입력칸·textarea 값 유무), checked(checkbox·radio·switch, aria-checked 포함),
  selected(aria-selected), expanded(aria-expanded), disabled(disabled, aria-disabled). 해당하는 것만 넣는다.
  값 자체는 어디에도 넣지 않는다. state는 state_hash·매칭 지문에 들어가지 않는다.
- 한 줄 형식: 번호|역할(없으면 태그)|이름(없으면 label_text)|영역(없으면 -)|x,y,너비x높이(정수)|표시
  표시는 가려짐, 입력됨, 비어 있음, 선택됨, 펼쳐짐, 비활성을 쉼표로 잇는다. select는 줄 끝에 "옵션: 1=..., 2=...".
- 요소가 60개를 넘으면 60개를 고르고, 60개 이하면 문서 순서 그대로 전부 보낸다.
실행 전 `npm run build:collect` 필요.
"""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import async_playwright

from worker.agent.observation import LIMIT, describe, prompt_line, state_hash
from worker.collect.collector import observe
from worker.driver.playwright_driver import PlaywrightDriver
from worker.matching.match import fingerprint

PROMPT = Path(__file__).resolve().parents[1] / 'prompts' / 'action_v4.md'

# 고정 예시 행. 손으로 적은 기대 줄은 아래 EXAMPLE_LINE이고, 같은 줄이 prompts/action_v4.md에 있어야 한다.
EXAMPLE_ROW = {'el_id': 12, 'tag': 'input', 'role': 'checkbox', 'name': 'Remember me', 'landmark': 'main',
               'label_text': None, 'bbox': {'x': 24.4, 'y': 409.6, 'width': 16.2, 'height': 15.8},
               'occluded': True, 'state': {'checked': True, 'disabled': False}}
EXAMPLE_LINE = '12|checkbox|Remember me|main|24,410,16x16|가려짐,선택됨'


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 1280, 'height': 800})

    async def items(self, body):
        await self.page.set_content(f'<!doctype html><html lang="en"><body>{body}</body></html>')
        return await observe(self.page)

    def by_name(self, items, name):
        return next(i for i in items if i['name'] == name)

    async def test_filled_checked_selected_expanded(self):
        items = await self.items(
            '<label>Full <input value="Kim"></label><label>Empty <input></label>'
            '<label>Note <textarea>x</textarea></label>'
            '<label>Agree <input type="checkbox" checked></label><label>Later <input type="checkbox"></label>'
            '<div role="switch" aria-checked="true" aria-label="Dark" tabindex="0">D</div>'
            '<div role="listbox" aria-label="Status"><div role="option" aria-selected="true">Todo</div>'
            '<div role="option" aria-selected="false">Done</div></div>'
            '<button aria-expanded="true">Filter</button><button disabled>Gone</button>'
            '<button aria-disabled="true">Soft</button>')
        state = lambda name: self.by_name(items, name)['state']
        self.assertIs(state('Full')['filled'], True)
        self.assertIs(state('Empty')['filled'], False)
        self.assertIs(state('Note')['filled'], True)
        self.assertIs(state('Agree')['checked'], True)
        self.assertIs(state('Later')['checked'], False)
        self.assertIs(state('Dark')['checked'], True)
        self.assertIs(state('Todo')['selected'], True)
        self.assertIs(state('Done')['selected'], False)
        self.assertIs(state('Filter')['expanded'], True)
        self.assertIs(state('Gone')['disabled'], True)
        self.assertIs(state('Soft')['disabled'], True)
        # 해당하지 않는 값은 넣지 않는다.
        self.assertNotIn('expanded', state('Full'))
        self.assertNotIn('filled', state('Filter'))

    async def test_password_value_never_leaves_the_page(self):
        await self.page.set_content('<!doctype html><html lang="en"><body>'
                                    '<label>Password <input type="password"></label><button>Sign in</button></body></html>')
        await self.page.fill('input', 'S3cret!x')
        items = await observe(self.page)
        driver = SimpleNamespace(page=self.page)
        lines = [prompt_line(r) for r in await describe(items, driver)]
        self.assertIs(self.by_name(items, 'Password')['state']['filled'], True)
        self.assertNotIn('S3cret!x', json.dumps(items, ensure_ascii=False))
        self.assertNotIn('S3cret!x', '\n'.join(lines))
        self.assertIn('입력됨', lines[0])

    async def test_cmdk_cursor_item_is_not_reported_as_selected(self):
        # cmdk는 aria-selected를 체크된 항목이 아니라 커서가 놓인 항목에 붙인다(Status 필터를 열면 Backlog).
        # [cmdk-item]에서는 selected 키를 넣지 않는다. 다른 role=option, role=tab은 그대로다.
        items = await self.items(
            '<div role="listbox" aria-label="Status"><div cmdk-item role="option" aria-selected="true">Backlog</div></div>'
            '<div role="listbox" aria-label="Role"><div role="option" aria-selected="true">Admin</div></div>'
            '<div role="tablist"><div role="tab" aria-selected="true">Overview</div></div>')
        self.assertNotIn('selected', self.by_name(items, 'Backlog')['state'])
        self.assertIs(self.by_name(items, 'Admin')['state']['selected'], True)
        self.assertIs(self.by_name(items, 'Overview')['state']['selected'], True)

    async def test_select_line_lists_options(self):
        await self.page.set_content('<!doctype html><html lang="en"><body>'
                                    '<select aria-label="Role" style="position:absolute;left:10px;top:20px;width:100px;height:30px">'
                                    '<option>Admin</option><option>User</option></select></body></html>')
        driver = PlaywrightDriver(self.page, window_ms=500)
        self.addAsyncCleanup(driver.aclose)
        rows = await describe(await observe(self.page), driver)
        self.assertTrue(prompt_line(rows[0]).endswith('옵션: 1=Admin, 2=User'))


class LineFormatTests(unittest.IsolatedAsyncioTestCase):
    def test_fixed_example_line_matches_hand_written_and_prompt(self):
        self.assertEqual(prompt_line(EXAMPLE_ROW), EXAMPLE_LINE)
        self.assertIn(EXAMPLE_LINE, PROMPT.read_text(encoding='utf-8'))

    def test_missing_role_name_landmark_fall_back(self):
        row = {'el_id': 3, 'tag': 'div', 'role': None, 'name': '', 'label_text': 'Qty',
               'landmark': None, 'bbox': {'x': 0, 'y': 0, 'width': 10, 'height': 10},
               'occluded': False, 'state': {'filled': False}}
        self.assertEqual(prompt_line(row), '3|div|Qty|-|0,0,10x10|비어 있음')

    def test_pipe_in_name_label_and_options_becomes_slash(self):
        # worker/rules/r09.py와 같은 방식: 글자 안의 "|"는 "/"로 바꿔 칸 구분이 어긋나지 않게 한다.
        bbox = {'x': 0, 'y': 0, 'width': 10, 'height': 10}
        line = prompt_line({'el_id': 2, 'tag': 'a', 'role': 'link', 'name': '로그인 | 회원가입', 'label_text': None,
                            'landmark': 'banner', 'bbox': bbox, 'occluded': False, 'state': {}})
        self.assertEqual(line.count('|'), 5)
        self.assertEqual(line.split('|')[2], '로그인 / 회원가입')
        unnamed = prompt_line({'el_id': 3, 'tag': 'button', 'role': 'button', 'name': '', 'label_text': 'A|B',
                               'landmark': None, 'bbox': bbox, 'occluded': False, 'state': {}})
        self.assertEqual(unnamed.split('|')[2], 'A/B')
        select = prompt_line({'el_id': 4, 'tag': 'select', 'role': 'combobox', 'name': 'Size', 'label_text': None,
                              'landmark': None, 'bbox': bbox, 'occluded': False, 'state': {},
                              'options': [{'option': 1, 'text': 'S | 90'}, {'option': 2, 'text': 'M'}]})
        self.assertEqual(select, '4|combobox|Size|-|0,0,10x10||옵션: 1=S / 90, 2=M')

    def test_all_marks_in_order(self):
        row = {'el_id': 1, 'tag': 'button', 'role': 'button', 'name': 'X', 'label_text': None,
               'landmark': 'main', 'bbox': {'x': 1, 'y': 2, 'width': 3, 'height': 4}, 'occluded': True,
               'state': {'filled': True, 'selected': True, 'expanded': True, 'disabled': True}}
        self.assertEqual(prompt_line(row), '1|button|X|main|1,2,3x4|가려짐,입력됨,선택됨,펼쳐짐,비활성')

    def test_state_does_not_change_state_hash_or_fingerprint(self):
        row = {'el_id': 1, 'tag': 'input', 'role': 'textbox', 'name': 'Email', 'label_text': None,
               'landmark': 'main', 'bbox': {'x': 0, 'y': 0, 'width': 10, 'height': 10}, 'occluded': False}
        empty, filled = {**row, 'state': {'filled': False}}, {**row, 'state': {'filled': True}}
        self.assertEqual(state_hash('http://a.test/users', [empty]), state_hash('http://a.test/users', [filled]))
        self.assertEqual(fingerprint(empty), fingerprint(filled))
        self.assertNotIn('state', fingerprint(filled))

    async def test_sixty_limit(self):
        self.assertEqual(LIMIT, 60)
        bbox = {'x': 10, 'y': 10, 'width': 20, 'height': 20}
        rows = lambda n: [{'el_id': i, 'tag': 'button', 'role': 'button', 'name': f'B{i}', 'label_text': None,
                           'landmark': 'main', 'bbox': bbox, 'occluded': False, 'state': {}}
                          for i in range(1, n + 1)]
        driver = SimpleNamespace(page=SimpleNamespace(viewport_size={'width': 1280, 'height': 800}))
        self.assertEqual(len(await describe(rows(61), driver)), 60)
        self.assertEqual([r['el_id'] for r in await describe(rows(60), driver)], list(range(1, 61)))


if __name__ == '__main__':
    unittest.main()
