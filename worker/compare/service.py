"""Read persisted evidence and cache a comparison; caller owns authorization/commit."""
from collections import defaultdict
import json

from sqlalchemy import select

from apps.api.db.models import Attempt, Comparison, ElementSnapshot, Issue, Metric, Run, Step
from worker.compare.engine import align_paths, issue_changes, metric_changes, screen


def steps(db, attempt_id):
    if attempt_id is None:
        return []
    rows = db.execute(select(Step, ElementSnapshot.data).outerjoin(
        ElementSnapshot, ElementSnapshot.step_id == Step.id).where(
        Step.attempt_id == attempt_id).order_by(Step.idx))
    return [{'idx': s.idx, 'action': s.action, 'fingerprint': snap} for s, snap in rows]


def issue_identity(issue):
    if issue.rule_id not in ('R02', 'R10'):
        return issue.element_key
    try:
        target = json.loads(issue.explanation.rsplit(' 대상: ', 1)[1])
        if isinstance(target, list) and target and all(isinstance(t, str) for t in target):
            return 'axe:' + json.dumps(target, ensure_ascii=False)
    except (ValueError, IndexError):
        pass
    return None  # An action fingerprint cannot stand in for the actual axe node.


def issues(db, run_id):
    rows = db.execute(select(Issue, Attempt.index, Step.idx, Step.url).outerjoin(
        Step, Issue.step_id == Step.id).outerjoin(Attempt, Step.attempt_id == Attempt.id).where(
        Issue.run_id == run_id).order_by(Issue.id))
    return [{**{key: getattr(i, key) for key in (
        'id', 'rule_id', 'severity', 'confidence', 'element_key', 'measured', 'threshold',
        'explanation', 'suggestion', 'score_reason', 'is_reference')},
        'step': {'attempt_index': n, 'idx': idx} if i.step_id is not None else None,
        'screen': screen(url) if url else None, '_identity': issue_identity(i)} for i, n, idx, url in rows]


def measurements(db, run_id, kind, attempt_id=None):
    q = select(Metric.key, Metric.value).join(Attempt, Metric.attempt_id == Attempt.id).where(
        Metric.run_id == run_id, Attempt.kind == kind, Attempt.success.is_(True),
        Attempt.end_reason == 'success')
    if kind == 'replay':
        q = q.where(Attempt.replay_status == 'full')
    if attempt_id is not None:
        q = q.where(Attempt.id == attempt_id)
    values = defaultdict(list)
    for key, value in db.execute(q):
        values[key].append(value)
    return dict(values)


def compare_runs(db, base: Run, target: Run):
    if base.task_id != target.task_id or base.viewport != target.viewport:
        raise ValueError('Runs must have the same task and viewport')
    if base.status != 'completed' or target.status != 'completed':
        raise ValueError('Both runs must be completed')
    # Stable lock order serializes the cache upsert, including concurrent reverse comparisons.
    list(db.scalars(select(Run).where(Run.id.in_([base.id, target.id])).order_by(Run.id).with_for_update()))
    new, resolved, kept = issue_changes(issues(db, base.id), issues(db, target.id))
    def public(rows):
        return [{k: v for k, v in row.items() if k not in ('screen', '_identity')} for row in rows]
    agent_base, agent_target = measurements(db, base.id, 'agent'), measurements(db, target.id, 'agent')
    replay_attempt = db.scalar(select(Attempt).where(Attempt.run_id == target.id,
        Attempt.kind == 'replay').order_by(Attempt.index).limit(1))
    agent_count = lambda run_id: db.scalars(select(Attempt.id).where(Attempt.run_id == run_id,
        Attempt.kind == 'agent', Attempt.success.is_(True), Attempt.end_reason == 'success')).all()
    has_agent = db.scalar(select(Attempt.id).where(Attempt.run_id == target.id, Attempt.kind == 'agent').limit(1))
    replay = None
    if replay_attempt:
        reference = db.get(Attempt, base.representative_attempt_id) if base.representative_attempt_id else None
        replay = {'replay_status': replay_attempt.replay_status or 'partial',
                  'diverged_at_step': replay_attempt.diverged_at_step,
                  'metric_changes': metric_changes(
                      measurements(db, base.id, reference.kind, reference.id) if reference else {},
                      measurements(db, target.id, 'replay', replay_attempt.id), replay=True,
                      comparable=replay_attempt.replay_status == 'full')}
    result = {'base_run_id': base.id, 'target_run_id': target.id,
              'issues_new': public(new), 'issues_resolved': public(resolved), 'issues_kept': public(kept),
              'replay': replay, 'agent': {'spread_weak': len(agent_count(base.id)) == 2 or len(agent_count(target.id)) == 2,
                                        'metric_changes': metric_changes(agent_base, agent_target)} if has_agent else None,
              'path_alignment': align_paths(steps(db, base.representative_attempt_id),
                                            steps(db, target.representative_attempt_id))}
    cached = db.scalar(select(Comparison).where(Comparison.base_run_id == base.id,
                                              Comparison.target_run_id == target.id))
    if cached is None:
        db.add(Comparison(base_run_id=base.id, target_run_id=target.id, summary=result))
    else:
        cached.summary = result
    db.flush()
    return result
