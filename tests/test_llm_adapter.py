import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from worker.llm import FakeAdapter, JsonlCallLog, LLMRequest, ask_and_log
from worker.schemas import ClickAction, WaitAction, parse_action_json


def make_request(**overrides):
    fields = {
        "purpose": "action",
        "prompt_version": "action_v1",
        "system": "시스템 프롬프트",
        "user_text": "과업: 회원가입하기",
        "run_id": 7,
    }
    fields.update(overrides)
    return LLMRequest(**fields)


class FakeAdapterTests(unittest.TestCase):
    def test_default_reply_is_valid_action(self):
        result = asyncio.run(FakeAdapter().ask(make_request()))
        self.assertIsInstance(parse_action_json(result.text), WaitAction)
        self.assertEqual(result.model, "fake")
        self.assertEqual(result.cost_usd, 0.0)

    def test_replies_come_back_in_order_then_repeat(self):
        click = '{"action":"click","target":3,"thought":"메뉴를 연다","expectation":"메뉴가 열린다"}'
        wait = '{"action":"wait","thought":"기다린다","expectation":"목록이 나온다"}'
        adapter = FakeAdapter([click, wait])
        texts = [asyncio.run(adapter.ask(make_request())).text for _ in range(3)]
        self.assertEqual(texts, [click, wait, click])
        self.assertIsInstance(parse_action_json(texts[0]), ClickAction)

    def test_remembers_received_requests(self):
        adapter = FakeAdapter()
        request = make_request(user_text="과업: 첫 글 작성")
        asyncio.run(adapter.ask(request))
        self.assertEqual(adapter.received, [request])


class CallLogTests(unittest.TestCase):
    def test_each_call_writes_one_line_with_llm_call_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_calls.jsonl"
            log = JsonlCallLog(path)
            adapter = FakeAdapter()
            asyncio.run(ask_and_log(adapter, make_request(), log))
            asyncio.run(ask_and_log(adapter, make_request(run_id=None, purpose="explain"), log))

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            first, second = (json.loads(line) for line in lines)
            self.assertEqual(
                set(first),
                {
                    "run_id", "purpose", "model", "prompt_version", "input_tokens",
                    "output_tokens", "cost_usd", "latency_ms", "created_at",
                },
            )
            self.assertEqual(first["run_id"], 7)
            self.assertEqual(first["purpose"], "action")
            self.assertEqual(first["prompt_version"], "action_v1")
            self.assertEqual(first["model"], "fake")
            self.assertIsNone(second["run_id"])
            self.assertEqual(second["purpose"], "explain")


if __name__ == "__main__":
    unittest.main()
