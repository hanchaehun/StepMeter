"""Offline runtime and mutation verification for the pinned commerce app."""
import asyncio
import json
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from benchmark.build_variant import ROOT, VARIANTS
from benchmark.serve import serve
from worker.collect.collector import observe, record_first_view, snapshot
from worker.rules import r06

APP = 'react-shopping-cart'
OUTPUT = ROOT / 'evidence' / APP / 'w2'
TARGET = '.product-action button:first-of-type'


async def verify():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    labels = {'split': 'development', 'review_status': 'pending', 'cases': {}}
    results = []
    rules = dict(small='R01', contrast='R02', inert='R03', overlay='R04', **{'below-fold': 'R06'}, unnamed='R10')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for variant in VARIANTS:
                with serve(ROOT / 'builds' / APP / variant / 'dist') as origin:
                    page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                    external = []
                    page.on('request', lambda request: external.append(request.url) if urlsplit(request.url).hostname not in {'127.0.0.1', None} else None)
                    await page.goto(origin)
                    await page.locator(TARGET).first.wait_for()
                    await page.wait_for_timeout(500)
                    await record_first_view(page)
                    search = page.get_by_role('searchbox', name='Search products')
                    await search.scroll_into_view_if_needed()
                    items = await observe(page)
                    first = await snapshot(page, next(i['el_id'] for i in items if i['name'] == 'Search products'))
                    assert bool(r06.evaluate(first, is_first_target=True)) == (variant == 'below-fold')
                    assert r06.evaluate(first, action='type') is None
                    if variant == 'below-fold':
                        await page.locator('input[type=search]').click()
                    await search.fill('Broccoli')
                    assert await page.locator('.product').count() == 1
                    target = page.locator(TARGET).first
                    await target.scroll_into_view_if_needed()
                    await page.wait_for_timeout(400)
                    if variant == 'small':
                        box = await target.bounding_box()
                        assert box['width'] == box['height'] == 16
                        help_box = await page.get_by_role('button', name='Product help').bounding_box()
                        assert abs(help_box['x'] - box['x']) < 24
                    if variant == 'overlay':
                        items = await observe(page)
                        snap = await snapshot(page, next(i['el_id'] for i in items if i['name'] == 'ADD TO CART'))
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
                    await page.screenshot(path=str(OUTPUT / f'{variant}.png'), full_page=True)
                    if variant == 'overlay':
                        try:
                            await target.click(timeout=500)
                        except Exception:
                            pass
                        else:
                            raise AssertionError('Overlay did not block click')
                    else:
                        await target.click()
                        if variant == 'inert':
                            await page.wait_for_timeout(3000)
                            assert await page.locator('.cart-count').count() == 0
                        else:
                            await target.click()  # same product twice => quantity 2
                            if variant == 'small':
                                assert (await target.bounding_box())['width'] == 16
                            await page.locator('a.cart-icon').click()
                            assert await page.locator('.cart-items .quantity').inner_text() == '2 Nos.'
                            if variant == 'baseline':
                                await page.wait_for_timeout(400)
                                opened = await page.evaluate('async () => await axe.run()')
                                assert not opened['violations']
                            await page.get_by_role('button', name='Remove Broccoli - 1 Kg').click()
                            assert await page.locator('.cart-items .cart-item').count() == 0
                    assert not external, external
                    labels['cases'][variant] = [] if variant == 'baseline' else [{'rule': rules[variant], 'target': 'input[type="search"]' if variant == 'below-fold' else TARGET}]
                    results.append({'case': variant, 'verified': True, 'external_requests': external,
                                    'axe_violations': sorted(ids), 'first_snapshot': first.model_dump()})
                    (OUTPUT / f'{variant}-axe.json').write_text(json.dumps(axe, indent=2), encoding='utf-8')
                    await page.close()
            labels['cases']['baseline-remove'] = []
        finally:
            await browser.close()
    (OUTPUT / 'verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    (OUTPUT / 'labels-candidate.json').write_text(json.dumps(labels, indent=2) + '\n', encoding='utf-8')
    print('Commerce: search/add quantity 2 and remove tasks plus 6 source mutations verified offline; review pending')


if __name__ == '__main__':
    asyncio.run(verify())
