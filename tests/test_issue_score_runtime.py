"""ORM scoring arithmetic: 2 distinct detections / 3 ended agents = 2/3."""
import unittest

from sqlalchemy import select

from apps.api.db.models import Issue, Step
from ml.issue_clf.runtime import finalize_scores, remember
from ml.issue_clf.scoring import ScoreConfig
from tests import test_measurement_persistence as persistence_tests
from worker.agent.persistence import Canceled
from worker.rules.candidate import Candidate
from worker.rules.persistence import save_candidates


class RuntimeTests(unittest.TestCase):
    setUp = persistence_tests.PersistenceTests.setUp

    def test_final_frequency_duplicates_references_and_rollback(self):
        config = ScoreConfig((.2, .2, .2, .2, .1, .1), .65)
        evidence, path_ids = {}, []
        for step in (self.step, Step(attempt_id=self.attempts[0].id, idx=1,
                action={'action': 'click'}, thought='test', url='https://local.invalid',
                state_hash='h', changed=False, effect_type='no_change'),
                Step(attempt_id=self.attempts[1].id, idx=0,
                action={'action': 'click'}, thought='test', url='https://local.invalid',
                state_hash='h', changed=False, effect_type='no_change')):
            self.session.add(step)
            self.session.flush()
            rows = save_candidates(self.session, self.run.id, [Candidate(
                'R01', 'high', '12px vs 24px', 12, 24, step_id=step.id)], confidence=1)
            remember(evidence, rows, ['button:nth-of-type(1)'], step.id)
            path_ids.append(rows[0].id)
        reference = save_candidates(self.session, self.run.id, [Candidate(
            'R09', 'medium', 'reference', is_reference=True, step_id=self.step.id)], confidence=1)[0]
        offpath = save_candidates(self.session, self.run.id, [Candidate(
            'R10', 'high', 'offpath', is_reference=True)], confidence=.9)[0]
        audit = finalize_scores(self.session, self.run.id, config, evidence)
        # .2 + .2*(1-12/24) + .2*(2/3) + .2 = 19/30.
        for row in self.session.scalars(select(Issue).where(Issue.id.in_(path_ids))):
            self.assertAlmostEqual(row.confidence, 19/30)
            self.assertTrue(row.is_reference)
            self.assertIn('finalized n=3', row.score_reason)
        self.assertTrue(reference.is_reference)
        self.assertEqual(offpath.confidence, .9)
        self.assertEqual(audit[0]['features']['detection_ratio'], 2/3)
        self.assertEqual(finalize_scores(self.session, self.run.id, config, evidence), audit)
        self.session.rollback()
        self.assertEqual(len(list(self.session.scalars(select(Issue)))), self.initial_issues)

    def test_unfinished_canceled_and_missing_evidence_do_not_write(self):
        config = ScoreConfig((1, 0, 0, 0, 0, 0), .5)
        issue = save_candidates(self.session, self.run.id, [Candidate(
            'R01', 'high', 'small', step_id=self.step.id)], confidence=1)[0]
        self.attempts[2].end_reason = None
        with self.assertRaises(ValueError):
            finalize_scores(self.session, self.run.id, config, {})
        self.attempts[2].end_reason = 'gave_up'
        with self.assertRaises(ValueError):
            finalize_scores(self.session, self.run.id, config, {})
        self.assertIsNone(issue.score_reason)
        self.run.status = 'canceled'
        with self.assertRaises(Canceled):
            finalize_scores(self.session, self.run.id, config, {})

    def test_axe_uses_actual_selector_and_replay_is_not_scored(self):
        evidence = {}
        for index, attempt in enumerate(self.attempts[:2]):
            step = self.step if index == 0 else Step(attempt_id=attempt.id, idx=0,
                action={'action': 'click'}, thought='test', url='https://local.invalid',
                state_hash='h', changed=False, effect_type='no_change')
            self.session.add(step)
            self.session.flush()
            issue = save_candidates(self.session, self.run.id, [Candidate(
                'R02', 'high', 'Contrast. 대상: ["#actual"]', 2.9, 4.5,
                step_id=step.id, element_key=f'action-{index}')], confidence=1)
            remember(evidence, issue, [f'button-{index}'], step.id)
        replay_step = Step(attempt_id=self.attempts[3].id, idx=0,
            action={'action': 'click'}, thought='test', url='https://local.invalid',
            state_hash='h', changed=False, effect_type='no_change')
        self.session.add(replay_step)
        self.session.flush()
        replay_issue = save_candidates(self.session, self.run.id, [Candidate(
            'R01', 'high', 'Replay', step_id=replay_step.id)], confidence=.91)[0]
        audit = finalize_scores(self.session, self.run.id,
                                ScoreConfig((0,0,1,0,0,0), .7), evidence)
        self.assertEqual(len(audit), 2)
        self.assertTrue(all(row['confidence'] == 2/3 for row in audit))
        self.assertTrue(all(row['features']['role'] is None and row['features']['area'] is None
                            for row in audit))
        self.assertEqual(replay_issue.confidence, .91)
        self.assertIsNone(replay_issue.score_reason)
