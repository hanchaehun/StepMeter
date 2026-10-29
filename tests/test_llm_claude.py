"""Claude 어댑터 테스트. 진짜 API를 부르지 않고 가짜 client로 확인한다."""

import asyncio
import unittest
from types import SimpleNamespace

from worker.llm import LLMRequest
from worker.llm.claude import ClaudeAdapter
from worker.llm.pricing import cost_usd
from worker.schemas import ClickAction, parse_action_json


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.sent = None

    async def create(self, **params):
        self.sent = params
        return self.response


def fake_client(content, input_tokens=1000, output_tokens=100, cache_write=0, cache_read=0):
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(messages=FakeMessages(SimpleNamespace(content=content, usage=usage)))


def tool_block(**fields):
    return SimpleNamespace(type="tool_use", name="choose_action", input=fields)


def make_request(**overrides):
    fields = {
        "purpose": "action",
        "prompt_version": "action_v1",
        "system": "시스템 프롬프트",
        "user_text": "과업: 회원가입하기",
        "image_jpeg": b"\xff\xd8fake",
    }
    fields.update(overrides)
    return LLMRequest(**fields)


class ClaudeAdapterTests(unittest.TestCase):
    def test_action_request_is_packed_for_claude(self):
        client = fake_client([tool_block(action="wait", thought="기다린다", expectation="목록이 나온다")])
        asyncio.run(ClaudeAdapter(client=client).ask(make_request()))
        sent = client.messages.sent

        self.assertEqual(sent["model"], "claude-haiku-5-5")
        self.assertNotIn("temperature", sent)  # 5.5 세대는 온도를 받지 않는다
        self.assertEqual(sent["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(sent["tool_choice"], {"type": "tool", "name": "choose_action"})
        content = sent["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")  # 스크린샷이 글보다 먼저
        self.assertEqual(content[1], {"type": "text", "text": "과업: 회원가입하기"})

    def test_only_haiku_and_sonnet_are_allowed(self):
        client = fake_client([])
        for model in ("claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                ClaudeAdapter(model=model, client=client)

    def test_models_without_forced_tool_use_auto(self):
        # Sonnet 5.5는 tool_choice: tool을 받지 않는다 (보내면 400).
        client = fake_client([tool_block(action="wait", thought="기다린다", expectation="목록이 나온다")])
        asyncio.run(ClaudeAdapter(model="claude-sonnet-5-5", client=client).ask(make_request()))
        self.assertEqual(client.messages.sent["tool_choice"], {"type": "auto"})

    def test_action_tool_is_strict_without_unsupported_constraints(self):
        client = fake_client([tool_block(action="wait", thought="기다린다", expectation="목록이 나온다")])
        asyncio.run(ClaudeAdapter(client=client).ask(make_request()))
        tool = client.messages.sent["tools"][0]
        self.assertIs(tool["strict"], True)
        self.assertIs(tool["input_schema"]["additionalProperties"], False)
        for field in tool["input_schema"]["properties"].values():
            self.assertNotIn("minimum", field)  # strict 모드는 숫자 제약을 지원하지 않는다

    def test_explain_request_has_no_action_tool(self):
        client = fake_client([SimpleNamespace(type="text", text="버튼이 작다.")])
        result = asyncio.run(ClaudeAdapter(client=client).ask(
            make_request(purpose="explain", prompt_version="explain_v1", image_jpeg=None)))
        self.assertNotIn("tools", client.messages.sent)
        self.assertEqual(len(client.messages.sent["messages"][0]["content"]), 1)
        self.assertEqual(result.text, "버튼이 작다.")

    def test_tool_answer_becomes_valid_action_json(self):
        client = fake_client([tool_block(
            action="click", target=12, thought="메뉴를 연다",
            expectation="메뉴가 열린다", confusion=None, text=None,
        )])
        result = asyncio.run(ClaudeAdapter(client=client).ask(make_request()))
        action = parse_action_json(result.text)
        self.assertIsInstance(action, ClickAction)
        self.assertEqual(action.target, 12)

    def test_missing_tool_answer_gives_empty_text(self):
        client = fake_client([SimpleNamespace(type="text", text="잘 모르겠다")])
        result = asyncio.run(ClaudeAdapter(client=client).ask(make_request()))
        self.assertEqual(result.text, "")

    def test_usage_is_reported(self):
        client = fake_client(
            [tool_block(action="wait", thought="기다린다", expectation="목록이 나온다")],
            input_tokens=1000, output_tokens=100, cache_write=2000, cache_read=0,
        )
        result = asyncio.run(ClaudeAdapter(client=client).ask(make_request()))
        self.assertEqual(result.input_tokens, 3000)  # 1000 + 2000 + 0
        self.assertEqual(result.output_tokens, 100)
        self.assertAlmostEqual(result.cost_usd, 0.0004)


class PricingTests(unittest.TestCase):
    # 기대값은 요금표 단가로 손으로 계산했다 (100만 토큰당 달러).

    def test_short_prompt(self):
        # 입력 1000×0.10 + 캐시 쓰기 2000×0.125 + 출력 100×0.50
        # = 100 + 250 + 50 = 400  → 400 / 1,000,000 = 0.0004달러
        self.assertAlmostEqual(
            cost_usd("claude-haiku-5-5", input_tokens=1000, output_tokens=100,
                     cache_write_tokens=2000), 0.0004)

    def test_cache_read(self):
        # 입력 500×0.10 + 캐시 읽기 4000×0.01 + 출력 200×0.50
        # = 50 + 40 + 100 = 190 → 0.00019달러
        self.assertAlmostEqual(
            cost_usd("claude-haiku-5-5", input_tokens=500, output_tokens=200,
                     cache_read_tokens=4000), 0.00019)

    def test_long_prompt_uses_higher_rates(self):
        # 입력 150,000은 100K 초과 → 150,000×0.50 + 출력 1000×2.50
        # = 75,000 + 2,500 = 77,500 → 0.0775달러
        self.assertAlmostEqual(
            cost_usd("claude-haiku-5-5", input_tokens=150_000, output_tokens=1000), 0.0775)

    def test_unknown_model_cost_is_none(self):
        self.assertIsNone(cost_usd("some-other-model", input_tokens=10, output_tokens=10))


if __name__ == "__main__":
    unittest.main()
