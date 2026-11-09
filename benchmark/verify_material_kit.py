"""Verify MUI normal tasks and source mutations after React rerendering."""
import asyncio
import json

from playwright.async_api import async_playwright

from benchmark.build_variant import ROOT, VARIANTS
from benchmark.serve import serve
from worker.collect.collector import observe, record_first_view, snapshot
from worker.rules import r06

APP = 'material-kit-react'
OUTPUT = ROOT / 'evidence' / APP / 'w2'
TOGGLE = '.MuiInputBase-root:has(input[name="password"]) button:first-of-type'
LABEL = '.MuiFormControl-root:has(input[name="password"]) > label'


async def verify():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    labels = {'split': 'development', 'review_status': 'pending', 'cases': {}}
    rules = dict(small='R01', contrast='R02', inert='R03', overlay='R04', **{'below-fold': 'R06'}, unnamed='R10')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for variant in VARIANTS:
                directory = ROOT / 'builds' / APP / variant / 'dist'
                if not directory.exists():
                    raise ValueError(f'{variant} build missing')
                with serve(directory) as origin:
                    page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                    await page.goto(origin + '/sign-in')
                    await page.locator('input[name=email]').wait_for()
                    await page.evaluate('document.fonts.ready')
                    await record_first_view(page)
                    if variant == 'below-fold':
                        await page.locator('input[name=email]').scroll_into_view_if_needed()
                    items = await observe(page)
                    initial = await snapshot(page, next(i['el_id'] for i in items if i['name'] == 'Email address'))
                    assert bool(r06.evaluate(initial, is_first_target=True)) == (variant == 'below-fold')
                    await page.locator('input[name=email]').fill('demo@example.test')
                    await page.locator('input[name=password]').fill('demo-password')
                    target = page.locator(TOGGLE)
                    await target.scroll_into_view_if_needed()
                    box = await target.bounding_box()
                    if variant == 'small':
                        assert box['width'] == box['height'] == 16
                        help_box = await page.get_by_role('button', name='Password help').bounding_box()
                        assert abs(help_box['x'] - box['x']) < 24
                    if variant == 'overlay':
                        items = await observe(page)
                        snap = await snapshot(page, next(i['el_id'] for i in items if i['name'] == 'Show password'))
                        assert snap.occluded
                    await page.add_script_tag(path=str(ROOT.parent / 'node_modules/axe-core/axe.min.js'))
                    axe = await page.evaluate('async () => await axe.run()')
                    ids = {v['id'] for v in axe['violations']}
                    if variant == 'baseline':
                        assert not ids, ids
                    if variant == 'contrast':
                        assert 'color-contrast' in ids
                    if variant == 'unnamed':
                        assert 'button-name' in ids
                    await page.screenshot(path=str(OUTPUT / f'{variant}.png'), full_page=False)
                    if variant != 'overlay':
                        await target.click()
                        if variant == 'inert':
                            await page.wait_for_timeout(3000)
                            assert await page.locator('input[name=password]').get_attribute('type') == 'password'
                        else:
                            assert await page.locator('input[name=password]').get_attribute('type') == 'text'
                            if variant == 'small':
                                assert (await target.bounding_box())['width'] == 16  # survives rerender
                    else:
                        try:
                            await target.click(timeout=500)
                        except Exception:
                            pass
                        else:
                            raise AssertionError('Overlay did not block click')
                    target_key = 'input[name="email"]' if variant == 'below-fold' else LABEL if variant == 'contrast' else TOGGLE
                    labels['cases'][variant] = [] if variant == 'baseline' else [{'rule': rules[variant], 'target': target_key}]
                    results.append({'case': variant, 'verified': True, 'axe_violations': sorted(ids),
                                    'first_snapshot': initial.model_dump()})
                    (OUTPUT / f'{variant}-axe.json').write_text(json.dumps(axe, indent=2), encoding='utf-8')
                    await page.close()
            with serve(ROOT / 'builds' / APP / 'baseline/dist') as origin:
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                await page.goto(origin + '/products')
                await page.get_by_role('button', name='Sort By:').click()
                await page.get_by_role('menuitem', name='Price: Low-High').click()
                await page.get_by_role('button', name='Filters', exact=True).click()
                await page.get_by_role('radio', name='Apparel').check()
                assert await page.get_by_role('radio', name='Apparel').is_checked()
                await page.wait_for_timeout(500)
                await page.add_script_tag(path=str(ROOT.parent / 'node_modules/axe-core/axe.min.js'))
                axe = await page.evaluate('async () => await axe.run()')
                assert not axe['violations'], {v['id'] for v in axe['violations']}
                await page.screenshot(path=str(OUTPUT / 'baseline-products.png'), full_page=False)
                labels['cases']['baseline-products'] = []
        finally:
            await browser.close()
    (OUTPUT / 'verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    (OUTPUT / 'labels-candidate.json').write_text(json.dumps(labels, indent=2) + '\n', encoding='utf-8')
    print('MUI: two normal tasks and six source mutations verified; review pending')


if __name__ == '__main__':
    asyncio.run(verify())
