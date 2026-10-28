import unittest

from worker.llm.action_tool import ACTION_TOOL
from worker.llm.prompts import load_prompt
from worker.schemas import ACTION_NAMES


class ActionPromptTests(unittest.TestCase):
    def test_prompt_file_loads(self):
        self.assertIn("choose_action", load_prompt("action_v1"))

    def test_prompt_explains_every_action_in_schema(self):
        # 스키마에 행동이 추가되면 프롬프트에도 설명을 넣어야 이 테스트가 통과한다.
        prompt = load_prompt("action_v1")
        for name in ACTION_NAMES:
            with self.subTest(action=name):
                self.assertIn(f"- {name}:", prompt)

    def test_tool_offers_exactly_the_schema_actions(self):
        enum = ACTION_TOOL["input_schema"]["properties"]["action"]["enum"]
        self.assertEqual(set(enum), set(ACTION_NAMES))


if __name__ == "__main__":
    unittest.main()
