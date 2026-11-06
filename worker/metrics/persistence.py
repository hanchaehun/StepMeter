"""Write owned metric rows. The caller controls commit/rollback and run state."""

import math
from collections.abc import Mapping
from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.db.models import Attempt, Metric, Run


UNITS = {
    "click_count": "count", "type_count": "count", "step_count": "count",
    "back_count": "count", "no_response_click_count": "count",
    "repeated_click_count": "count", "page_transition_count": "count",
    "travel_distance": "px", "scroll_distance": "px", "fitts_id_sum": "bit",
}


def _write(session: Session, run_id: int, attempt_id: int | None,
           values: Mapping[str, float]) -> list[Metric]:
    if any(key not in UNITS or not math.isfinite(value) or value < 0
           for key, value in values.items()):
        raise ValueError("Unknown metric or invalid nonnegative finite value")
    # Serialize our upserts without a schema change/unique index.
    if session.scalar(select(Run).where(Run.id == run_id).with_for_update()) is None:
        raise ValueError("Run does not exist")
    rows = []
    for key, value in values.items():
        row = session.scalars(select(Metric).where(
            Metric.run_id == run_id, Metric.attempt_id == attempt_id, Metric.key == key,
        )).one_or_none()
        if row is None:
            row = Metric(run_id=run_id, attempt_id=attempt_id, key=key, unit=UNITS[key])
            session.add(row)
        row.value = value
        # W3 dispersion/calibration is not fabricated from a single attempt.
        row.spread = None
        row.spread_quality = None
        row.model_version_id = None
        rows.append(row)
    session.flush()
    return rows


def save_attempt_metrics(session: Session, attempt_id: int,
                         values: Mapping[str, float]) -> list[Metric]:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        raise ValueError("Attempt does not exist")
    return _write(session, attempt.run_id, attempt_id, values)


def save_run_medians(session: Session, run_id: int, *, kind: str = "agent") -> list[Metric]:
    """Aggregate successful finished attempts of ONE kind; never mix replay/agent.

    No successes => no aggregate, not a misleading zero. All selected attempts
    must already have the same W2 metric keys. Caller runs after postprocessing.
    """
    if kind not in {"agent", "replay"}:
        raise ValueError("Unknown attempt kind")
    if session.scalar(select(Run).where(Run.id == run_id).with_for_update()) is None:
        raise ValueError("Run does not exist")
    attempts = list(session.scalars(select(Attempt).where(
        Attempt.run_id == run_id, Attempt.kind == kind, Attempt.success.is_(True),
        Attempt.end_reason.is_not(None),
    )))
    if kind == "replay":
        attempts = [attempt for attempt in attempts if attempt.replay_status == "full"]
    if not attempts:
        session.execute(delete(Metric).where(
            Metric.run_id == run_id, Metric.attempt_id.is_(None), Metric.key.in_(UNITS),
        ))
        return []
    measurements = []
    for attempt in attempts:
        rows = session.scalars(select(Metric).where(
            Metric.run_id == run_id, Metric.attempt_id == attempt.id, Metric.key.in_(UNITS),
        ))
        values = {row.key: row.value for row in rows}
        if not values:
            raise ValueError("A successful attempt has no W2 metrics")
        measurements.append(values)
    if any(values.keys() != measurements[0].keys() for values in measurements):
        raise ValueError("Successful attempts must have the same metric keys")
    session.execute(delete(Metric).where(
        Metric.run_id == run_id, Metric.attempt_id.is_(None), Metric.key.in_(UNITS),
        Metric.key.not_in(measurements[0]),
    ))
    return _write(session, run_id, None, {
        key: float(median(values[key] for values in measurements)) for key in measurements[0]
    })
