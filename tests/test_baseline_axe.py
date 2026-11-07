"""axe 결과를 eval.py 예측 형식으로 바꾸는 부분 테스트. 브라우저 없이 손으로 만든 axe 결과를 넣는다."""
import unittest

from benchmark.baseline_axe import normalize_target, to_predictions


def violation(axe_id, *targets):
    return {'id': axe_id, 'nodes': [{'target': t} for t in targets]}


class NormalizeTargetTests(unittest.TestCase):
    def test_plain_selector(self):
        self.assertEqual(normalize_target(['#signup']), '#signup')

    def test_iframe_and_shadow_dom(self):
        self.assertEqual(normalize_target(['iframe', '#confirm']), 'iframe >> #confirm')
        self.assertEqual(normalize_target([['#plans', '#pro']]), '#plans >> #pro')


class ToPredictionsTests(unittest.TestCase):
    def test_axe_rules_become_stepmeter_rules(self):
        predictions, unmapped = to_predictions({
            'baseline': [],
            'contrast': [violation('color-contrast', ['#signup'])],
            'unnamed': [violation('button-name', ['#signup'])],
            'small': [violation('target-size', ['#signup'], ['#help'])],
        })
        self.assertEqual(predictions['split'], 'development')
        self.assertEqual(predictions['cases']['baseline'], [])
        self.assertEqual(predictions['cases']['contrast'], [{'rule': 'R02', 'target': '#signup'}])
        self.assertEqual(predictions['cases']['unnamed'], [{'rule': 'R10', 'target': '#signup'}])
        self.assertEqual(predictions['cases']['small'],
                         [{'rule': 'R01', 'target': '#help'}, {'rule': 'R01', 'target': '#signup'}])
        self.assertEqual(unmapped['small'], [])

    def test_same_finding_on_several_screens_counts_once(self):
        predictions, _ = to_predictions({
            'contrast': [violation('color-contrast', ['#signup']), violation('color-contrast', ['#signup'])]})
        self.assertEqual(predictions['cases']['contrast'], [{'rule': 'R02', 'target': '#signup'}])

    def test_unmapped_axe_rules_are_kept_out_of_predictions(self):
        predictions, unmapped = to_predictions({'baseline': [violation('region', ['main'])]})
        self.assertEqual(predictions['cases']['baseline'], [])
        self.assertEqual(unmapped['baseline'], [{'axe': 'region', 'target': 'main'}])


if __name__ == '__main__':
    unittest.main()
