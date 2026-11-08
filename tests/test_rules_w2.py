"""Threshold/exception expectations from plan 5.4, 5.7 and chapter 6."""

import unittest

from tests.test_cursor_distance import snapshot_at
from worker.rules import r01, r02, r03, r04, r05, r06, r07, r10
from worker.rules.engine import axe_target_size_result, evaluate_axe, evaluate_step
from worker.schemas import ElementSnapshot


def target(size=20, **changes):
    data = snapshot_at(0, 0).model_dump()
    data.update(bbox={"x": 0, "y": 0, "width": size, "height": size},
                in_first_view=True, first_view_scroll_px=0)
    data.update(changes)
    return ElementSnapshot.model_validate(data)


def neighbor(center_x):
    return {"role": "button", "name": "Other", "bbox": {
        "x": center_x - 10, "y": 0, "width": 20, "height": 20,
    }}


class RulesW2Tests(unittest.TestCase):
    def test_r01_spacing_boundaries_inline_and_recommendation(self):
        # Target center (10,10): distance 23 => overlapping radius-12 circles.
        crowded = target(20, nearby_targets=[neighbor(33)])
        self.assertEqual(r01.evaluate(crowded).severity, "high")
        # Distance 24 => just tangent, spacing exception applies.
        self.assertIsNone(r01.evaluate(target(20, nearby_targets=[neighbor(34)])))
        self.assertIsNone(r01.evaluate(target(20)))
        self.assertIsNone(r01.evaluate(target(20, inline_in_text=True), axe_violation=True))
        self.assertEqual(r01.evaluate(target(24)).severity, "low")
        self.assertEqual(r01.evaluate(target(43), mobile=True).severity, "medium")
        self.assertIsNone(r01.evaluate(target(44)))
        self.assertIsNone(r01.evaluate(crowded, axe_violation=False))
        self.assertEqual(r01.evaluate(target(20), axe_violation=True).severity, "high")

    def test_r02_r10_only_axe_violations(self):
        self.assertEqual(r02.evaluate("color-contrast").rule_id, "R02")
        self.assertIsNone(r02.evaluate("color-contrast-enhanced"))
        for rule in ("button-name", "link-name", "label", "select-name"):
            self.assertEqual(r10.evaluate(rule).rule_id, "R10")
        self.assertIsNone(r10.evaluate("region"))
        self.assertTrue(r10.evaluate("label", is_reference=True).is_reference)

    def test_r03_only_click_and_noise_filtered_no_change(self):
        self.assertEqual(r03.evaluate("click", "no_change").rule_id, "R03")
        for effect in ("dom_mutation", "modal_change", "url_change"):
            self.assertIsNone(r03.evaluate("click", effect))
        self.assertIsNone(r03.evaluate("type", "no_change"))
        with self.assertRaises(ValueError):
            r03.evaluate("click", "unknown")

    def test_r04_and_r05_use_collector_and_core_decisions(self):
        data = target().model_dump()
        data.update(occluded=True, occluder={
            "tag": "div", "role": None, "name": "Banner", "bbox": data["bbox"],
        })
        self.assertEqual(r04.evaluate(ElementSnapshot.model_validate(data)).rule_id, "R04")
        self.assertIsNone(r04.evaluate(target()))
        self.assertEqual(r05.evaluate("loop").severity, "high")
        for reason in (None, "success", "budget_exceeded", "gave_up"):
            self.assertIsNone(r05.evaluate(reason))

    def test_r06_click_target_and_late_element(self):
        outside = target(in_first_view=False, first_view_scroll_px=120)
        self.assertEqual(r06.evaluate(outside).measured, 120)
        self.assertIsNone(r06.evaluate(outside, action="type"))
        self.assertIsNone(r06.evaluate(target()))
        self.assertIsNone(r06.evaluate(target(in_first_view=False, first_view_scroll_px=None)))
        self.assertIsNotNone(r06.evaluate(target(in_first_view=False, first_view_scroll_px=0)))

    def test_r07_top_tenth_width_boundary_ties_and_unmeasurable(self):
        # 10 targets: the largest ID alone is the upper 10%.
        result = r07.evaluate([target(31)] * 10, list(range(1, 11)))
        self.assertEqual([i for i, item in enumerate(result) if item], [9])
        self.assertIsNone(r07.evaluate([target(32)], [10])[0])
        self.assertIsNone(r07.evaluate([target(20)], [0])[0])
        self.assertEqual(r07.evaluate([target(0)], [None]), [None])
        self.assertEqual(len([v for v in r07.evaluate([target()] * 2, [2, 2]) if v]), 2)
        with self.assertRaises(ValueError):
            r07.evaluate([target()], [])
        with self.assertRaises(ValueError):
            r07.evaluate([target()], [float("inf")])

    def test_step_bindings_and_axe_incomplete_not_promoted(self):
        items = evaluate_step(target(44), step_id=12, action="click", effect_type="no_change",
                              is_first_target=True)
        self.assertEqual([item.rule_id for item in items], ["R03"])
        self.assertEqual(items[0].step_id, 12)
        node = {"path_keys": [0], "is_reference": False, "in_viewport": True, "target": ["#a"]}
        results = {"violations": [], "passes": [], "incomplete": [
            {"id": "color-contrast", "nodes": [node]},
        ]}
        self.assertEqual(evaluate_axe(results, {0: 12}), [])
        self.assertIsNone(axe_target_size_result(results, 0))
        results["passes"] = [{"id": "target-size", "nodes": [node]}]
        self.assertFalse(axe_target_size_result(results, 0))
        results["violations"] = [{"id": "button-name", "nodes": [node]}]
        self.assertEqual(evaluate_axe(results, {0: 12}, {12: target()})[0].step_id, 12)
        with self.assertRaises(KeyError):
            evaluate_axe(results, {})
