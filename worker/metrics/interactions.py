"""Pure counters. Inputs are chronological observations, not inferred DOM changes."""

import math
from collections.abc import Sequence
from urllib.parse import urlsplit

from worker.schemas import ACTION_NAMES


def count_interactions(actions: Sequence[str]) -> dict[str, float]:
    """Count actions before done; type counts fields/actions, never characters."""
    counts = dict.fromkeys(("click_count", "type_count", "step_count", "back_count"), 0.0)
    for action in actions:
        if action not in ACTION_NAMES:
            raise ValueError(f"Unknown action: {action}")
        if action == "done":
            break
        counts["step_count"] += 1
        if action == "select":
            counts["click_count"] += 1
        elif action in {"click", "type", "back"}:
            counts[f"{action}_count"] += 1
    return counts


def count_no_response_clicks(actions: Sequence[str], effects: Sequence[str]) -> int:
    if len(actions) != len(effects):
        raise ValueError("One effect is required per action")
    count = 0
    for action, effect in zip(actions, effects):
        if effect not in {"url_change", "modal_change", "dom_mutation", "no_change"}:
            raise ValueError(f"Unknown effect: {effect}")
        if action == "done":
            break
        count += action in {"click", "select"} and effect == "no_change"
    return count


def count_repeated_clicks(actions: Sequence[str], target_keys: Sequence[str | None]) -> int:
    """Count extra consecutive clicks: A,A,A => 2; A,type,A => 0.

    Keys must identify the same DOM target on the same page, not reusable el_id.
    Unknown identities (None) do not establish repetition.
    """
    if len(actions) != len(target_keys):
        raise ValueError("One target identity is required per action")
    previous = None
    count = 0
    for action, key in zip(actions, target_keys):
        if action == "done":
            break
        current = key if action in {"click", "select"} else None
        count += current is not None and current == previous
        previous = current
    return count


def calculate_scroll_distance(scroll_y: Sequence[float]) -> float:
    """Sum absolute vertical deltas, including initial and final observations."""
    if any(not math.isfinite(y) for y in scroll_y):
        raise ValueError("Scroll positions must be finite")
    return sum((abs(b - a) for a, b in zip(scroll_y, scroll_y[1:])), 0.0)


def count_page_transitions(urls: Sequence[str]) -> int:
    """Count URL path changes (5.6); query/hash changes alone do not count."""
    paths = [urlsplit(url).path or "/" for url in urls]
    return sum(a != b for a, b in zip(paths, paths[1:]))
