"""Verify pinned SB Admin source variants and produce review-pending labels."""
from __future__ import annotations

import asyncio
import json
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.async_api import async_playwright

from benchmark.build_variant import ROOT, VARIANTS
from benchmark.verify_conversion import QuietHandler
from worker.collect.collector import observe, record_first_view, snapshot
from worker.rules import r06

OUTPUT = ROOT / 'evidence/sb-admin-2/w2'
TARGET = 'form.user a.btn-primary'


async def verify(origin: str):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    labels = {'split': 'development', 'review_status': 'pending', 'cases': {}}
    results = []
    rules = dict(small='R01', contrast='R02', inert='R03', overlay='R04', **{'below-fold': 'R06'}, unnamed='R10')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for variant in VARIANTS:
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                if variant == 'small':
                    from benchmark.verify_sb_admin_2 import small as measure_small
                    baseline = await measure_small(page, origin + '/baseline')
                    measured = await measure_small(page, origin + '/small')
                    assert not baseline['defect'] and measured['defect']
                    assert measured['accessible_name_remember_me']
                    await page.locator('#exampleInputEmail').fill('demo@example.test')
                    await page.locator('#exampleInputPassword').fill('demo-password')
                    hit = measured['hit_area_px']
                    await page.mouse.click(hit['x'] + hit['w'] / 2, hit['y'] + hit['h'] / 2)
                    assert await page.locator('#customCheck').is_checked()
                    await page.screenshot(path=str(OUTPUT / 'small.png'), full_page=True)
                    labels['cases']['small'] = [{'rule': 'R01', 'target': '#customCheck'}]
                    results.append({'case': 'small', 'verified': True,
                                    'baseline': baseline, 'measurement': measured})
                    await page.close()
                    continue
                await page.goto(f'{origin}/{variant}/register.html')
                await record_first_view(page)
                if variant == 'below-fold':
                    assert (await page.locator('#exampleFirstName').bounding_box())['y'] >= 800
                    await page.locator('#exampleFirstName').scroll_into_view_if_needed()
                    items = await observe(page)
                    snap = await snapshot(page, next(i['el_id'] for i in items if i['name'] == 'First name'))
                    # ADR 0009: 가입 과업의 첫 행동(First name 입력)이 첫 화면 밖이면 R06, 첫 행동이 아니면 없음
                    assert r06.evaluate(snap, action='type', is_first_target=True).rule_id == 'R06'
                    assert r06.evaluate(snap, action='type', is_first_target=False) is None
                    await page.locator('#exampleFirstName').click()
                else:
                    items = await observe(page)
                    normal = await snapshot(page, next(i['el_id'] for i in items if i['name'] == 'First name'))
                    assert r06.evaluate(normal, action='type', is_first_target=True) is None
                await page.locator('#exampleFirstName').fill('Demo')
                await page.locator('#exampleLastName').fill('User')
                await page.locator('#exampleInputEmail').fill('demo@example.test')
                await page.locator('#exampleInputPassword').fill('demo-password')
                await page.locator('#exampleRepeatPassword').fill('demo-password')
                target = page.locator(TARGET)
                await target.scroll_into_view_if_needed()
                items = await observe(page)
                snaps = [await snapshot(page, i['el_id']) for i in items]
                box = await target.bounding_box()
                if variant == 'overlay':
                    assert next(s for s in snaps if s.name == 'Register Account').occluded
                await page.add_script_tag(path=str(ROOT.parent / 'node_modules/axe-core/axe.min.js'))
                axe = await page.evaluate('async () => await axe.run()')
                ids = {v['id'] for v in axe['violations']}
                if variant == 'baseline':
                    assert not ids, ids
                if variant == 'contrast':
                    assert 'color-contrast' in ids
                if variant == 'unnamed':
                    assert 'link-name' in ids
                await page.screenshot(path=str(OUTPUT / f'{variant}.png'), full_page=True)
                if variant == 'overlay':
                    try:
                        await target.click(timeout=500)
                    except Exception:
                        pass
                    else:
                        raise AssertionError('Overlay did not block native click')
                else:
                    await target.click()
                    if variant == 'inert':
                        await page.wait_for_timeout(3000)
                        assert page.url.endswith('/register.html')
                    else:
                        assert '/login.html' in page.url
                labels['cases'][variant] = ([{'rule': rules[variant],
                    'target': '#exampleFirstName' if variant == 'below-fold' else TARGET}] if variant != 'baseline' else [])
                result = {'case': variant, 'verified': True, 'axe_violations': sorted(ids),
                          'snapshots': [s.model_dump() for s in snaps]}
                results.append(result)
                (OUTPUT / f'{variant}-axe.json').write_text(json.dumps(axe, indent=2), encoding='utf-8')
                await page.close()
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})
            await page.goto(origin + '/baseline/login.html')
            await page.locator('#exampleInputEmail').fill('demo@example.test')
            await page.locator('#exampleInputPassword').fill('demo-password')
            await page.locator('#customCheck').check(force=True)
            assert await page.locator('#customCheck').is_checked()
            await page.add_script_tag(path=str(ROOT.parent / 'node_modules/axe-core/axe.min.js'))
            axe = await page.evaluate('async () => await axe.run()')
            assert not axe['violations']
            labels['cases']['baseline-login'] = []
            await page.screenshot(path=str(OUTPUT / 'baseline-login.png'), full_page=True)
        finally:
            await browser.close()
    (OUTPUT / 'verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    (OUTPUT / 'labels-candidate.json').write_text(json.dumps(labels, indent=2) + '\n', encoding='utf-8')
    print('Verified SB Admin: 2 baseline tasks + 6 source mutations; PM review pending')


def main():
    root = ROOT / 'builds/sb-admin-2'
    if not all((root / v / 'register.html').exists() for v in VARIANTS):
        raise SystemExit('First run build_variant sb-admin-2 for all seven variants; see benchmark/w2.md')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        asyncio.run(verify(f'http://127.0.0.1:{server.server_port}'))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
