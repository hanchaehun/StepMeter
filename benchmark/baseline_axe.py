"""axe-core 단독 베이스라인 (개발계획서 8.3, 담당: LLM·프롬프트).

같은 과업 경로를 따라가며 화면마다 axe-core만 돌리고, 찾은 위반을 우리 규칙 번호로 바꿔
benchmark/eval.py의 예측 형식으로 저장한다. 채점은 PM이 정답을 승인한 뒤 eval.py로 한다.

    python -m benchmark.baseline_axe
    python -m benchmark.eval --labels benchmark/labels/conversion.json \\
        --predictions benchmark/evidence/baseline-axe/conversion-predictions.json \\
        --output benchmark/evidence/baseline-axe/conversion-score.json

정한 것
- axe 기본 규칙에 target-size를 켠다(기본값은 꺼짐). axe가 낼 수 있는 가장 좋은 결과와 비교하려는 것이다.
  StepMeter R01은 axe target-size 결과가 없으면 자체 크기·간격 계산을 쓴다(worker/rules/README.md).
- 이름 누락(R10)으로 볼 axe 규칙은 StepMeter R10과 같은 목록(worker/rules/r10.py NAME_RULES)을 쓴다.
- axe는 과업 경로를 모르므로 경로 밖 요소도 그대로 예측에 넣는다. StepMeter는 경로 밖을 '참고'로 따로 둔다.
- 규칙 번호로 바꿀 수 없는 axe 위반은 예측에 넣지 않고 보고서의 unmapped에만 남긴다.
- 과업 경로: 쿠키 안내 닫기 → (결함 적용) → 가입 화면 → 가입 누른 뒤 → 구독 확인 뒤. 세 화면의 결과를 합친다.
  쿠키 안내가 떠 있는 첫 화면은 결함을 적용하기 전이라 넣지 않는다 (verify_conversion.py와 같은 순서).
"""
from __future__ import annotations

import asyncio
import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from worker.rules.r10 import NAME_RULES

ROOT = Path(__file__).resolve().parents[1]
APP = 'conversion'
OUTPUT = ROOT / 'benchmark/evidence/baseline-axe'
AXE = ROOT / 'node_modules/axe-core/axe.min.js'
AXE_OPTIONS = {'rules': {'target-size': {'enabled': True}}}

# axe 규칙 → StepMeter 규칙 번호 (개발계획서 5.4, 5.5, worker/rules/README.md)
AXE_TO_RULE = {
    'target-size': 'R01',
    'color-contrast': 'R02',
    **{rule: 'R10' for rule in NAME_RULES},
}


def normalize_target(axe_target: list) -> str:
    """axe의 target(iframe·shadow DOM은 중첩 목록)을 'iframe >> #confirm' 같은 글자 하나로 바꾼다."""
    parts = []
    for part in axe_target:
        parts.append(' >> '.join(part) if isinstance(part, list) else part)
    return ' >> '.join(parts)


def to_predictions(violations_by_case: dict[str, list[dict]]) -> tuple[dict, dict]:
    """케이스별 axe 위반 목록을 eval.py 예측 형식과 매핑 못 한 위반 목록으로 나눈다."""
    cases, unmapped = {}, {}
    for case, violations in violations_by_case.items():
        found, skipped = set(), set()
        for violation in violations:
            rule = AXE_TO_RULE.get(violation['id'])
            for node in violation['nodes']:
                target = normalize_target(node['target'])
                if rule:
                    found.add((rule, target))
                else:
                    skipped.add((violation['id'], target))
        cases[case] = [{'rule': r, 'target': t} for r, t in sorted(found)]
        unmapped[case] = [{'axe': a, 'target': t} for a, t in sorted(skipped)]
    return {'split': 'development', 'cases': cases}, unmapped


async def run_axe(page) -> list[dict]:
    await page.add_script_tag(path=str(AXE))
    result = await page.evaluate('async options => await axe.run(document, options)', AXE_OPTIONS)
    return result['violations']


async def collect(origin: str) -> dict[str, list[dict]]:
    from playwright.async_api import async_playwright

    from benchmark.mutate import apply, load_config

    paths = [None, *sorted((ROOT / f'benchmark/mutations/{APP}').glob('*.yaml'))]
    violations_by_case: dict[str, list[dict]] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for path in paths:
                config = load_config(path) if path else None
                case = config['id'] if config else 'baseline'
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                if config and config.get('page') == 'entry.html':
                    await page.goto(origin + '/' + config['page'])
                    await apply(page, config)
                    found = await run_axe(page)
                    await page.locator('#signup').scroll_into_view_if_needed()
                    found += await run_axe(page)
                    await page.locator('#signup').click()
                    assert page.url.endswith(config['success_path'])
                    violations_by_case[case] = found
                    await page.close()
                    continue
                await page.goto(origin + '/index.html')
                await page.frame_locator('iframe').locator('#confirm').wait_for()
                await page.get_by_role('button', name='필수만 사용').click()
                if config:
                    await apply(page, config)

                found = await run_axe(page)  # 1. 가입 화면
                await page.locator('#email').fill('demo@example.test')
                await page.locator('#password').fill('demo-password')
                try:  # 가려진 버튼(overlay)은 사람처럼 못 누를 수 있다
                    await page.locator('#signup').click(timeout=2000)
                except Exception:
                    pass
                found += await run_axe(page)  # 2. 가입 누른 뒤
                await page.get_by_role('button', name='Pro 월 9,900원 선택').click()
                await page.frame_locator('iframe').get_by_role('button').click()
                found += await run_axe(page)  # 3. 구독 확인 뒤

                violations_by_case[case] = found
                await page.close()
        finally:
            await browser.close()
    return violations_by_case


def main() -> None:
    # 연습용 페이지 서버는 실행할 때만 불러온다. 테스트(Docker 이미지)는 to_predictions만 쓰므로
    # 이 파일과 worker/만 있으면 된다.
    from benchmark.verify_conversion import QuietHandler

    handler = partial(QuietHandler, directory=str(ROOT / f'benchmark/fixtures/{APP}'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        violations = asyncio.run(collect(f'http://127.0.0.1:{server.server_port}'))
    finally:
        server.shutdown()
        server.server_close()
    predictions, unmapped = to_predictions(violations)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f'{APP}-predictions.json').write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUTPUT / f'{APP}-unmapped.json').write_text(
        json.dumps(unmapped, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for case, rows in predictions['cases'].items():
        print(f'{case:12} {rows}  unmapped={len(unmapped[case])}')
    print(f'saved: {OUTPUT}')


if __name__ == '__main__':
    main()
