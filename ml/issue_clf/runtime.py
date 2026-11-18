"""Run-local scoring evidence and final ORM update; no labels or model calls."""
from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select

from apps.api.db.models import Attempt, ElementSnapshot, Issue, Step
from ml.issue_clf.features import FEATURE_VERSION, Observation, extract_features
from ml.issue_clf.scoring import ScoreConfig, score_features
from worker.agent.persistence import running
from worker.compare.engine import screen
from worker.rules.axe_target import AXE_RULES, read_target
from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot as Snapshot

LOGGER = logging.getLogger(__name__)

# Structural ancestry distinguishes same-name siblings, frames and shadow roots.
# Captured BEFORE the action can remove its target. No form values are read.
TARGET_SCRIPT = """el => {
    const parts=[];
    while (el) {
        const root=el.getRootNode(), path=[];
        for (let n=el;n;n=n.parentElement) {
            const siblings=[...(n.parentNode?.children||[])].filter(x=>x.localName===n.localName);
            path.unshift(n.localName+':nth-of-type('+(siblings.indexOf(n)+1)+')');
        }
        parts.unshift(path.join(' > '));
        el=root.host || el.ownerDocument.defaultView?.frameElement;
    }
    return parts;
}"""


def remember(evidence, issues, target, step_id):
    """Attach actual finding identity; axe snapshots are unknown conservatively."""
    evidence[('step', step_id)] = {'target': ('dom', target), 'action_snapshot': True}
    for issue in issues:
        actual = read_target(issue.explanation) if issue.rule_id in AXE_RULES else None
        if issue.rule_id in AXE_RULES and actual is None:
            raise ValueError('Missing axe target identity for scoring')
        evidence[issue.id] = {
            'target': ('axe', actual) if actual else ('dom', target),
            'action_snapshot': issue.rule_id not in AXE_RULES,
        }


def finalize_scores(session, run_id, config: ScoreConfig, evidence: dict) -> list[dict]:
    """Caller owns transaction and completion; cancellation checked before writes.

    Only completed agent path findings with captured identities are scored.
    Replay and run-level reference rules retain their original values. Missing
    evidence aborts scoring rather than publishing an arbitrary frequency.
    """
    run = running(session, run_id)
    attempts = list(session.scalars(select(Attempt).where(
        Attempt.run_id == run_id, Attempt.kind == 'agent')))
    if len(attempts) != run.repeat_n or any(a.end_reason is None for a in attempts):
        raise ValueError('Scoring requires all scheduled agent attempts to finish')
    ids = [a.id for a in attempts]
    steps = list(session.scalars(select(Step).where(Step.attempt_id.in_(ids)).order_by(Step.idx)))
    by_step = {s.id: s for s in steps}
    snapshots = {s.step_id: s.data for s in session.scalars(select(ElementSnapshot).where(
        ElementSnapshot.step_id.in_(by_step)))}
    paths = {a.id: [s.id for s in steps if s.attempt_id == a.id and
                    s.action['action'] not in ('done', 'fail')] for a in attempts}
    issues = list(session.scalars(select(Issue).where(
        Issue.run_id == run_id, Issue.step_id.in_(by_step)).order_by(Issue.id)))
    observations = []
    for issue in issues:
        step = by_step[issue.step_id]
        source = evidence.get(issue.id)
        # R07 is generated after the loop; reuse the captured target of its step.
        if source is None and issue.rule_id not in AXE_RULES:
            source = evidence.get(('step', issue.step_id))
        if source is None:
            raise ValueError('Missing actual target evidence for scoring')
        candidate = Candidate(**{key: getattr(issue, key) for key in
            ('rule_id', 'severity', 'explanation', 'measured', 'threshold', 'step_id',
             'element_key', 'is_reference')})
        snap = snapshots.get(step.id) if source['action_snapshot'] else None
        observations.append(Observation(candidate, step.attempt_id,
            json.dumps([screen(step.url), source['target'],
                        issue.element_key if source['action_snapshot'] else None], ensure_ascii=False),
            Snapshot.model_validate(snap) if snap else None,
            paths[step.attempt_id].index(step.id), len(paths[step.attempt_id]),
            step.action.get('confusion'), None))
    if not observations:
        return []
    features = extract_features(observations, attempt_ids=ids)
    params = config.as_dict()
    config_id = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
    audit = []
    for issue, feature in zip(issues, features):
        # Re-finalization may reapply the same configuration but cannot promote
        # an existing reference candidate into the default list.
        result = score_features(feature, config, was_reference=issue.is_reference)
        issue.confidence, issue.is_reference = result.confidence, result.is_reference
        issue.score_reason = f'{result.score_reason}; config={config_id}; finalized n={len(ids)}'
        audit.append({'issue_id': issue.id, 'features': feature.as_dict(),
                      'confidence': result.confidence, 'is_reference': result.is_reference})
    session.flush()
    LOGGER.info('issue_score_finalized %s', json.dumps({
        'run_id': run_id, 'feature_version': FEATURE_VERSION, 'config_id': config_id,
        'config': params, 'rows': audit}, ensure_ascii=False))
    return audit
