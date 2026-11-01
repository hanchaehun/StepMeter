"""Hand-calculated cursor distances; reuse the validated snapshot fixture."""

import json
import unittest
from pathlib import Path

from worker.metrics.cursor_distance import calculate_cursor_distance
from worker.schemas import ElementSnapshot


def snapshot_at(x: float, y: float) -> ElementSnapshot:
    fixture = Path(__file__).parent / "fixtures" / "mock" / "element_snapshot.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    data["viewport"] = {"width": 1000, "height": 800}
    data["bbox"] = {"x": x, "y": y, "width": 100, "height": 100}
    data["occluded"] = False
    data["occluder"] = None
    data["in_first_view"] = False
    data["first_view_scroll_px"] = None
    data["nearby_targets"] = []
    return ElementSnapshot.model_validate(data)


class CursorDistanceTests(unittest.TestCase):
    def test_two_snapshots(self):
        snapshots = (snapshot_at(450, 450), snapshot_at(750, 850))
        # (500,400) -> (500,500): 100; -> (800,900): 3-4-5 triangle, 500.
        self.assertEqual(calculate_cursor_distance(snapshots), 600.0)

    def test_single_snapshot(self):
        # Viewport center (500,400) -> target center (500,500): 100 CSS px.
        self.assertEqual(calculate_cursor_distance([snapshot_at(450, 450)]), 100.0)

    def test_empty_list(self):
        self.assertEqual(calculate_cursor_distance([]), 0.0)
