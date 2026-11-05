from worker.rules.candidate import Candidate


NAME_RULES = frozenset({
    "button-name", "link-name", "label", "select-name", "input-button-name",
    "input-image-alt", "aria-command-name", "aria-input-field-name",
    "aria-toggle-field-name", "aria-dialog-name", "aria-meter-name",
    "aria-progressbar-name", "aria-tooltip-name", "aria-treeitem-name",
})


def evaluate(axe_rule_id: str, *, is_reference: bool = False) -> Candidate | None:
    if axe_rule_id in NAME_RULES:
        return Candidate("R10", "medium", "axe-core가 접근 가능한 이름·레이블 누락을 확인했습니다.",
                         is_reference=is_reference)
    return None
