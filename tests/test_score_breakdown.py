"""rules_only breakdown for rule owners: severity, repeated elements, attempt end reasons.

Hand-computed fixture (units are (case, rule, matched key), convention v1). Each case is
served on its own port, as benchmark.serve does, so unmatched keys differ only by origin:
  app/baseline  :1001 R01 /|nav (low, attempts 1 success + 2 loop)        FP
                      R03 /|x   (high, attempt 2 loop)                    FP
                      R09 /|y   (not one of the six scored rules)         ignored
  app/small     :1002 R01 #a    (high attempt 3 success + low attempt 4)  TP, label
                      R01 /|nav (low, attempt 3 success)                  FP
                      R03 /|x   (high, attempt 4 gave_up)                 FP
  app/inert     :1003 R01 /|nav (high, attempt 5 safety_stop)             FP
                      R03 #b    label, no issue                           FN
  other/baseline :1004 R01 /|nav (low, attempt 6 success)                 FP (other app: other element)
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.async_api import async_playwright

from benchmark.eval import score
from benchmark.score_development import RULES, breakdown, element_key, score_case, step_attempts, write_breakdown

TRUTH = {'app/baseline': [], 'app/small': [{'rule': 'R01', 'target': '#a'}],
         'app/inert': [{'rule': 'R03', 'target': '#b'}], 'other/baseline': []}


def hit(rule, target, severity, attempt, end, measured=None, threshold=None):
    return {'rule': rule, 'target': target, 'severity': severity, 'measured': measured,
            'threshold': threshold, 'attempt_id': attempt, 'end_reason': end}


B, S, I, O = (f'http://127.0.0.1:{port}/' for port in (1001, 1002, 1003, 1004))
ISSUES = {
    'app/baseline': [hit('R01', B+'|nav', 'low', 1, 'success', 30.0, 44.0),
                     hit('R01', B+'|nav', 'low', 2, 'loop', 30.0, 44.0),
                     hit('R03', B+'|x', 'high', 2, 'loop'),
                     hit('R09', B+'|y', 'low', 1, 'success')],
    'app/small': [hit('R01', '#a', 'high', 3, 'success', 20.0, 24.0),
                  hit('R01', '#a', 'low', 4, 'gave_up', 30.0, 44.0),
                  hit('R01', S+'|nav', 'low', 3, 'success', 30.0, 44.0),
                  hit('R03', S+'|x', 'high', 4, 'gave_up')],
    'app/inert': [hit('R01', I+'|nav', 'high', 5, 'safety_stop', 20.0, 24.0)],
    'other/baseline': [hit('R01', O+'|nav', 'low', 6, 'success', 30.0, 44.0)],
}


class ElementKey(unittest.TestCase):
    def test_server_origin_removed_only_from_unmatched_keys(self):
        self.assertEqual(element_key('http://127.0.0.1:49982/sign-in|#email'), '/sign-in|#email')
        self.assertEqual(element_key('http://127.0.0.1:5/#/users|main > a'), '/#/users|main > a')
        self.assertEqual(element_key('#go'), '#go')
        self.assertEqual(element_key('main > button:nth-child(2)'), 'main > button:nth-child(2)')
        self.assertEqual(element_key('unresolved:7'), 'unresolved:7')


class BreakdownNumbers(unittest.TestCase):
    def setUp(self):
        self.data = breakdown(TRUTH, ISSUES)

    def test_totals_match_existing_scorer(self):
        self.assertEqual(self.data['totals']['R01'], {'tp': 1, 'fp': 4, 'fn': 0})
        self.assertEqual(self.data['totals']['R03'], {'tp': 0, 'fp': 2, 'fn': 1})
        for rule in ('R02', 'R04', 'R06', 'R10'):
            self.assertEqual(self.data['totals'][rule], {'tp': 0, 'fp': 0, 'fn': 0})
        self.assertNotIn('R09', self.data['totals'])
        predictions = {case: [{'rule': i['rule'], 'target': i['target']} for i in rows if i['rule'] in RULES]
                       for case, rows in ISSUES.items()}
        scored = score({'split': 'development', 'review_status': 'approved', 'cases': TRUTH},
                       {'split': 'development', 'cases': predictions})['rules']
        for rule, values in scored.items():
            self.assertEqual(self.data['totals'][rule], {k: values[k] for k in ('tp', 'fp', 'fn')})

    def test_severity_split(self):
        zero = {'high': 0, 'medium': 0, 'low': 0, 'none': 0}
        self.assertEqual(self.data['severity']['R01'], {
            'TP': {**zero, 'high': 1}, 'FP': {**zero, 'high': 1, 'low': 3}, 'FN': zero})
        self.assertEqual(self.data['severity']['R03'], {
            'TP': zero, 'FP': {**zero, 'high': 2}, 'FN': {**zero, 'none': 1}})
        self.assertEqual(self.data['mixed_severity']['R01'], {'TP': 1, 'FP': 0})
        self.assertEqual(self.data['mixed_severity']['R03'], {'TP': 0, 'FP': 0})

    def test_repeated_elements(self):
        self.assertEqual(self.data['elements']['R01']['FP'], {
            'elements': 2, 'occurrences': 4, 'cases_per_element': {'1': 1, '3': 1},
            'baseline_only': 1, 'variant_only': 0, 'baseline_and_variant': 1})
        self.assertEqual(self.data['elements']['R01']['TP'], {
            'elements': 1, 'occurrences': 1, 'cases_per_element': {'1': 1},
            'baseline_only': 0, 'variant_only': 1, 'baseline_and_variant': 0})
        self.assertEqual(self.data['elements']['R03']['FP'], {
            'elements': 1, 'occurrences': 2, 'cases_per_element': {'2': 1},
            'baseline_only': 0, 'variant_only': 0, 'baseline_and_variant': 1})
        self.assertEqual(self.data['elements']['R03']['FN'], {
            'elements': 1, 'occurrences': 1, 'cases_per_element': {'1': 1},
            'baseline_only': 0, 'variant_only': 1, 'baseline_and_variant': 0})

    def test_false_positive_end_reasons(self):
        self.assertEqual(self.data['fp_end_reasons']['R01'], {
            'success_only': 2, 'failure_only': 1, 'both': 1,
            'by_end_reason': {'loop': 1, 'safety_stop': 1, 'success': 3}})
        self.assertEqual(self.data['fp_end_reasons']['R03'], {
            'success_only': 0, 'failure_only': 2, 'both': 0,
            'by_end_reason': {'gave_up': 1, 'loop': 1}})

    def test_rows(self):
        rows = self.data['rows']
        self.assertEqual([r['outcome'] for r in rows], ['FP']*6 + ['TP', 'FN'])
        find = {(r['app'], r['case'], r['rule'], r['target']): r for r in rows}
        inert = find[('app', 'inert', 'R01', I+'|nav')]
        self.assertEqual(inert['element'], '/|nav')
        self.assertEqual({k: inert[k] for k in ('baseline', 'severity', 'measured', 'threshold', 'issues', 'attempts',
                                                'end_reasons', 'end_reason_class', 'element_cases',
                                                'element_baseline_cases', 'element_variant_cases')},
                         {'baseline': False, 'severity': 'high', 'measured': [20.0], 'threshold': [24.0],
                          'issues': 1, 'attempts': 1, 'end_reasons': ['safety_stop'],
                          'end_reason_class': 'failure_only', 'element_cases': 3,
                          'element_baseline_cases': 1, 'element_variant_cases': 2})
        base = find[('app', 'baseline', 'R01', B+'|nav')]
        self.assertEqual((base['baseline'], base['issues'], base['attempts'], base['end_reasons'], base['end_reason_class']),
                         (True, 2, 2, ['loop', 'success'], 'both'))
        label = find[('app', 'small', 'R01', '#a')]
        self.assertEqual((label['severity'], label['mixed_severity'], label['measured'], label['threshold']),
                         ('high', True, [20.0, 30.0], [24.0, 44.0]))
        missed = find[('app', 'inert', 'R03', '#b')]
        self.assertEqual((missed['severity'], missed['issues'], missed['end_reasons'], missed['end_reason_class']),
                         ('none', 0, [], None))

    def test_json_and_csv_same_rows_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'run-한글.json'
            write_breakdown(self.data, path, run='run-한글')
            raw = path.with_suffix('.csv').read_bytes()
            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
            with path.with_suffix('.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            stored = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(stored['run'], 'run-한글')
            self.assertEqual(len(rows), len(stored['rows']))
            self.assertEqual({r['run'] for r in rows}, {'run-한글'})
            label = next(r for r in rows if r['target'] == '#a')
            self.assertEqual((label['measured'], label['end_reasons'], label['outcome']), ('20.0;30.0', 'gave_up;success', 'TP'))
            with self.assertRaises(FileExistsError):
                write_breakdown(self.data, path, run='run-한글')


class IssueRowsFromScoring(unittest.IsolatedAsyncioTestCase):
    async def test_score_case_reports_matched_key_per_path_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            location = Path(temp)
            (location/'dom').mkdir()
            (location/'dom/d.html').write_text('<main data-stepmeter-evidence-id="2"><button id="go" data-stepmeter-evidence-id="3">Go</button>'
                                               '<a data-stepmeter-evidence-id="4">Help</a></main>', encoding='utf-8')
            records = [{'issue_id': i, 'target_id': t, 'selector': s, 'screen': 'S', 'dom': 'd.html'}
                       for i, t, s in ((1, '3', '#go'), (2, '4', 'main > a'), (4, '4', 'main > a'))]
            (location/'dom/index.json').write_text(json.dumps(records), encoding='utf-8')
            (location/'labels').mkdir()
            (location/'labels/example.json').write_text(json.dumps({'review_status': 'approved',
                'cases': {'small': [{'rule': 'R01', 'target': '#go'}]}}), encoding='utf-8')
            issues = [SimpleNamespace(id=1, rule_id='R01', step_id=10, is_reference=False, severity='high', measured=20.0, threshold=24.0),
                      SimpleNamespace(id=2, rule_id='R01', step_id=11, is_reference=False, severity='low', measured=30.0, threshold=44.0),
                      SimpleNamespace(id=3, rule_id='R09', step_id=11, is_reference=True, severity='low', measured=None, threshold=None),
                      SimpleNamespace(id=4, rule_id='R01', step_id=None, is_reference=False, severity='low', measured=30.0, threshold=44.0)]
            rows = []
            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                page = await browser.new_page(java_script_enabled=False)
                with patch('benchmark.score_development.ROOT', location):
                    await score_case(page, SimpleNamespace(scalars=lambda _: issues),
                                     {'app_id': 'example', 'label_case': 'small'}, location, 1, issue_rows=rows)
                await browser.close()
        self.assertEqual(rows, [
            {'issue_id': 1, 'rule': 'R01', 'target': '#go', 'step_id': 10, 'severity': 'high', 'measured': 20.0, 'threshold': 24.0},
            {'issue_id': 2, 'rule': 'R01', 'target': 'S|main > a', 'step_id': 11, 'severity': 'low', 'measured': 30.0, 'threshold': 44.0}])


class StepAttempts(unittest.TestCase):
    def test_step_to_attempt_end_reason_for_one_run(self):
        from sqlalchemy import create_engine
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.orm import sessionmaker

        from apps.api.db.models import AccessCode, Attempt, Base, Project, Run, Step, Task

        @compiles(JSONB, 'sqlite')
        def jsonb_sqlite(_type, _compiler, **kw):
            return 'JSON'

        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with sessionmaker(engine).begin() as db:
            owner = AccessCode(code_hash='synthetic', active=False);db.add(owner);db.flush()
            project = Project(owner_id=owner.id, name='Synthetic', base_url='http://example.test/');db.add(project);db.flush()
            task = Task(project_id=project.id, description='Synthetic');db.add(task);db.flush()
            runs = [Run(task_id=task.id, viewport='desktop', mode='agent', repeat_n=3, model='claude-haiku-5-5') for _ in range(2)]
            db.add_all(runs);db.flush()
            attempts = [Attempt(run_id=runs[0].id, index=1, kind='agent', end_reason='success'),
                        Attempt(run_id=runs[0].id, index=2, kind='agent', end_reason='loop'),
                        Attempt(run_id=runs[1].id, index=1, kind='agent', end_reason='gave_up')]
            db.add_all(attempts);db.flush()
            steps = [Step(attempt_id=a.id, idx=0, action={'action': 'click'}, thought='', url='http://example.test/',
                          state_hash='0', changed=False, effect_type='no_change') for a in attempts]
            db.add_all(steps);db.flush()
            expected = {steps[0].id: (attempts[0].id, 'success'), steps[1].id: (attempts[1].id, 'loop')}
            self.assertEqual(step_attempts(db, runs[0].id), expected)
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
