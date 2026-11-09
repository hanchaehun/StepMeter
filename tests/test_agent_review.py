"""Independent synthetic browser review; SQLite shim does not verify PostgreSQL locks."""
import asyncio, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from playwright.async_api import async_playwright
from apps.api.db.models import Base, AccessCode, Project, Task, Run, Attempt, Step, Metric, LlmCall, Issue, ElementSnapshot
from worker.agent.run import execute_run
from worker.agent.loop import execute_attempt
from worker.llm.fake import FakeAdapter
from worker.llm.base import LLMResult
from worker.queue import runs
@compiles(JSONB, 'sqlite')
def compile_jsonb(_type, _compiler, **kw): return 'JSON'
def progress(session, run_id, finished=False):
 session.flush()
 for a in session.scalars(select(Attempt).where(Attempt.run_id==run_id)):
  a.steps_count=session.scalar(select(func.count(Step.id)).where(Step.attempt_id==a.id))
 run=session.get(Run,run_id)
 if run.status!='running': return False
 if finished: run.progress=100
 return True
def action(name, **kw): return json.dumps(dict(action=name, thought='synthetic', expectation='synthetic', **kw))
DONE=action('done', reason='goal_reached')
class AgentReviewTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.engine=create_engine('sqlite://'); self.addCleanup(self.engine.dispose)
  Base.metadata.create_all(self.engine); self.factory=sessionmaker(self.engine,expire_on_commit=False)
  self.pw=await async_playwright().start(); self.browser=await self.pw.chromium.launch(headless=True)
  self.patches=[patch('worker.agent.persistence.update_progress',progress),patch('worker.agent.run.update_progress',progress),patch.object(runs,'SCREENSHOT_DIR',Path(self.tmp.name)/'shots')]
  for p in self.patches: p.start(); self.addCleanup(p.stop)
  self.path=Path(self.tmp.name)/'test.html'; self.path.write_text('<!doctype html><title>Synthetic</title><button>Save</button><button>Save</button><p>complete</p>')
  with self.factory.begin() as s:
   c=AccessCode(code_hash='synthetic'); s.add(c); s.flush(); p=Project(owner_id=c.id,name='synthetic',base_url=self.path.as_uri()); s.add(p); s.flush(); t=Task(project_id=p.id,description='synthetic',success_condition={'text_present':'complete'}); s.add(t);s.flush(); r=Run(task_id=t.id,mode='agent',viewport='desktop',repeat_n=1,model='fake',status='queued');s.add(r);s.flush();self.run_id=r.id;self.task_id=t.id
 async def asyncTearDown(self):
  await self.browser.close();await self.pw.stop()
 async def run_replies(self,replies):
  await execute_run(self.run_id,self.factory,adapter_factory=lambda m:FakeAdapter(replies),browser=self.browser)
 def get_metric(self,key):
  with self.factory() as s: return s.scalar(select(Metric.value).where(Metric.run_id==self.run_id,Metric.attempt_id.is_(None),Metric.key==key))
 async def test_explicit_agent_accepts_previous_base_and_repeated_invocation_is_idempotent(self):
  with self.factory.begin() as s:
   base=Run(task_id=self.task_id,mode='agent',viewport='desktop',repeat_n=1,model='fake',status='completed');s.add(base);s.flush();s.get(Run,self.run_id).base_run_id=base.id
  await self.run_replies([DONE]);await self.run_replies([DONE])
  with self.factory() as s:
   self.assertEqual(s.get(Run,self.run_id).status,'completed');self.assertEqual(s.scalar(select(func.count(Attempt.id)).where(Attempt.run_id==self.run_id)),1)
 async def test_duplicate_labeled_nodes_are_not_repeated_clicks(self):
  await self.run_replies([action('click',target=1),action('click',target=2),DONE])
  self.assertEqual(self.get_metric('repeated_click_count'),0)
 async def test_success_verifies_both_conditions(self):
  with self.factory.begin() as s:s.get(Task,self.task_id).success_condition={'text_present':'complete','url_contains':'missing'}
  await self.run_replies([DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id));self.assertFalse(a.success);self.assertEqual(a.end_reason,'gave_up');self.assertIsNone(s.get(Run,self.run_id).representative_attempt_id)
  self.assertIsNone(self.get_metric('step_count'))
 async def test_cancel_during_call_preserves_cost_not_steps(self):
  factory=self.factory;run_id=self.run_id
  class CancelAdapter:
   async def ask(self,request):
    with factory.begin() as s:s.get(Run,run_id).status='canceled'
    return LLMResult(text=DONE,model='fake',input_tokens=10,output_tokens=10,cost_usd=.25,latency_ms=1)
  await execute_run(run_id,factory,adapter_factory=lambda m:CancelAdapter(),browser=self.browser)
  with factory() as s:
   self.assertEqual(s.get(Run,run_id).status,'canceled');self.assertEqual(s.get(Run,run_id).cost_usd,.25);self.assertEqual(s.scalar(select(func.count(LlmCall.id))),1);self.assertEqual(s.scalar(select(func.count(Step.id))),0)
 async def test_driver_safety_guard_blocks_before_side_effect(self):
  self.path.write_text('<!doctype html><button onclick="document.body.dataset.executed=1">Pay now</button>')
  await self.run_replies([action('click',target=1),DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id));self.assertEqual(a.end_reason,'safety_stop');self.assertEqual(s.scalar(select(func.count(Step.id))),0)
 async def test_timeout_is_finished_budget_exceeded(self):
  with self.factory.begin() as s:
   s.get(Run,self.run_id).status='running';a=Attempt(run_id=self.run_id,index=1,kind='agent');s.add(a);s.flush();aid=a.id
  class SlowAdapter:
   async def ask(self,r):await asyncio.sleep(2);return LLMResult(DONE,'fake',0,0,0,0)
  page=await self.browser.new_page()
  await execute_attempt(page,self.factory,dict(id=self.run_id,base_url=self.path.as_uri(),description='synthetic',viewport='desktop',success_condition=None),aid,SlowAdapter(),axe_path=Path('node_modules/axe-core/axe.min.js'),max_seconds=1)
  with self.factory() as s:self.assertEqual(s.get(Attempt,aid).end_reason,'budget_exceeded')
 async def test_same_url_reload_is_error_not_fabricated_success(self):
  self.path.write_text('<!doctype html><button onclick="location.reload()">Reload</button><div style="height:1000px"></div><button>Below</button><p>complete</p>')
  await self.run_replies([action('click',target=1),action('scroll',direction='down'),action('click',target=1),DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'error')
   self.assertEqual(a.end_detail,'EffectObservationError')
   self.assertEqual(s.scalar(select(func.count(Step.id))),0)
   self.assertIsNone(s.get(Run,self.run_id).representative_attempt_id)
 async def test_accessible_payment_name_cannot_bypass_guard(self):
  from worker.agent.safety import guard_target, SafetyStop
  p=await self.browser.new_page()
  await p.set_content('<span id="label">Pay now</span><button aria-labelledby="label">$</button>')
  h=await p.query_selector('button')
  with self.assertRaises(SafetyStop): await guard_target(h,'click')
 async def test_occluded_action_persists_snapshot_without_r03_duplicate(self):
  self.path.write_text('<!doctype html><button style="width:120px;height:60px" onclick="this.remove()">Continue</button><div style="position:fixed;left:0;top:0;width:150px;height:80px;background:#fff8"></div><p>complete</p>')
  await self.run_replies([action('click',target=1),DONE])
  with self.factory() as s:
   step=s.scalar(select(Step).where(Step.idx==0))
   snapshot=s.scalar(select(ElementSnapshot).where(ElementSnapshot.step_id==step.id))
   self.assertEqual(step.effect_type,'no_change')
   self.assertFalse(step.changed)
   self.assertTrue(snapshot.occluded)
   self.assertTrue(snapshot.data['occluded'])
   rules=list(s.scalars(select(Issue.rule_id).where(Issue.step_id==step.id)))
   self.assertIn('R04',rules)
   self.assertNotIn('R03',rules)
   self.assertTrue(Path(self.tmp.name,'shots',step.screenshot_key).read_bytes().startswith(b'\xff\xd8\xff'))
 async def test_inner_timeout_is_error_not_attempt_budget(self):
  class TimeoutAdapter:
   async def ask(self,request):
    raise TimeoutError('synthetic model request timeout')
  await execute_run(self.run_id,self.factory,adapter_factory=lambda _:TimeoutAdapter(),browser=self.browser)
  with self.factory() as s:
   attempt=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(attempt.end_reason,'error')
   self.assertEqual(attempt.end_detail,'TimeoutError')
if __name__=='__main__':unittest.main(verbosity=2)
