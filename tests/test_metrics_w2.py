"""Manual arithmetic and development plan 5.2/5.3/5.6 examples."""

import unittest

from tests.test_cursor_distance import snapshot_at
from worker.metrics.fitts import calculate_fitts_ids, fitts_id
from worker.metrics.interactions import (
    calculate_scroll_distance, count_interactions, count_no_response_clicks,
    count_page_transitions, count_repeated_clicks,
)
from worker.schemas import BBox


class MetricsW2Tests(unittest.TestCase):
    def test_fitts_cardinal_diagonal_and_zero_distance(self):
        # Width 100, D=100 => log2(2)=1 in horizontal and vertical approaches.
        box = BBox(x=50, y=-50, width=100, height=100)
        self.assertEqual(fitts_id((0, 0), box), 1)
        self.assertEqual(fitts_id((100, -100), box), 1)
        self.assertEqual(fitts_id((100, 0), box), 0)
        # Center (100,100), D=100sqrt(2), W=100sqrt(2), ID=1.
        diagonal = BBox(x=50, y=50, width=100, height=100)
        self.assertAlmostEqual(fitts_id((0, 0), diagonal), 1)

    def test_fitts_rectangle_and_degenerate_target(self):
        # 3-4-5 direction, D=500; W=min(60/.6,80/.8)=100; log2(6).
        box = BBox(x=270, y=360, width=60, height=80)
        self.assertAlmostEqual(fitts_id((0, 0), box), 2.584962500721156)
        self.assertIsNone(fitts_id((0, 0), BBox(x=0, y=0, width=0, height=10)))
        self.assertEqual(calculate_fitts_ids([]), [])
        self.assertEqual(calculate_fitts_ids([snapshot_at(450, 450)]), [1])

    def test_counts_stop_before_done(self):
        actions = ["click", "type", "type", "scroll", "wait", "back", "select", "done", "click"]
        self.assertEqual(count_interactions(actions), {
            "click_count": 1, "type_count": 2, "step_count": 7, "back_count": 1,
        })
        self.assertEqual(count_interactions([])["step_count"], 0)
        with self.assertRaises(ValueError):
            count_interactions(["tap"])

    def test_no_response_uses_effect_not_any_action(self):
        self.assertEqual(count_no_response_clicks(
            ["click", "type", "click", "done", "click"],
            ["no_change", "no_change", "modal_change", "no_change", "no_change"],
        ), 1)
        with self.assertRaises(ValueError):
            count_no_response_clicks(["click"], [])
        with self.assertRaises(ValueError):
            count_no_response_clicks(["click"], ["unknown"])

    def test_repetition_needs_consecutive_known_target_identity(self):
        self.assertEqual(count_repeated_clicks(["click"] * 3, ["page1:A"] * 3), 2)
        self.assertEqual(count_repeated_clicks(["click", "type", "click"], ["A"] * 3), 0)
        self.assertEqual(count_repeated_clicks(["click"] * 2, [None, None]), 0)
        self.assertEqual(count_repeated_clicks(["click"] * 2, ["page1:1", "page2:1"]), 0)
        with self.assertRaises(ValueError):
            count_repeated_clicks(["click"], [])

    def test_scroll_and_paths_include_initial_and_final_observations(self):
        self.assertEqual(calculate_scroll_distance([0, 300, 100, 100]), 500)
        self.assertEqual(calculate_scroll_distance([]), 0)
        self.assertEqual(calculate_scroll_distance([100]), 0)
        with self.assertRaises(ValueError):
            calculate_scroll_distance([0, float("nan")])
        self.assertEqual(count_page_transitions([
            "https://local/a", "https://local/a?q=2", "https://local/a#part",
            "https://local/b", "https://local/a",
        ]), 2)
