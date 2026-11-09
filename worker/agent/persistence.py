"""Short ORM transactions; cancellation is authoritative in every writer."""
from datetime import datetime, timezone

from sqlalchemy import select, update

from apps.api.db.models import Attempt, ElementSnapshot, LlmCall, Run, Step
from worker.queue.runs import update_progress, save_screenshot


class Canceled(Exception):
    pass


def running(session, run_id):
    row = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if row is None or row.status != 'running':
        raise Canceled()
    return row


def start(session, run_id):
    return session.execute(update(Run).where(Run.id == run_id, Run.status == 'queued').values(
        status='running', started_at=datetime.now(timezone.utc), prompt_version='action_v1',
    ).returning(Run.id)).scalar_one_or_none() is not None


def log_call(factory, run_id, result):
    with factory.begin() as session:
        # Preserve charged-call evidence even if cancellation arrived during ask.
        row = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if row is None:
            raise Canceled()
        session.add(LlmCall(run_id=run_id, purpose='action', model=result.model,
                           prompt_version='action_v1', input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens, cost_usd=result.cost_usd,
                           latency_ms=result.latency_ms))
        if result.cost_usd is not None:
            row.cost_usd += result.cost_usd


def save_step(session, run_id, attempt_id, idx, action, url, state, result, *, fitts=None):
    # A step already executed before cancellation is still evidence. The caller
    # checks progress AFTER committing it and then stops.
    row = Step(attempt_id=attempt_id, idx=idx, action=action.model_dump(), thought=action.thought,
               screenshot_key=save_screenshot(result.screenshot), url=url, state_hash=state,
               fitts_id=fitts, **result.effect.as_step_effect())
    session.add(row)
    session.flush()
    if result.element is not None:
        data = result.element.model_dump()
        session.add(ElementSnapshot(step_id=row.id, data=data, **{k: data[k] for k in
                    ('bbox', 'style', 'bg_chain', 'occluded', 'in_first_view', 'name', 'role')}))
    session.flush()
    active = update_progress(session, run_id)
    return row.id, active


def finish_attempt(factory, run_id, attempt_id, reason, success=False, estimated=False, detail=None):
    with factory.begin() as session:
        running(session, run_id)
        attempt = session.get(Attempt, attempt_id)
        attempt.end_reason, attempt.success = reason, success
        attempt.success_estimated, attempt.end_detail = estimated, detail
        session.flush()
        if not update_progress(session, run_id):
            raise Canceled()
