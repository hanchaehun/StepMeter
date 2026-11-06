"""Contrast decisions come only from axe, never from guessed RGB values."""

from worker.rules.candidate import Candidate


def evaluate(axe_rule_id: str, *, is_reference: bool = False) -> Candidate | None:
    if axe_rule_id == "color-contrast":
        return Candidate("R02", "high", "axe-core가 텍스트 대비 기준 위반을 확인했습니다.",
                         is_reference=is_reference)
    return None
