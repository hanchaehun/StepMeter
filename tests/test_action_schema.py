import json
import unittest

from worker.schemas import (
    ActionInputError,
    parse_action_json,
)


COMMON = {"thought": "다음 단계를 진행한다", "expectation": "화면이 바뀐다"}


class ActionSchemaTests(unittest.TestCase):
    def parse(self, **fields):
        return parse_action_json(json.dumps({**COMMON, **fields}, ensure_ascii=False))

    def assert_rejected(self, payload, code="invalid_fields"):
        with self.assertRaises(ActionInputError) as caught:
            parse_action_json(payload)
        self.assertEqual(caught.exception.code, code)

    def test_eight_actions_accept_only_their_fields(self):
        cases = [
            ({"action": "click", "target": 1}, "click"),
            ({"action": "type", "target": 2, "text": "새 값"}, "type"),
            ({"action": "select", "target": 3, "option": 1}, "select"),
            ({"action": "scroll", "direction": "up"}, "scroll"),
            ({"action": "back"}, "back"),
            ({"action": "wait"}, "wait"),
            ({"action": "done", "reason": "goal_reached"}, "done"),
            ({"action": "fail"}, "fail"),
        ]
        for fields, name in cases:
            with self.subTest(name=name):
                self.assertEqual(self.parse(**fields).action, name)
                self.assertEqual(self.parse(**fields).confusion, None)

    def test_type_keeps_text_including_spaces_and_empty_string(self):
        self.assertEqual(self.parse(action="type", target=1, text="  값  ").text, "  값  ")
        self.assertEqual(self.parse(action="type", target=1, text="").text, "")

    def test_text_limit(self):
        self.assertEqual(len(self.parse(action="type", target=1, text="x" * 4096).text), 4096)
        self.assert_rejected(json.dumps({**COMMON, "action": "type", "target": 1, "text": "x" * 4097}))

    def test_explanations_are_nonblank_and_bounded_without_modification(self):
        self.assertEqual(self.parse(action="wait", thought="  근거  ").thought, "  근거  ")
        for key in ("thought", "expectation", "confusion"):
            for value in ("   ", "x" * 501):
                with self.subTest(key=key, size=len(value)):
                    self.assert_rejected(json.dumps({**COMMON, "action": "wait", key: value}))
        self.assertEqual(self.parse(action="wait", confusion=None).confusion, None)

    def test_required_and_unrelated_fields_are_rejected(self):
        for fields in (
            {"action": "click"},
            {"action": "type", "target": 1},
            {"action": "select", "target": 1},
            {"action": "click", "target": 1, "text": "wrong"},
            {"action": "wait", "target": 1},
            {"action": "fail", "reason": "goal_reached"},
            {"action": "done"},
        ):
            with self.subTest(fields=fields):
                self.assert_rejected(json.dumps({**COMMON, **fields}))

    def test_target_and_option_must_be_strict_positive_integers(self):
        for key, action_fields in (
            ("target", {"action": "click"}),
            ("option", {"action": "select", "target": 1}),
        ):
            for value in (0, -1, True, "1", 1.0):
                with self.subTest(key=key, value=value):
                    self.assert_rejected(json.dumps({**COMMON, **action_fields, key: value}))

    def test_scroll_and_done_values_are_closed(self):
        self.assert_rejected(json.dumps({**COMMON, "action": "scroll", "direction": "left"}))
        self.assert_rejected(json.dumps({**COMMON, "action": "done", "reason": "success"}))

    def test_invalid_json_shape_duplicates_constants_and_unknown_action(self):
        for raw, code in (
            ("[]", "invalid_shape"),
            ('{"action":"wait","action":"click"}', "duplicate_key"),
            (json.dumps({**COMMON, "action": "wait"})[:-1] + ',"x":NaN}', "invalid_json"),
            (json.dumps({**COMMON, "action": "hover"}), "invalid_action"),
            ("{} {}", "invalid_json"),
        ):
            with self.subTest(raw=raw[:30]):
                self.assert_rejected(raw, code)

    def test_error_does_not_echo_sensitive_text(self):
        raw = json.dumps({**COMMON, "action": "type", "target": 0, "text": "secret-example"})
        with self.assertRaises(ActionInputError) as caught:
            parse_action_json(raw)
        self.assertNotIn("secret-example", str(caught.exception))

    def test_type_request_repr_does_not_echo_input(self):
        action = self.parse(action="type", target=1, text="secret-example")
        self.assertNotIn("secret-example", repr(action))

    def test_done_reasons_remain_distinct(self):
        self.assertEqual(self.parse(action="done", reason="goal_reached").reason, "goal_reached")
        self.assertEqual(self.parse(action="done", reason="safety_stop").reason, "safety_stop")


if __name__ == "__main__":
    unittest.main()
