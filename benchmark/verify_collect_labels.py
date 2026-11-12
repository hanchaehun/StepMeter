"""Local-only numbered checkbox smoke on pinned SB Admin baseline/small builds.

Not a complete benchmark run or human-study six-page acceptance. No real LLM,
credentials, form submission, labels or holdout access are involved.
"""
import argparse
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from worker.collect.collector import observe, record_first_view
from worker.driver.playwright_driver import PlaywrightDriver
from worker.rules.engine import evaluate_step
from worker.schemas import ClickAction

ROOT = Path(__file__).resolve().parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


async def verify(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for variant in ('baseline', 'small'):
                source = ROOT / 'builds' / 'sb-admin-2' / variant
                if not (source / 'stepmeter-build.json').is_file():
                    raise ValueError(f'Prepare sb-admin-2 {variant} with benchmark.build_variant first')
                server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(source)))
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                context = await browser.new_context(viewport={'width': 1280, 'height': 800})
                driver = None
                try:
                    async def local_only(route):
                        if urlsplit(route.request.url).hostname == '127.0.0.1':
                            await route.continue_()
                        else:
                            await route.abort()
                    await context.route('**/*', local_only)
                    page = await context.new_page()
                    await page.goto(f'http://127.0.0.1:{server.server_port}/login.html', wait_until='networkidle')
                    await record_first_view(page)
                    rows = await observe(page)
                    target = next(r for r in rows if r['role'] == 'checkbox' and r['name'] == 'Remember Me')
                    driver = PlaywrightDriver(page, window_ms=1000)
                    result = await driver.perform(ClickAction(action='click', target=target['el_id'],
                        thought='Select Remember Me', expectation='Checkbox becomes checked'))
                    assert await page.locator('#customCheck').is_checked(), 'Checkbox did not toggle'
                    assert not result.element.occluded, 'Visible checkbox incorrectly occluded'
                    assert result.effect.effect_type == 'dom_mutation', 'Native checked response not detected'
                    (output / f'{variant}-before.jpg').write_bytes(result.screenshot)
                    await page.screenshot(path=str(output / f'{variant}-after.png'))
                    # A temporary local overlay must prevent the next action and
                    # feed R04 rather than R03. This is a synthetic regression.
                    await page.evaluate("""() => {const e=document.createElement('div');
                        e.style='position:fixed;inset:0;z-index:2147483647;background:#ffffff80';
                        e.id='w3-test-overlay';document.body.append(e)}""")
                    await observe(page)
                    blocked = await driver.perform(ClickAction(action='click', target=target['el_id'],
                        thought='Try covered checkbox', expectation='Covered action is recorded'))
                    assert await page.locator('#customCheck').is_checked(), 'Covered action toggled checkbox'
                    rules = [c.rule_id for c in evaluate_step(blocked.element, step_id=1,
                        action='click', effect_type=blocked.effect.effect_type, is_first_target=False)]
                    assert 'R04' in rules and 'R03' not in rules, 'Occlusion rule composition failed'
                    reports.append({'variant': variant, 'ok': True, 'target': target,
                        'snapshot': result.element.model_dump(), 'effect': result.effect.as_step_effect(),
                        'covered_rules': rules,
                        'build': json.loads((source / 'stepmeter-build.json').read_text(encoding='utf-8'))})
                finally:
                    if driver:
                        await driver.aclose()
                    await context.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
        finally:
            await browser.close()
    (output / 'report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Passed {len(reports)} development variants; evidence: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence' / 'w3-collect-labels')
    asyncio.run(verify(parser.parse_args().output))


if __name__ == '__main__':
    main()
