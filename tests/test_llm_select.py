"""가짜 LLM 모드 고르기 테스트 (tests/e2e/README.md "가짜 LLM으로 돌리기" 요청 항목별)."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker.llm import FakeAdapter, LLMRequest, LLMSelectError, make_adapter
from worker.llm.claude import ClaudeAdapter
from worker.schemas import ClickAction, DoneAction, TypeAction, parse_action_json

SIGNUP_REPLIES = Path(__file__).parent / "fixtures" / "e2e" / "signup" / "fake_replies.json"


def fake_env(**extra):
    env = {"STEPMETER_LLM": "fake", "STEPMETER_FAKE_REPLIES": str(SIGNUP_REPLIES)}
    env.update(extra)
    return env


def request(purpose="action"):
    return LLMRequest(purpose=purpose, prompt_version="action_v1", system="지시서", user_text="과업")


def ask(adapter, purpose="action"):
    return asyncio.run(adapter.ask(request(purpose)))


class ChooseAdapterTests(unittest.TestCase):
    def test_without_setting_uses_claude(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            adapter = make_adapter("claude-haiku-5-5", env={})
        self.assertIsInstance(adapter, ClaudeAdapter)
        self.assertEqual(adapter.model, "claude-haiku-5-5")

    def test_fake_setting_uses_fake_adapter(self):
        self.assertIsInstance(make_adapter("claude-haiku-5-5", env=fake_env()), FakeAdapter)

    def test_fake_mode_starts_without_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            adapter = make_adapter("claude-haiku-5-5", env=fake_env())
        self.assertEqual(ask(adapter).model, "fake")

    def test_unknown_setting_is_rejected(self):
        with self.assertRaises(LLMSelectError):
            make_adapter("claude-haiku-5-5", env={"STEPMETER_LLM": "gpt"})


class FakeRepliesTests(unittest.TestCase):
    def test_signup_replies_come_back_in_file_order(self):
        adapter = make_adapter("claude-haiku-5-5", env=fake_env())
        kinds = [type(parse_action_json(ask(adapter).text)) for _ in range(3)]
        self.assertEqual(kinds, [TypeAction, ClickAction, DoneAction])

    def test_each_attempt_starts_from_first_reply(self):
        first = make_adapter("claude-haiku-5-5", env=fake_env())
        ask(first)
        ask(first)
        second = make_adapter("claude-haiku-5-5", env=fake_env())
        self.assertIsInstance(parse_action_json(ask(second).text), TypeAction)

    def test_explain_gets_fixed_text_without_skipping_actions(self):
        adapter = make_adapter("claude-haiku-5-5", env=fake_env())
        explanation = ask(adapter, purpose="explain").text
        self.assertTrue(explanation.strip())
        self.assertIsInstance(parse_action_json(ask(adapter).text), TypeAction)

    def test_fake_call_costs_nothing(self):
        result = ask(make_adapter("claude-haiku-5-5", env=fake_env()))
        self.assertEqual((result.model, result.cost_usd), ("fake", 0.0))


class FakeSettingErrorTests(unittest.TestCase):
    def test_blocked_on_staging_and_production(self):
        for stage in ("staging", "production", "Production"):
            with self.subTest(stage=stage), self.assertRaises(LLMSelectError):
                make_adapter("claude-haiku-5-5", env=fake_env(STEPMETER_ENV=stage))

    def test_needs_replies_file(self):
        with self.assertRaises(LLMSelectError):
            make_adapter("claude-haiku-5-5", env={"STEPMETER_LLM": "fake"})

    def test_missing_file(self):
        with self.assertRaises(LLMSelectError):
            make_adapter("claude-haiku-5-5", env=fake_env(STEPMETER_FAKE_REPLIES="/없는/파일.json"))

    def write(self, content):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def test_wrong_reply_is_caught_before_measuring(self):
        bad = [{"action": "click", "target": "1", "thought": "누른다", "expectation": "바뀐다"}]
        path = self.write(json.dumps(bad, ensure_ascii=False))
        with self.assertRaises(LLMSelectError) as caught:
            make_adapter("claude-haiku-5-5", env=fake_env(STEPMETER_FAKE_REPLIES=path))
        self.assertIn("1번째", str(caught.exception))

    def test_empty_or_non_list_file(self):
        for content in ("[]", "{}", "not json"):
            with self.subTest(content=content), self.assertRaises(LLMSelectError):
                make_adapter("claude-haiku-5-5", env=fake_env(STEPMETER_FAKE_REPLIES=self.write(content)))


if __name__ == "__main__":
    unittest.main()
