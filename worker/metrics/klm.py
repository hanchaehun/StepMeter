"""Desktop literature KLM, exactly ADR 0011 section 3; no response-time R."""

from collections.abc import Mapping
from typing import Any

K, P, B, H, M, S = .28, 1.1, .1, .4, 1.35, 1.1
MOTOR_ACTIONS = frozenset({"click", "type", "select", "scroll", "back"})


def estimate_step(action: Mapping[str, Any], *, first_action: bool,
                  previous_action: str | None = None, auto_scrolled: bool = False,
                  mobile: bool = False) -> float | None:
    """No calibration. submit anticipates #75's optional Enter (one K).

    The caller supplies actual preparation scroll and screen-boundary evidence.
    Empty type is a field action, not zero work. Zero-cost actions never get M/H/S.
    """
    kind = action["action"]
    if kind not in MOTOR_ACTIONS | {"wait", "done", "fail"}:
        raise ValueError("Unknown KLM action")
    if kind == "type":
        if not isinstance(action.get("text"), str) or type(action.get("submit", False)) is not bool:
            raise ValueError("Type requires text and optional boolean submit")
    if mobile:
        return None
    if kind not in MOTOR_ACTIONS:
        return 0.0
    base = {"click": M + P + 2*B, "back": M + P + 2*B,
            "select": M + 2*P + 4*B, "scroll": M + S}
    seconds = (M + P + 2*B + H + K*(len(action["text"]) + action.get("submit", False))
               if kind == "type" else base[kind])
    seconds += M if first_action else 0
    seconds += H if previous_action == "type" else 0
    seconds += S if auto_scrolled else 0
    return round(seconds, 10)
