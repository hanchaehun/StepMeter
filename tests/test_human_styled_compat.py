"""Compatibility checks for the MUI-shaped native controls, not human trials."""
import tempfile
import unittest
from pathlib import Path

from tests.test_collect_styled_controls import STYLE, control
from tests.test_human_session import meta, schema, session


class HumanStyledCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self, html, interact):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'page.html'
            path.write_text('<main>' + STYLE + html + '</main>', encoding='utf-8')
            data = await session.run_session_async(meta(), path.as_uri(), headless=True, interact=interact)
        self.assertEqual(schema.validate_session(data), [])
        self.assertTrue(all(set(e) == {'t_ms', 'type', 'x', 'y', 'target_key'} for e in data['events']))
        return data

    async def test_pointer_toggle_twice_keeps_native_target_key(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            for checked in (True, False):
                await page.locator('input').click()
                self.assertEqual(await page.locator('input').is_checked(), checked)
            await page.wait_for_timeout(50)
            return True

        data = await self.run_fixture(control('Women'), interact)
        events = [e for e in data['events'] if e['type'] in ('down', 'up', 'click')]
        self.assertEqual([e['type'] for e in events], ['down', 'up', 'click'] * 2)
        self.assertTrue(all(e['target_key'] == 'input|checkbox|Women||main' for e in events), events)

    async def test_keyboard_toggle_has_key_without_synthetic_click(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            await page.locator('input').focus()
            await page.keyboard.press('Space')
            self.assertTrue(await page.locator('input').is_checked())
            await page.wait_for_timeout(50)
            return True

        data = await self.run_fixture(control('Women'), interact)
        keys = [e for e in data['events'] if e['type'] == 'key']
        self.assertEqual([e['target_key'] for e in keys], ['input|checkbox|Women||main'])
        self.assertEqual([e for e in data['events'] if e['type'] == 'click'], [])

    async def test_visible_label_operated_checkbox_records_linked_input(self):
        # PM 결정(2026-11-10, ADR 0010 9번): 사람 수집은 보이는 label을 눌러 조작할 수 있는 체크박스·라디오를
        # 연결된 입력칸으로 기록한다. 근거: #43·#44의 6페이지 핵심 클릭 기대 대상(4번 Remember Me → input|checkbox).
        # 좌표(손 계산): body 여백 8px → label (8..158, 8..48), 그 안의 투명 입력칸 (8..46, 8..46).
        # (100, 28)은 label 글자 쪽(입력칸 밖), (27, 27)은 입력칸 자리.
        async def interact(page):
            await page.wait_for_timeout(400)
            await page.mouse.click(100, 28)
            self.assertTrue(await page.locator('input').is_checked())    # label로 실제 조작된다
            await page.mouse.click(27, 27)
            self.assertFalse(await page.locator('input').is_checked())
            await page.wait_for_timeout(50)
            return True

        data = await self.run_fixture('<label><span class="control"><input type="checkbox"></span>No indicator</label>', interact)
        events = [e for e in data['events'] if e['type'] in ('down', 'up', 'click')]
        self.assertEqual([(e['type'], e['x']) for e in events],
                         [('down', 100), ('up', 100), ('click', 100), ('down', 27), ('up', 27), ('click', 27)])
        self.assertEqual([e['target_key'] for e in events], ['input|checkbox|No indicator||main'] * 6, events)

    # 숨김 사례는 tests/test_collect_styled_controls.py의 제외 사례와 같은 모양이다. 화면 밖 사례만 label은
    # 화면 안에 두고 입력칸을 화면 밖으로 보냈다(화면 밖 label은 누를 수 없다). 마지막 줄은 본문 글자.
    # 좌표(손 계산): body 여백 8px, 150×40 label이 세로로 쌓인다 → i번째 줄 (8..158, 8+40i..48+40i).
    # 줄마다 입력칸 자리 (27, 27+40i)와 label 글자 쪽 (100, 28+40i), 본문 글자는 6번째 줄 (30, 228).
    OPERATE_CASES = [
        ('Hidden display', control('Hidden display', attrs='style="display:none"')),
        ('Hidden visibility', control('Hidden visibility', attrs='style="visibility:hidden"')),
        ('No pointer', control('No pointer', attrs='style="pointer-events:none"')),
        ('Offscreen', control('Offscreen', attrs='style="position:fixed;left:-9999px"')),
        ('Hidden parent', control('Hidden parent', wrapper='opacity:0')),
    ]
    BODY_TEXT = '<p style="margin:0;height:40px">본문 글자</p>'

    async def operated_rows(self):
        """클릭마다 (사례, 누른 곳, 브라우저가 조작한 입력칸의 key 또는 None, 기록된 target_key 목록)."""
        spots = []
        for i, (name, _) in enumerate(self.OPERATE_CASES):
            spots += [(name, '입력칸 자리', 27, 27 + 40 * i), (name, 'label 글자 쪽', 100, 28 + 40 * i)]
        spots.append(('본문 글자', '글자', 30, 228))
        checked_js = "() => [...document.querySelectorAll('input')].map(el => el.checked)"
        # 입력칸의 key는 수집 번들 describe(el)의 다섯 칸을 element_key 형식(tag|role|name|label_text|landmark)으로 잇는다
        keys_js = """() => [...document.querySelectorAll('input')].map(el => {
            const d = __stepmeter.describe(el);
            return [d.tag, d.role ?? '', d.name ?? '', d.label_text ?? '', d.landmark ?? ''].join('|');
        })"""
        operated = []

        async def interact(page):
            await page.wait_for_timeout(400)
            keys = await page.evaluate(keys_js)
            for _, _, x, y in spots:
                before = await page.evaluate(checked_js)
                await page.mouse.click(x, y)
                after = await page.evaluate(checked_js)
                changed = [k for k, b, a in zip(keys, before, after) if b != a]
                self.assertLessEqual(len(changed), 1, (x, y, changed))
                operated.append(changed[0] if changed else None)
            await page.wait_for_timeout(50)
            return True

        html = ''.join(case for _, case in self.OPERATE_CASES) + self.BODY_TEXT
        data = await self.run_fixture(html, interact)
        pointer = [e for e in data['events'] if e['type'] in ('down', 'up', 'click')]
        return [(name, spot, key, [e['target_key'] for e in pointer if (e['x'], e['y']) == (x, y)])
                for (name, spot, x, y), key in zip(spots, operated)]

    async def test_records_control_only_when_click_operates_it(self):
        # PM 결정(2026-11-10 수정, ADR 0010 9번): 사람 수집은 클릭이 실제로 조작한 컨트롤을 기록한다. label이면
        # 연결된 입력칸, 조작된 컨트롤이 없으면(본문 글자 등) null. 입력칸 자체의 CSS로는 판단하지 않는다.
        # 기대값은 브라우저에서 읽은 클릭 전후 input.checked다: 바뀐 입력칸이 있으면 그 입력칸의 key, 없으면 null.
        rows = await self.operated_rows()
        self.assertEqual(len(rows), 11)
        for name, spot, operated_key, recorded in rows:
            with self.subTest(case=name, spot=spot):
                self.assertEqual(recorded, [operated_key] * 3)   # down·up·click
        self.assertIsNone(rows[-1][2])   # 본문 글자 클릭은 어떤 입력칸도 조작하지 않는다
