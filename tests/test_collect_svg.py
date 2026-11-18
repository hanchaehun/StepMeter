"""Disconnected painted rectangles: bbox centre is empty, both islands visible.

The authored path paints (40,40)-(78,64) and (40,135)-(46,147).
Its bounding box is 38x107 and centre (59,93.5) is water, not an occluder.
"""
import unittest

from playwright.async_api import async_playwright

from worker.collect.collector import click_point, observe, snapshot
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import ClickAction


HTML = '''<style>body{margin:0} svg{background:lightblue}</style>
<svg width="300" height="220" viewBox="0 0 300 220">
<path id="tokyo" role="button" tabindex="0" aria-label="Tokyo" fill="green"
d="M40 40H78V64H40Z M40 135H46V147H40Z"
onclick="document.querySelector('output').textContent='opened'"></path></svg>
<output>closed</output>'''


class SVGTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page(viewport={'width': 800, 'height': 600})
        self.driver = PlaywrightDriver(self.page, window_ms=1000)
        self.addAsyncCleanup(self.driver.aclose)

    async def test_opt_out_restores_center_contract(self):
        await self.page.evaluate('globalThis.__stepmeterSvgGeometry = false')
        await self.page.set_content(HTML)
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertTrue(row['occluded'])

    async def test_default_on_disconnected_path_is_not_occluded_and_number_click_opens(self):
        await self.page.set_content(HTML)
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertFalse(row['occluded'], 'Empty SVG bbox centre is not a covering element')
        result = await self.driver.perform(ClickAction(action='click', target=row['el_id'],
            thought='Open Tokyo', expectation='Travel guide opens'))
        self.assertFalse(result.element.occluded)
        self.assertEqual(await self.page.locator('output').inner_text(), 'opened')

    async def test_real_cover_still_blocks(self):
        await self.page.set_content(HTML + '<div style="position:absolute;inset:0;background:#fff8"></div>')
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertTrue(row['occluded'])
        await self.driver.perform(ClickAction(action='click', target=row['el_id'],
            thought='Open Tokyo', expectation='Travel guide opens'))
        self.assertEqual(await self.page.locator('output').inner_text(), 'closed')

    async def test_interactive_group_uses_noninteractive_child_geometry(self):
        grouped = '''<style>body{margin:0}</style><svg width="300" height="220">
        <g role="button" tabindex="0" aria-label="Tokyo" fill="green"
        onclick="document.querySelector('output').textContent='opened'">
        <path d="M40 40H78V64H40Z M40 135H46V147H40Z"></path></g></svg>
        <output>closed</output>'''
        await self.page.set_content(grouped)
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertEqual(row['tag'], 'g')
        self.assertFalse(row['occluded'])
        await self.driver.perform(ClickAction(action='click', target=row['el_id'],
            thought='Open Tokyo', expectation='Travel guide opens'))
        self.assertEqual(await self.page.locator('output').inner_text(), 'opened')

    async def test_cover_added_after_observation_is_checked_again(self):
        await self.page.set_content(HTML)
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        await self.page.evaluate('''() => {
            const cover=document.createElement('div');
            cover.style.cssText='position:absolute;inset:0;background:#fff8';
            document.body.append(cover);
        }''')
        self.assertTrue((await snapshot(self.page, row['el_id'])).occluded)

    async def test_partial_cover_does_not_change_the_chosen_geometry_point(self):
        await self.page.set_content(HTML)
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        point = await click_point(self.page, row['el_id'])
        await self.page.evaluate('''({x,y}) => {
            const cover=document.createElement('div');
            cover.style.cssText=`position:absolute;left:${x-2}px;top:${y-2}px;width:4px;height:4px;background:red`;
            document.body.append(cover);
        }''', point)
        # Most of both islands remains exposed. The predetermined point is
        # covered, so the collector must not pick another exposed location.
        self.assertTrue((await snapshot(self.page, row['el_id'])).occluded)

    async def test_open_shadow_group_and_real_outer_overlay(self):
        await self.page.set_content('<div id="host"></div>')
        await self.page.locator('#host').evaluate('(el,html)=>el.attachShadow({mode:"open"}).innerHTML=html', HTML)
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertFalse(row['occluded'])
        await self.page.evaluate('''() => {
            const c=document.createElement('div');c.style.cssText='position:absolute;inset:0;background:red';
            document.body.append(c);
        }''')
        self.assertTrue((await snapshot(self.page, row['el_id'])).occluded)

    async def test_painted_center_covered_does_not_search_uncovered_edges(self):
        # Solid 100x100 square. Only its centre is covered; keep the centre rule.
        await self.page.set_content(HTML.replace('M40 40H78V64H40Z M40 135H46V147H40Z',
            'M40 40H140V140H40Z') +
            '<div style="position:absolute;left:80px;top:80px;width:20px;height:20px;background:red"></div>')
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertTrue(row['occluded'])

    async def test_transformed_shape_inside_same_origin_frame(self):
        await self.page.set_content('<iframe style="position:absolute;left:100px;top:80px;width:400px;height:300px;border:0"></iframe>')
        frame = self.page.frames[1]
        await frame.set_content(HTML.replace('<path ', '<path transform="translate(20,10) scale(1.2)" '))
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertFalse(row['occluded'])
        await self.driver.perform(ClickAction(action='click', target=row['el_id'],
            thought='Open Tokyo', expectation='Travel guide opens'))
        self.assertEqual(await frame.locator('output').inner_text(), 'opened')

    async def test_css_perspective_projects_the_shape_plane(self):
        await self.page.set_content(HTML.replace('<svg ',
            '<svg style="transform:perspective(500px) rotateX(25deg) rotateY(-20deg)" '))
        row = next(r for r in await observe(self.page) if r['name'] == 'Tokyo')
        self.assertFalse(row['occluded'])
        await self.driver.perform(ClickAction(action='click', target=row['el_id'],
            thought='Open Tokyo', expectation='Travel guide opens'))
        self.assertEqual(await self.page.locator('output').inner_text(), 'opened')
