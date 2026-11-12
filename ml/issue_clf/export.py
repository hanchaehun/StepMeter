"""Read-only feature export from measurement evidence supplied by the evaluator.

Input is a measurement-only JSON export, never benchmark labels/predictions.
See README for the adapter contract and missing-value semantics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ml.issue_clf.features import FEATURE_VERSION, Observation, extract_features
from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot

END_REASONS = frozenset({'success', 'gave_up', 'loop', 'budget_exceeded', 'blocked', 'error', 'safety_stop'})
DEVELOPMENT_APPS = frozenset({'shadcn-admin', 'material-kit-react', 'sb-admin-2', 'react-shopping-cart'})


def build_dataset(payload: dict) -> dict:
    """A single run, preserving app/case grouping for W4 app-level folds."""
    allowed = {'version', 'app_id', 'case_id', 'run_id', 'attempts', 'observations'}
    if set(payload) != allowed or payload['version'] != 1:
        raise ValueError('Expected version 1 measurement export fields only')
    if payload['app_id'] not in DEVELOPMENT_APPS:
        raise ValueError('W3 feature preparation accepts development apps only')
    if type(payload['run_id']) is not int or payload['run_id'] <= 0:
        raise ValueError('Positive run ID required')
    if not isinstance(payload['case_id'], str) or not payload['case_id'].strip():
        raise ValueError('Case ID required')
    attempts = payload['attempts']
    if any(set(a) != {'id', 'kind', 'end_reason'} or a['kind'] not in ('agent', 'replay')
           or a['end_reason'] not in END_REASONS
           or type(a['id']) is not int or a['id'] <= 0 for a in attempts):
        raise ValueError('Only completed, identified attempts are accepted')
    if len({a['id'] for a in attempts}) != len(attempts):
        raise ValueError('Duplicate attempt ID')
    eligible = [a['id'] for a in attempts if a['kind'] == 'agent']
    observations = []
    for item in payload['observations']:
        # Whitelist context: no labels, expected selectors, model output, task
        # input values or post-score confidence may enter this feature vector.
        if set(item) - {'candidate', 'attempt_id', 'target_key', 'snapshot',
                        'step_index', 'step_count', 'confusion', 'estimated'}:
            raise ValueError('Unknown observation fields')
        raw = dict(item)
        c = raw.pop('candidate')
        if set(c) - {'rule_id', 'severity', 'measured', 'threshold', 'is_reference', 'step_id', 'element_key'}:
            raise ValueError('Expected measurement candidate fields only')
        candidate = Candidate(explanation='', **c)
        snapshot = raw.pop('snapshot', None)
        observations.append(Observation(candidate=candidate,
            snapshot=ElementSnapshot.model_validate(snapshot) if snapshot else None, **raw))
    features = extract_features(observations, attempt_ids=eligible)
    metadata = {k: payload[k] for k in ('app_id', 'case_id', 'run_id')}
    return {
        'feature_version': FEATURE_VERSION,
        **metadata,
        'rows': [{'attempt_id': obs.attempt_id, 'rule_id': obs.candidate.rule_id,
                  'target_key': obs.target_key, 'step_id': obs.candidate.step_id,
                  'features': row.as_dict()} for obs, row in zip(observations, features)],
        # Failure analysis deliberately omits end_detail/thought/input text.
        'failed_attempts': [{'attempt_id': a['id'], 'end_reason': a['end_reason']}
                            for a in attempts if a['kind'] == 'agent' and a['end_reason'] != 'success'],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    result = build_dataset(payload)
    # All validation happens before output is touched. Never overwrite evidence.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
