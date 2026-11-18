"""Read-only Michi collector smoke; clicks only the public Tokyo map region.

No model, credentials, search submission, drag or full-task success claim.
"""
import argparse
import asyncio
import json

from playwright.async_api import async_playwright

from worker.collect.collector import click_point, observe, snapshot
from worker.driver.playwright_driver import PlaywrightDriver
from worker.schemas import ClickAction

URL = 'https://michi-japan-travel-atlas.satinylake10.chatgpt.site/'


async def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})
            await page.goto(URL, wait_until='networkidle')
            await page.wait_for_timeout(1500)
            rows = await observe(page)
            names = ('東京都', '도쿄도', '도쿄', 'Tokyo', '도쿄 여행 안내')
            matches = [r for r in rows if r['name'] in names]
            report = {'url': URL, 'element_count': len(rows), 'tokyo': matches,
                      'scope': 'collector region click only; not agent task completion'}
            await page.screenshot(path=str(output/'before.png'))
            if len(matches) != 1:
                report['names'] = [r['name'] for r in rows]
                report['status'] = 'target_unresolved'
            else:
                row = matches[0]
                await page.evaluate('globalThis.__stepmeterSvgGeometry = false')
                report['center_snapshot'] = (await snapshot(page, row['el_id'])).model_dump()
                await page.evaluate('delete globalThis.__stepmeterSvgGeometry')
                report['snapshot'] = (await snapshot(page, row['el_id'])).model_dump()
                report['action_point'] = (await click_point(page, row['el_id'])
                                          if not report['snapshot']['occluded'] else None)
                driver = PlaywrightDriver(page, window_ms=1000)
                try:
                    result = await driver.perform(ClickAction(action='click', target=row['el_id'],
                        thought='Open Tokyo map', expectation='Tokyo guide panel opens'))
                    report['occluded'] = result.element.occluded
                    report['effect'] = result.effect.as_step_effect()
                    await page.wait_for_timeout(500)
                    report['after_names'] = [r['name'] for r in await observe(page)]
                    report['status'] = ('opened_tokyo' if not result.element.occluded
                                        and '지요다구 선택' in report['after_names']
                                        else 'expected_screen_missing')
                    await page.screenshot(path=str(output/'after.png'))
                finally:
                    await driver.aclose()
            (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['status'] == 'opened_tokyo' else 2
        finally:
            await browser.close()


if __name__ == '__main__':
    from pathlib import Path
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    raise SystemExit(asyncio.run(verify(p.parse_args().output)))
