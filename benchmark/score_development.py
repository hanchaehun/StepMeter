"""Offline scoring of captured evidence. Labels enter here, never the worker.

Restores inert DOMs without scripts/network and matches actual issue nodes against
reviewed selectors (equal to or contained in the labelled target). Unknown target
identity is reported and counted as unmatched, never silently ignored.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import Issue
from benchmark.eval import score
from benchmark.run_development import ROOT, load_cases
from ml.issue_clf.features import FEATURE_VERSION

RULES = {'R01','R02','R03','R04','R06','R10'}


async def score_case(page, db, case, location, run_id, *, calibration_rows=None):
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
        if not issue.is_reference:
            predictions['scored'].add(key)
    return truth,{k:[{'rule':r,'target':t} for r,t in sorted(v)] for k,v in predictions.items()},extra,unknown


async def evaluate(directory, database, *, calibration_output=None):
    summary=json.loads((directory/'summary.json').read_text(encoding='utf-8'))
    cases={r['app_id']+'/'+r['case_id']:r for r in load_cases()}
    truth,predictions={}, {'rules_only':{},'scored':{}}
    exclusions,extras,unresolved={},{},{}
    calibration = {}
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
                    t,p,e,u=await score_case(page,db,case,directory/case['app_id']/case['case_id'],result['run_id'],calibration_rows=rows)
                    if rows is not None:
                        calibration[key] = rows
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
    with (directory/'score.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    if calibration_output is not None:
        with calibration_output.open('x', encoding='utf-8') as f:
            json.dump({'split': 'development', 'feature_version': FEATURE_VERSION,
                       'review_status': 'approved', 'truth': truth, 'cases': calibration,
                       'excluded_cases': exclusions}, f, ensure_ascii=False, indent=2)
    return result


def main():
    import os
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path)
    p.add_argument('--calibration-output', type=Path)
    args=p.parse_args()
    print(json.dumps(asyncio.run(evaluate(args.directory,os.environ['DATABASE_URL'],calibration_output=args.calibration_output)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
