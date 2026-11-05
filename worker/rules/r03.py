"""The driver owns noise filtering and the three-second observation window."""

from worker.rules.candidate import Candidate


def evaluate(action: str, effect_type: str) -> Candidate | None:
    if effect_type not in {"url_change", "modal_change", "dom_mutation", "no_change"}:
        raise ValueError(f"Unknown effect: {effect_type}")
    if action == "click" and effect_type == "no_change":
        return Candidate("R03", "high", "클릭 후 노이즈를 제외한 유효한 변화가 감지되지 않았습니다.")
    return None
