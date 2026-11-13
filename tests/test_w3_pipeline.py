"""Independent contracts: 32 tasks, 10 version pairs, labelled ancestor matching."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import async_playwright
from unittest.mock import patch

from benchmark.evidence_capture import EvidenceSink
from benchmark.regression_versions import OVERLAY
from benchmark.run_development import load_cases
from benchmark.score_development import score_case
from infra.scripts.prepare_staging import configuration
from worker.collect.collector import observe, record_first_view, snapshot
from worker.schemas import parse_action_json


class ManifestTests(unittest.TestCase):
    def test_frozen_scope_and_human_inputs(self):
        rows=load_cases()
        self.assertEqual(len(rows),32)
        self.assertEqual(sum(r['case_id'].startswith('baseline') for r in rows),8)
        self.assertEqual(sum(not r['case_id'].startswith('baseline') for r in rows),24)
        self.assertEqual(len({r['app_id'] for r in rows}),4)
        for row in rows:
            if row['app_id']=='sb-admin-2':
                self.assertIn('Study1234',row['description'])
        recipes=json.loads(Path('benchmark/regression_cases.json').read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(recipes),10)
        self.assertEqual(len({r['id'] for r in recipes}),10)

    def test_proxy_precedes_spa_and_rejects_credentials(self):
        result=configuration('https://api.example.test')
        self.assertEqual(result['rewrites'][0],{'source':'/api/:path*','destination':'https://api.example.test/:path*'})
        for url in ('http://api.example.test','https://key:secret@api.example.test','https://api.example.test/path'):
            with self.assertRaises(ValueError):configuration(url)


class BrowserContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw=await async_playwright().start()
        self.browser=await self.pw.chromium.launch()
        self.page=await self.browser.new_page()
        self.tmp=tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        await self.browser.close();await self.pw.stop();self.tmp.cleanup()

    async def test_confirm_gate_adds_one_click_without_changing_original_handler(self):
        await self.page.set_content('<button id="save">Save</button><output id="count">0</output>')
        await self.page.evaluate("() => { document.querySelector('#save').onpointerdown=()=>document.querySelector('#count').textContent++; }")
        await self.page.evaluate(OVERLAY.replace('CONFIG',json.dumps({'kind':'regression','selector':'#save'}),1))
        await self.page.locator('#save').click()
        self.assertEqual(await self.page.locator('#count').inner_text(),'0')
        await self.page.get_by_role('button',name='Continue',exact=True).click()
        self.assertEqual(await self.page.locator('#count').inner_text(),'1')
        self.assertEqual(await self.page.locator('dialog').count(),0)

    async def test_immutable_pre_action_capture_and_actual_axe_descendant(self):
        await self.page.set_content('<main><script type="application/json">{}</script><button id="save"><span id="text">Save</span></button></main>')
        await record_first_view(self.page)
        elements=await observe(self.page)
        number=next(e['el_id'] for e in elements if e['name']=='Save')
        action=parse_action_json(json.dumps({'action':'click','target':number,'thought':'Save form','expectation':'Saved'}))
        sink=EvidenceSink(Path(self.tmp.name)/'dom')
        axe={'violations':[{'nodes':[{'target':['#text']}]}]}
        evidence=await sink.capture(self.page,action,axe,'https://example.test/form',1)
        snap=await snapshot(self.page,number)
        issues=[SimpleNamespace(id=1,rule_id='R02',explanation='Contrast 대상: ["#text"]')]
        sink.record(1,1,0,action,snap,issues,evidence)
        self.assertIsNone(sink.rows[0]['snapshot']) # descendant is not the action button
        await self.page.set_content('<p>Menu already closed</p>')
        location=Path(self.tmp.name)
        labels=location/'labels';labels.mkdir()
        (labels/'example.json').write_text(json.dumps({'review_status':'approved','cases':{'small':[{'rule':'R02','target':'main > button:nth-child(2)'}]}}))
        issue=SimpleNamespace(id=1,rule_id='R02',is_reference=False,step_id=1)
        db=SimpleNamespace(scalars=lambda _: [issue])
        with patch('benchmark.score_development.ROOT',location):
            truth,predictions,extra,unknown=await score_case(self.page,db,
                {'app_id':'example','label_case':'small'},location,1)
        self.assertEqual(predictions['scored'],truth)
        self.assertEqual(unknown,[])
        self.assertEqual(extra,[])


class WorkerExportIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_fake_worker_to_measurement_features_and_offline_score(self):
        """Synthetic API-independent pipeline; real Claude validation remains separate."""
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.compiler import compiles
        from apps.api.db.models import AccessCode, Attempt, Base, Project, Run, Task
        from benchmark.run_development import export_measurements
        from benchmark.serve import serve
        from ml.issue_clf.export import build_dataset
        from tests.test_agent_core import progress
        from worker.agent.run import execute_run
        from worker.llm.fake import FakeAdapter

        @compiles(JSONB, 'sqlite')
        def jsonb_sqlite(_type, _compiler, **kw):
            return 'JSON'

        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'index.html').write_text('''<main><button id="go" style="position:absolute;left:100px;top:100px;width:16px;height:16px;padding:0" onclick="document.querySelector('output').textContent='Finished'">Go</button>
            <a href="#" style="position:absolute;left:118px;top:100px;width:16px;height:16px">Help</a><output></output></main>''')
            engine=create_engine('sqlite:///'+str(root/'test.db'))
            Base.metadata.create_all(engine)
            factory=sessionmaker(engine,expire_on_commit=False)
            with serve(root) as origin:
                with factory.begin() as db:
                    owner=AccessCode(code_hash='synthetic',active=False);db.add(owner);db.flush()
                    project=Project(owner_id=owner.id,name='Synthetic',base_url=origin+'/index.html');db.add(project);db.flush()
                    task=Task(project_id=project.id,description='Click Go',success_condition={'text_present':'Finished'});db.add(task);db.flush()
                    run=Run(task_id=task.id,viewport='desktop',mode='agent',repeat_n=3,model='claude-haiku-5-5');db.add(run);db.flush();rid=run.id
                replies=[json.dumps({'action':'click','target':1,'thought':'Click Go','expectation':'Finished'}),
                         json.dumps({'action':'done','reason':'goal_reached','thought':'Finished','expectation':'Finished'})]
                sink=EvidenceSink(root/'dom')
                with patch('worker.agent.persistence.update_progress',progress), patch('worker.agent.run.update_progress',progress):
                    await execute_run(rid,factory,adapter_factory=lambda _:FakeAdapter(replies),evidence_sink=sink)
                with factory() as db:
                    self.assertEqual(db.get(Run,rid).status,'completed', [(a.end_reason,a.end_detail) for a in db.scalars(select(Attempt).where(Attempt.run_id==rid))])
                    self.assertEqual(len(list(db.scalars(select(Attempt).where(Attempt.run_id==rid,Attempt.success.is_(True))))),3)
                    measurement=export_measurements(db,rid,{'app_id':'sb-admin-2','case_id':'synthetic'},sink.rows)
                    features=build_dataset(measurement)
                    r01=[r for r in features['rows'] if r['rule_id']=='R01']
                    self.assertEqual(len(r01),3)
                    self.assertEqual([r['features']['detection_ratio'] for r in r01],[1,1,1])
                    self.assertNotIn('expected',json.dumps(measurement))
                    labels=root/'labels';labels.mkdir()
                    (labels/'sb-admin-2.json').write_text(json.dumps({'review_status':'approved','cases':{'synthetic':[{'rule':'R01','target':'#go'}]}}))
                    async with async_playwright() as pw:
                        browser=await pw.chromium.launch()
                        page=await browser.new_page(java_script_enabled=False)
                        with patch('benchmark.score_development.ROOT',root):
                            truth,predictions,_,unknown=await score_case(page,db,{'app_id':'sb-admin-2','label_case':'synthetic'},root,rid)
                        self.assertEqual(predictions['scored'],truth)
                        self.assertEqual(unknown,[])
                        await browser.close()
            engine.dispose()
