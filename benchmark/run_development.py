"""Run the 32 public development tasks against real PostgreSQL; no holdout access.

DATABASE_URL=... python -m benchmark.run_development --output benchmark/evidence/w3/run-01
--case app/case may be repeated. --preflight checks all prerequisites without model calls.
Model defaults to Haiku; repeat_n=3 uses the public API's minimum repetition.
"""
from __future__ import annotations

import argparse
import hashlib
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import AccessCode, Attempt, Issue, Project, Run, Step, Task
from benchmark.evidence_capture import EvidenceSink
from benchmark.serve import serve
from ml.issue_clf.export import build_dataset
from worker.agent.run import execute_run

ROOT = Path(__file__).resolve().parent


def load_cases():
    payload = json.loads((ROOT/'tasks.json').read_text(encoding='utf-8'))
    allowed = {'shadcn-admin','material-kit-react','sb-admin-2','react-shopping-cart'}
    rows = payload['cases']
    if payload['split'] != 'development' or any(r['app_id'] not in allowed for r in rows):
        raise ValueError('Public development tasks only')
    ids = [r['app_id']+'/'+r['case_id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate case')
    return rows


def build_root(case):
    app, variant = case['app_id'], case['variant']
    root = ROOT/'builds'/app/variant
    return root if app == 'sb-admin-2' else root/'dist'



def build_problem(case):
    root=ROOT/'builds'/case['app_id']/case['variant']
    try:
        manifest=json.loads((root/'stepmeter-build.json').read_text(encoding='utf-8'))
        apps=json.loads((ROOT/'apps.json').read_text(encoding='utf-8'))['apps']
        app=next(a for a in apps if a['id']==case['app_id'] and a['split']=='development')
        if (manifest['app'],manifest['variant'],manifest['revision'])!=(app['id'],case['variant'],app['revision']):
            return 'Build provenance mismatch'
        expected=[f"baselines/{app['id']}.patch"]
        if case['variant']!='baseline':expected.append(f"mutations/{app['id']}/{case['variant']}.patch")
        patches=[{'path':name,'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest()} for name in expected]
        if manifest['patches']!=patches:return 'Build patches changed; reproduce the pinned artifact'
        if not (build_root(case)/('login.html' if app['id']=='sb-admin-2' else 'index.html')).is_file():
            return 'Production entry missing'
    except (OSError,ValueError,KeyError,StopIteration):
        return 'Pinned production build missing or invalid'
    return None


def export_measurements(db, run_id, case, evidence):
    attempts = list(db.scalars(select(Attempt).where(Attempt.run_id == run_id, Attempt.end_reason.is_not(None))))
    steps = {s.id: s for s in db.scalars(select(Step).join(Attempt).where(Attempt.run_id == run_id))}
    index = {r['issue_id']: r for r in evidence}
    observations = []
    for issue in db.scalars(select(Issue).where(Issue.run_id == run_id)):
        record = index.get(issue.id)
        if not record or issue.step_id not in steps:
            continue
        st = steps[issue.step_id]
        count = sum(s.attempt_id == st.attempt_id and s.action['action'] not in ('done','fail') for s in steps.values())
        observations.append({'attempt_id': st.attempt_id,
            'target_key': record['screen']+'|'+record['selector'] if record['selector'] else None,
            'snapshot': record['snapshot'], 'step_index': st.idx, 'step_count': count,
            'confusion': record['confusion'], 'estimated': record['estimated'],
            'candidate': {key: getattr(issue,key) for key in ('rule_id','severity','measured','threshold','step_id','is_reference')}})
    return {'version':1, 'app_id':case['app_id'], 'case_id':case['case_id'], 'run_id':run_id,
            'attempts':[{'id':a.id,'kind':a.kind,'end_reason':a.end_reason} for a in attempts],
            'observations':observations}


async def run_case(case, factory, output, model):
    location = output/case['app_id']/case['case_id']
    sink = EvidenceSink(location/'dom', case.get('check'), case.get('milestones', []))
    root = build_root(case)
    with serve(root) as origin:
        with factory.begin() as db:
            # Disabled owner: benchmark data cannot be accessed with a guessed invitation code.
            import secrets
            owner = AccessCode(code_hash=secrets.token_hex(32), active=False, label='W3 isolated benchmark')
            db.add(owner);db.flush()
            project = Project(owner_id=owner.id,name='W3 '+case['app_id'],base_url=origin+case['path'])
            db.add(project);db.flush()
            task = Task(project_id=project.id, description=case['description'],success_condition=case['success_condition'])
            db.add(task);db.flush()
            run = Run(task_id=task.id,viewport='desktop',mode='agent',repeat_n=3,model=model)
            db.add(run);db.flush();run_id=run.id
        await execute_run(run_id, factory, evidence_sink=sink)
        with factory() as db:
            run = db.get(Run,run_id)
            data = export_measurements(db,run_id,case,sink.rows)
            (location/'provenance.json').write_text((ROOT/'builds'/case['app_id']/case['variant']/'stepmeter-build.json').read_text(encoding='utf-8'),encoding='utf-8')
            attempts = list(db.scalars(select(Attempt).where(Attempt.run_id==run_id)))
            summary = {'run_id':run_id,'status':run.status,'cost_usd':run.cost_usd,
                'attempts':[{'id':a.id,'end_reason':a.end_reason,'end_detail':a.end_detail,
                    'success':a.success,'success_estimated':a.success_estimated,
                    'verified_success':sink.completions.get(a.id) if case.get('check') else bool(a.success and not a.success_estimated)} for a in attempts]}
            summary['verified_success_count'] = sum(a['verified_success'] is True for a in summary['attempts'])
            (location/'measurement.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            (location/'features.json').write_text(json.dumps(build_dataset(data),ensure_ascii=False,indent=2),encoding='utf-8')
            (location/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
            return summary


async def main_async(args):
    rows = load_cases()
    if args.case:
        requested = set(args.case)
        known = {r['app_id']+'/'+r['case_id'] for r in rows}
        if requested-known:
            raise ValueError('Unknown development case')
        rows = [r for r in rows if r['app_id']+'/'+r['case_id'] in requested]
    args.output.mkdir(parents=True,exist_ok=False)
    database = os.environ.get('DATABASE_URL','')
    prerequisites = {'postgresql':database.startswith('postgresql+psycopg://'),
                     'model_key':bool(os.environ.get('ANTHROPIC_API_KEY')),
                     'real_model_mode':os.environ.get('STEPMETER_LLM','') not in ('fake',),
                     'collector':(ROOT.parent/'worker/collect/dist/collect.js').is_file(),
                     'axe':(ROOT.parent/'node_modules/axe-core/axe.min.js').is_file()}
    report = {'model':args.model,'repeat_n':3,'prerequisites':prerequisites,'cases':{}}
    for c in rows:
        report['cases'][c['app_id']+'/'+c['case_id']] = {'status':'pending' if build_problem(c) is None else 'unavailable',
            'reason':build_problem(c)}
    def save():
        (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    if args.preflight or not all(prerequisites.values()):
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if all(prerequisites.values()) and all(v['status']=='pending' for v in report['cases'].values()) else 2
    engine = create_engine(database)
    factory = sessionmaker(engine,expire_on_commit=False)
    try:
        for c in rows:
            key=c['app_id']+'/'+c['case_id']
            if report['cases'][key]['status']=='unavailable':
                continue
            try:
                report['cases'][key]=await run_case(c,factory,args.output,args.model)
            except Exception as error:
                report['cases'][key]={'status':'error','reason':type(error).__name__}
            save()
    finally:
        engine.dispose()
    return 0 if all(v['status']=='completed' for v in report['cases'].values()) else 2


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',action='append')
    p.add_argument('--preflight',action='store_true')
    p.add_argument('--model',choices=['claude-haiku-5-5','claude-sonnet-5-5'],default='claude-haiku-5-5')
    raise SystemExit(asyncio.run(main_async(p.parse_args())))


if __name__=='__main__':
    main()
