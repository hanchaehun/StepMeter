"""Synthetic offline integration. SQLite progress shim does NOT validate PG locking."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from apps.api.db.models import AccessCode, Attempt, Base, LlmCall, Metric, Project, Run, Step, Task
from worker.agent import run as agent_run
from worker.agent.action_feedback import missing_fields, retry_message, unexpected_fields
from worker.agent.run import execute_run
from worker.agent.observation import describe, state_hash
from worker.agent.safety import _literal_in_task
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


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_modal_control_survives_observation_limit(self):
        bbox = {'x': 600, 'y': 380, 'width': 80, 'height': 40}
        background = [
            {'el_id': i, 'tag': 'button', 'landmark': 'main', 'bbox': bbox, 'occluded': True}
            for i in range(1, 31)
        ]
        confirm = {'el_id': 31, 'tag': 'button', 'landmark': None, 'bbox': bbox, 'occluded': False}
        driver = SimpleNamespace(page=SimpleNamespace(viewport_size={'width': 1280, 'height': 800}))

        observed = await describe([*background, confirm], driver)

        self.assertEqual(len(observed), 30)
        self.assertEqual(observed[0], confirm)
        self.assertEqual(observed[1]['visibility'], '(가려짐)')


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

    def test_submit_is_optional_for_type_and_named_when_sent_with_another_action(self):
        # #75: type.submit has a default (False), so it is never reported missing.
        self.assertEqual(missing_fields(action('type', target=1, text='a')), ('type', ()))
        self.assertEqual(unexpected_fields(action('type', target=1, text='a', submit=True)), ())
        # submit belongs to type only; the retry names the field, never its value.
        self.assertEqual(unexpected_fields(action('click', target=1, submit=True)), ('submit',))
        message = retry_message('invalid_fields', 'click', (), ('submit',))
        self.assertIn('submit is not used by click', message)
        self.assertNotIn('True', message)
        for payload in ('not json', '[1]', '{"action":"explode","submit":true}', None):
            self.assertEqual(unexpected_fields(payload), ())

    def test_representative(self):
        rows = [Attempt(id=1,index=2,success=True), Attempt(id=2,index=1,success=True),
                Attempt(id=3,index=3,success=False)]
        self.assertEqual(representative(rows,{1:1,2:3,3:2}),2)


BENCHMARK_PASSWORD = 'Study1234'


def benchmark_password_descriptions():
    # Read the real task sentences so the tests follow benchmark/tasks.json if the wording changes.
    path = Path(__file__).resolve().parents[1] / 'benchmark' / 'tasks.json'
    cases = json.loads(path.read_text(encoding='utf-8'))['cases']
    return sorted({c['description'] for c in cases if BENCHMARK_PASSWORD in c['description']})


class PasswordLiteralTests(unittest.TestCase):
    # Rule (ADR 0011 #1 + PM decision): the value must equal one task token exactly, case-sensitive.
    # Token boundaries: whitespace, non-ASCII, ( ) [ ] { } " ' `; trailing . , ; : may be dropped.
    def test_benchmark_password_sentences_accept_password(self):
        descriptions = benchmark_password_descriptions()
        self.assertEqual(len(descriptions), 3)
        for d in descriptions:
            with self.subTest(d):
                self.assertTrue(_literal_in_task(d, BENCHMARK_PASSWORD))

    def test_benchmark_password_sentences_reject_other_values(self):
        for d in benchmark_password_descriptions():
            for value in ('Pass1234', 'Study123', 'tudy1234', 'study1234', 'STUDY1234', '', ' ', '\t'):
                with self.subTest(d=d, value=value):
                    self.assertFalse(_literal_in_task(d, value))

    def test_accepted_surroundings(self):
        cases = [
            'abc123',                       # whole sentence
            'abc123 is the password',       # sentence start
            'The password is abc123',       # sentence end
            'Enter abc123.',                # trailing period
            'Enter abc123, then log in',
            'Enter abc123; then log in',
            'password: abc123: done',
            'Enter "abc123" here', "Enter 'abc123' here", 'Enter `abc123` here',
            'Enter (abc123) here', 'Enter [abc123] here', 'Enter {abc123} here',
            '비밀번호 abc123를 입력', '비밀번호를 abc123로 바꿔', '비밀번호 abc123(확인 칸에도)',
            '비밀번호는abc123입니다',
        ]
        for d in cases:
            with self.subTest(d):
                self.assertTrue(_literal_in_task(d, 'abc123'))

    def test_rejected_surroundings(self):
        cases = [
            'Enter abc123! in the password field',   # ! stays part of the token
            'Enter abc123? now', 'Enter abc123@x now', 'Enter #abc123 now',
            'Enter abc1234 in the field', 'Enter xabc123 in the field',
            'Enter abc123-4 now', 'password=abc123', 'Enter ABC123 now', 'No password here',
        ]
        for d in cases:
            with self.subTest(d):
                self.assertFalse(_literal_in_task(d, 'abc123'))

    def test_symbol_password_is_accepted_whole(self):
        self.assertTrue(_literal_in_task('Enter abc123! in the password field', 'abc123!'))
        self.assertTrue(_literal_in_task('Enter abc123!.', 'abc123!'))


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

    async def test_benchmark_timing_export_uses_task_identity_and_db_metric(self):
        from benchmark.run_development import export_timing
        from benchmark.evidence_capture import EvidenceSink
        sink=EvidenceSink(Path(self.tmp.name)/'timing-dom')
        await execute_run(self.run_id,self.factory,browser=self.browser,evidence_sink=sink,
            adapter_factory=lambda model:FakeAdapter([action('click',target=1),action('done',reason='goal_reached')]))
        case=dict(app_id='synthetic',case_id='baseline-next',id='next',variant='baseline',description='Click Next')
        with self.factory() as db:
            result=export_timing(db,self.run_id,case,sink)
            self.assertEqual(result['page_id'],'synthetic/next/baseline')
            self.assertEqual(result['viewport'],'desktop')
            item=result['attempts'][0]
            self.assertTrue(item['verified_success'])
            metric=db.scalar(select(Metric).where(Metric.attempt_id==item['id'],Metric.key=='est_task_time'))
            self.assertEqual(item['est_task_time'],dict(value=metric.value,unit='s',model_version_id=None))
            aggregate=db.scalar(select(Metric).where(Metric.run_id==self.run_id,
                Metric.attempt_id.is_(None),Metric.key=='est_task_time'))
            self.assertEqual(result['run_est_task_time'],dict(value=aggregate.value,unit='s',model_version_id=None))
            # Export preserves independent check failure even if the worker says success.
            sink.completions[item['id']]=False
            checked=export_timing(db,self.run_id,dict(case,check='false'),sink)
            self.assertFalse(checked['attempts'][0]['verified_success'])

    async def test_r06_trace_includes_first_and_later_non_issue_targets(self):
        from benchmark.evidence_capture import EvidenceSink
        from benchmark.review_r06 import review
        self.html='<html lang="en"><title>Test</title><body><button>Inert</button></body></html>'
        sink=EvidenceSink(Path(self.tmp.name)/'r06-dom')
        await execute_run(self.run_id,self.factory,browser=self.browser,evidence_sink=sink,
            adapter_factory=lambda model:FakeAdapter([action('click',target=1),action('click',target=1),action('fail')]))
        payload=json.loads((sink.directory/'r06.json').read_text(encoding='utf-8'))
        rows=payload['observations']
        self.assertEqual([r['is_first_target'] for r in rows],[True,False])
        self.assertEqual([r['candidate_created'] for r in rows],[False,False])
        self.assertEqual(review(payload)['disagreements'],0)

    async def test_explicit_score_config_finalizes_after_attempt(self):
        from apps.api.db.models import Issue
        from ml.issue_clf.scoring import ScoreConfig
        self.html = '<html lang="en"><title>Test</title><body><button>Go</button></body></html>'
        config = Path(self.tmp.name)/'issue-score.json'
        config.write_text(json.dumps(ScoreConfig((0, 0, 1, 0, 0, 0), 1).as_dict()), encoding='utf-8')
        with patch.dict('os.environ', {'STEPMETER_ISSUE_SCORE_CONFIG': str(config)}):
            await self.run_replies([action('click',target=1), action('fail')])
        with self.factory() as s:
            issue = s.scalar(select(Issue).where(Issue.rule_id == 'R03'))
            self.assertIsNotNone(issue)
            self.assertEqual(issue.confidence, 1)
            self.assertFalse(issue.is_reference)
            self.assertIn('finalized n=1', issue.score_reason)
            self.assertEqual(s.get(Run, self.run_id).status, 'completed')

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

    # 멈추는 종료(done(safety_stop)·SafetyStop·LoginWall) 전에도 설정된 성공 조건을 페이지로 확인한다.
    # 조건(text_present 'Complete')이 이미 충족됐으면 확인된 성공, 아니면 원래 종료 사유, 조건이 없으면 추정 성공으로 바꾸지 않는다.
    def ending(self):
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            return a.end_reason,a.success,a.success_estimated,a.end_detail

    async def test_safety_stop_done_after_goal_is_verified_success(self):
        self.html='<html><title>Test</title><body><p>Complete</p><button>Next</button></body></html>'
        await self.run_replies([action('done',reason='safety_stop')])
        self.assertEqual(self.ending()[:3],('success',True,False))

    async def test_safety_stop_done_before_goal_stays_safety_stop(self):
        self.html='<html><title>Test</title><body><p>Pending</p><button>Next</button></body></html>'
        await self.run_replies([action('done',reason='safety_stop')])
        self.assertEqual(self.ending()[:3],('safety_stop',False,False))

    async def test_login_wall_after_goal_is_verified_success(self):
        self.html='<html><title>Test</title><body><p>Complete</p><input type="password"></body></html>'
        await self.run_replies([action('type',target=1,text='invented')])
        self.assertEqual(self.ending()[:3],('success',True,False))

    async def test_login_wall_before_goal_stays_blocked(self):
        self.html='<html><title>Test</title><body><p>Pending</p><input type="password"></body></html>'
        await self.run_replies([action('type',target=1,text='invented')])
        self.assertEqual(self.ending(),('blocked',False,False,'login_wall'))

    async def test_safety_stop_without_condition_is_not_estimated_success(self):
        with self.factory.begin() as s:
            s.get(Task,self.task_id).success_condition=None
        self.html='<html><title>Test</title><body><p>Complete</p><button>Next</button></body></html>'
        await self.run_replies([action('done',reason='safety_stop')])
        self.assertEqual(self.ending()[:3],('safety_stop',False,False))

    async def test_unsafe_control_after_goal_is_verified_success(self):
        self.html='<html><title>Test</title><body><p>Complete</p><button>Pay now</button></body></html>'
        await self.run_replies([action('click',target=1)])
        self.assertEqual(self.ending()[:3],('success',True,False))

    # fail(모델의 포기)도 done(safety_stop)과 같은 원칙: 조건 충족이면 확인된 성공, 미충족이면 gave_up,
    # 조건이 없으면 추정 성공으로 바꾸지 않고 gave_up.
    async def test_fail_after_goal_is_verified_success(self):
        self.html='<html><title>Test</title><body><p>Complete</p><button>Next</button></body></html>'
        await self.run_replies([action('fail')])
        self.assertEqual(self.ending()[:3],('success',True,False))

    async def test_fail_before_goal_stays_gave_up(self):
        self.html='<html><title>Test</title><body><p>Pending</p><button>Next</button></body></html>'
        await self.run_replies([action('fail')])
        self.assertEqual(self.ending()[:3],('gave_up',False,False))

    async def test_fail_without_condition_stays_gave_up(self):
        with self.factory.begin() as s:
            s.get(Task,self.task_id).success_condition=None
        self.html='<html><title>Test</title><body><p>Complete</p><button>Next</button></body></html>'
        await self.run_replies([action('fail')])
        self.assertEqual(self.ending()[:3],('gave_up',False,False))

    async def test_failed_goal_check_keeps_original_stop(self):
        self.html='<html><title>Test</title><body><p>Complete</p><button>Next</button></body></html>'
        with patch('worker.agent.termination.verify_success',side_effect=RuntimeError('page closed')):
            await self.run_replies([action('done',reason='safety_stop')])
        self.assertEqual(self.ending()[:3],('safety_stop',False,False))

    async def test_visible_password_field_does_not_block_attempt(self):
        self.html='<html><body><input type="password"></body></html>'
        await self.run_replies([action('fail')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'gave_up')
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),1)

    async def test_literal_task_password_can_be_typed(self):
        self.html='<html><body><input type="password"><button onclick="document.body.textContent=document.querySelector(\'input\').value===\'abc123\'?\'Complete\':\'Wrong\'">Login</button></body></html>'
        with self.factory.begin() as s:
            s.get(Task,self.task_id).description='Enter abc123 in the password field and log in'
        await self.run_replies([action('type',target=1,text='abc123'),action('click',target=2),action('done',reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'success')
            self.assertEqual(s.scalar(select(func.count()).select_from(Step)),3)

    async def test_password_absent_from_task_blocks_before_typing(self):
        self.html='<html><body><input type="password" value="original"></body></html>'
        await self.run_replies([action('type',target=1,text='invented')])
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.end_detail,a.steps_count),('blocked','login_wall',0))

    async def test_password_value_must_be_complete_nonempty_literal(self):
        self.html='<html><body><input type="password"></body></html>'
        with self.factory.begin() as s:
            s.get(Task,self.task_id).description='Enter abc1234 in the password field'
        await self.run_replies([action('type',target=1,text='abc123')])
        with self.factory() as s:
            self.assertEqual((s.scalar(select(Attempt)).end_reason,
                              s.scalar(select(Attempt)).end_detail),('blocked','login_wall'))

    async def test_password_prefix_before_punctuation_is_not_full_value(self):
        self.html='<html><body><input type="password"></body></html>'
        with self.factory.begin() as s:
            s.get(Task,self.task_id).description='Enter abc123! in the password field'
        await self.run_replies([action('type',target=1,text='abc123')])
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.end_detail,a.steps_count),('blocked','login_wall',0))

    async def test_full_punctuated_password_literal_is_allowed(self):
        self.html='<html><body><input type="password"></body></html>'
        with self.factory.begin() as s:
            s.get(Task,self.task_id).description='Enter abc123! in the password field'
        await self.run_replies([action('type',target=1,text='abc123!'),action('fail')])
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.steps_count),('gave_up',2))

    async def test_benchmark_login_password_with_korean_particle_proceeds(self):
        # sb-admin-2 login-like page; task sentence is the real one ("비밀번호 Study1234를 ...").
        description = next(d for d in benchmark_password_descriptions() if 'Remember Me' in d)
        self.html = ('<html><body><form class="user">'
                     '<input type="email" id="exampleInputEmail" aria-label="Email">'
                     '<input type="password" id="exampleInputPassword" aria-label="Password">'
                     '<button type="button" onclick="document.body.textContent='
                     '(document.querySelector(\'#exampleInputEmail\').value===\'study@example.com\'&&'
                     'document.querySelector(\'#exampleInputPassword\').value===\'Study1234\')?\'Complete\':\'Wrong\'">'
                     'Login</button></form></body></html>')
        with self.factory.begin() as s:
            s.get(Task, self.task_id).description = description
        await self.run_replies([action('type', target=1, text='study@example.com'),
                                action('type', target=2, text=BENCHMARK_PASSWORD),
                                action('click', target=3), action('done', reason='goal_reached')])
        with self.factory() as s:
            a = s.scalar(select(Attempt))
            self.assertEqual((a.end_reason, a.end_detail, a.steps_count), ('success', None, 4))

    async def test_password_field_click_is_allowed(self):
        self.html='<html><body><input type="password"></body></html>'
        await self.run_replies([action('click',target=1),action('fail')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'gave_up')
            self.assertEqual(s.scalar(select(func.count()).select_from(Step)),2)

    async def test_payment_card_field_remains_safety_stop(self):
        self.html='<html><body><input autocomplete="cc-number"></body></html>'
        await self.run_replies([action('type',target=1,text='0000')])
        with self.factory() as s:
            self.assertEqual((s.scalar(select(Attempt)).end_reason,
                              s.scalar(select(Attempt)).steps_count),('safety_stop',0))

    async def test_sectioned_password_autocomplete_requires_literal_value(self):
        self.html='<html><body><input type="text" autocomplete="section-login current-password"></body></html>'
        await self.run_replies([action('type',target=1,text='invented')])
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.end_detail,a.steps_count),('blocked','login_wall',0))

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

    async def test_out_of_list_target_retries_without_executing_it(self):
        adapter=FakeAdapter([action('click',target=99),action('click',target=1),
                             action('done',reason='goal_reached')])
        await execute_run(self.run_id,self.factory,browser=self.browser,
                          adapter_factory=lambda _:adapter)
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'success')
            self.assertEqual(s.scalar(select(func.count()).select_from(Step)),2)
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)),3)
        self.assertIn('invalid_target',json.loads(adapter.received[1].user_text)['invalid_action'])

    async def test_out_of_list_target_exhaustion_is_input_error(self):
        await self.run_replies([action('click',target=99)])
        with self.factory() as s:
            a=s.scalar(select(Attempt))
            self.assertEqual((a.end_reason,a.end_detail,a.steps_count),
                             ('error','ActionInputError:invalid_target',0))

    async def test_r07_is_attached_to_small_clicked_target(self):
        from apps.api.db.models import Issue
        self.html='<html><body><button style="position:absolute;left:100px;top:100px;width:20px;height:20px" onclick="document.body.textContent=\'Complete\'">Go</button></body></html>'
        await self.run_replies([action('click',target=1),action('done',reason='goal_reached')])
        with self.factory() as s:
            step=s.scalar(select(Step).where(Step.idx==0))
            issue=s.scalar(select(Issue).where(Issue.rule_id=='R07'))
            self.assertIsNotNone(issue)
            self.assertEqual(issue.step_id,step.id)
            self.assertIsNotNone(issue.element_key)
            self.assertAlmostEqual(issue.measured,step.fitts_id)

    async def test_r07_includes_small_select_target(self):
        from apps.api.db.models import Issue
        self.html='''<html><body><select style="position:absolute;left:100px;top:100px;width:20px;height:20px" onchange="document.querySelector('p').textContent='Complete'"><option>A</option><option>B</option></select><p></p></body></html>'''
        await self.run_replies([action('select',target=1,option=2),action('done',reason='goal_reached')])
        with self.factory() as s:
            step=s.scalar(select(Step).where(Step.idx==0))
            issue=s.scalar(select(Issue).where(Issue.rule_id=='R07'))
            self.assertIsNotNone(issue)
            self.assertEqual(issue.step_id,step.id)

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

    async def test_timeout_detail_names_the_stage_without_message(self):
        # #75 follow-up: a timeout records which step stage ran, never the browser message.
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        with patch('worker.agent.loop.PlaywrightDriver.perform',
                   side_effect=PlaywrightTimeout('Timeout 30000ms exceeded. secret=abc')):
            await self.run_replies([action('click', target=1)])
        with self.factory() as s:
            a = s.scalar(select(Attempt))
            self.assertEqual((a.end_reason, a.end_detail), ('error', 'TimeoutError@perform'))

    async def test_builtin_timeout_outside_budget_names_the_stage(self):
        with patch('worker.agent.loop.labeled_screenshot', side_effect=TimeoutError()):
            await self.run_replies([action('click', target=1)])
        with self.factory() as s:
            a = s.scalar(select(Attempt))
            self.assertEqual((a.end_reason, a.end_detail), ('error', 'TimeoutError@screenshot'))

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

    async def test_klm_step_attempt_and_run_storage(self):
        self.html = '''<html lang="en"><title>KLM</title><main><input aria-label="Name">
            <button onclick="document.querySelector('p').textContent='Complete'">Next</button><p></p></main></html>'''
        await self.run_replies([action('type', target=1, text='x'*16), action('click', target=2), action('done', reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'success')
            steps=list(s.scalars(select(Step).order_by(Step.idx)))
            self.assertEqual([step.est_seconds for step in steps],[8.88,3.05,0])
            values=list(s.scalars(select(Metric).where(Metric.key=='est_task_time')))
            self.assertEqual(len(values),2)
            self.assertTrue(all(abs(m.value-11.93)<1e-8 for m in values))
            self.assertTrue(all(m.model_version_id is None for m in values))

    async def test_klm_mobile_has_no_time_metric(self):
        with self.factory.begin() as s: s.get(Run,self.run_id).viewport='mobile'
        await self.run_replies([action('click',target=1),action('done',reason='goal_reached')])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt)).end_reason,'success')
            self.assertTrue(all(step.est_seconds is None for step in s.scalars(select(Step))))
            self.assertEqual(list(s.scalars(select(Metric).where(Metric.key=='est_task_time'))),[])
