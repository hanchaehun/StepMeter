"""Hand-written selector strings; no model calls or participant data."""
import unittest
from worker.rules.axe_target import read_target, rewrite_explanation, split_explanation

class TargetTests(unittest.TestCase):
    def test_exact_suffix_and_nested_selectors(self):
        suffix = ' 대상: [ ["#host", "button"], "#한글" ]  '
        original = "Old prose" + suffix
        self.assertEqual(rewrite_explanation(original, "New prose"), "New prose" + suffix)
        self.assertEqual(read_target(original), [["#host", "button"], "#한글"])
        self.assertEqual(split_explanation(original), ("Old prose", suffix))

    def test_marker_inside_selector_is_not_a_separator(self):
        original = 'Old 대상: ["# 대상: hello"]'
        self.assertEqual(rewrite_explanation(original, "New"), original.replace("Old", "New", 1))

    def test_missing_malformed_and_fabricated_targets(self):
        self.assertIsNone(read_target("No metadata"))
        self.assertEqual(rewrite_explanation("Old", "New"), "New")
        with self.assertRaises(ValueError): rewrite_explanation("Old", "New", require_target=True)
        for original in ('Old 대상: nope', 'Old 대상: []', 'Old 대상: [7]', 'Old 대상: ["#a"] garbage'):
            with self.assertRaises(ValueError): read_target(original)
        with self.assertRaises(ValueError): rewrite_explanation('Old 대상: ["#a"]', 'New 대상: ["#b"]')
