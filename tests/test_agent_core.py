"""Synthetic offline integration. SQLite progress shim does NOT validate PG locking."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from apps.api.db.models import AccessCode, Attempt, Base, LlmCall, Metric, Project, Run, Step, Task
from worker.agent import run as agent_run
from worker.agent.action_feedback import missing_fields, retry_message
from worker.agent.run import execute_run
from worker.agent.observation import state_hash
from worker.agent.termination import LoopGuard, representative
from worker.llm.fake import FakeAdapter
from worker.schemas import parse_action_json


@compiles(JSONB, 'sqlite')
def jsonb_sqlite(_type, _compiler, **kw):
    return 'JSON'


def progress(session, run_id, finished=False):
    session.flush()
    row = session.get(Run, run_id)
    for attempt in session.scalars(select(Attempt).where(Attempt.run_id==run_id)):
        attempt.steps_count = session.scalar(select(func.count()).select_from(Step).where(Step.attempt_id==attempt.id))
    if row.status != 'running':
        return False
    row.progress = 100 if finished else 20
    return True


def action(kind, **kwargs):
    return json.dumps(dict(action=kind, thought='Synthetic test', expectation='Expected test state', **kwargs))


class PureTests(unittest.TestCase):
    def test_state_and_loop_payload(self):
        self.assertEqual(state_hash('https://a/x?q=1',[{'name':'B'},{'name':'A'}]),
                         state_hash('https://a/x?q=2',[{'name':'A'},{'name':'B'}]))
        guard = LoopGuard()
        for n in range(3):
            item = json.loads(action('click',target=1)); item['thought']=str(n)
            self.assertEqual(guard.repeated('same', parse_action_json(json.dumps(item))), n==2)

    def test_missing_fields_names_only_required_fields_of_chosen_action(self):
        # Required fields per action come from worker/schemas.py (click: target, type: target+text, done: reason).
        self.assertEqual(missing_fields(action('click')), ('click', ('target',)))
        self.assertEqual(missing_fields(action('type')), ('type', ('target', 'text')))
        self.assertEqual(missing_fields(action('done')), ('done', ('reason',)))
        self.assertEqual(missing_fields(action('wait')), ('wait', ()))
        for payload in ('not json', '[1]', '{"thought":"x"}', '{"action":"explode"}', None):
            self.assertEqual(missing_fields(payload), (None, ()))

    def test_retry_message_without_names_keeps_previous_text(self):
        self.assertEqual(retry_message('invalid_fields', None, ()),
                         'The previous action was invalid (invalid_fields). Choose a valid action with every required field.')

    def test_representative(self):
        rows = [Attempt(id=1,index=2,success=True), Attempt(id=2,index=1,success=True),
                Attempt(id=3,index=3,success=False)]
        self.assertEqual(representative(rows,{1:1,2:3,3:2}),2)


class SyntheticIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = create_engine('sqlite:///'+self.tmp.name+'/test.db')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        with self.factory.begin() as s:
            code=AccessCode(code_hash='synthetic');s.add(code);s.flush()
            p=Project(owner_id=code.id,name='Synthetic',base_url='http://synthetic.test/');s.add(p);s.flush()
            t=Task(project_id=p.id,description='Click Next',success_condition={'text_present':'Complete'});s.add(t);s.flush()
            r=Run(task_id=t.id,viewport='desktop',mode='agent',repeat_n=1,model='claude-haiku-5-5');s.add(r);s.flush()
            self.run_id=r.id; self.task_id=t.id
        self.pw=await async_playwright().start()
        self.browser=await self.pw.chromium.launch(headless=True)
        async def route(route):
            await route.fulfill(content_type='text/html',body=self.html)
        # Route every created context so no external network is possible.
        original=self.browser.new_context
        async def context(**kwargs):
            ctx=await original(**kwargs);await ctx.route('**/*',route);return ctx
        self.ctxpatch=patch.object(self.browser,'new_context',context);self.ctxpatch.start()
        self.addCleanup(self.ctxpatch.stop)
        self.patches=[patch('worker.agent.persistence.update_progress',progress),
                      patch('worker.agent.run.update_progress',progress),
                      patch('worker.queue.runs.SCREENSHOT_DIR',Path(self.tmp.name)/'shots')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.html='<html lang="en"><title>Synthetic</title><body><main><button onclick="this.outerHTML=\'<p>Complete</p>\'">Next</button></main></body></html>'

    async def asyncTearDown(self):
        await self.browser.close(); await self.pw.stop()

    async def run_replies(self, replies):
        await execute_run(self.run_id,self.factory,browser=self.browser,
                          adapter_factory=lambda model: FakeAdapter(replies))

    async def test_success_persists_and_deduplicates_delivery(self):
        replies=[action('click',target=1),action('done',reason='goal_reached')]
        await self.run_replies(replies)
        await self.run_replies(replies) # Duplicate queue delivery is no-op.
        with self.factory() as s:
            r=s.get(Run,self.run_id);a=s.scalar(select(Attempt))
            self.assertEqual((r.status,r.progress,a.success,a.success_estimated,a.steps_count),('completed',100,True,False,2))
            self.assertEqual(r.representative_attempt_id,a.id)
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),2)
            self.assertEqual(s.scalar(select(Metric.value).where(Metric.attempt_id.is_(None),Metric.key=='step_count')),1)
            self.assertEqual(len(list(s.scalars(select(Step)))),2)
            self.assertTrue(all(Path(self.tmp.name,'shots',x.screenshot_key).is_file() for x in s.scalars(select(Step))))

    async def test_label_proxy_completes_agent_path_with_native_snapshot(self):
        from tests.test_collect_labels import HTML
        from apps.api.db.models import ElementSnapshot
        self.html = HTML + '<p id="result"></p><script>document.querySelector("input").addEventListener("change",()=>document.querySelector("#result").textContent="Complete")</script>'
        await self.run_replies([action('click', target=1), action('done', reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason, 'success', s.scalar(select(Attempt)).end_detail)
            step = s.scalar(select(Step).where(Step.idx == 0))
            self.assertEqual(step.effect_type, 'dom_mutation')
            snap = s.scalar(select(ElementSnapshot).where(ElementSnapshot.step_id == step.id))
            self.assertEqual((snap.data['tag'], snap.data['role'], snap.data['name']),
                             ('input', 'checkbox', 'Remember Me'))

    async def test_false_goal_has_no_success_median(self):
        await self.run_replies([action('done',reason='goal_reached')])
        with self.factory() as s:
            a=s.scalar(select(Attempt));self.assertEqual((a.end_reason,a.success),('gave_up',False))
            self.assertIsNone(s.get(Run,self.run_id).representative_attempt_id)
            self.assertEqual(list(s.scalars(select(Metric).where(Metric.attempt_id.is_(None)))),[])

    async def test_loop_and_unsafe_and_blocked(self):
        self.html='<html><title>Test</title><body><button>Next</button></body></html>'
        await self.run_replies([action('click',target=1)]*3)
        with self.factory() as s:
            a=s.scalar(select(Attempt));self.assertEqual((a.end_reason,a.steps_count),('loop',3))

    async def test_safety_driver_stops_before_click(self):
        self.html='<html><title>Test</title><body><button onclick="document.body.textContent=\'Complete\'">Pay now</button></body></html>'
        await self.run_replies([action('click',target=1)])
        with self.factory() as s:
            a=s.scalar(select(Attempt));self.assertEqual((a.end_reason,a.steps_count),('safety_stop',0))

    async def test_login_is_blocked_without_call(self):
        self.html='<html><body><input type="password"></body></html>'
        await self.run_replies([action('done',reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'blocked')
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),0)

    async def test_null_condition_is_estimated_and_repeat_adapters_reset(self):
        with self.factory.begin() as s:
            s.get(Task,self.task_id).success_condition=None
            s.get(Run,self.run_id).repeat_n=2
        await self.run_replies([action('done',reason='goal_reached')])
        with self.factory() as s:
            attempts=list(s.scalars(select(Attempt).order_by(Attempt.index)))
            self.assertEqual([(a.success,a.success_estimated,a.steps_count) for a in attempts],[(True,True,1)]*2)
            self.assertEqual(s.get(Run,self.run_id).representative_attempt_id,attempts[0].id)

    async def test_agent_mode_accepts_existing_base(self):
        with self.factory.begin() as s:
            base=Run(task_id=self.task_id,viewport='desktop',mode='agent',repeat_n=1,
                     model='claude-haiku-5-5',status='completed')
            s.add(base);s.flush();s.get(Run,self.run_id).base_run_id=base.id
        await self.run_replies([action('done',reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.get(Run,self.run_id).status,'completed')

    async def test_invalid_response_still_logs_call(self):
        await self.run_replies(['{"action":"explode"}'])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'error')
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),3)
            self.assertEqual(s.scalar(select(func.count()).select_from(Step)),0)

    async def test_missing_click_target_retries_without_executing_it(self):
        invalid=action('click')
        adapter=FakeAdapter([invalid,action('click',target=1),action('done',reason='goal_reached')])
        await execute_run(self.run_id,self.factory,browser=self.browser,
                          adapter_factory=lambda _:adapter)
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.success,a.steps_count),('success',True,2))
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),3)
            self.assertEqual(s.scalar(select(func.count()).select_from(Step)),2)
        self.assertEqual(json.loads(adapter.received[1].user_text)['invalid_action'],
                         'The previous action was invalid (invalid_fields): missing target for click. '
                         'Include every required field for the chosen action.')

    async def test_done_without_reason_three_times_names_field_not_reply(self):
        marker='UNIQUE-REPLY-TEXT-7f3a'
        reply=json.dumps(dict(action='done',thought=marker,expectation=marker,confusion=marker))
        await self.run_replies([reply])
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual(a.end_reason,'error')
            self.assertEqual(a.end_detail,'ActionInputError:invalid_fields:reason')
            self.assertNotIn(marker,a.end_detail)
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),3)

    # ADR 0010 #8 (2026-11-10): all attempts error -> failed; any other end -> completed.
    async def run_attempts(self, *scripts):
        with self.factory.begin() as s:
            s.get(Run,self.run_id).repeat_n=len(scripts)
        adapters=iter([FakeAdapter(script) for script in scripts])
        with patch('worker.agent.run.save_run_medians',wraps=agent_run.save_run_medians) as medians:
            await execute_run(self.run_id,self.factory,browser=self.browser,
                              adapter_factory=lambda _:next(adapters))
        self.assertEqual(medians.call_count,1)

    ERROR=['{"action":"explode"}']
    GAVE_UP=[action('fail')]
    SUCCESS=[action('click',target=1),action('done',reason='goal_reached')]

    async def test_all_error_attempts_fail_run(self):
        await self.run_attempts(self.ERROR,self.ERROR,self.ERROR)
        with self.factory() as s:
            r=s.get(Run,self.run_id)
            attempts=list(s.scalars(select(Attempt).order_by(Attempt.index)))
            self.assertEqual([a.end_reason for a in attempts],['error']*3)
            self.assertEqual(r.status,'failed')
            self.assertIsNotNone(r.finished_at)
            self.assertNotEqual(r.progress,100)
            per_attempt={m.attempt_id for m in s.scalars(select(Metric).where(Metric.key=='step_count'))}
            self.assertEqual(per_attempt,{a.id for a in attempts})
            self.assertEqual(list(s.scalars(select(Metric).where(Metric.attempt_id.is_(None)))),[])

    async def test_errors_with_one_gave_up_complete_without_success_median(self):
        await self.run_attempts(self.ERROR,self.ERROR,self.GAVE_UP)
        with self.factory() as s:
            r=s.get(Run,self.run_id)
            self.assertEqual([a.end_reason for a in s.scalars(select(Attempt).order_by(Attempt.index))],
                             ['error','error','gave_up'])
            self.assertEqual((r.status,r.progress),('completed',100))
            self.assertIsNone(r.representative_attempt_id)
            self.assertEqual(list(s.scalars(select(Metric).where(Metric.attempt_id.is_(None)))),[])

    async def test_one_error_two_successes_complete(self):
        await self.run_attempts(self.ERROR,self.SUCCESS,self.SUCCESS)
        with self.factory() as s:
            r=s.get(Run,self.run_id)
            attempts=list(s.scalars(select(Attempt).order_by(Attempt.index)))
            self.assertEqual([a.end_reason for a in attempts],['error','success','success'])
            self.assertEqual((r.status,r.progress),('completed',100))
            self.assertIn(r.representative_attempt_id,{attempts[1].id,attempts[2].id})
            self.assertNotEqual(list(s.scalars(select(Metric).where(Metric.attempt_id.is_(None)))),[])

    async def test_stale_target_reobserves_before_next_action(self):
        class RerenderAdapter(FakeAdapter):
            async def ask(inner, request):
                if not inner.received:
                    page=self.browser.contexts[0].pages[0]
                    await page.evaluate("const b=document.querySelector('button'); b.replaceWith(b.cloneNode(true))")
                return await super().ask(request)
        adapter=RerenderAdapter([action('click',target=1),action('click',target=1),
                                 action('done',reason='goal_reached')])
        await execute_run(self.run_id,self.factory,browser=self.browser,
                          adapter_factory=lambda _:adapter)
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.success,a.steps_count),('success',True,2))
            self.assertEqual([row.idx for row in s.scalars(select(Step).order_by(Step.idx))],[0,1])
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),3)

    async def test_cancel_during_model_call_never_executes_or_completes(self):
        class CancelAdapter:
            name='fake'
            async def ask(inner, request):
                with self.factory.begin() as s:
                    s.get(Run,self.run_id).status='canceled'
                return await FakeAdapter([action('click',target=1)]).ask(request)
        await execute_run(self.run_id,self.factory,browser=self.browser,
                          adapter_factory=lambda _:CancelAdapter())
        with self.factory() as s:
            self.assertEqual(s.get(Run,self.run_id).status,'canceled')
            self.assertEqual(s.scalar(select(func.count()).select_from(Step)),0)
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),1)

    async def test_select_populates_click_distance_and_step_fitts(self):
        self.html = '''<html lang="en"><title>Select</title><main><select aria-label="Choice" style="position:absolute;left:100px;top:100px;width:100px;height:40px" onchange="document.querySelector('p').textContent='Complete'"><option>A</option><option>B</option></select><p></p></main></html>'''
        await self.run_replies([action('select', target=1, option=2), action('done', reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason, 'success', s.scalar(select(Attempt)).end_detail)
            step = s.scalar(select(Step).where(Step.idx == 0))
            self.assertIsNotNone(step.fitts_id)
            metrics = {m.key: m.value for m in s.scalars(select(Metric).where(Metric.attempt_id.is_not(None)))}
            self.assertEqual(metrics['click_count'], 1)
            # Desktop center (640,400) -> select center (150,120).
            self.assertAlmostEqual(metrics['travel_distance'], (490**2 + 280**2)**0.5)
            self.assertEqual(metrics['fitts_id_sum'], step.fitts_id)

    async def test_r08_is_saved_once_from_two_of_three_attempts(self):
        from apps.api.db.models import Issue
        self.html = '<html lang="en"><title>Back</title><main><a href="/next">Next</a><p>Complete</p></main></html>'
        with self.factory.begin() as s:
            s.get(Run, self.run_id).repeat_n = 3
        replies = iter([
            [action('click', target=1), action('back'), action('done', reason='goal_reached')],
            [action('click', target=1), action('back'), action('done', reason='goal_reached')],
            [action('done', reason='goal_reached')],
        ])
        await execute_run(self.run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _: FakeAdapter(next(replies)))
        with self.factory() as s:
            issues = list(s.scalars(select(Issue).where(Issue.rule_id == 'R08')))
            self.assertEqual(len(issues), 1, [(a.end_reason, a.end_detail) for a in s.scalars(select(Attempt))])
            self.assertEqual((issues[0].measured, issues[0].threshold, issues[0].is_reference), (2, 2, True))
            self.assertIsNone(issues[0].step_id)
