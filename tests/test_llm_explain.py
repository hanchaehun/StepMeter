"""설명 생성 (개발계획서 6.1, worker/llm/explain.py). 기대값은 손으로 정했다."""
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import AccessCode, Base, Issue, LlmCall, Project, Run, Task
# 모듈째 불러온다: 클래스를 직접 import하면 test_agent_core의 테스트가 여기서 한 번 더 돈다.
# 불러오면서 sqlite에서 JSONB를 쓰게 하는 등록도 된다.
from tests import test_agent_core as core
from worker.llm.base import LLMResult
from worker.llm.explain import IssueText, apply, explain_run, generate, group, parse, user_text
from worker.llm.fake import FakeAdapter

R02_TARGET = ' 대상: ["#apply"]'


def issue(issue_id, rule_id='R01', measured=16.0, threshold=24.0, element='button|button|신청하기||main',
          prose='타겟이 24px 최소 크기·간격 기준에 미달합니다.'):
    return IssueText(issue_id, rule_id, 'high', measured, threshold, element, prose)


class Stub:
    """가짜가 아닌 어댑터처럼 보이게 이름만 바꾸고, 정해 둔 답을 돌려준다."""

    name = 'stub'

    def __init__(self, text):
        self.text, self.received = text, []

    async def ask(self, request):
        self.received.append(request)
        return LLMResult(text=self.text, model='stub', input_tokens=10, output_tokens=5,
                         cost_usd=0.001, latency_ms=1)


def answer(*items):
    return json.dumps([{'id': i, 'explanation': e, 'suggestion': s} for i, e, s in items], ensure_ascii=False)


class TextTests(unittest.TestCase):
    def test_same_problem_becomes_one_line(self):
        groups = group([issue(1), issue(2), issue(3, measured=20.0)])
        self.assertEqual([ids for _, ids in groups], [[1, 2], [3]])

    def test_line_format(self):
        self.assertEqual(user_text(group([issue(1)])),
                         '1|작은 타겟|높음|16|24|button/button/신청하기//main|타겟이 24px 최소 크기·간격 기준에 미달합니다.')

    def test_missing_values_are_dash(self):
        line = user_text(group([issue(1, 'R04', None, None, None, '가려져 있습니다.')]))
        self.assertEqual(line, '1|가려진 요소|높음|-|-|-|가려져 있습니다.')

    def test_parse_keeps_only_known_complete_answers(self):
        text = '설명입니다 ' + answer((1, ' 버튼이 작습니다. ', '키우세요.'), (2, '모름', '모름'),
                                      (1, '두 번째 답', '무시'))
        self.assertEqual(parse(text, {1}), {1: ('버튼이 작습니다.', '키우세요.')})

    def test_parse_drops_target_text_and_empty(self):
        text = answer((1, '버튼 대상: ["#a"]', '키우세요.'), (2, '', '키우세요.'))
        self.assertEqual(parse(text, {1, 2}), {})

    def test_parse_broken_json(self):
        self.assertEqual(parse('[{"id": 1,', {1}), {})
        self.assertEqual(parse('답 없음', {1}), {})

    def test_parse_keeps_finished_items_of_cut_answer(self):
        # 답 길이 한도에서 끊긴 답 (run 13): 끝까지 쓴 1번만 쓴다
        text = '[{"id": 1, "explanation": "버튼이 작습니다.", "suggestion": "키우세요."}, {"id": 2, "explanation": "글자가'
        self.assertEqual(parse(text, {1, 2}), {1: ('버튼이 작습니다.', '키우세요.')})


class GenerateTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_request_and_answer_copied_to_same_problems(self):
        adapter = Stub(answer((1, "'신청하기' 버튼이 16px라 기준 24px보다 작습니다.", '24px 이상으로 키우세요.')))
        result, out = await generate(adapter, [issue(1), issue(2)], run_id=7)
        self.assertEqual(len(adapter.received), 1)
        request = adapter.received[0]
        self.assertEqual((request.purpose, request.prompt_version, request.run_id), ('explain', 'explain_v1', 7))
        self.assertEqual(set(out), {1, 2})
        self.assertEqual(out[1][1], '24px 이상으로 키우세요.')
        self.assertEqual(result.cost_usd, 0.001)

    async def test_invented_number_keeps_template(self):
        # 44는 입력 어디에도 없다 → 버린다
        adapter = Stub(answer((1, '버튼이 작습니다.', '44px 이상으로 키우세요.')))
        with self.assertLogs('worker.llm.explain', 'WARNING') as logs:
            _, out = await generate(adapter, [issue(1)])
        self.assertEqual(out, {})
        self.assertIn('[44.0]', logs.output[0])  # 왜 버렸는지 로그에 남는다

    async def test_missing_answer_is_logged(self):
        adapter = Stub(answer((1, '버튼이 작습니다.', '키우세요.')))
        with self.assertLogs('worker.llm.explain', 'WARNING') as logs:
            _, out = await generate(adapter, [issue(1), issue(2, measured=20.0)])
        self.assertEqual(set(out), {1})
        self.assertIn('[2]', logs.output[0])

    async def test_no_issues_no_call(self):
        adapter = Stub('[]')
        self.assertEqual(await generate(adapter, []), (None, {}))
        self.assertEqual(adapter.received, [])


class DbTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        engine = create_engine('sqlite:///' + self.tmp.name + '/test.db')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.factory = sessionmaker(engine, expire_on_commit=False)
        with self.factory.begin() as s:
            code = AccessCode(code_hash='x'); s.add(code); s.flush()
            p = Project(owner_id=code.id, name='p', base_url='http://x.test/'); s.add(p); s.flush()
            t = Task(project_id=p.id, description='d', success_condition={'text_present': 'ok'}); s.add(t); s.flush()
            r = Run(task_id=t.id, viewport='desktop', mode='agent', repeat_n=1, model='claude-haiku-5-5',
                    status='running'); s.add(r); s.flush()
            self.run_id = r.id
            rows = [Issue(run_id=r.id, rule_id='R02', severity='high', confidence=1.0,
                          explanation='axe-core가 텍스트 대비 기준 위반을 확인했습니다.' + R02_TARGET),
                    Issue(run_id=r.id, rule_id='R02', severity='high', confidence=1.0,
                          explanation='대상이 없는 R02'),
                    Issue(run_id=r.id, rule_id='R04', severity='high', confidence=1.0,
                          explanation='행동 대상의 조작 지점이 다른 요소에 가려져 있습니다.')]
            s.add_all(rows); s.flush()
            self.ids = [row.id for row in rows]

    def rows(self):
        with self.factory() as s:
            return {row.id: row for row in s.scalars(select(Issue))}

    def test_apply_keeps_target_from_db_and_sets_suggestion(self):
        with self.factory.begin() as s:
            changed = apply(s, self.run_id, {self.ids[0]: ('글자가 배경과 잘 구분되지 않습니다.', '글자색을 더 진하게 하세요.'),
                                             self.ids[1]: ('새 설명', '제안')})
        self.assertEqual(changed, 1)  # 대상이 없는 R02는 건너뛴다
        rows = self.rows()
        self.assertEqual(rows[self.ids[0]].explanation, '글자가 배경과 잘 구분되지 않습니다.' + R02_TARGET)
        self.assertEqual(rows[self.ids[0]].suggestion, '글자색을 더 진하게 하세요.')
        self.assertEqual(rows[self.ids[1]].explanation, '대상이 없는 R02')

    async def test_explain_run_records_call_and_updates(self):
        # 줄 순서: R02(대상 있음) 1, R02(대상 없음) 2, R04 3
        adapter = Stub(answer((3, '누르려는 곳을 다른 요소가 덮고 있습니다.', '덮는 요소를 치우세요.')))
        self.assertEqual(await explain_run(self.factory, self.run_id, adapter), 1)
        rows = self.rows()
        self.assertEqual(rows[self.ids[2]].suggestion, '덮는 요소를 치우세요.')
        with self.factory() as s:
            call = s.scalar(select(LlmCall))
            self.assertEqual((call.purpose, call.prompt_version), ('explain', 'explain_v1'))
            self.assertAlmostEqual(s.get(Run, self.run_id).cost_usd, 0.001)

    async def test_answer_length_raised_only_during_call(self):
        seen = []

        class Long(Stub):
            max_tokens = 1024

            async def ask(self, request):
                seen.append(self.max_tokens)
                return await super().ask(request)
        adapter = Long('[]')
        await explain_run(self.factory, self.run_id, adapter)
        self.assertEqual(seen, [8192])
        self.assertEqual(adapter.max_tokens, 1024)

    async def test_fake_adapter_is_not_called(self):
        adapter = FakeAdapter()
        self.assertEqual(await explain_run(self.factory, self.run_id, adapter), 0)
        self.assertEqual(adapter.received, [])
        with self.factory() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(LlmCall)), 0)

    async def test_llm_failure_keeps_templates(self):
        class Broken(Stub):
            async def ask(self, request):
                raise RuntimeError('down')
        self.assertEqual(await explain_run(self.factory, self.run_id, Broken('')), 0)
        self.assertIsNone(self.rows()[self.ids[2]].suggestion)


class RunHookTests(unittest.IsolatedAsyncioTestCase):
    """execute_run이 에이전트 측정 끝에 explain_run을 한 번 부르고 completed로 끝낸다."""

    asyncSetUp = core.SyntheticIntegration.asyncSetUp
    asyncTearDown = core.SyntheticIntegration.asyncTearDown
    run_replies = core.SyntheticIntegration.run_replies

    async def test_called_once_after_attempts(self):
        with patch('worker.agent.run.explain_run', new=AsyncMock(return_value=0)) as hook:
            await self.run_replies([core.action('click', target=1), core.action('done', reason='goal_reached')])
        self.assertEqual(hook.await_count, 1)
        self.assertEqual(hook.await_args.args[1], self.run_id)
        with self.factory() as s:
            self.assertEqual(s.get(Run, self.run_id).status, 'completed')
