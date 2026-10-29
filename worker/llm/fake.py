"""가짜 어댑터. 진짜 AI를 부르지 않고 미리 적어 둔 답을 돌려준다.

API 키나 크레딧 없이 에이전트 루프와 호출 기록을 시험할 때 쓴다.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from worker.llm.base import LLMRequest, LLMResult

# 아무 답도 지정하지 않았을 때 돌려주는 기본 답. worker/schemas.py의 wait 행동 형식.
DEFAULT_REPLY = '{"action":"wait","thought":"가짜 응답이다","expectation":"화면이 그대로다"}'


class FakeAdapter:
    name = "fake"

    def __init__(self, replies: Sequence[str] | None = None):
        # replies에 넣은 답을 순서대로 하나씩 돌려주고, 끝나면 처음부터 다시 돈다.
        self._replies = list(replies) if replies else [DEFAULT_REPLY]
        self._next = 0
        self.received: list[LLMRequest] = []  # 테스트에서 무엇을 받았는지 확인용

    async def ask(self, request: LLMRequest) -> LLMResult:
        started = time.perf_counter()
        self.received.append(request)
        text = self._replies[self._next % len(self._replies)]
        self._next += 1
        return LLMResult(
            text=text,
            model="fake",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
