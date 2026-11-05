"""Score normalized development detections against reviewed, rendered labels.

Input contract is benchmark-local, not an API schema. Keys identify a case,
rule and stable target; duplicates count once. Missing cases are errors.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': precision, 'recall': recall,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def keys(rows: list) -> set:
    result = set()
    for row in rows:
        if set(row) != {'rule', 'target'} or not all(isinstance(v, str) and v for v in row.values()):
            raise ValueError('issues require nonempty rule and target strings')
        result.add((row['rule'], row['target']))
    return result


def score(labels: dict, predictions: dict) -> dict:
    if labels.get('split') != 'development' or predictions.get('split') != 'development':
        raise ValueError('public evaluator accepts development split only')
    if labels.get('review_status') != 'approved':
        raise ValueError('PM approval required before accuracy evaluation')
    truth, detected = labels['cases'], predictions['cases']
    if not truth or set(truth) != set(detected):
        raise ValueError('prediction cases must exactly match nonempty label cases (include empty lists)')
    expected, actual = set(), set()
    for case, rows in truth.items():
        expected.update((case, *key) for key in keys(rows))
        actual.update((case, *key) for key in keys(detected[case]))
    tp, fp, fn = expected & actual, actual - expected, expected - actual
    return {'micro': metrics(len(tp), len(fp), len(fn)), 'rules': {
        rule: metrics(sum(k[1] == rule for k in tp), sum(k[1] == rule for k in fp),
                      sum(k[1] == rule for k in fn))
        for rule in sorted({k[1] for k in expected | actual})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = score(json.loads(args.labels.read_text(encoding='utf-8')),
                   json.loads(args.predictions.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['micro']))


if __name__ == '__main__':
    main()
