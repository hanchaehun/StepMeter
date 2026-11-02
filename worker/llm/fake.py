"""가짜 어댑터. 진짜 AI를 부르지 않고 미리 적어 둔 답을 돌려준다.

API 키나 크레딧 없이 에이전트 루프와 호출 기록을 시험할 때 쓴다.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from worker.llm.base import LLMRequest, LLMResult

# 아무 답도 지정하지 않았을 때 돌려주는 기본 답. worker/schemas.py의 wait 행동 형식.
DEFAULT_REPLY = '{"action":"wait","thought":"가짜 응답이다","expectation":"화면이 그대로다"}'

# 행동 선택이 아닌 호출(설명 생성 등)에 돌려주는 고정 문장.
# Issue.explanation이 필수 문자열이라 가짜 모드에서도 빈 글자를 주지 않는다 (tests/e2e/README.md).
DEFAULT_TEXT = "가짜 모드에서 만든 설명이다."


class FakeAdapter:
    name = "fake"

    def __init__(self, replies: Sequence[str] | None = None, text: str = DEFAULT_TEXT):
        # 행동 선택(purpose="action")에는 replies를 순서대로 하나씩 돌려주고, 끝나면 처음부터 다시 돈다.
        # 그 밖의 호출에는 text를 돌려주고 행동 순서는 건드리지 않는다.
        self._replies = list(replies) if replies else [DEFAULT_REPLY]
        self._next = 0
        self._text = text
        self.received: list[LLMRequest] = []  # 테스트에서 무엇을 받았는지 확인용

    async def ask(self, request: LLMRequest) -> LLMResult:
        started = time.perf_counter()
        self.received.append(request)
        if request.purpose == "action":
            text = self._replies[self._next % len(self._replies)]
            self._next += 1
        else:
            text = self._text
        return LLMResult(
            text=text,
            model="fake",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
