"""진짜 Claude에 행동 프롬프트를 두 번 보내 어댑터가 실제로 동작하는지 확인한다 (LLM·프롬프트).

    python -m worker.llm.live_check

확인하는 것
1. 답이 오고 worker/schemas.py의 행동 형식 검사를 통과하는가
2. 첫 호출에 캐시 쓰기, 두 번째 호출에 캐시 읽기 토큰이 생기는가 (시스템 프롬프트 캐싱)
3. 토큰·비용·시간이 data/llm_calls.jsonl에 기록되는가

API 키는 저장소 루트의 .env(ANTHROPIC_API_KEY)에서 읽는다. 호출 두 번, Haiku 5.5 기준 1센트 미만.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from worker.llm import JsonlCallLog, LLMRequest, ask_and_log
from worker.llm.claude import ClaudeAdapter
from worker.llm.prompts import load_prompt
from worker.schemas import ActionInputError, parse_action_json

ROOT = Path(__file__).resolve().parents[2]
MODEL = 'claude-haiku-5-5'

# 계획서 4.2 "요소 정보" 한 줄 형식(번호|역할|이름|영역|위치)으로 쓴 예시 화면. 스크린샷 없이 글만 보낸다.
USER_TEXT = """과업: 회원가입하기

요소 목록:
1|link|StepShop|banner|좌상단
2|link|상품|navigation|상단
3|button|로그인|banner|우상단
4|button|회원가입|banner|우상단
5|textbox|검색 (placeholder: 상품 검색)|banner|상단 중앙

최근 행동: 없음"""


def load_env_file(path: Path) -> None:
    """.env의 KEY=VALUE 줄을 환경 변수로 읽는다. 이미 있는 값은 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class UsageSpy:
    """진짜 client를 감싸 마지막 응답의 usage(캐시 쓰기·읽기 토큰 포함)를 보관한다."""

    def __init__(self, client):
        self._client = client
        self.messages = self
        self.last_usage = None

    async def create(self, **params):
        response = await self._client.messages.create(**params)
        self.last_usage = response.usage
        return response


async def main() -> None:
    load_env_file(ROOT / '.env')
    if not os.environ.get('ANTHROPIC_API_KEY'):
        raise SystemExit('.env에 ANTHROPIC_API_KEY가 없다. .env.example을 복사해 키를 넣는다.')

    from anthropic import AsyncAnthropic

    spy = UsageSpy(AsyncAnthropic())
    adapter = ClaudeAdapter(model=MODEL, client=spy)
    log = JsonlCallLog(ROOT / 'data/llm_calls.jsonl')
    request = LLMRequest(purpose='action', prompt_version='action_v1',
                         system=load_prompt('action_v1'), user_text=USER_TEXT)

    for n in (1, 2):
        result = await ask_and_log(adapter, request, log)
        print(f'--- 호출 {n}')
        print('답:', result.text or '(빈 답)')
        try:
            action = parse_action_json(result.text)
            print('형식 검사: 통과 →', type(action).__name__)
        except ActionInputError as error:
            print('형식 검사: 실패 →', error.code)
        usage = spy.last_usage
        write = getattr(usage, 'cache_creation_input_tokens', 0) or 0
        read = getattr(usage, 'cache_read_input_tokens', 0) or 0
        print(f'입력 {result.input_tokens}토큰 (캐시 쓰기 {write}, 캐시 읽기 {read}), '
              f'출력 {result.output_tokens}토큰, 비용 ${result.cost_usd:.6f}, {result.latency_ms}ms')

    print('\n기록 파일:', log.path)


if __name__ == '__main__':
    asyncio.run(main())
