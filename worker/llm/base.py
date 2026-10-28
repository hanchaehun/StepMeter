"""어댑터가 주고받는 요청·결과 형식.

에이전트 코어 같은 다른 파트는 이 파일의 LLMRequest를 만들어 어댑터에 넘기고,
LLMResult를 돌려받는다. 어떤 회사 모델을 쓰는지는 몰라도 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

# 왜 불렀는지. llm_call.purpose 컬럼에 그대로 저장된다 (개발계획서 10장).
#   action   : 다음 행동 고르기 (4.3, 4.4)
#   explain  : 문제 설명 문장 쓰기 (6.1)
#   baseline : 베이스라인 실험 (8.3)
Purpose = Literal["action", "explain", "baseline"]


@dataclass(frozen=True)
class LLMRequest:
    """어댑터에 보내는 요청 한 건."""

    purpose: Purpose
    prompt_version: str  # prompts/ 파일 이름의 버전. 예: "action_v1"
    system: str  # 시스템 프롬프트 (prompts/ 파일 내용)
    user_text: str  # 과업 설명, 요소 목록, 최근 이력 등
    image_jpeg: bytes | None = None  # 번호 라벨을 그린 스크린샷 (4.2)
    run_id: int | None = None  # 어떤 측정에서 불렀는지. 측정 밖 실험이면 None


@dataclass(frozen=True)
class LLMResult:
    """어댑터가 돌려주는 결과 한 건."""

    text: str  # 모델 답. purpose가 action이면 행동 JSON 글자
    model: str  # 실제로 쓴 모델 이름
    input_tokens: int
    output_tokens: int
    cost_usd: float | None  # 단가를 모르면 None (16장: 단가는 사용 시점 요금표로 확인)
    latency_ms: int  # 보내고 답 받을 때까지 걸린 시간


class LLMAdapter(Protocol):
    """모든 어댑터(가짜, Claude, Gemini)가 지켜야 하는 모양."""

    name: str

    async def ask(self, request: LLMRequest) -> LLMResult: ...
