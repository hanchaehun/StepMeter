"""Offline scoring of captured evidence. Labels enter here, never the worker.

Restores inert DOMs without scripts/network and matches actual issue nodes against
reviewed selectors (equal to or contained in the labelled target). Unknown target
identity is reported and counted as unmatched, never silently ignored.

--breakdown-output <file.json> also writes a rules_only breakdown (JSON + same rows as
CSV) for rule owners. On an already scored folder score.json is left untouched; the
recomputed scores must equal it.
"""
import argparse
import asyncio
import csv
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import Attempt, Issue, Step
from benchmark.eval import score
from benchmark.run_development import ROOT, load_cases
from ml.issue_clf.features import FEATURE_VERSION

RULES = {'R01','R02','R03','R04','R06','R10'}
SEVERITIES = ('high', 'medium', 'low')
OUTCOMES = ('FP', 'TP', 'FN')
ROW_FIELDS = ('app', 'case', 'baseline', 'rule', 'outcome', 'severity', 'mixed_severity', 'target', 'element',
              'measured', 'threshold', 'issues', 'attempts', 'end_reasons', 'end_reason_class',
              'element_cases', 'element_baseline_cases', 'element_variant_cases')
DEFINITIONS = {
    'unit': '채점 규약 v1 단위 (케이스, 규칙, 일치 키 target). rules_only(step이 있는 경로 이슈)만 센다.',
    'severity': '한 단위의 심각도는 그 단위를 만든 이슈 중 가장 높은 것(high>medium>low). FN은 이슈가 없어 none.',
    'element': ('같은 요소는 (앱, 규칙, 결과 TP/FP/FN, element)가 같은 단위들이다. element는 target에서 '
                '실행 서버 주소(scheme://host:port)를 뺀 값이다. 케이스마다 서버 포트가 달라서다. '
                '케이스 이름이 baseline으로 시작하면 정상판.'),
    'end_reason': '단위를 만든 이슈의 step → attempt 종료 사유. success가 아니면 실패 시도다.',
}


def element_key(target):
    """Match key without the benchmark server origin; every case is served on its own port."""
    screen, separator, selector = target.partition('|')
    parts = urlsplit(screen)
    if not separator or not (parts.scheme and parts.netloc):
        return target
    return screen[len(parts.scheme) + 3 + len(parts.netloc):] + separator + selector


def breakdown(truth, issues):
    """rules_only scoring split by severity, repeated element and attempt end reason.

    truth: {'app/case': [{'rule', 'target'}]} as scored. issues: {'app/case': [{'rule', 'target'
    (matched key), 'severity', 'measured', 'threshold', 'attempt_id', 'end_reason'}]} for issues
    with a step. TP/FP/FN sets are those of benchmark.eval.score (convention v1).
    """
    expected = {(case, row['rule'], row['target']) for case, rows in truth.items() for row in rows}
    found = {}
    for case, rows in issues.items():
        for issue in rows:
            if issue['rule'] in RULES:
                found.setdefault((case, issue['rule'], issue['target']), []).append(issue)
    rows = []
    for case, rule, target in expected | set(found):
        hits = found.get((case, rule, target), [])
        outcome = ('TP' if (case, rule, target) in expected else 'FP') if hits else 'FN'
        severities = {h['severity'] for h in hits}
        reasons = sorted({h['end_reason'] or 'none' for h in hits})
        app, case_id = case.split('/', 1)
        rows.append({'app': app, 'case': case_id, 'baseline': case_id.startswith('baseline'),
            'rule': rule, 'outcome': outcome,
            'severity': next((s for s in SEVERITIES if s in severities), 'none'),
            'mixed_severity': len(severities) > 1, 'target': target, 'element': element_key(target),
            'measured': sorted({h['measured'] for h in hits if h['measured'] is not None}),
            'threshold': sorted({h['threshold'] for h in hits if h['threshold'] is not None}),
            'issues': len(hits), 'attempts': len({h['attempt_id'] for h in hits}),
            'end_reasons': reasons,
            'end_reason_class': None if not hits else 'failure_only' if 'success' not in reasons
                else 'success_only' if reasons == ['success'] else 'both'})
    elements = {}
    for row in rows:
        elements.setdefault((row['app'], row['rule'], row['outcome'], row['element']), []).append(row)
    for group in elements.values():
        baseline = sum(r['baseline'] for r in group)
        for row in group:
            row.update(element_cases=len(group), element_baseline_cases=baseline,
                       element_variant_cases=len(group) - baseline)
    rows.sort(key=lambda r: (OUTCOMES.index(r['outcome']), r['rule'], r['app'], r['element'], r['case']))
    rules = sorted(RULES | {r['rule'] for r in rows})
    result = {'mode': 'rules_only', 'definitions': DEFINITIONS, 'totals': {}, 'severity': {},
              'mixed_severity': {}, 'elements': {}, 'fp_end_reasons': {}}
    for rule in rules:
        mine = [r for r in rows if r['rule'] == rule]
        result['totals'][rule] = {o.lower(): sum(r['outcome'] == o for r in mine) for o in ('TP', 'FP', 'FN')}
        result['severity'][rule] = {o: {s: sum(r['outcome'] == o and r['severity'] == s for r in mine)
                                        for s in (*SEVERITIES, 'none')} for o in ('TP', 'FP', 'FN')}
        result['mixed_severity'][rule] = {o: sum(r['outcome'] == o and r['mixed_severity'] for r in mine)
                                          for o in ('TP', 'FP')}
        result['elements'][rule] = {}
        for outcome in ('TP', 'FP', 'FN'):
            groups = [g for (_, r, o, _), g in elements.items() if r == rule and o == outcome]
            spread = {}
            for group in groups:
                spread[str(len(group))] = spread.get(str(len(group)), 0) + 1
            result['elements'][rule][outcome] = {'elements': len(groups),
                'occurrences': sum(len(g) for g in groups),
                'cases_per_element': dict(sorted(spread.items(), key=lambda item: int(item[0]))),
                'baseline_only': sum(all(r['baseline'] for r in g) for g in groups),
                'variant_only': sum(not any(r['baseline'] for r in g) for g in groups),
                'baseline_and_variant': sum(any(r['baseline'] for r in g) and not all(r['baseline'] for r in g)
                                            for g in groups)}
        fps = [r for r in mine if r['outcome'] == 'FP']
        by_reason = {}
        for row in fps:
            for reason in row['end_reasons']:
                by_reason[reason] = by_reason.get(reason, 0) + 1
        result['fp_end_reasons'][rule] = {
            **{c: sum(r['end_reason_class'] == c for r in fps) for c in ('success_only', 'failure_only', 'both')},
            'by_end_reason': dict(sorted(by_reason.items()))}
    result['rows'] = rows
    return result


def write_breakdown(data, path, *, run):
    """JSON plus a CSV of the same rows (utf-8-sig for spreadsheet apps). Never overwrites."""
    targets = (path, path.with_suffix('.csv'))
    if path.suffix.lower() != '.json':
        raise ValueError('Breakdown output must be a .json file')
    if any(p.exists() for p in targets):
        raise FileExistsError('Breakdown output already exists')
    with targets[0].open('x', encoding='utf-8') as f:
        json.dump({'run': run, **data}, f, ensure_ascii=False, indent=2)
    with targets[1].open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=('run', *ROW_FIELDS))
        writer.writeheader()
        for row in data['rows']:
            writer.writerow({'run': run, **{k: ';'.join(map(str, v)) if isinstance(v, list) else v
                                            for k, v in row.items()}})
    return targets


def step_attempts(db, run_id):
    """step id -> (attempt id, attempt end reason) for one run."""
    rows = db.execute(select(Step.id, Attempt.id, Attempt.end_reason)
                      .join(Attempt, Step.attempt_id == Attempt.id).where(Attempt.run_id == run_id))
    return {step: (attempt, reason) for step, attempt, reason in rows}


async def score_case(page, db, case, location, run_id, *, calibration_rows=None, issue_rows=None):
    labels=json.loads((ROOT/'labels'/f"{case['app_id']}.json").read_text(encoding='utf-8'))
    if labels['review_status']!='approved':
        raise ValueError('PM approval required')
    truth=labels['cases'][case['label_case']]
    capture_file=location/'dom/index.json'
    records=json.loads(capture_file.read_text(encoding='utf-8')) if capture_file.exists() else []
    by_issue={r['issue_id']:r for r in records}
    features = {}
    if calibration_rows is not None:
        payload = json.loads((location/'features.json').read_text(encoding='utf-8'))
        if (payload['feature_version'] != FEATURE_VERSION or payload['run_id'] != run_id
                or payload['app_id'] != case['app_id'] or payload['case_id'] != case['case_id']):
            raise ValueError('Feature provenance mismatch')
        features = {(r['step_id'], r['rule_id'], r['target_key']): r['features'] for r in payload['rows']}
    predictions={'rules_only':set(),'scored':set()}
    extra,unknown=[],[]
    for issue in db.scalars(select(Issue).where(Issue.run_id==run_id)):
        if issue.rule_id not in RULES:
            extra.append({'rule':issue.rule_id,'issue_id':issue.id});continue
        record=by_issue.get(issue.id)
        matched=None
        if record and record['target_id'] is not None:
            await page.set_content((location/'dom'/record['dom']).read_text(encoding='utf-8'))
            for expected in truth:
                if expected['rule']!=issue.rule_id:
                    continue
                fits=await page.evaluate('''({sel,id})=>{
                    const actual=document.querySelector('[data-stepmeter-evidence-id="'+id+'"]');
                    return actual && [...document.querySelectorAll(sel)].some(n=>n===actual || n.contains(actual));
                }''',{'sel':expected['target'],'id':record['target_id']})
                if fits:
                    matched=expected['target'];break
        if matched is None:
            matched=(record['screen']+'|'+record['selector']) if record and record['selector'] else 'unresolved:'+str(issue.id)
            if not record or record['target_id'] is None:
                unknown.append(issue.id)
        key=(issue.rule_id,matched)
        if calibration_rows is not None and issue.step_id is not None:
            identity = record['screen']+'|'+record['selector'] if record and record['selector'] else None
            feature = features.get((issue.step_id, issue.rule_id, identity))
            if feature is None:
                raise ValueError('Missing measured features; cannot calibrate an unresolved finding')
            # These six path rules are primary candidates before scoring.
            calibration_rows.append({'rule': issue.rule_id, 'target': matched,
                                     'features': feature, 'was_reference': False})
        if issue.step_id is not None:
            predictions['rules_only'].add(key)
            if issue_rows is not None:
                issue_rows.append({'issue_id': issue.id, 'rule': issue.rule_id, 'target': matched,
                                   'step_id': issue.step_id, 'severity': issue.severity,
                                   'measured': issue.measured, 'threshold': issue.threshold})
        if not issue.is_reference:
            predictions['scored'].add(key)
    return truth,{k:[{'rule':r,'target':t} for r,t in sorted(v)] for k,v in predictions.items()},extra,unknown


async def evaluate(directory, database, *, calibration_output=None, breakdown_output=None):
    summary=json.loads((directory/'summary.json').read_text(encoding='utf-8'))
    cases={r['app_id']+'/'+r['case_id']:r for r in load_cases()}
    truth,predictions={}, {'rules_only':{},'scored':{}}
    exclusions,extras,unresolved={},{},{}
    calibration = {}
    issue_rows = {}
    previous = None
    if breakdown_output is not None:
        # Fail before browser work; an existing score.json is compared, never rewritten.
        if breakdown_output.suffix.lower() != '.json':
            raise ValueError('Breakdown output must be a .json file')
        if breakdown_output.exists() or breakdown_output.with_suffix('.csv').exists():
            raise FileExistsError('Breakdown output already exists')
        if (directory/'score.json').exists():
            previous = json.loads((directory/'score.json').read_text(encoding='utf-8'))
    engine=create_engine(database)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            context=await browser.new_context(java_script_enabled=False)
            await context.route('**/*',lambda route:route.abort())
            page=await context.new_page()
            with sessionmaker(engine)() as db:
                for key,result in summary['cases'].items():
                    if result.get('status')!='completed' or not result.get('run_id'):
                        exclusions[key]=result;continue
                    case=cases[key]
                    rows = [] if calibration_output is not None else None
                    found = [] if breakdown_output is not None else None
                    t,p,e,u=await score_case(page,db,case,directory/case['app_id']/case['case_id'],result['run_id'],
                                             calibration_rows=rows,issue_rows=found)
                    if rows is not None:
                        calibration[key] = rows
                    if found is not None:
                        ends = step_attempts(db, result['run_id'])
                        for row in found:
                            row['attempt_id'], row['end_reason'] = ends[row['step_id']]
                        issue_rows[key] = found
                    truth[key]=t;extras[key]=e;unresolved[key]=u
                    for mode in predictions:predictions[mode][key]=p[mode]
            await browser.close()
    finally:engine.dispose()
    result={'evaluated_cases':len(truth),'excluded_cases':exclusions,'other_rules':extras,'unresolved_issue_ids':unresolved}
    if truth:
        labels={'split':'development','review_status':'approved','cases':truth}
        result['scores']={k:score(labels,{'split':'development','cases':v}) for k,v in predictions.items()}
        result['predictions']=predictions
    else:result['scores']=None
    baseline=[v for k,v in summary['cases'].items() if k.split('/')[1].startswith('baseline')]
    result['baseline_completion']={'scheduled_attempts':len(baseline)*summary['repeat_n'],
        'verified_successes':sum(v.get('verified_success_count',0) for v in baseline),
        'unavailable_cases':sum(v.get('status')!='completed' for v in baseline)}
    if previous is None:
        with (directory/'score.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    elif json.loads(json.dumps({k: result.get(k) for k in ('scores','predictions')})) != {
            k: previous.get(k) for k in ('scores','predictions')}:
        raise ValueError('Recomputed scores differ from existing score.json')
    if calibration_output is not None:
        with calibration_output.open('x', encoding='utf-8') as f:
            json.dump({'split': 'development', 'feature_version': FEATURE_VERSION,
                       'review_status': 'approved', 'truth': truth, 'cases': calibration,
                       'excluded_cases': exclusions}, f, ensure_ascii=False, indent=2)
    if breakdown_output is not None:
        data = breakdown(truth, issue_rows)
        scored = result['scores']['rules_only']['rules'] if result['scores'] else {}
        for rule, totals in data['totals'].items():
            if totals != {k: scored.get(rule, {}).get(k, 0) for k in ('tp', 'fp', 'fn')}:
                raise ValueError('Breakdown totals differ from rules_only scores')
        write_breakdown(data, breakdown_output, run=directory.name)
    return result


def main():
    import os
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    p.add_argument('--calibration-output', type=Path)
    p.add_argument('--breakdown-output', type=Path,
                   help='rules_only breakdown JSON; a CSV of the same rows is written next to it')
    args=p.parse_args()
    print(json.dumps(asyncio.run(evaluate(args.directory,os.environ['DATABASE_URL'],calibration_output=args.calibration_output,
                                          breakdown_output=args.breakdown_output)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
