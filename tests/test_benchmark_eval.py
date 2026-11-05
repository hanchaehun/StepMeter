"""Evaluation arithmetic from explicit sets, independent of detector implementation."""
import unittest

from benchmark.eval import score


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.labels = {'split': 'development', 'review_status': 'approved', 'cases': {
            'normal': [], 'broken': [{'rule': 'R01', 'target': 'a'}, {'rule': 'R02', 'target': 'b'}]}}
        self.predictions = {'split': 'development', 'cases': {
            'normal': [{'rule': 'R01', 'target': 'c'}],
            'broken': [{'rule': 'R01', 'target': 'a'}, {'rule': 'R01', 'target': 'a'}]}}

    def test_micro_and_duplicates(self):
        # intersection={a}, false positive={c}, missed={b}: P=R=F1=1/2.
        result = score(self.labels, self.predictions)
        self.assertEqual(result['micro'], dict(tp=1, fp=1, fn=1, precision=.5, recall=.5, f1=.5))
        self.assertEqual(result['rules']['R02']['recall'], 0)
        self.assertIsNone(result['rules']['R02']['precision'])

    def test_missing_normal_case_rejected(self):
        del self.predictions['cases']['normal']
        with self.assertRaises(ValueError):
            score(self.labels, self.predictions)

    def test_unreviewed_or_holdout_rejected(self):
        for field, value in [('review_status', 'pending'), ('split', 'holdout')]:
            labels = {**self.labels, field: value}
            with self.assertRaises(ValueError):
                score(labels, self.predictions)
