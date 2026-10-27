"""ElementSnapshot 형식 검사 (docs/element_snapshot_spec.md)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from worker.schemas import ElementSnapshot

MOCK = Path(__file__).resolve().parent / "fixtures" / "mock"


def load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


class ElementSnapshotSchemaTests(unittest.TestCase):
    def setUp(self):
        self.snap = load("element_snapshot.json")

    def assert_rejected(self, data):
        with self.assertRaises(ValidationError):
            ElementSnapshot.model_validate(data)

    def changed(self, path, value):
        data = copy.deepcopy(self.snap)
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return data

    def test_mock_is_valid(self):
        snap = ElementSnapshot.model_validate(self.snap)
        self.assertEqual(snap.bbox.center, (160, 720))  # (100 + 120/2, 700 + 40/2)
        self.assertEqual(snap.bg_chain[0].tag, "button")

    def test_numbers_must_be_finite_and_in_range(self):
        for path, value in (
            (("bbox", "width"), -1),
            (("bbox", "x"), float("nan")),
            (("bbox", "y"), float("inf")),
            (("style", "opacity"), 1.5),
            (("style", "font_weight"), 0),
            (("style", "font_size"), -1),
            (("viewport", "width"), 0),
            (("first_view_scroll_px",), -10),
            (("el_id",), 0),
        ):
            with self.subTest(path=path, value=value):
                self.assert_rejected(self.changed(path, value))

    def test_no_type_coercion_or_extra_fields(self):
        self.assert_rejected(self.changed(("el_id",), "4"))
        self.assert_rejected(self.changed(("bbox", "x"), "100"))
        self.assert_rejected(self.changed(("occluded",), 1))
        self.assert_rejected(self.changed(("style", "font_weight"), 700.0))
        self.assert_rejected({**self.snap, "xpath": "/html/body/button"})

    def test_closed_values(self):
        self.assert_rejected(self.changed(("context",), "closed_shadow"))
        self.assert_rejected(self.changed(("landmark",), "header"))
        self.assert_rejected(self.changed(("tag",), "BUTTON"))
        self.assert_rejected(self.changed(("bg_chain",), []))

    def test_occluder_only_when_occluded(self):
        self.assert_rejected(self.changed(("occluded",), False))
        data = self.changed(("occluded",), False)
        data["occluder"] = None
        self.assertFalse(ElementSnapshot.model_validate(data).occluded)

    def test_first_view_element_needs_no_scroll(self):
        self.assert_rejected(self.changed(("first_view_scroll_px",), 50))
        data = self.changed(("in_first_view",), False)
        data["first_view_scroll_px"] = None  # 로드 때 없던 요소
        self.assertIsNone(ElementSnapshot.model_validate(data).first_view_scroll_px)


if __name__ == "__main__":
    unittest.main()
