"""Compare frozen human page medians with verified agent literature KLM times.

No participant files, model calls, calibration or database writes. Missing predictions
remain pending, never zero. One run per model/page must be selected before comparison.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


def positive_seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('Expected positive finite seconds')
    return float(value)


def spearman(xs, ys):
    """Pearson correlation of average ranks; ties do not use the no-ties formula."""
    if len(xs) != len(ys):
        raise ValueError('Paired observations required')
    if len(xs) < 3:
        return None

    def ranks(values):
        ordered = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        start = 0
        while start < len(values):
            end = start + 1
            while end < len(values) and values[ordered[end]] == values[ordered[start]]:
                end += 1
            for i in ordered[start:end]:
                result[i] = (start + 1 + end) / 2
            start = end
        return result

    a, b = ranks(xs), ranks(ys)
    ma, mb = mean(a), mean(b)
    denominator = math.sqrt(sum((x-ma)**2 for x in a) * sum((y-mb)**2 for y in b))
    return sum((x-ma)*(y-mb) for x, y in zip(a, b))/denominator if denominator else None


def prediction(payload, tasks):
    """Accept only matching desktop tasks and uncalibrated verified agent attempts."""
    page = payload['page_id']
    if payload.get('version') != 1 or payload.get('viewport') != 'desktop':
        raise ValueError('Expected desktop timing export version 1')
    if page not in tasks or payload['task_description'] != tasks[page]:
        raise ValueError('Page/task mismatch')
    if not isinstance(payload.get('model'), str) or not payload['model']:
        raise ValueError('Model provenance required')
    seen, times, excluded, blocked = set(), [], defaultdict(int), False
    for row in payload['attempts']:
        if row['id'] in seen:
            raise ValueError('Duplicate attempt')
        seen.add(row['id'])
        if (row['kind'] != 'agent' or row['success'] is not True
                or row['success_estimated'] is not False or not row['end_reason']
                or row['verified_success'] is not True):
            excluded['not_verified_agent_success'] += 1
            # The DB run median includes worker successes. Do not silently replace
            # it with a different median when such a success cannot be verified.
            if row['kind'] == 'agent' and row['success'] is True:
                blocked = True
            continue
        metric = row.get('est_task_time')
        if metric is None:
            excluded['metric_missing'] += 1
            blocked = True
            continue
        if (metric.get('unit') != 's' or 'model_version_id' not in metric
                or metric['model_version_id'] is not None):
            raise ValueError('Only literature KLM seconds are comparable')
        times.append(positive_seconds(metric['value']))
    aggregate = payload.get('run_est_task_time')
    value = None
    if aggregate is not None:
        if (aggregate.get('unit') != 's' or 'model_version_id' not in aggregate
                or aggregate['model_version_id'] is not None):
            raise ValueError('Run aggregate must be literature KLM seconds')
        measured = positive_seconds(aggregate['value'])
        if times and not blocked:
            if not math.isclose(measured, median(times), rel_tol=1e-9):
                raise ValueError('Stored run median disagrees with verified agent attempts')
            value = measured
    return dict(page_id=page, model=payload['model'], run_id=payload['run_id'],
                prediction_seconds=value, run_median_unverifiable=blocked,
                successful_attempts=len(times), excluded_attempts=dict(excluded),
                build_manifest_sha256=payload.get('build_manifest_sha256'))


def compare(human_pages, exports, tasks):
    """Pair each procedure stratum separately, plus all; require >=3 human successes.

    Summaries originate from analyze.summarize. Both observed and adjusted metrics
    are reported. Zero/constant/insufficient data are explicit, not fabricated scores.
    """
    predictions, seen = {}, set()
    for payload in exports:
        item = prediction(payload, tasks)
        key = (item['page_id'], item['model'])
        if key in predictions:
            raise ValueError('Select one run per model/page before comparing')
        predictions[key] = item
    pairs, groups = [], defaultdict(list)
    models = sorted({model for page, model in predictions})
    for human in human_pages:
        page, procedure = human['page_id'], human['procedure_version']
        if page not in tasks:
            raise ValueError('Unknown human page')
        if (page, procedure) in seen:
            raise ValueError('Duplicate human page summary')
        seen.add((page, procedure))
        for model in models or [None]:
            pred = predictions.get((page, model))
            row = dict(page_id=page, procedure_version=procedure, model=model,
                       human_n=human['eligible_successes'], prediction=pred,
                       status='pending_agent_data')
            if human['eligible_successes'] < 3:
                row['status'] = 'insufficient_human_successes'
            elif pred and pred['prediction_seconds'] is not None:
                observed = positive_seconds(human['observed_median'])
                adjusted = positive_seconds(human['adjusted_median'])
                p = pred['prediction_seconds']
                row.update(status='paired', observed_seconds=observed, adjusted_seconds=adjusted,
                           observed_ape_percent=abs(p-observed)/observed*100,
                           adjusted_ape_percent=abs(p-adjusted)/adjusted*100)
                groups[(model, procedure)].append(row)
            pairs.append(row)
    scores = []
    for (model, procedure), rows in sorted(groups.items()):
        predicted = [r['prediction']['prediction_seconds'] for r in rows]
        score = dict(model=model, procedure_version=procedure, paired_pages=len(rows),
                     scope='paired_pages_only', missing_pages=len(tasks)-len(rows))
        for mode in ('observed', 'adjusted'):
            score[mode+'_mape_percent'] = mean(r[mode+'_ape_percent'] for r in rows)
            correlation = spearman([r[mode+'_seconds'] for r in rows], predicted)
            score[mode+'_spearman'] = correlation
            score[mode+'_spearman_status'] = ('available' if correlation is not None
                else 'fewer_than_three_pages_or_constant_ranks')
        scores.append(score)
    return dict(status='paired' if scores else 'pending_comparable_data', pairs=pairs, scores=scores,
                limitations=['Build identity must be checked against the private session notes.',
                              'No calibration, imputation, or pooling of model runs.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--human', type=Path, required=True)
    parser.add_argument('--timing', type=Path, action='append', default=[])
    parser.add_argument('--plan', type=Path, default=Path(__file__).resolve().parents[2]/'human-study/session_plan.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {p.resolve() for p in [args.human, args.plan, *args.timing]}:
        raise ValueError('Cannot overwrite an input')
    plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
    tasks = {row['page_id']: row['task_say'] for row in plan['pages']}
    human = json.loads(args.human.read_text(encoding='utf-8-sig'))
    exports = [json.loads(p.read_text(encoding='utf-8-sig')) for p in args.timing]
    result = compare(human['pages'], exports, tasks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
