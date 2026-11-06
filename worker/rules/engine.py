"""W2 composition; rule candidates have no fabricated confidence/ML score."""

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from worker.rules import r01, r02, r03, r04, r06, r10
from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot


def element_key(snapshot: ElementSnapshot) -> str:
    return "|".join((snapshot.tag, snapshot.role or "", snapshot.name,
                     snapshot.label_text or "", snapshot.landmark or ""))


def evaluate_step(snapshot: ElementSnapshot, *, step_id: int, action: str,
                  effect_type: str, is_first_target: bool, mobile: bool = False,
                  axe_target_size: bool | None = None) -> list[Candidate]:
    """Only call for a target-bearing step; first_target is attempt-wide."""
    candidates = (
        r01.evaluate(snapshot, mobile=mobile, axe_violation=axe_target_size),
        r03.evaluate(action, effect_type), r04.evaluate(snapshot),
        r06.evaluate(snapshot, is_first_target=is_first_target),
    )
    return [replace(candidate, step_id=step_id, element_key=element_key(snapshot))
            for candidate in candidates if candidate is not None]


def evaluate_axe(results: dict[str, Any], step_ids: Mapping[int, int],
                 snapshots: Mapping[int, ElementSnapshot] | None = None) -> list[Candidate]:
    """Only violations become candidates; incomplete never means pass or failure.

    Off-path visible text and unnamed controls remain reference candidates.
    Offscreen, off-path contrast is outside plan 5.5's inspection scope.
    R01 is evaluated with its snapshot (spacing/inline/44px exceptions).
    """
    candidates = []
    for violation in results["violations"]:
        for node in violation["nodes"]:
            reference = node["is_reference"]
            if violation["id"] == "color-contrast" and reference and not node["in_viewport"]:
                continue
            candidate = (r02.evaluate(violation["id"], is_reference=reference)
                         or r10.evaluate(violation["id"], is_reference=reference))
            if candidate is not None:
                # Mapping is supplied after the core has persisted the action.
                for path_key in node["path_keys"] or [None]:
                    step_id = step_ids[path_key] if path_key is not None else None
                    if step_id is not None and step_id <= 0:
                        raise ValueError("A persisted positive step ID is required")
                    snapshot = (snapshots or {}).get(step_id) if step_id is not None else None
                    target = json.dumps(node["target"], ensure_ascii=False)
                    candidates.append(replace(
                        candidate, step_id=step_id,
                        element_key=element_key(snapshot) if snapshot is not None else None,
                        explanation=f"{candidate.explanation} 대상: {target}",
                    ))
    return candidates


def axe_target_size_result(results: dict[str, Any], path_key: int) -> bool | None:
    """Prefer axe's definitive per-target result; absence/incomplete => fallback."""
    for group, value in (("violations", True), ("passes", False)):
        for rule in results[group]:
            if rule["id"] == "target-size" and any(
                path_key in node["path_keys"] for node in rule["nodes"]
            ):
                return value
    return None
