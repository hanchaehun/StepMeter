"""Attempt step counts from persisted actions (all finished outcomes)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import Attempt, Metric, Run, Step
from worker.metrics.interactions import count_interactions
from worker.metrics.persistence import save_attempt_metrics


def finalize_run_metrics(session: Session, run_id: int, *, kind: str = "agent") -> list[Metric]:
    """Save observed step_count per attempt only; never commit.

    Includes successful and unsuccessful finished attempts of the selected kind.
    Run medians belong exclusively to save_run_medians (ADR 0010).
    This describes work performed, not successful-path UX. Caller invokes after
    all attempts finish and before completing the run, in the same transaction.
    """
    if kind not in {"agent", "replay"}:
        raise ValueError("Unknown attempt kind")
    run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run is None or run.status != "running":
        raise ValueError("Run must exist and be running")
    attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id)))
    if not attempts or any(attempt.end_reason is None for attempt in attempts):
        raise ValueError("All attempts must be finished before metric aggregation")
    selected = [attempt for attempt in attempts if attempt.kind == kind]
    if not selected:
        raise ValueError("No attempts of the selected kind")
    measurements = []
    for attempt in selected:
        steps = list(session.scalars(select(Step).where(
            Step.attempt_id == attempt.id,
        ).order_by(Step.idx)))
        # Validate every selected path before writing any metrics.
        count = count_interactions([step.action["action"] for step in steps])["step_count"]
        measurements.append((attempt.id, count))
    rows = []
    for attempt_id, count in measurements:
        rows.extend(save_attempt_metrics(session, attempt_id, {"step_count": count}))
    return rows
