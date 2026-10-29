"""Claude 어댑터 (개발계획서 3장 "교체 가능한 어댑터").

API 키는 환경 변수 ANTHROPIC_API_KEY에서 읽는다. 코드나 저장소에 키를 적지 않는다.

계획서와 다른 점: 4.6은 온도 0을 전제로 하지만, Claude 5.5 세대 모델은 temperature
설정을 받지 않는다 (보내면 400 오류). 그래서 온도를 보내지 않는다.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from worker.llm.action_tool import ACTION_TOOL, ACTION_TOOL_NAME
from worker.llm.base import LLMRequest, LLMResult
from worker.llm.pricing import cost_usd

DEFAULT_MODEL = "claude-haiku-5-5"  # 개발 중 기본 모델 (PM 결정, 16장 "소형 모델")
DEFAULT_MAX_TOKENS = 1024  # 행동 JSON 하나에 충분 (16장: 단계당 출력 약 150토큰)

# 쓸 수 있는 모델 (PM 결정 10/29). 개발·반복 실행은 Haiku, 결과를 내는 측정은 Sonnet.
ALLOWED_MODELS = frozenset({"claude-haiku-5-5", "claude-sonnet-5-5"})

# 도구 강제(tool_choice: tool)를 받는 모델. Haiku 5.5는 강제하면 생각 단계를 건너뛰어
# 출력 토큰이 적다. Sonnet 5.5는 강제를 받지 않으므로(보내면 400) auto로 보내고,
# 프롬프트의 "choose_action 도구를 한 번만 써서 답한다"와 도구의 strict: true로 형식을 지킨다.
FORCED_TOOL_MODELS = frozenset({"claude-haiku-5-5"})


class ClaudeAdapter:
    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, client: Any | None = None,
                 max_tokens: int = DEFAULT_MAX_TOKENS):
        if model not in ALLOWED_MODELS:
            raise ValueError(f"쓸 수 없는 모델이다: {model} (가능: {sorted(ALLOWED_MODELS)})")
        if client is None:
            # 실제로 쓸 때만 라이브러리를 불러온다. 테스트는 가짜 client를 넣는다.
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic()  # ANTHROPIC_API_KEY 환경 변수를 읽는다
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def build_params(self, request: LLMRequest) -> dict[str, Any]:
        """Claude API에 보낼 내용을 만든다 (1단계: 포장)."""

        content: list[dict[str, Any]] = []
        if request.image_jpeg is not None:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(request.image_jpeg).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": request.user_text})

        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # 시스템 프롬프트는 매 단계 똑같으므로 캐시해 비용을 줄인다 (16장).
            "system": [{"type": "text", "text": request.system,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": content}],
        }
        if request.purpose == "action":
            # 행동 선택은 choose_action 도구로 답하게 한다 (4.3 구조화 출력).
            params["tools"] = [ACTION_TOOL]
            if self.model in FORCED_TOOL_MODELS:
                params["tool_choice"] = {"type": "tool", "name": ACTION_TOOL_NAME}
            else:
                params["tool_choice"] = {"type": "auto"}
        return params

    async def ask(self, request: LLMRequest) -> LLMResult:
        params = self.build_params(request)
        started = time.perf_counter()
        response = await self.client.messages.create(**params)  # 2단계: 보내기
        latency_ms = int((time.perf_counter() - started) * 1000)

        text = extract_text(response, request.purpose)  # 3단계: 답 꺼내기

        usage = response.usage  # 4단계: 토큰과 비용
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        return LLMResult(
            text=text,
            model=self.model,
            # llm_call.input_tokens에는 캐시분까지 합친 전체 입력을 남긴다.
            input_tokens=usage.input_tokens + cache_write + cache_read,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd(
                self.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_write_tokens=cache_write,
                cache_read_tokens=cache_read,
            ),
            latency_ms=latency_ms,
        )


def extract_text(response: Any, purpose: str) -> str:
    """응답에서 필요한 부분만 꺼낸다.

    행동 선택이면 choose_action 도구 입력을 JSON 글자로 바꿔 돌려준다.
    값이 null인 항목은 뺀다 (형식 검사에서 '다른 행동의 필드'로 거절되지 않게).
    도구 답이 없으면 빈 글자를 돌려주고, 에이전트 쪽 형식 검사가 거절한다.
    """

    if purpose == "action":
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == ACTION_TOOL_NAME:
                cleaned = {k: v for k, v in dict(block.input).items() if v is not None}
                return json.dumps(cleaned, ensure_ascii=False)
        return ""
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
