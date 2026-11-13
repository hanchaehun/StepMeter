"""LLM 스크린샷 베이스라인 (개발계획서 8.3, 담당: LLM·프롬프트).

axe 베이스라인(baseline_axe.py)과 같은 과업 경로를 따라가며 화면 세 장(below-fold는 두 장)을 찍고, 상용 LLM에
"이 화면들에서 UX 문제를 찾아라"라고만 요청한다. 답을 benchmark/eval.py 예측 형식으로 저장한다.

    python -m benchmark.baseline_llm              # .env의 ANTHROPIC_API_KEY 사용, Haiku 5.5
    python -m benchmark.baseline_llm --repeat 1   # 반복 횟수 (기본 3)

정한 것
- 화면: 가입 화면, 가입 누른 뒤, 구독 확인 뒤 (axe 베이스라인과 같은 세 화면). 한 케이스의 세 장을 한 번에 보낸다.
  R03(반응 없음)은 앞뒤 화면을 비교해야 알 수 있어서다.
- below-fold만 가입 시작 화면(entry.html)에서 시작한다(ADR 0009, ADR 0010 7번). 과업은 "가입 시작 링크를 찾아
  가입 폼을 연다"이고 화면은 두 장이다: 처음 연 모습, 아래로 스크롤해 링크가 보이는 모습.
  번호표는 뷰포트 안에만 붙으므로 스크롤한 화면이 없으면 링크를 번호로 답할 수 없다(verify_conversion.py도 같은 두 화면을 찍는다).
- 채점은 정답과 같은 이름표(CSS 선택자)로 해야 하므로, 뷰포트 안 상호작용 요소에 번호표를 그려 보여 주고
  LLM은 번호로 답한다(에이전트 관찰 4.2와 같은 방식). 번호 → 선택자는 axe.utils.getSelector로 만든다.
  번호표가 없는 요소(뷰포트 밖, iframe·shadow DOM 안)는 답할 수 없다.
- 찾을 문제는 정답에 쓰는 여섯 규칙(R01·R02·R03·R04·R06·R10)으로 알려 준다. 규칙 번호로 답해야 같은 정답으로 채점할 수 있다.
- LLM 답은 매번 다를 수 있어 케이스마다 --repeat번 묻고, 절반 넘게 나온 (규칙, 요소)만 예측에 넣는다.
- 답 길이 상한은 MAX_TOKENS(4096). 행동 선택용 기본값(1024)으로는 스크린샷 세 장 설명이 잘린다.
  JSON 배열로 읽히지 않은 답(잘림, 빈 답)은 개수를 출력하고 raw 파일에 남긴다.
- 원본 답과 스크린샷은 benchmark/evidence/baseline-llm/에 남긴다 (git 제외).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections import Counter
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from worker.llm import JsonlCallLog, LLMRequest, ask_and_log, make_adapter
from worker.llm.prompts import load_prompt

ROOT = Path(__file__).resolve().parents[1]
APP = 'conversion'
OUTPUT = ROOT / 'benchmark/evidence/baseline-llm'
AXE = ROOT / 'node_modules/axe-core/axe.min.js'
PROMPT_VERSION = 'baseline_v2'
MODEL = 'claude-haiku-5-5'
MAX_TOKENS = 4096
RULES = frozenset({'R01', 'R02', 'R03', 'R04', 'R06', 'R10'})
TASK = '이메일과 비밀번호로 무료 가입한 뒤 Pro 요금제를 골라 구독을 확인한다.'
SCREENS = ('가입 화면 (쿠키 안내를 닫은 직후)',
           "이메일·비밀번호를 입력하고 '무료로 가입하기'를 누른 뒤",
           'Pro 요금제를 고르고 구독을 확인한 뒤')
# 가입 시작 화면(entry.html)에서 시작하는 케이스. verify_conversion.ENTRY_PAGES와 같아야 한다(capture에서 확인).
ENTRY_CASES = frozenset({'below-fold'})
ENTRY_TASK = "가입 시작 화면에서 '가입 시작하기' 링크를 찾아 눌러 가입 폼을 연다."
ENTRY_SCREENS = ('가입 시작 화면을 처음 연 모습 (스크롤 전)',
                 "아래로 스크롤해 '가입 시작하기' 링크가 보이는 모습")

# 뷰포트 안 상호작용 요소에 번호표를 그리고 번호 → 선택자 표를 돌려준다 (개발계획서 4.2 대상과 같은 요소).
MARK_JS = """() => {
  axe.setup(document);
  const sel = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[role=checkbox],'
    + '[role=menuitem],[onclick],[tabindex]:not([tabindex="-1"])';
  const layer = document.createElement('div');
  layer.id = '__stepmeter_marks';
  layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647';
  const marks = [];
  for (const el of document.querySelectorAll(sel)) {
    const b = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (!b.width || !b.height || cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
    const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
    if (cx < 0 || cy < 0 || cx >= innerWidth || cy >= innerHeight) continue;
    const n = marks.length + 1;
    marks.push({number: n, selector: axe.utils.getSelector(el)});
    // 작은 요소를 가리지 않게 테두리는 얇게, 번호는 요소 바로 위 바깥에 붙인다.
    const box = document.createElement('div');
    box.style.cssText = `position:fixed;left:${b.x}px;top:${b.y}px;width:${b.width}px;height:${b.height}px;`
      + 'outline:1px solid #d00';
    const tag = document.createElement('div');
    tag.textContent = String(n);
    const top = b.y >= 14 ? b.y - 14 : b.y + b.height;
    tag.style.cssText = `position:fixed;left:${b.x}px;top:${top}px;background:#d00;color:#fff;`
      + 'font:bold 11px/13px sans-serif;padding:0 3px';
    layer.append(box, tag);
  }
  axe.teardown();
  document.body.appendChild(layer);
  return marks;
}"""
UNMARK_JS = "() => document.getElementById('__stepmeter_marks')?.remove()"


def read_array(text: str) -> list | None:
    """LLM 답에서 JSON 배열을 꺼낸다. 배열로 읽히지 않으면(잘림, 빈 답) None."""
    match = re.search(r'\[.*\]', text, re.S)
    if not match:
        return None
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return items if isinstance(items, list) else None


def parse_answer(text: str) -> list[dict]:
    """LLM 답에서 찾은 문제 목록을 꺼낸다. 형식이 틀린 항목은 버린다."""
    items = read_array(text) or []
    found = []
    for item in items:
        if (isinstance(item, dict) and item.get('rule') in RULES
                and isinstance(item.get('screen'), int) and isinstance(item.get('number'), int)):
            found.append(item)
    return found


def to_keys(items: list[dict], marks_by_screen: list[list[dict]]) -> set[tuple[str, str]]:
    """(화면, 번호)를 선택자로 바꿔 (규칙, 선택자) 묶음으로 만든다. 없는 번호는 버린다."""
    keys = set()
    for item in items:
        screen = item['screen'] - 1
        if not 0 <= screen < len(marks_by_screen):
            continue
        selector = {m['number']: m['selector'] for m in marks_by_screen[screen]}.get(item['number'])
        if selector:
            keys.add((item['rule'], selector))
    return keys


def majority(runs: list[set[tuple[str, str]]]) -> list[dict]:
    """반복 실행 중 절반 넘게 나온 (규칙, 선택자)만 남긴다."""
    counts = Counter(key for run in runs for key in run)
    return [{'rule': r, 'target': t} for (r, t), n in sorted(counts.items()) if n * 2 > len(runs)]


async def capture(origin: str) -> dict[str, dict]:
    """케이스마다 세 화면의 번호표 스크린샷(JPEG 품질 70, 4.2)과 번호표 표를 모은다."""
    from playwright.async_api import async_playwright

    from benchmark.mutate import apply, load_config
    from benchmark.verify_conversion import ENTRY_PAGES

    if set(ENTRY_PAGES) != ENTRY_CASES:
        raise RuntimeError(f'ENTRY_CASES {sorted(ENTRY_CASES)}가 verify_conversion.ENTRY_PAGES와 다르다')

    async def shoot(page):
        await page.add_script_tag(path=str(AXE))
        marks = await page.evaluate(MARK_JS)
        image = await page.screenshot(type='jpeg', quality=70)
        await page.evaluate(UNMARK_JS)
        return image, marks

    paths = [None, *sorted((ROOT / f'benchmark/mutations/{APP}').glob('*.yaml'))]
    cases = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for path in paths:
                config = load_config(path) if path else None
                case = config['id'] if config else 'baseline'
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                if case in ENTRY_CASES:  # 가입 시작 화면에서 시작 (ADR 0009)
                    await page.goto(f'{origin}/{ENTRY_PAGES[case]}')
                    await apply(page, config)
                    shots = [await shoot(page)]  # 1. 처음 연 모습
                    await page.locator('#signup').scroll_into_view_if_needed()
                    shots.append(await shoot(page))  # 2. 스크롤해 링크가 보이는 모습
                    cases[case] = {'images': [s[0] for s in shots], 'marks': [s[1] for s in shots]}
                    await page.close()
                    continue
                await page.goto(origin + '/index.html')
                await page.frame_locator('iframe').locator('#confirm').wait_for()
                await page.get_by_role('button', name='필수만 사용').click()
                if config:
                    await apply(page, config)
                shots = [await shoot(page)]  # 1. 가입 화면
                await page.locator('#email').fill('demo@example.test')
                await page.locator('#password').fill('demo-password')
                try:  # 가려진 버튼(overlay)은 사람처럼 못 누를 수 있다
                    await page.locator('#signup').click(timeout=2000)
                except Exception:
                    pass
                shots.append(await shoot(page))  # 2. 가입 누른 뒤
                await page.get_by_role('button', name='Pro 월 9,900원 선택').click()
                await page.frame_locator('iframe').get_by_role('button').click()
                shots.append(await shoot(page))  # 3. 구독 확인 뒤
                cases[case] = {'images': [s[0] for s in shots], 'marks': [s[1] for s in shots]}
                await page.close()
        finally:
            await browser.close()
    return cases


def user_text(case: str) -> str:
    task, screens = (ENTRY_TASK, ENTRY_SCREENS) if case in ENTRY_CASES else (TASK, SCREENS)
    lines = [f'과업: {task}', '', '화면 설명:']
    lines += [f'{i}. {desc}' for i, desc in enumerate(screens, start=1)]
    return '\n'.join(lines)


async def ask_all(cases: dict[str, dict], repeat: int) -> tuple[dict, dict]:
    adapter = make_adapter(MODEL)
    if hasattr(adapter, 'max_tokens'):
        adapter.max_tokens = MAX_TOKENS
    log = JsonlCallLog(ROOT / 'data/llm_calls.jsonl')
    system = load_prompt(PROMPT_VERSION)
    predictions, raw = {}, {}
    for case, shot in cases.items():
        request = LLMRequest(purpose='baseline', prompt_version=PROMPT_VERSION, system=system,
                             user_text=user_text(case), image_jpeg=shot['images'][0],
                             extra_images_jpeg=tuple(shot['images'][1:]))
        runs, answers = [], []
        for _ in range(repeat):
            result = await ask_and_log(adapter, request, log)
            answers.append({'text': result.text, 'cost_usd': result.cost_usd,
                            'output_tokens': result.output_tokens, 'readable': read_array(result.text) is not None})
            runs.append(to_keys(parse_answer(result.text), shot['marks']))
        predictions[case] = majority(runs)
        raw[case] = {'marks': shot['marks'], 'answers': answers}
    return {'split': 'development', 'cases': predictions}, raw


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    load_env_file(ROOT / '.env')

    from benchmark.verify_conversion import QuietHandler

    handler = partial(QuietHandler, directory=str(ROOT / f'benchmark/fixtures/{APP}'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        cases = asyncio.run(capture(f'http://127.0.0.1:{server.server_port}'))
    finally:
        server.shutdown()
        server.server_close()
    predictions, raw = asyncio.run(ask_all(cases, args.repeat))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case, shot in cases.items():
        for i, image in enumerate(shot['images'], start=1):
            (OUTPUT / f'{APP}-{case}-{i}.jpg').write_bytes(image)
    (OUTPUT / f'{APP}-predictions.json').write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUTPUT / f'{APP}-raw.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    answers = [a for r in raw.values() for a in r['answers']]
    total = sum(a['cost_usd'] or 0 for a in answers)
    unreadable = sum(not a['readable'] for a in answers)
    for case, rows in predictions['cases'].items():
        print(f'{case:12} {rows}')
    print(f'답 형식 오류: {unreadable}/{len(answers)}  (0이 아니면 {OUTPUT.name}/{APP}-raw.json 확인)')
    print(f'cost: ${total:.4f}  saved: {OUTPUT}')


if __name__ == '__main__':
    main()
