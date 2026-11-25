import asyncio
import json
import unittest

from worker.llm.base import LLMResult
from worker.rules.r09 import StepRecord, candidates, judge, judgeable, parse_mismatches, user_text


def record(idx, action="click", target="가입하기", expectation="가입 폼이 열릴 것", effect="no_change",
           before="http://x/a", after="http://x/a", step_id=None):
    return StepRecord(step_id if step_id is not None else 100 + idx, idx, action, target, expectation,
                      effect, before, after)


class ScriptedAdapter:
    name = "scripted"

    def __init__(self, text):
        self.text, self.received = text, []

    async def ask(self, request):
        self.received.append(request)
        return LLMResult(self.text, "scripted", 1, 1, 0.0, 1)


class UserTextTests(unittest.TestCase):
    def test_one_line_per_step_with_url_change(self):
        text = user_text([record(0), record(1, effect="navigation", after="http://x/b")])
        self.assertEqual(text.splitlines(), [
            "0|click|가입하기|가입 폼이 열릴 것|no_change|같음",
            "1|click|가입하기|가입 폼이 열릴 것|navigation|http://x/a → http://x/b",
        ])

    def test_separator_and_newlines_in_values_do_not_break_lines(self):
        text = user_text([record(0, target="A|B", expectation="첫 줄\n둘째 줄")])
        self.assertEqual(text, "0|click|A/B|첫 줄 둘째 줄|no_change|같음")

    def test_unknown_after_url_and_missing_target(self):
        self.assertEqual(user_text([record(0, action="scroll", target=None, after=None)]),
                         "0|scroll|-|가입 폼이 열릴 것|no_change|알 수 없음")

    def test_done_and_fail_are_not_judged(self):
        steps = judgeable([record(0), record(1, action="done"), record(2, action="fail")])
        self.assertEqual([r.idx for r in steps], [0])


class ParseTests(unittest.TestCase):
    def test_reads_array_and_keeps_known_steps_only(self):
        text = '설명 [{"step": 0, "reason": " 폼이  안 열림 "}, {"step": 9, "reason": "x"}] 끝'
        self.assertEqual(parse_mismatches(text, {0, 1}), {0: "폼이 안 열림"})

    def test_unreadable_or_empty_answers_give_nothing(self):
        for text in ("", "모르겠다", "[{", "[]", '[{"step": "0", "reason": "x"}]', '[{"step": 0}]',
                     '[{"step": true, "reason": "x"}]'):
            with self.subTest(text=text):
                self.assertEqual(parse_mismatches(text, {0}), {})


class CandidateTests(unittest.TestCase):
    def test_low_reference_candidate_on_that_step(self):
        [c] = candidates([record(0), record(1)], {1: "화면 변화가 없었다"})
        self.assertEqual((c.rule_id, c.severity, c.is_reference, c.step_id), ("R09", "low", True, 101))
        self.assertEqual(c.explanation, "가입하기 뒤 결과가 기대와 다릅니다. 화면 변화가 없었다")


class JudgeTests(unittest.TestCase):
    def test_one_call_with_judge_purpose(self):
        adapter = ScriptedAdapter(json.dumps([{"step": 0, "reason": "변화 없음"}], ensure_ascii=False))
        result, found = asyncio.run(judge(adapter, [record(0), record(1, action="done")], run_id=7))
        self.assertEqual(len(adapter.received), 1)
        request = adapter.received[0]
        self.assertEqual((request.purpose, request.prompt_version, request.run_id), ("judge", "judge_v1", 7))
        self.assertNotIn("done", request.user_text)
        self.assertEqual(result.model, "scripted")
        self.assertEqual([c.step_id for c in found], [100])

    def test_no_judgeable_steps_means_no_call(self):
        adapter = ScriptedAdapter("[]")
        self.assertEqual(asyncio.run(judge(adapter, [record(0, action="done")])), (None, []))
        self.assertEqual(adapter.received, [])


if __name__ == "__main__":
    unittest.main()


class LoopTests(unittest.IsolatedAsyncioTestCase):
    """loop.py가 시도가 끝난 뒤 R09를 한 번 부르고 저장하는지 (ADR 0011 6번)."""

    from tests.test_agent_review import AgentReviewTests as _Base
    asyncSetUp = _Base.asyncSetUp
    asyncTearDown = _Base.asyncTearDown

    async def run_with(self, adapter):
        from worker.agent.run import execute_run
        await execute_run(self.run_id, self.factory, adapter_factory=lambda _: adapter, browser=self.browser)

    def rows(self):
        from sqlalchemy import select
        from apps.api.db.models import Issue, LlmCall
        with self.factory() as s:
            calls = [(c.purpose, c.prompt_version) for c in s.scalars(select(LlmCall).order_by(LlmCall.id))]
            issues = [(i.rule_id, i.severity, i.explanation) for i in s.scalars(select(Issue).where(Issue.rule_id == "R09"))]
        return calls, issues

    def adapter(self, judge_text, name="scripted"):
        replies = iter([json.dumps(dict(action="click", target=1, thought="t", expectation="저장될 것")),
                        json.dumps(dict(action="done", reason="goal_reached", thought="t", expectation="끝"))])

        class Adapter:
            pass
        Adapter.name = name

        async def ask(_self, request):
            text = next(replies) if request.purpose == "action" else judge_text
            return LLMResult(text, "scripted", 1, 1, 0.0, 1)
        Adapter.ask = ask
        return Adapter()

    async def test_mismatch_is_saved_as_r09_and_call_is_logged_as_judge(self):
        await self.run_with(self.adapter('[{"step": 0, "reason": "저장 표시가 없었다"}]'))
        calls, issues = self.rows()
        # 이슈가 생겼으니 run 끝에 설명 생성(explain)도 한 번 묻는다. 이 답은 설명 형식이 아니라 템플릿 설명이 남는다.
        self.assertEqual(calls, [("action", "action_v4"), ("action", "action_v4"), ("judge", "judge_v1"),
                                 ("explain", "explain_v1")])
        self.assertEqual(issues, [("R09", "low", "Save 뒤 결과가 기대와 다릅니다. 저장 표시가 없었다")])

    async def test_fake_adapter_is_not_asked(self):
        await self.run_with(self.adapter('[{"step": 0, "reason": "x"}]', name="fake"))
        calls, issues = self.rows()
        self.assertEqual([c[0] for c in calls], ["action", "action"])
        self.assertEqual(issues, [])

    async def test_judge_failure_does_not_change_attempt(self):
        class Boom(Exception):
            pass
        adapter = self.adapter("[]")
        original = type(adapter).ask

        async def ask(_self, request):
            if request.purpose == "judge":
                raise Boom()
            return await original(_self, request)
        type(adapter).ask = ask
        await self.run_with(adapter)
        from sqlalchemy import select
        from apps.api.db.models import Attempt
        with self.factory() as s:
            self.assertEqual(s.scalar(select(Attempt.end_reason)), "success")
        self.assertEqual(self.rows()[1], [])

    async def test_retried_action_is_not_recorded_for_r09(self):
        # 목록에 없는 번호(99)는 다시 묻기로 버려져 Step이 되지 않는다. R09 기록도 실제 저장된 Step과 같아야 한다
        from unittest.mock import patch
        from sqlalchemy import select
        from apps.api.db.models import Step
        from worker.agent import loop
        replies = iter([json.dumps(dict(action="click", target=99, thought="t", expectation="버려질 행동")),
                        json.dumps(dict(action="click", target=1, thought="t", expectation="저장될 것")),
                        json.dumps(dict(action="done", reason="goal_reached", thought="t", expectation="끝"))])
        adapter = self.adapter("[]")

        async def ask(_self, request):
            text = next(replies) if request.purpose == "action" else "[]"
            return LLMResult(text, "scripted", 1, 1, 0.0, 1)
        type(adapter).ask = ask
        seen = []
        original = loop.judge_expectations

        async def spy(adapter, records, **kw):
            seen.append(list(records))
            return await original(adapter, records, **kw)
        with patch.object(loop, "judge_expectations", spy):
            await self.run_with(adapter)
        with self.factory() as s:
            steps = [(st.id, st.idx) for st in s.scalars(select(Step).order_by(Step.idx))]
        self.assertEqual(len(seen), 1)  # 시도당 한 번
        self.assertEqual([(r.step_id, r.idx) for r in seen[0]], steps)
        self.assertEqual(len(steps), 2)  # click 1 + done
        self.assertNotIn("버려질 행동", [r.expectation for r in seen[0]])
