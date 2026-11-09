"""Render local conversion cases; verify mutations and preserve evidence, not detector scores."""
from __future__ import annotations

import asyncio
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.async_api import async_playwright

from benchmark.mutate import apply, load_config
from worker.collect.collector import observe, record_first_view, snapshot

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'benchmark/evidence/conversion'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass



async def verify_entry(page, origin: str, config: dict) -> dict:
    """R06 uses the first target of an entry page, before cookie/form interactions."""
    from worker.rules import r06

    await page.goto(origin + '/' + config['page'])
    # Negative control: the exact same first target is visible without the mutation.
    await record_first_view(page)
    items = await observe(page)
    assert len(items) == 1 and items[0]['name'] == '가입 시작하기'
    normal = await snapshot(page, items[0]['el_id'])
    assert normal.in_first_view
    assert r06.evaluate(normal, is_first_target=True) is None
    await apply(page, config)
    await record_first_view(page)
    assert await observe(page) == []  # no target-bearing action occurred yet
    await page.screenshot(path=str(OUTPUT / 'below-fold-initial.png'), full_page=True)
    await page.locator('#signup').scroll_into_view_if_needed()
    items = await observe(page)
    assert len(items) == 1
    snap = await snapshot(page, items[0]['el_id'])
    assert not snap.in_first_view and snap.first_view_scroll_px > 0
    assert r06.evaluate(snap, is_first_target=True).rule_id == 'R06'
    assert r06.evaluate(snap, is_first_target=False) is None
    await page.add_script_tag(path=str(ROOT / 'node_modules/axe-core/axe.min.js'))
    axe = await page.evaluate('async () => await axe.run()')
    assert not axe['violations']
    (OUTPUT / 'below-fold-axe.json').write_text(json.dumps(axe, ensure_ascii=False, indent=2), encoding='utf-8')
    await page.screenshot(path=str(OUTPUT / 'below-fold.png'), full_page=True)
    await page.locator('#signup').click()  # first click/type/select target of this task
    assert page.url.endswith(config['success_path'])
    return {'case': 'below-fold', 'verified': True, 'rule': 'R06',
            'task': config['task'], 'first_target': '#signup',
            'snapshots': [snap.model_dump()], 'page_errors': []}

async def verify(origin: str) -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'verification.json').unlink(missing_ok=True)
    report = {'kind': 'fixture verification, not StepMeter accuracy', 'cases': []}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for path in [None, *sorted((ROOT / 'benchmark/mutations/conversion').glob('*.yaml'))]:
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                config = load_config(path) if path else None
                if config and config.get('page') == 'entry.html':
                    case = await verify_entry(page, origin, config)
                    assert not errors, errors
                    report['cases'].append(case)
                    await page.close()
                    continue
                await page.goto(origin + '/index.html')
                await page.frame_locator('iframe').locator('#confirm').wait_for()
                await record_first_view(page)
                # Modal remains until the user explicitly dismisses it.
                items = await observe(page)
                signup = next(i for i in items if i['name'] == '무료로 가입하기')
                assert (await snapshot(page, signup['el_id'])).occluded
                await page.get_by_role('button', name='필수만 사용').click()
                config = load_config(path) if path else None
                name = config['id'] if config else 'baseline'
                await record_first_view(page)
                items = await observe(page)
                snaps = [await snapshot(page, i['el_id']) for i in items]
                if path is None:
                    expected = {'이메일', '비밀번호', '무료로 가입하기', 'Pro 월 9,900원 선택', '구독 내용 확인하기'}
                    assert {s.name for s in snaps} == expected
                shadow = next(s for s in snaps if s.name == 'Pro 월 9,900원 선택')
                frame = next(s for s in snaps if s.name == '구독 내용 확인하기')
                assert shadow.context == 'open_shadow' and not shadow.occluded
                assert frame.context == 'same_origin_iframe' and not frame.occluded
                # Independently compare frame coordinate transformation to the DOM geometry.
                outer = await page.locator('iframe').bounding_box()
                inner = await page.frame_locator('iframe').locator('#confirm').evaluate(
                    'el => ({x:el.getBoundingClientRect().x,y:el.getBoundingClientRect().y})')
                assert abs(frame.bbox.x - outer['x'] - inner['x']) < 1
                assert abs(frame.bbox.y - outer['y'] - inner['y']) < 1
                if config:
                    await apply(page, config)
                    await record_first_view(page)
                    items = await observe(page)
                    snaps = [await snapshot(page, i['el_id']) for i in items]
                await page.screenshot(path=str(OUTPUT / f'{name}-initial.png'), full_page=True)
                await page.locator('#email').fill('demo@example.test')
                await page.locator('#password').fill('demo-password')
                target = page.locator('#signup')
                box = await target.bounding_box()
                if name == 'small':
                    assert box['width'] == 16 and box['height'] == 16
                    help_box = await page.get_by_role('button', name='가입 도움말').bounding_box()
                    # Adjacent 16px targets: center distance 16 < diameter 24 (SC 2.5.8).
                    assert abs(help_box['x'] - box['x']) < 24 and help_box['y'] == box['y']
                elif name == 'contrast':
                    colors = await target.evaluate('el => [getComputedStyle(el).color,getComputedStyle(el).backgroundColor]')
                    assert colors == ['rgb(238, 238, 238)', 'rgb(255, 255, 255)']
                elif name == 'overlay':
                    s = next(s for s in snaps if s.name == '무료로 가입하기')
                    assert s.occluded and s.occluder is not None
                elif name == 'unnamed':
                    assert await target.evaluate('el => el.textContent') == ''
                    assert any(s.name == '' and s.tag == 'button' for s in snaps)
                if name != 'overlay':
                    await target.click()
                    if name == 'inert':
                        assert await page.locator('#result').inner_text() == ''
                    else:
                        assert await page.locator('#result').inner_text() == '데모 가입 완료'
                # Restore scroll to exercise the subscription flow, including shadow and iframe.
                await page.get_by_role('button', name='Pro 월 9,900원 선택').click()
                await page.frame_locator('iframe').get_by_role('button').click()
                assert '데모 구독 확인 완료' in await page.frame_locator('iframe').locator('#confirmation').inner_text()
                assert not errors, errors
                await page.screenshot(path=str(OUTPUT / f'{name}.png'), full_page=True)
                await page.add_script_tag(path=str(ROOT / 'node_modules/axe-core/axe.min.js'))
                axe = await page.evaluate('async () => await axe.run()')
                rules = {v['id'] for v in axe['violations']}
                if name == 'baseline':
                    assert not rules, rules
                if name == 'contrast':
                    assert 'color-contrast' in rules
                if name == 'unnamed':
                    assert 'button-name' in rules
                (OUTPUT / f'{name}-axe.json').write_text(json.dumps(axe, ensure_ascii=False, indent=2), encoding='utf-8')
                case = {'case': name, 'verified': True, 'rule': config['rule'] if config else None,
                        'snapshots': [s.model_dump() for s in snaps], 'page_errors': errors}
                report['cases'].append(case)
                await page.close()
        finally:
            await browser.close()
    (OUTPUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    candidates = {'split': 'development', 'review_status': 'pending',
                  'evidence': 'benchmark/evidence/conversion/verification.json',
                  'cases': {c['case']: ([{'rule': c['rule'], 'target': '#signup'}] if c['rule'] else [])
                            for c in report['cases']}}
    (OUTPUT / 'labels-candidate.json').write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    handler = partial(QuietHandler, directory=str(ROOT / 'benchmark/fixtures/conversion'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = asyncio.run(verify(f'http://127.0.0.1:{server.server_port}'))
        print(f"Verified {len(result['cases'])} cases; evidence: {OUTPUT}")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
