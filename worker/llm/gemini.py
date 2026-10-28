"""Gemini 어댑터 자리 (개발계획서 3장). 키가 정해지면 ClaudeAdapter와 같은 모양으로 채운다."""

from __future__ import annotations

from worker.llm.base import LLMRequest, LLMResult


class GeminiAdapter:
    name = "gemini"

    async def ask(self, request: LLMRequest) -> LLMResult:
        raise NotImplementedError("Gemini 어댑터는 아직 없다. ClaudeAdapter나 FakeAdapter를 쓴다.")
