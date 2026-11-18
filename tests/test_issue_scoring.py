"""Independent arithmetic from plan 6.2; test weights are NOT fitted weights."""
import unittest
from dataclasses import replace

from ml.issue_clf.features import Features
from ml.issue_clf.scoring import ScoreConfig, score_features


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.features = Features(1, 2.9/4.5, 1-2.9/4.5, False, 'button', 4800,
                                 True, 0.5, 2/3, True)
        self.config = ScoreConfig((.2, .2, .2, .2, .1, .1), .7)

    def test_plan_weighted_sum(self):
        # .2 + .2*(16/45) + .2*(2/3) + .2 + .1 = 317/450.
        result = score_features(self.features, self.config)
        self.assertAlmostEqual(result.confidence, 317/450)
        self.assertFalse(result.is_reference)
        self.assertIn('severity +0.200', result.score_reason)

    def test_estimate_penalty_and_missing_magnitude(self):
        f = replace(self.features, violation_extent=None, estimated=True)
        # .2 + 0 + 2/15 + .2 + .1 - .1 = 8/15.
        self.assertAlmostEqual(score_features(f, self.config).confidence, 8/15)
        self.assertTrue(score_features(f, self.config).is_reference)

    def test_threshold_equality_keeps_issue_and_reference_is_never_promoted(self):
        config = ScoreConfig((1, 0, 0, 0, 0, 0), .6)
        f = replace(self.features, severity=.6)
        self.assertFalse(score_features(f, config).is_reference)
        self.assertTrue(score_features(f, config, was_reference=True).is_reference)
        self.assertTrue(score_features(replace(f, on_path=False), config).is_reference)

    def test_negative_sum_clamps_and_configuration_is_explicit(self):
        config = ScoreConfig((0, 0, 0, 0, 0, 1), .1)
        self.assertEqual(score_features(replace(self.features, estimated=True), config).confidence, 0)
        self.assertEqual(ScoreConfig.from_dict(self.config.as_dict()), self.config)
        for weights in ((1, 1, 0, 0, 0, 0), (1, 0), (float('nan'), 0, 0, 0, 0, 0)):
            with self.assertRaises(ValueError):
                ScoreConfig(weights, .5)

    def test_invalid_configuration_and_features_are_rejected(self):
        for raw in (None, [], {}, {'scoring_version': 'issue-score-v1',
                                  'weights': [], 'threshold': .5}):
            with self.assertRaises(ValueError):
                ScoreConfig.from_dict(raw)
        for changed in ({'severity': -.1}, {'detection_ratio': float('nan')},
                        {'on_path': 'false'}, {'violation_extent': True}):
            with self.assertRaises(ValueError):
                score_features(replace(self.features, **changed), self.config)
