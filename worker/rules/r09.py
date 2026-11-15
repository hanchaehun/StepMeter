"""R09 기대 불일치: 에이전트의 expectation과 실제 결과가 다르다고 LLM이 판단 (개발계획서 6장, 낮음·참고).

시도가 끝난 뒤 한 번만 묻는다. 단계마다 물으면 LLM 호출이 거의 두 배가 되고,
R09는 채점 대상이 아닌 참고 규칙이라 그 비용을 쓰지 않는다 (ADR 0011 2번).
스크린샷 없이 행동·기대·화면 반응 종류·주소 변화만 글로 보낸다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from worker.llm.base import LLMRequest, LLMResult
from worker.rules.candidate import Candidate

PROMPT = Path(__file__).resolve().parents[2] / "prompts/judge_v1.md"
PROMPT_VERSION = "judge_v1"
# done·fail은 화면을 바꾸는 행동이 아니라 판단하지 않는다.
SKIPPED_ACTIONS = frozenset({"done", "fail"})


@dataclass(frozen=True)
class StepRecord:
    """판단에 쓰는 한 단계. loop.py가 단계를 저장한 뒤 만든다."""

    step_id: int
    idx: int
    action: str
    target: str | None
    expectation: str
    effect: str
    url_before: str
    url_after: str | None


def judgeable(records: Sequence[StepRecord]) -> list[StepRecord]:
    return [r for r in records if r.action not in SKIPPED_ACTIONS]


def _clean(text: str | None) -> str:
    # 한 줄 형식이 깨지지 않게 줄바꿈과 구분자를 바꾼다.
    return " ".join((text or "").split()).replace("|", "/")


def user_text(records: Sequence[StepRecord]) -> str:
    lines = []
    for r in records:
        if r.url_after is None:
            moved = "알 수 없음"
        elif r.url_after == r.url_before:
            moved = "같음"
        else:
            moved = f"{_clean(r.url_before)} → {_clean(r.url_after)}"
        lines.append("|".join([str(r.idx), r.action, _clean(r.target) or "-", _clean(r.expectation),
                               r.effect, moved]))
    return "\n".join(lines)


def parse_mismatches(text: str, known: set[int]) -> dict[int, str]:
    """{단계 번호: 이유}. 읽을 수 없거나 모르는 단계는 버린다 (R09는 참고라 실패시키지 않는다)."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return {}
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    found: dict[int, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        step, reason = item.get("step"), item.get("reason")
        if type(step) is int and step in known and isinstance(reason, str) and reason.strip():
            found.setdefault(step, " ".join(reason.split())[:300])
    return found


def candidates(records: Sequence[StepRecord], mismatches: dict[int, str]) -> list[Candidate]:
    out = []
    for r in records:
        if r.idx in mismatches:
            name = _clean(r.target) or r.action
            out.append(Candidate("R09", "low", f"{name} 뒤 결과가 기대와 다릅니다. {mismatches[r.idx]}",
                                 is_reference=True, step_id=r.step_id))
    return out


async def judge(adapter, records: Sequence[StepRecord], *, run_id: int | None = None
                ) -> tuple[LLMResult | None, list[Candidate]]:
    """LLM에 한 번 묻고 (호출 결과, R09 후보)를 돌려준다. 판단할 단계가 없으면 묻지 않는다."""
    steps = judgeable(records)
    if not steps:
        return None, []
    request = LLMRequest(purpose="judge", prompt_version=PROMPT_VERSION,
                         system=PROMPT.read_text(encoding="utf-8"), user_text=user_text(steps), run_id=run_id)
    result = await adapter.ask(request)
    return result, candidates(steps, parse_mismatches(result.text, {r.idx for r in steps}))
