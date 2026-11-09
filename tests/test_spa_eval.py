"""Manual toy arithmetic and independent fixture declarations, not collector output."""
import copy
import unittest

from benchmark.spa_eval import evaluate_state, local_url, summarize, validate_manifest


def item(el_id, x=0, name="A", occluded=False):
    return {"el_id": el_id, "bbox": {"x": x, "y": 0, "width": 20, "height": 20},
            "name": name, "role": "button", "occluded": occluded}


def truth(key="a", x=0, **kwargs):
    return {"key": key, "selector": f"#{key}", "bbox": item(1, x)["bbox"],
            "name": "A", "role": "button", "occluded": False, **kwargs}


class SpaMetricsTests(unittest.TestCase):
    def test_omissions_and_contamination_have_different_denominators(self):
        # 3 expected, 2 correct observed + 1 extra: recall misses 1/3; contamination 1/3.
        result = evaluate_state([truth("a"), truth("b", 40), truth("c", 80)],
                                [item(1), item(2, 40), item(3, 120)])
        self.assertEqual(result["omission_rate"], 1/3)
        self.assertEqual(result["contamination_rate"], 1/3)
        self.assertEqual(result["omitted"], ["c"])
        self.assertEqual(result["unmatched_observed_ids"], [3])

    def test_duplicates_are_ambiguous_not_arbitrarily_matched(self):
        result = evaluate_state([truth()], [item(1), item(2)])
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["ambiguous"], ["a"])
        self.assertFalse(result["thresholds_pass"])

    def test_overlapping_truth_is_ambiguous(self):
        result = evaluate_state([truth("a"), truth("b")], [item(1)])
        self.assertEqual(result["ambiguous"], ["a", "b"])
        self.assertEqual(result["matches"], {})

    def test_names_do_not_drive_matching(self):
        result = evaluate_state([truth()], [item(1, name="Wrong name")])
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["name_role_occlusion_mismatches"][0]["field"], "name")

    def test_occluded_raw_is_not_pollution_and_cap_is_separate(self):
        labels = [truth(str(i), i*30, occluded=(i == 0)) for i in range(33)]
        result = evaluate_state(labels, [item(i+1, i*30, occluded=(i == 0)) for i in range(33)])
        self.assertEqual(result["contamination_rate"], 0)
        self.assertEqual(len(result["unoccluded_ids"]), 32)
        self.assertEqual(len(result["capped_30_ids"]), 30)
        self.assertEqual(result["cap_excluded_count"], 2)

    def test_zero_denominator_is_not_perfect_score(self):
        result = evaluate_state([], [])
        self.assertIsNone(result["omission_rate"])
        self.assertIsNone(result["contamination_rate"])
        self.assertFalse(result["thresholds_pass"])

    def test_excluded_hidden_truth_is_negative_control(self):
        result = evaluate_state([truth(), truth("hidden", 40, include=False)], [item(1), item(2, 40)])
        self.assertEqual(result["expected"], 1)
        self.assertEqual(result["unmatched_observed_ids"], [2])

    def test_loopback_only(self):
        for url in ("http://127.0.0.1:8000/x", "http://localhost/x", "http://[::1]:8000"):
            self.assertEqual(local_url(url), url)
        for url in ("https://example.org", "file:///tmp/a", "http://user:pass@localhost", "http://localhost.evil"):
            with self.assertRaises(ValueError):
                local_url(url)

    def test_review_and_exhaustive_labels_required(self):
        manifest = {"version": 1, "app": {"id": "test", "kind": "synthetic", "revision": "v1"},
                    "viewport": {"width": 800, "height": 600}, "ground_truth_review": {"status": "pending"},
                    "scenarios": [{"id": "a", "exhaustive": True, "truth": [truth()], "path": "/"}]}
        validate_manifest(manifest)
        bad = copy.deepcopy(manifest)
        bad["ground_truth_review"]["status"] = "approved"
        with self.assertRaises(ValueError):
            validate_manifest(bad)
        bad = copy.deepcopy(manifest)
        bad["scenarios"][0]["exhaustive"] = False
        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_pending_truth_never_reports_passed_or_three_spas(self):
        report = {"ground_truth_review": {"status": "pending"}, "scenarios": [{
            "status": "measured", "extraction_ms": 10, "coverage": [], "blocked_external_hosts": [],
            "metrics": evaluate_state([truth()], [item(1)]), "clicks": [{"status": "matched"}]}]}
        summary = summarize(report)
        self.assertEqual(summary["status"], "review_pending")
        self.assertFalse(summary["certifies_three_spas"])
        report["scenarios"][0]["clicks"][0]["status"] = "wrong_target"
        self.assertEqual(summarize(report)["status"], "failed")
