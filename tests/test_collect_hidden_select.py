"""숨긴 native select 수집 제외 (Radix Select).

기대값은 PM 결정에서 가져왔다(구현을 보고 만들지 않았다).
- 요소 자신이 aria-hidden="true"이고 1px 이하로 잘린 요소만 수집에서 뺀다.
- 조상의 aria-hidden(모달 배경)과 aria-hidden이 없는 sr-only 입력칸은 그대로 수집한다.
실행 전 `npm run build:collect` 필요.
"""
import unittest

from playwright.async_api import async_playwright

from worker.collect.collector import observe

# Radix VisuallyHidden가 숨긴 select에 주는 인라인 스타일 그대로.
RADIX_HIDDEN = ('position:absolute;border:0;width:1px;height:1px;padding:0;margin:-1px;'
                'overflow:hidden;clip:rect(0, 0, 0, 0);white-space:nowrap;word-wrap:normal')
SR_ONLY = 'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)'


class HiddenSelectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 800, 'height': 600})

    async def items(self, body):
        await self.page.set_content(f'<!doctype html><html lang="ko"><body>{body}</body></html>')
        return await observe(self.page)

    async def test_radix_hidden_native_select_is_not_collected(self):
        items = await self.items(
            '<form><button type="button" role="combobox" aria-expanded="false">Role</button>'
            f'<select aria-hidden="true" tabindex="-1" style="{RADIX_HIDDEN}">'
            '<option value="admin">Admin</option><option value="user">User</option></select></form>')
        self.assertEqual([i['tag'] for i in items], ['button'])

    async def test_sr_only_checkbox_inside_label_is_kept(self):
        items = await self.items(
            f'<label style="display:inline-block;padding:8px"><input type="checkbox" style="{SR_ONLY}">'
            '<span>Remember me</span></label>')
        self.assertEqual([(i['tag'], i['role']) for i in items], [('input', 'checkbox')])

    async def test_button_under_aria_hidden_ancestor_is_kept(self):
        items = await self.items('<div aria-hidden="true"><button>배경 버튼</button></div>')
        self.assertEqual([i['tag'] for i in items], ['button'])


if __name__ == '__main__':
    unittest.main()
