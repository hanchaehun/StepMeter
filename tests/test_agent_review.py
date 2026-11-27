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
   # #75 follow-up: the timeout detail names the running stage (model call = llm).
   self.assertEqual(attempt.end_detail,'TimeoutError@llm')
 async def test_page_csp_does_not_end_attempt(self):
  # #95: 측정 페이지의 CSP가 data: 이미지를 막아도 시도가 오류로 끝나면 안 된다
  self.path.write_text('<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src \'self\'"><title>CSP</title><button>Next</button><p>complete</p>')
  await self.run_replies([action('click',target=1),DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'success')
   self.assertIsNone(a.end_detail)
 async def test_unusable_type_target_is_fed_back_not_fatal(self):
  # 읽기 전용 칸에 입력하려 해도 시도를 끝내지 않고, 이유를 알려 다시 고르게 한다
  self.path.write_text('<!doctype html><input readonly aria-label="날짜" value="2026-11-27"><button onclick="document.querySelector(\'p\').textContent=\'complete\'">확인</button><p>ready</p>')
  adapter=FakeAdapter([action('type',target=1,text='2026-11-28'),action('click',target=2),DONE])
  await execute_run(self.run_id,self.factory,adapter_factory=lambda m:adapter,browser=self.browser)
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'success')
   self.assertEqual(s.scalar(select(func.count(Step.id)).where(Step.attempt_id==a.id)),2)
  asks=[r for r in adapter.received if r.purpose=='action']
  self.assertIn('invalid_action',json.loads(asks[1].user_text))
 async def test_unusable_target_retry_limit_still_ends_attempt(self):
  # 다시 고를 기회는 기존 다시 관찰 한도(3회)를 같이 쓴다. 한도를 넘으면 지금처럼 오류로 끝난다
  self.path.write_text('<!doctype html><input readonly aria-label="날짜" value="2026-11-27"><p>ready</p>')
  await self.run_replies([action('type',target=1,text='2026-11-28')])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'error')
   self.assertEqual(a.end_detail,'EffectObservationError')
 async def test_hidden_first_screen_waits_until_elements_show(self):
  # 로딩 중 페이지 전체를 숨기는 사이트: 요소가 보이면 그때 첫 화면을 기록한다(보이는 버튼에 R06 없음)
  self.path.write_text('<!doctype html><body style="opacity:0"><button onclick="document.querySelector(\'p\').textContent=\'complete\'">시작</button><p>ready</p><script>setTimeout(()=>{document.body.style.opacity=1},1200)</script></body>')
  await self.run_replies([action('click',target=1),DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'success')
   self.assertEqual(s.scalar(select(func.count(Issue.id)).where(Issue.run_id==self.run_id,Issue.rule_id=='R06')),0)
 async def test_mobile_run_uses_mobile_user_agent(self):
  # #96: 모바일 측정은 모바일 브라우저로 접속해야 UA로 화면을 나누는 사이트가 모바일 페이지를 준다
  self.path.write_text('<!doctype html><p id="ua">?</p><script>document.getElementById("ua").textContent=/Mobile/.test(navigator.userAgent)?"mobile-ua complete":"desktop-ua"</script>')
  with self.factory.begin() as s: s.get(Run,self.run_id).viewport='mobile'
  await self.run_replies([DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'success')
 async def test_visible_iframe_navigation_is_a_reaction(self):
  # 달력처럼 숨은 iframe에 새 문서를 띄워 보여 주면 보이는 화면 변화다(시도 오류가 아님)
  self.path.with_name('cal.html').write_text('<!doctype html><p>calendar 28</p>')
  self.path.write_text('<!doctype html><button onclick="var f=document.getElementById(\'cal\');f.src=\'cal.html\';f.style.display=\'block\'">날짜</button><iframe id="cal" src="about:blank" style="display:none;width:300px;height:200px"></iframe><p>complete</p>')
  await self.run_replies([action('click',target=1),DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'success')
   self.assertEqual(s.scalar(select(Step.effect_type).where(Step.attempt_id==a.id,Step.idx==0)),'dom_mutation')
 async def test_hidden_iframe_navigation_does_not_end_attempt(self):
  # 숨은 iframe이 새 문서를 불러오면 보이는 변화는 없지만, 성공한 네트워크 응답이 있으므로 ADR 0011 규칙대로 반응(dom_mutation)이다. 시도는 오류로 끝나지 않는다
  self.path.with_name('cal.html').write_text('<!doctype html><p>calendar 28</p>')
  self.path.write_text('<!doctype html><button onclick="document.getElementById(\'cal\').src=\'cal.html\'">날짜</button><iframe id="cal" src="about:blank" style="display:none"></iframe><p>complete</p>')
  await self.run_replies([action('click',target=1),DONE])
  with self.factory() as s:
   a=s.scalar(select(Attempt).where(Attempt.run_id==self.run_id))
   self.assertEqual(a.end_reason,'success')
   self.assertEqual(s.scalar(select(Step.effect_type).where(Step.attempt_id==a.id,Step.idx==0)),'dom_mutation')
if __name__=='__main__':unittest.main(verbosity=2)
