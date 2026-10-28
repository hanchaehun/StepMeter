"""LLM 어댑터 (담당: LLM·프롬프트). 개발계획서 3장, 4.3, 10장 llm_call, 16장."""

from worker.llm.base import LLMAdapter, LLMRequest, LLMResult
from worker.llm.call_log import JsonlCallLog, ask_and_log
from worker.llm.fake import FakeAdapter

__all__ = [
    "FakeAdapter",
    "JsonlCallLog",
    "LLMAdapter",
    "LLMRequest",
    "LLMResult",
    "ask_and_log",
]
