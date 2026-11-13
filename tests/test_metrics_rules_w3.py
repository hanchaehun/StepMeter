"""Plan-derived R08 thresholds and hand-counted synthetic human events."""
import copy
import unittest
from ml.timing.human import click_events
from worker.metrics.interactions import count_interactions, count_no_response_clicks, count_repeated_clicks
from worker.rules.r08 import evaluate

class W3Tests(unittest.TestCase):
    def test_r08_counts_attempts_not_back_presses(self):
        for counts in ([], [1], [1, 1], [4, 0, 0], [0, 0, 0]):
            self.assertIsNone(evaluate(counts))
        candidate = evaluate([1, 3, 0])
        self.assertEqual((candidate.rule_id, candidate.measured, candidate.threshold), ('R08', 2, 2))
        self.assertEqual(candidate.severity, 'medium')
        self.assertTrue(candidate.is_reference)
        self.assertIsNotNone(evaluate([1, 1, 1]))
        self.assertIsNone(evaluate([1, 1, 0, 0]))
        for counts in ([-1, 0, 0], [True, 1, 0]):
            with self.assertRaises(ValueError): evaluate(counts)

    def test_select_is_one_click_equivalent(self):
        self.assertEqual(count_interactions(['select', 'click', 'done', 'select'])['click_count'], 2)
        self.assertEqual(count_no_response_clicks(['select'], ['no_change']), 1)
        self.assertEqual(count_repeated_clicks(['select', 'select'], ['A', 'A']), 1)

    def test_up_and_click_count_once_even_if_popup_target_disappears(self):
        kinds = ['down', 'up', 'click', 'down', 'up', 'move', 'stable', 'down', 'up', 'click']
        events = [dict(type=k, t_ms=i * 10, x=1, y=2, target_key='A' if k != 'click' else None) for i,k in enumerate(kinds)]
        original = copy.deepcopy(events)
        clicks = click_events(events)
        self.assertEqual([e['t_ms'] for e in clicks], [10, 40, 80])
        self.assertEqual(events, original)
        self.assertIsNot(clicks[0], events[1])

    def test_click_only_null_target_and_incomplete_down(self):
        events = [dict(type=k, t_ms=i, target_key=None) for i,k in enumerate(['click','down','up','click','down'])]
        self.assertEqual(len(click_events(events)), 2)
        self.assertEqual(click_events([]), [])
        with self.assertRaises(ValueError): click_events([dict(type='up',t_ms=3),dict(type='up',t_ms=2)])
