"""Stable axe target suffix contract for rules, explanation writers and readers."""

import json
from typing import Any

MARKER = " 대상: "
AXE_RULES = frozenset({"R02", "R10"})


def _target(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and bool(item) or _target(item) for item in value)


def split_explanation(explanation: str) -> tuple[str, str | None]:
    """Return prose and the exact suffix, including original JSON whitespace.

    Search backwards, since selector strings can themselves contain the marker.
    Malformed target metadata fails explicitly rather than silently losing it.
    """
    position = explanation.rfind(MARKER)
    if position < 0:
        return explanation, None
    while position >= 0:
        try:
            value = json.loads(explanation[position + len(MARKER):])
        except json.JSONDecodeError:
            value = None
        if _target(value):
            return explanation[:position], explanation[position:]
        position = explanation.rfind(MARKER, 0, position)
    raise ValueError("Invalid axe target suffix")


def read_target(explanation: str) -> list[Any] | None:
    """Read the original axe target array (including nested shadow selectors)."""
    _, suffix = split_explanation(explanation)
    return json.loads(suffix[len(MARKER):]) if suffix is not None else None


def rewrite_explanation(original: str, generated: str, *, require_target: bool = False) -> str:
    """The model supplies prose only; metadata always comes from the stored row."""
    if not isinstance(generated, str) or not generated.strip():
        raise ValueError("Generated explanation must be nonempty text")
    if MARKER in generated:
        raise ValueError("Generated explanation must not include target metadata")
    _, suffix = split_explanation(original)
    if require_target and suffix is None:
        raise ValueError("Missing axe target suffix")
    return generated.strip() + (suffix or "")
