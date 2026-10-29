"""LLM 호출 기록 (개발계획서 1.1 원칙 4, 10장 llm_call).

DB가 준비되기 전까지는 JSON Lines 파일에 한 줄씩 남긴다.
기본 위치 data/llm_calls.jsonl 은 .gitignore의 data/ 규칙 때문에 커밋되지 않는다.
DB가 생기면 같은 항목을 llm_call 테이블에 쓰는 클래스를 하나 더 만들면 된다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from worker.llm.base import LLMAdapter, LLMRequest, LLMResult

DEFAULT_LOG_PATH = Path("data/llm_calls.jsonl")


class JsonlCallLog:
    def __init__(self, path: Path = DEFAULT_LOG_PATH):
        self.path = path

    def write(self, request: LLMRequest, result: LLMResult) -> None:
        # 항목 이름은 llm_call 테이블 컬럼과 같게 둔다 (id는 DB가 붙인다).
        row = {
            "run_id": request.run_id,
            "purpose": request.purpose,
            "model": result.model,
            "prompt_version": request.prompt_version,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
            "latency_ms": result.latency_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def ask_and_log(adapter: LLMAdapter, request: LLMRequest, log: JsonlCallLog) -> LLMResult:
    """어댑터에 묻고, 결과를 기록한 뒤 돌려준다. 다른 파트는 이 함수만 부르면 된다."""

    result = await adapter.ask(request)
    log.write(request, result)
    return result
