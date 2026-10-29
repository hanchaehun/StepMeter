"""모델 단가와 호출 1회 비용 계산 (개발계획서 16장).

단가는 바뀔 수 있으므로 쓰기 전에 Anthropic 요금표에서 다시 확인한다.
여기 없는 모델은 비용을 None으로 기록한다 (모르는 값을 지어내지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass

# 한 요청의 입력(캐시 포함)이 이 토큰 수를 넘으면 비싼 단가가 붙는다 (Haiku 5.5만 해당).
LONG_PROMPT_THRESHOLD = 100_000


@dataclass(frozen=True)
class Rates:
    """100만 토큰당 달러."""

    input: float
    output: float
    cache_write_5m: float
    cache_read: float


# (짧은 프롬프트 단가, 100K 초과 단가). 2026-10-28 확인.
PRICES: dict[str, tuple[Rates, Rates]] = {
    "claude-haiku-5-5": (
        Rates(input=0.10, output=0.50, cache_write_5m=0.125, cache_read=0.01),
        Rates(input=0.50, output=2.50, cache_write_5m=0.625, cache_read=0.05),
    ),
    # Sonnet 5.5는 프롬프트 길이와 관계없이 단가가 같다. 2026-10-29 확인.
    "claude-sonnet-5-5": (
        Rates(input=2.00, output=10.00, cache_write_5m=2.50, cache_read=0.20),
        Rates(input=2.00, output=10.00, cache_write_5m=2.50, cache_read=0.20),
    ),
}


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float | None:
    """토큰 수로 호출 1회 비용을 계산한다. input_tokens는 캐시가 아닌 입력만 센다."""

    if model not in PRICES:
        return None
    short, long = PRICES[model]
    prompt_tokens = input_tokens + cache_write_tokens + cache_read_tokens
    rates = long if prompt_tokens > LONG_PROMPT_THRESHOLD else short
    total = (
        input_tokens * rates.input
        + output_tokens * rates.output
        + cache_write_tokens * rates.cache_write_5m
        + cache_read_tokens * rates.cache_read
    )
    return total / 1_000_000
