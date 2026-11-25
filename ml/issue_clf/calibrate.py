"""Compare explicit heuristic configurations on approved development evidence.

Labels enter only this offline evaluator. It never reads holdout files, writes
the service config or claims that development selection is final evaluation.
"""
import argparse
import json
from pathlib import Path

from benchmark.eval import score
from ml.issue_clf.export import DEVELOPMENT_APPS
from ml.issue_clf.features import FEATURE_VERSION, Features
from ml.issue_clf.scoring import ScoreConfig, score_features

RULES = frozenset({'R01', 'R02', 'R03', 'R04', 'R06', 'R10'})


def compare(payload, configurations):
    if (payload.get('split') != 'development' or payload.get('review_status') != 'approved'
            or payload.get('feature_version') != FEATURE_VERSION):
        raise ValueError('Approved development evidence required')
    cases, truth = payload['cases'], payload['truth']
    if not cases or set(cases) != set(truth):
        raise ValueError('Measured and truth cases must match; include empty cases')
    if any(key.split('/')[0] not in DEVELOPMENT_APPS for key in cases):
        raise ValueError('Public development apps only')
    labels = {'split': 'development', 'review_status': 'approved', 'cases': truth}
    rules_only = {}
    for key, rows in cases.items():
        if any(row['rule'] not in RULES or not Features(**row['features']).on_path for row in rows):
            raise ValueError('Six scored path rules only')
        if any(row['rule'] not in RULES for row in truth[key]):
            raise ValueError('Non-scored truth rule')
        # The comparison baseline is the primary list before scoring; rule references are not in it.
        rules_only[key] = [{'rule': r['rule'], 'target': r['target']} for r in rows if not r['was_reference']]
    baseline = score(labels, {'split': 'development', 'cases': rules_only})
    results = []
    for config in configurations:
        predicted = {}
        for key, rows in cases.items():
            predicted[key] = [{'rule': r['rule'], 'target': r['target']} for r in rows
                if not score_features(Features(**r['features']), config,
                                      was_reference=r['was_reference']).is_reference]
        measured = score(labels, {'split': 'development', 'cases': predicted})
        before, after = baseline['micro']['precision'], measured['micro']['precision']
        delta = after-before if before is not None and after is not None else None
        results.append({'config': config.as_dict(), 'scores': measured,
                        'precision_delta': delta, 'target_met': delta is not None and delta >= .05})
    return {'scope': 'development comparison; selection requires reviewer judgment',
            'evaluated_cases': len(cases), 'excluded_cases': payload.get('excluded_cases', {}),
            'rules_only': baseline, 'configurations': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--configs', type=Path, required=True, help='JSON array of explicit ScoreConfig objects')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    configs = [ScoreConfig.from_dict(c) for c in json.loads(args.configs.read_text(encoding='utf-8'))]
    if not configs:
        raise ValueError('At least one configuration required')
    result = compare(payload, configs)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
