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

    async def test_unrepresented_transparent_input_does_not_gain_target_key(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            await page.mouse.click(27, 27)
            await page.wait_for_timeout(50)
            return True

        data = await self.run_fixture('<label><span class="control"><input type="checkbox"></span>No indicator</label>', interact)
        clicks = [e for e in data['events'] if e['type'] == 'click']
        self.assertEqual(len(clicks), 1)
        self.assertIsNone(clicks[0]['target_key'])
