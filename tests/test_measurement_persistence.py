"""Real ORM transaction tests; TEST_DATABASE_URL also runs them on PostgreSQL.

The default is isolated in-memory SQLite, with JSONB rendered as JSON only in
tests. It verifies values/rollback, not PostgreSQL locks or production migration.
"""

import os
import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from apps.api.db.models import AccessCode, Attempt, Base, Issue, Metric, Project, Run, Step, Task
from worker.metrics.persistence import save_attempt_metrics, save_run_medians
from worker.rules.candidate import Candidate
from worker.rules.persistence import save_candidates


@compiles(JSONB, "sqlite")
def jsonb_for_sqlite(_type, _compiler, **_kw):
    return "JSON"


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ.get("TEST_DATABASE_URL", "sqlite://"))
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        self.initial_issues = self.session.scalar(select(func.count()).select_from(Issue))
        self.initial_metrics = self.session.scalar(select(func.count()).select_from(Metric))
        code = AccessCode(code_hash="w2-transaction-test")
        self.session.add(code)
        self.session.flush()
        project = Project(owner_id=code.id, name="Local test", base_url="https://local.invalid")
        self.session.add(project)
        self.session.flush()
        task = Task(project_id=project.id, description="Local measurement test")
        self.session.add(task)
        self.session.flush()
        self.run = Run(task_id=task.id, viewport="desktop", mode="agent", repeat_n=3,
                       model="fake", status="running")
        self.session.add(self.run)
        self.session.flush()
        self.attempts = []
        for index in range(1, 5):
            attempt = Attempt(run_id=self.run.id, index=index, kind="agent" if index < 4 else "replay",
                              success=index != 3, end_reason="success" if index != 3 else "gave_up",
                              replay_status="full" if index == 4 else None)
            self.session.add(attempt)
            self.attempts.append(attempt)
        self.session.flush()
        self.step = Step(attempt_id=self.attempts[0].id, idx=0, action={"action": "click"},
                         thought="test", url="https://local.invalid", state_hash="state",
                         changed=False, effect_type="no_change")
        self.session.add(self.step)
        self.session.flush()

    def test_attempt_upsert_and_successful_same_kind_median(self):
        # Successful agent counts 2,4 => median 3; failure 100 and replay 900 excluded.
        for attempt, value in zip(self.attempts, (2, 4, 100, 900)):
            save_attempt_metrics(self.session, attempt.id, {"click_count": value})
        first = save_attempt_metrics(self.session, self.attempts[0].id, {"click_count": 2})[0]
        again = save_attempt_metrics(self.session, self.attempts[0].id, {"click_count": 2})[0]
        self.assertEqual(first.id, again.id)
        aggregate = save_run_medians(self.session, self.run.id)
        self.assertEqual([(m.key, m.value, m.unit) for m in aggregate], [("click_count", 3, "count")])
        self.assertIsNone(aggregate[0].attempt_id)
        self.assertIsNone(aggregate[0].spread)
        self.assertEqual(save_run_medians(self.session, self.run.id)[0].id, aggregate[0].id)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Metric)), self.initial_metrics + 5)

    def test_missing_metrics_fail_and_invalid_values_do_not_write(self):
        save_attempt_metrics(self.session, self.attempts[0].id, {"click_count": 2})
        with self.assertRaises(ValueError):
            save_run_medians(self.session, self.run.id)
        for values in ({"invented": 1}, {"click_count": -1}, {"click_count": float("inf")}):
            with self.assertRaises(ValueError):
                save_attempt_metrics(self.session, self.attempts[0].id, values)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Metric)), self.initial_metrics + 1)

    def test_no_success_does_not_fabricate_zero(self):
        for attempt in self.attempts:
            save_attempt_metrics(self.session, attempt.id, {"click_count": 2})
        save_run_medians(self.session, self.run.id)
        for attempt in self.attempts:
            attempt.success = False
        self.assertEqual(save_run_medians(self.session, self.run.id), [])
        aggregates = self.session.scalars(select(Metric).where(
            Metric.run_id == self.run.id, Metric.attempt_id.is_(None),
        )).all()
        self.assertEqual(aggregates, [])

    def test_issue_binding_upsert_and_caller_rollback(self):
        candidate = Candidate("R03", "high", "No response", step_id=self.step.id)
        issue = save_candidates(self.session, self.run.id, [candidate], confidence=0.7)[0]
        again = save_candidates(self.session, self.run.id, [candidate], confidence=0.8)[0]
        self.assertEqual(issue.id, again.id)
        self.assertEqual(again.confidence, 0.8)
        self.assertEqual(again.step_id, self.step.id)
        save_attempt_metrics(self.session, self.attempts[0].id, {"click_count": 1})
        self.session.rollback()
        # Both writes disappear: neither helper committed its caller's transaction.
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Issue)), self.initial_issues)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Metric)), self.initial_metrics)

    def test_issue_rejects_foreign_step_and_invalid_score(self):
        for confidence in (-0.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                save_candidates(self.session, self.run.id, [], confidence=confidence)
        other = Run(task_id=self.run.task_id, viewport="desktop", mode="agent", repeat_n=1, model="fake")
        self.session.add(other)
        self.session.flush()
        with self.assertRaises(ValueError):
            save_candidates(self.session, other.id, [
                Candidate("R03", "high", "wrong run", step_id=self.step.id),
            ], confidence=0.7)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Issue)), self.initial_issues)
