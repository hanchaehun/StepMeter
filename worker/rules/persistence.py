"""Persist rule candidates after a caller supplies the separate scoring result."""

import math
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import Attempt, Issue, Run, Step
from worker.rules.candidate import Candidate


def save_candidates(session: Session, run_id: int, candidates: Sequence[Candidate],
                    *, confidence: float) -> list[Issue]:
    """No commit; same candidate updates its row without losing issue labels.

    confidence has no invented default: the scorer/caller must supply it. Call
    separately for candidates with different scores. No stale issue deletion.
    """
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be finite and within [0, 1]")
    if session.scalar(select(Run).where(Run.id == run_id).with_for_update()) is None:
        raise ValueError("Run does not exist")
    for candidate in candidates:
        if candidate.step_id is not None:
            owner = session.scalar(select(Attempt.run_id).join(Step).where(Step.id == candidate.step_id))
            if owner != run_id:
                raise ValueError("Candidate step does not belong to this run")
    rows = []
    for candidate in candidates:
        row = session.scalars(select(Issue).where(
            Issue.run_id == run_id, Issue.rule_id == candidate.rule_id,
            Issue.step_id == candidate.step_id, Issue.element_key == candidate.element_key,
            Issue.explanation == candidate.explanation,
        )).one_or_none()
        if row is None:
            row = Issue(run_id=run_id, rule_id=candidate.rule_id,
                        step_id=candidate.step_id, element_key=candidate.element_key,
                        explanation=candidate.explanation)
            session.add(row)
        row.severity = candidate.severity
        row.confidence = confidence
        row.measured = candidate.measured
        row.threshold = candidate.threshold
        row.is_reference = candidate.is_reference
        rows.append(row)
        session.flush()
    return rows
