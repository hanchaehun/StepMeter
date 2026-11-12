"""Measurement-only W3 features; no labels, weights, thresholds or predictions.

The execution-tool adapter supplies a canonical target identity (including the
screen) for each observation. An action fingerprint alone is not sufficient for
axe findings, whose actual target can differ from the action target.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot

FEATURE_VERSION = "issue-features-v1"
SEVERITY = {"high": 1.0, "medium": 0.6, "low": 0.3}
# Only quantitative rules with a defined direction. Zero thresholds and boolean
# rules do not have a meaningful ratio/extent; missing values remain None.
LOWER_IS_WORSE = frozenset({"R01", "R02"})
HIGHER_IS_WORSE = frozenset({"R06", "R07"})


@dataclass(frozen=True)
class Observation:
    candidate: Candidate
    attempt_id: int
    target_key: str  # canonical (screen, actual target), supplied by evaluator
    snapshot: ElementSnapshot | None = None  # actual finding target, not clicked ancestor
    step_index: int | None = None
    step_count: int | None = None  # includes non-terminal actions only
    confusion: str | None = None
    estimated: bool | None = None  # unknown is not the same as confirmed


@dataclass(frozen=True)
class Features:
    severity: float
    measured_ratio: float | None
    violation_extent: float | None
    estimated: bool | None
    role: str | None
    area: float | None
    on_path: bool
    path_position: float | None
    detection_ratio: float
    confusion: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _number(value: float | None) -> float | None:
    if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
        raise ValueError("Measurements must be finite and nonnegative")
    return value


def extract_features(observations: Sequence[Observation], *, attempt_ids: Sequence[int]) -> list[Features]:
    """One row per observation, with repeated steps counted once per attempt.

    attempt_ids must be all completed *agent* attempts in this run (including
    failures), even those with no finding. Do not mix replay or other runs/tasks.
    Off-path references can share an identity with path findings, but do not
    contribute to path detection frequency. is_reference is an output-list flag,
    never used to infer on_path: score filtering may also set it (ADR 0011).
    """
    attempts = set(attempt_ids)
    if (not attempts or len(attempts) != len(attempt_ids)
            or any(type(a) is not int or a <= 0 for a in attempts)):
        raise ValueError("Unique positive completed agent attempt IDs are required")
    detected: dict[tuple[str, str], set[int]] = {}
    for obs in observations:
        if (type(obs.attempt_id) is not int or obs.attempt_id not in attempts
                or not isinstance(obs.target_key, str) or not obs.target_key.strip()):
            raise ValueError("Observation needs an eligible attempt and canonical target identity")
        if obs.candidate.rule_id not in {f'R{i:02}' for i in range(1, 12)}:
            raise ValueError('Unknown rule ID')
        if obs.candidate.step_id is not None and (type(obs.candidate.step_id) is not int or obs.candidate.step_id <= 0):
            raise ValueError('Positive persisted step ID required')
        if obs.confusion is not None and not isinstance(obs.confusion, str):
            raise ValueError('confusion must be text or None')
        if obs.candidate.step_id is not None:
            detected.setdefault((obs.candidate.rule_id, obs.target_key), set()).add(obs.attempt_id)
    rows = []
    for obs in observations:
        c = obs.candidate
        if c.severity not in SEVERITY:
            raise ValueError("Unknown severity")
        if obs.estimated is not None and type(obs.estimated) is not bool:
            raise ValueError("estimated must be bool or None")
        measured, threshold = _number(c.measured), _number(c.threshold)
        ratio = measured / threshold if measured is not None and threshold not in (None, 0) else None
        if ratio is not None and not math.isfinite(ratio):
            raise ValueError("Measurement ratio overflow")
        extent = None
        if ratio is not None and c.rule_id in LOWER_IS_WORSE:
            extent = min(1.0, max(0.0, 1.0 - ratio))
        elif ratio is not None and c.rule_id in HIGHER_IS_WORSE:
            extent = min(1.0, max(0.0, ratio - 1.0))
        on_path = c.step_id is not None
        position = None
        if obs.step_index is not None or obs.step_count is not None:
            if (not on_path or type(obs.step_count) is not int or type(obs.step_index) is not int
                    or obs.step_count <= 0 or not 0 <= obs.step_index < obs.step_count):
                raise ValueError("Path position requires a valid non-terminal index/count")
            position = obs.step_index / (obs.step_count - 1) if obs.step_count > 1 else 0.0
        box = obs.snapshot.bbox if obs.snapshot is not None else None
        area = box.width * box.height if box else None
        if area is not None and not math.isfinite(area):
            raise ValueError("Target area overflow")
        rows.append(Features(
            SEVERITY[c.severity], ratio, extent, obs.estimated,
            obs.snapshot.role if obs.snapshot else None, area, on_path, position,
            len(detected.get((c.rule_id, obs.target_key), ())) / len(attempts),
            on_path and bool(obs.confusion and obs.confusion.strip()),
        ))
    return rows
