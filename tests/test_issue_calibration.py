"""Hand-counted toy comparisons; these fixtures are not development results."""
import unittest

from ml.issue_clf.agreement import agreement
from ml.issue_clf.calibrate import compare
from ml.issue_clf.features import FEATURE_VERSION, Features
from ml.issue_clf.scoring import ScoreConfig


class CalibrationTests(unittest.TestCase):
    def test_duplicate_unit_precision_gain_and_recall_loss(self):
        def row(target, severity):
            return {'rule': 'R01', 'target': target, 'was_reference': False,
                    'features': Features(severity, None, None, None, None, None,
                                         True, None, 1/3, False).as_dict()}
        payload = {'split': 'development', 'review_status': 'approved',
                   'feature_version': FEATURE_VERSION,
                   'truth': {'sb-admin-2/small': [{'rule': 'R01', 'target': '#a'},
                                                {'rule': 'R01', 'target': '#b'}],
                             'sb-admin-2/baseline': []},
                   'cases': {'sb-admin-2/small': [row('#a', 1), row('#a', 1), row('#b', .3)],
                             'sb-admin-2/baseline': [row('#false', .6)]},
                   'excluded_cases': {'shadcn-admin/small': {'status': 'unavailable'}}}
        result = compare(payload, [ScoreConfig((1, 0, 0, 0, 0, 0), .8)])
        self.assertEqual(result['rules_only']['micro']['tp'], 2)
        self.assertEqual(result['rules_only']['micro']['fp'], 1)
        self.assertAlmostEqual(result['rules_only']['micro']['precision'], 2/3)
        after = result['configurations'][0]
        self.assertEqual(after['scores']['micro']['precision'], 1)
        self.assertEqual(after['scores']['micro']['recall'], .5)
        self.assertEqual(after['scores']['micro']['fn'], 1)
        self.assertAlmostEqual(after['precision_delta'], 1/3)
        self.assertTrue(after['target_met'])
        self.assertEqual(len(result['excluded_cases']), 1)
        payload['cases']['private/small'] = []
        payload['truth']['private/small'] = []
        with self.assertRaises(ValueError):
            compare(payload, [])

    def test_reference_rows_are_not_in_rules_only_baseline(self):
        # Hand count: one truth #a. Rows: #a (primary) and #ref (rule already marked reference).
        # rules_only = primary candidates only => TP 1, FP 0, precision 1.0.
        # A config that filters nothing keeps #a and drops #ref (was_reference) => precision 1.0.
        # delta 1.0 - 1.0 = 0 => target_met False.
        def row(target, was_reference):
            return {'rule': 'R01', 'target': target, 'was_reference': was_reference,
                    'features': Features(1, None, None, None, None, None,
                                         True, None, 1/3, False).as_dict()}
        payload = {'split': 'development', 'review_status': 'approved',
                   'feature_version': FEATURE_VERSION,
                   'truth': {'sb-admin-2/small': [{'rule': 'R01', 'target': '#a'}]},
                   'cases': {'sb-admin-2/small': [row('#a', False), row('#ref', True)]}}
        keep_all = ScoreConfig((1, 0, 0, 0, 0, 0), 0)
        result = compare(payload, [keep_all])
        self.assertEqual(result['rules_only']['micro']['precision'], 1.0)
        after = result['configurations'][0]
        self.assertEqual(after['scores']['micro']['precision'], 1.0)
        self.assertEqual(after['precision_delta'], 0)
        self.assertFalse(after['target_met'])

    def test_kappa_incomplete_duplicate_and_degenerate(self):
        # Marginals (2,1,1) on both sides. Po=2/4, Pe=6/16 => kappa=1/5.
        rows = [{'issue_id': str(i), 'label_a': a, 'label_b': b} for i, (a,b) in
                enumerate([('real','real'), ('real','false'), ('false','real'), ('unsure','unsure')])]
        self.assertAlmostEqual(agreement(rows)['kappa'], 1/5)
        rows.append({'issue_id': 'missing', 'label_a': '', 'label_b': 'real'})
        self.assertEqual(agreement(rows)['incomplete'], 1)
        self.assertEqual(agreement(rows)['paired'], 4)
        self.assertIsNone(agreement([rows[0]])['kappa'])
        self.assertIsNone(agreement([])['kappa'])
        with self.assertRaises(ValueError):
            agreement([rows[0], rows[0]])
