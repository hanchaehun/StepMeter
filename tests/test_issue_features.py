"""Plan §6.2/9.2 arithmetic, written independently of extractor output."""
import math
import unittest
from dataclasses import replace
from pathlib import Path

from ml.issue_clf.features import Observation, extract_features
from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot
from ml.issue_clf.export import build_dataset


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.c = Candidate('R02', 'high', 'Contrast below criterion', 2.9, 4.5, step_id=10)
        self.o = Observation(self.c, 1, '/login|#submit', step_index=1, step_count=3,
                             confusion='Cannot read the text', estimated=False)

    def features(self, *observations):
        return extract_features(observations or [self.o], attempt_ids=[1, 2, 3])

    def test_plan_contrast_example_and_position(self):
        f = self.features()[0]
        self.assertEqual(f.severity, 1)
        self.assertAlmostEqual(f.measured_ratio, 29 / 45)
        self.assertAlmostEqual(f.violation_extent, 16 / 45)
        self.assertEqual(f.path_position, 0.5)
        self.assertEqual(f.detection_ratio, 1 / 3)
        self.assertTrue(f.on_path)
        self.assertTrue(f.confusion)
        self.assertFalse(f.estimated)

    def test_unique_attempt_frequency_not_step_count(self):
        duplicate = replace(self.o, candidate=replace(self.c, step_id=11), step_index=2)
        second = replace(self.o, attempt_id=2)
        other_rule = replace(self.o, candidate=replace(self.c, rule_id='R01'))
        other_target = replace(self.o, target_key='/login|#cancel')
        rows = self.features(self.o, duplicate, second, other_rule, other_target)
        self.assertEqual([r.detection_ratio for r in rows], [2/3, 2/3, 2/3, 1/3, 1/3])

    def test_reference_flag_is_not_path_evidence(self):
        # A low-score path candidate can already be reference=True (ADR 0011).
        path = replace(self.o, candidate=replace(self.c, is_reference=True))
        offpath = Observation(replace(self.c, step_id=None, is_reference=True), 2,
                              self.o.target_key, confusion='not a path step')
        rows = self.features(path, offpath)
        self.assertTrue(rows[0].on_path)
        self.assertFalse(rows[1].on_path)
        self.assertFalse(rows[1].confusion)
        self.assertIsNone(rows[1].path_position)
        self.assertEqual(rows[0].detection_ratio, 1/3)

    def test_zero_threshold_and_missing_measurement_are_unknown(self):
        for c in (replace(self.c, rule_id='R06', measured=420, threshold=0),
                  replace(self.c, measured=None), replace(self.c, threshold=None)):
            f = self.features(replace(self.o, candidate=c, estimated=None))[0]
            self.assertIsNone(f.measured_ratio)
            self.assertIsNone(f.violation_extent)
            self.assertIsNone(f.estimated)

    def test_direction_clipping_and_boolean_rule(self):
        cases = [('R01', 12, 24, 0.5), ('R02', 9, 4.5, 0),
                 ('R07', 6, 4, 0.5), ('R07', 20, 4, 1), ('R04', 1, 1, None)]
        for rule, measured, threshold, extent in cases:
            with self.subTest(rule=rule):
                f = self.features(replace(self.o, candidate=replace(self.c,
                    rule_id=rule, measured=measured, threshold=threshold)))[0]
                self.assertEqual(f.violation_extent, extent)

    def test_snapshot_area_and_single_step_position(self):
        snap = ElementSnapshot.model_validate_json(
            (Path(__file__).parent / 'fixtures/mock/element_snapshot.json').read_text(encoding='utf-8'))
        # Fixed fixture is 120×40 CSS px.
        snap = snap.model_copy(update={'bbox': snap.bbox.model_copy(update={'width': 120.0, 'height': 40.0})})
        f = self.features(replace(self.o, snapshot=snap, step_index=0, step_count=1))[0]
        self.assertEqual(f.area, 4800)
        self.assertEqual(f.role, snap.role)
        self.assertEqual(f.path_position, 0)
        self.assertEqual(len(f.as_dict()), 10)

    def test_invalid_inputs_rejected(self):
        for ids in ([], [1, 1], [True], [0]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                extract_features([self.o], attempt_ids=ids)
        bad = [replace(self.o, attempt_id=9), replace(self.o, target_key=' '),
               replace(self.o, step_index=3), replace(self.o, step_count=0),
               replace(self.o, estimated='yes')]
        bad += [replace(self.o, candidate=replace(self.c, measured=v))
                for v in (-1, math.nan, math.inf, True)]
        for obs in bad:
            with self.subTest(obs=obs), self.assertRaises(ValueError):
                self.features(obs)

    def test_export_keeps_app_groups_failures_and_excludes_replay_denominator(self):
        payload = dict(version=1, app_id='sb-admin-2', case_id='small', run_id=1,
            attempts=[dict(id=1, kind='agent', end_reason='success'),
                      dict(id=2, kind='agent', end_reason='error'),
                      dict(id=3, kind='replay', end_reason='success')],
            observations=[dict(attempt_id=1, target_key='/login|#customCheck',
                candidate=dict(rule_id='R01', severity='high', measured=16, threshold=24, step_id=10))])
        result = build_dataset(payload)
        self.assertEqual(result['app_id'], 'sb-admin-2')
        self.assertEqual(result['rows'][0]['features']['detection_ratio'], 0.5)
        self.assertEqual(result['failed_attempts'], [{'attempt_id': 2, 'end_reason': 'error'}])
        self.assertNotIn('confidence', result['rows'][0]['features'])
        payload['observations'][0]['label'] = 'real'
        with self.assertRaises(ValueError):
            build_dataset(payload)

    def test_export_rejects_holdout_and_unfinished_attempts(self):
        payload = dict(version=1, app_id='sb-admin-2', case_id='small', run_id=1,
                       attempts=[dict(id=1, kind='agent', end_reason=None)], observations=[])
        with self.assertRaises(ValueError):
            build_dataset(payload)
        payload['app_id'] = 'unknown-private-app'
        with self.assertRaises(ValueError):
            build_dataset(payload)
