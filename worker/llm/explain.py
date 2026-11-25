"""설명 생성 (개발계획서 6.1): run이 끝난 뒤 이슈마다 설명 문장과 고칠 방법 하나를 받는다.

- run 하나에 한 번만 묻는다. 같은 (규칙, 측정값, 기준값, 요소, 지금 설명) 이슈는 한 줄로 묶어 같은 답을 쓴다.
  대비 부족처럼 같은 문제가 시도마다 반복해서 저장되기 때문이다.
- v1은 스크린샷 없이 글만 보낸다. 6.1은 해당 단계 스크린샷도 준다고 했지만,
  이슈마다 이미지를 보내면 측정 한 번보다 설명 비용이 더 커질 수 있어 뒤로 미뤘다.
- 답에 입력에 없던 숫자가 있으면 그 줄은 버리고 규칙이 쓴 템플릿 설명을 그대로 둔다 (6.1).
- "대상: …"은 모델이 쓰지 않는다. update_explanation이 DB 원본에서 다시 붙인다 (#62, prompts/README.md).
- 설명이 실패해도 측정 결과는 바뀌지 않는다. 템플릿 설명이 남을 뿐이다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import Issue
from worker.agent.persistence import Canceled, log_call, running
from worker.llm.base import LLMRequest, LLMResult
from worker.rules.axe_target import split_explanation
from worker.rules.persistence import update_explanation

log = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parents[2] / "prompts/explain_v1.md"
PROMPT_VERSION = "explain_v1"
MAX_LINES = 60  # 한 번에 보내는 줄 수. 넘는 줄은 템플릿 설명을 그대로 둔다
MAX_CHARS = 300
# 답 길이 한도. 어댑터 기본값 1024(행동 JSON 하나용)로는 michi 한 run의 설명도 중간에 잘렸다 (run 13, 출력 1024토큰).
# benchmark/baseline_llm.py처럼 어댑터에 max_tokens가 있으면 이 호출 동안만 바꾼다.
MAX_TOKENS = 8192

# apps/web/src/lib/rules.ts의 이름과 같다
RULE_NAMES = {
    "R01": "작은 타겟", "R02": "대비 부족", "R03": "무반응 클릭", "R04": "가려진 요소",
    "R05": "반복 루프", "R06": "첫 화면 밖 핵심 요소", "R07": "먼 이동 + 작은 타겟",
    "R08": "되돌아감", "R09": "기대 불일치", "R10": "이름 없는 요소", "R11": "키보드 가림",
}
SEVERITY = {"high": "높음", "medium": "중간", "low": "낮음"}
NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class IssueText:
    """설명을 묻는 이슈 하나. prose는 explanation에서 "대상: …"을 뗀 앞부분이다."""

    issue_id: int
    rule_id: str
    severity: str
    measured: float | None
    threshold: float | None
    element_key: str | None
    prose: str


def _clean(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "/")


def _number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _numbers(text: str) -> set[float]:
    return {float(x) for x in NUMBER.findall(text)}


def load(session: Session, run_id: int) -> list[IssueText]:
    """run의 이슈를 읽는다. "대상: …"이 손상된 이슈는 건너뛴다 (템플릿 유지)."""
    out = []
    for row in session.scalars(select(Issue).where(Issue.run_id == run_id).order_by(Issue.id)):
        try:
            prose, _ = split_explanation(row.explanation)
        except ValueError:
            continue
        out.append(IssueText(row.id, row.rule_id, row.severity, row.measured, row.threshold,
                             row.element_key, prose.strip()))
    return out


def group(issues: Sequence[IssueText]) -> list[tuple[IssueText, list[int]]]:
    """같은 문제를 한 줄로 묶는다. 순서는 처음 나온 순서."""
    groups: dict[tuple, tuple[IssueText, list[int]]] = {}
    for issue in issues:
        key = (issue.rule_id, issue.severity, issue.measured, issue.threshold, issue.element_key, issue.prose)
        groups.setdefault(key, (issue, []))[1].append(issue.issue_id)
    return list(groups.values())[:MAX_LINES]


def fields(issue: IssueText) -> list[str]:
    """한 줄의 칸 (번호 제외). 숫자 검사도 이 칸들만 기준으로 한다."""
    return [RULE_NAMES.get(issue.rule_id, issue.rule_id), SEVERITY.get(issue.severity, issue.severity),
            _number(issue.measured), _number(issue.threshold), _clean(issue.element_key) or "-",
            _clean(issue.prose) or "-"]


def user_text(groups: Sequence[tuple[IssueText, list[int]]]) -> str:
    return "\n".join(f"{i}|" + "|".join(fields(issue)) for i, (issue, _) in enumerate(groups, 1))


def _items(text: str) -> list:
    """답에서 JSON 배열을 읽는다. 배열이 중간에 끊겼으면 끝까지 쓴 항목만 읽는다."""
    match = re.search(r"\[.*\]", text, re.S)
    if match:
        try:
            items = json.loads(match.group(0))
            return items if isinstance(items, list) else []
        except json.JSONDecodeError:
            pass
    start = text.find("[")
    if start < 0:
        return []
    decoder, items, position = json.JSONDecoder(), [], start + 1
    while (position := text.find("{", position)) >= 0:
        try:
            item, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            break  # 여기서부터 잘렸다
        items.append(item)
    return items


def parse(text: str, known: set[int]) -> dict[int, tuple[str, str]]:
    """{번호: (설명, 고칠 방법)}. 읽을 수 없거나 모르는 번호, 빈 글, "대상:"이 든 글은 버린다."""
    found: dict[int, tuple[str, str]] = {}
    for item in _items(text):
        if not isinstance(item, dict):
            continue
        number, explanation, suggestion = item.get("id"), item.get("explanation"), item.get("suggestion")
        if type(number) is not int or number not in known:
            continue
        if not (isinstance(explanation, str) and isinstance(suggestion, str)):
            continue
        explanation, suggestion = " ".join(explanation.split()), " ".join(suggestion.split())
        if not explanation or not suggestion or "대상:" in explanation + suggestion:
            continue
        found.setdefault(number, (explanation[:MAX_CHARS], suggestion[:MAX_CHARS]))
    return found


async def generate(adapter, issues: Sequence[IssueText], *, run_id: int | None = None
                   ) -> tuple[LLMResult | None, dict[int, tuple[str, str]]]:
    """LLM에 한 번 묻고 (호출 결과, {issue_id: (설명, 고칠 방법)})를 돌려준다. 이슈가 없으면 묻지 않는다."""
    groups = group(issues)
    if not groups:
        return None, {}
    request = LLMRequest(purpose="explain", prompt_version=PROMPT_VERSION,
                         system=PROMPT.read_text(encoding="utf-8"), user_text=user_text(groups), run_id=run_id)
    result = await adapter.ask(request)
    answers = parse(result.text, set(range(1, len(groups) + 1)))
    # 버린 줄은 이유를 워커 로그에 남긴다. 답 원문은 DB에 없어서, 로그가 없으면 왜 템플릿이 남았는지 알 수 없다 (run 15).
    missing = [i for i in range(1, len(groups) + 1) if i not in answers]
    if missing:
        log.warning("explain run=%s: 답이 없거나 읽지 못한 줄 %s (답 앞부분: %r)", run_id, missing, result.text[:300])
    out: dict[int, tuple[str, str]] = {}
    for i, (issue, ids) in enumerate(groups, 1):
        if i not in answers:
            continue
        explanation, suggestion = answers[i]
        extra = _numbers(explanation + " " + suggestion) - _numbers(" ".join(fields(issue)))
        if extra:
            # 입력에 없던 숫자: 버리고 템플릿 유지 (6.1)
            log.warning("explain run=%s: %s번 줄(%s) 입력에 없던 숫자 %s: %r / %r",
                        run_id, i, issue.rule_id, sorted(extra), explanation, suggestion)
            continue
        for issue_id in ids:
            out[issue_id] = (explanation, suggestion)
    return result, out


def apply(session: Session, run_id: int, updates: dict[int, tuple[str, str]]) -> int:
    """설명과 고칠 방법을 저장하고 바꾼 이슈 수를 돌려준다. commit하지 않는다.

    이슈 행을 바꾸는 일은 update_explanation(측정 지표·규칙)이 맡고, 여기서는 그 행에 suggestion만 채운다.
    """
    changed = 0
    for issue_id, (explanation, suggestion) in updates.items():
        try:
            row = update_explanation(session, run_id, issue_id, explanation)
        except ValueError:
            continue  # R02·R10의 "대상: …"이 없거나 손상: 템플릿 유지
        row.suggestion = suggestion
        changed += 1
    return changed


async def explain_run(factory, run_id: int, adapter) -> int:
    """run 후처리에서 부른다. LLM 호출은 DB 잠금 밖에서, 저장은 짧은 트랜잭션에서 한다.

    가짜 어댑터면 부르지 않는다 (R09와 같다. 가짜 측정의 호출 기록 수를 바꾸지 않는다).
    취소(Canceled)만 올리고, 그 밖의 실패는 템플릿 설명을 남긴 채 넘어간다.
    """
    if getattr(adapter, "name", "fake") == "fake":
        return 0
    with factory() as session:
        issues = load(session, run_id)
    old_max = getattr(adapter, "max_tokens", None)
    if old_max is not None:
        adapter.max_tokens = max(old_max, MAX_TOKENS)
    try:
        result, updates = await generate(adapter, issues, run_id=run_id)
    except Canceled:
        raise
    except Exception:
        return 0
    finally:
        if old_max is not None:
            adapter.max_tokens = old_max
    if result is not None:
        log_call(factory, run_id, result, purpose="explain", prompt_version=PROMPT_VERSION)
    if not updates:
        return 0
    with factory.begin() as session:
        running(session, run_id)
        return apply(session, run_id, updates)
