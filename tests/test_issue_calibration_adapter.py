"""Join measured features to the evaluator's approved (rule, actual node) unit."""
import json
import tempfile
import unittest
from pathlib import Path

from playwright.async_api import async_playwright

from benchmark.score_development import score_case
from ml.issue_clf.calibrate import compare
from ml.issue_clf.features import FEATURE_VERSION, Features
from ml.issue_clf.scoring import ScoreConfig
from tests import test_measurement_persistence as fixtures
from worker.rules.candidate import Candidate
from worker.rules.persistence import save_candidates


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.PersistenceTests.setUp

    async def test_captured_node_and_feature_provenance(self):
        issue = save_candidates(self.session, self.run.id, [Candidate(
            'R01', 'high', 'Small target', 12, 24, step_id=self.step.id)], confidence=1)[0]
        feature = Features(1, .5, .5, None, 'checkbox', 144, True, 0, 1/3, False).as_dict()
        case = {'app_id': 'sb-admin-2', 'case_id': 'small', 'label_case': 'small'}
        with tempfile.TemporaryDirectory() as tmp:
            location = Path(tmp)
            (location/'dom').mkdir()
            (location/'dom/1.html').write_text(
                '<input id="customCheck" data-stepmeter-evidence-id="7" type="checkbox">', encoding='utf-8')
            (location/'dom/index.json').write_text(json.dumps([{
                'issue_id': issue.id, 'target_id': '7', 'dom': '1.html',
                'screen': '/login.html', 'selector': '#customCheck'}]), encoding='utf-8')
            features = {'feature_version': FEATURE_VERSION, 'run_id': self.run.id,
                'app_id': 'sb-admin-2', 'case_id': 'small', 'rows': [{
                    'step_id': self.step.id, 'rule_id': 'R01',
                    'target_key': '/login.html|#customCheck', 'features': feature}]}
            (location/'features.json').write_text(json.dumps(features), encoding='utf-8')
            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                try:
                    page = await browser.new_page(java_script_enabled=False)
                    rows = []
                    truth, _, _, unknown = await score_case(page, self.session, case, location,
                                                            self.run.id, calibration_rows=rows)
                    self.assertEqual(unknown, [])
                    self.assertEqual(rows[0]['target'], '#customCheck')
                    self.assertEqual(rows[0]['features'], feature)
                    result = compare({'split': 'development', 'review_status': 'approved',
                        'feature_version': FEATURE_VERSION, 'truth': {'sb-admin-2/small': truth},
                        'cases': {'sb-admin-2/small': rows}}, [ScoreConfig((1,0,0,0,0,0), 1)])
                    self.assertEqual(result['configurations'][0]['scores']['micro']['tp'], 1)
                    features['app_id'] = 'wrong-app'
                    (location/'features.json').write_text(json.dumps(features), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        await score_case(page, self.session, case, location, self.run.id, calibration_rows=[])
                finally:
                    await browser.close()
