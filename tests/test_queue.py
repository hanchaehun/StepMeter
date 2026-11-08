"""worker/queue/runs.py 검사. 기대값은 docs/worker_api_spec.md 2번 계산식으로 손계산했다.

DB·Redis를 비우므로 테스트 전용 주소를 준다. 없으면 해당 테스트를 건너뛴다.
    TEST_DATABASE_URL=postgresql+psycopg://stepmeter:stepmeter@localhost:5434/stepmeter_test
    TEST_REDIS_URL=redis://localhost:6379/15
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker.queue import runs

DB_URL = os.environ.get("TEST_DATABASE_URL")
REDIS_URL = os.environ.get("TEST_REDIS_URL")
INI = Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic.ini"


class ScreenshotTests(unittest.TestCase):
    def test_saves_bytes_and_returns_new_key(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runs, "SCREENSHOT_DIR", Path(d)):
            a = runs.save_screenshot(b"png-a")
            b = runs.save_screenshot(b"png-b")
            self.assertNotEqual(a, b)
            self.assertTrue(a.endswith(".png"))
            self.assertEqual((Path(d) / a).read_bytes(), b"png-a")


@unittest.skipUnless(DB_URL, "TEST_DATABASE_URL 없음")
class DbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        os.environ["DATABASE_URL"] = DB_URL
        cfg = Config(str(INI))
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        cls.engine = create_engine(DB_URL)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as c:
            c.exec_driver_sql("TRUNCATE access_code RESTART IDENTITY CASCADE")
            c.exec_driver_sql("INSERT INTO access_code (code_hash) VALUES ('h')")
            c.exec_driver_sql("INSERT INTO project (name, base_url, owner_id) VALUES ('p', 'https://a.example', 1)")
            c.exec_driver_sql("INSERT INTO task (project_id, description) VALUES (1, 't')")

    def sql(self, q: str, **params):
        from sqlalchemy import text

        with self.engine.begin() as c:
            result = c.execute(text(q), params)
            return result.first() if result.returns_rows else None

    def make_run(self, status: str = "running", progress: int = 0, repeat_n: int = 3) -> int:
        return self.sql(
            "INSERT INTO run (task_id, viewport, mode, repeat_n, model, status, progress) "
            "VALUES (1, 'desktop', 'agent', :n, 'claude-haiku-5-5', :s, :p) RETURNING id",
            n=repeat_n, s=status, p=progress,
        )[0]

    def add_attempt(self, run_id: int, index: int, steps: int, end_reason: str | None = None) -> None:
        attempt = self.sql(
            "INSERT INTO attempt (run_id, index, kind, end_reason) VALUES (:r, :i, 'agent', :e) RETURNING id",
            r=run_id, i=index, e=end_reason,
        )[0]
        for idx in range(steps):
            self.sql(
                "INSERT INTO step (attempt_id, idx, action, thought, url, state_hash, changed, effect_type) "
                "VALUES (:a, :i, '{}', 't', 'https://a.example', 'h', true, 'no_change')",
                a=attempt, i=idx,
            )

    def update(self, run_id: int, **kw) -> bool:
        from sqlalchemy.orm import Session

        with Session(self.engine) as s, s.begin():
            return runs.update_progress(s, run_id, **kw)

    def cancel(self, run_id: int) -> bool:
        from sqlalchemy.orm import Session

        with Session(self.engine) as s, s.begin():
            return runs.cancel_run(s, run_id)

    def run_row(self, run_id: int):
        return self.sql("SELECT status, progress, finished_at FROM run WHERE id = :id", id=run_id)

    # --- 진행률 ---
    def test_finished_and_open_attempts(self):
        # floor(90 × (1 + 15/30) / 3) = 45
        r = self.make_run()
        self.add_attempt(r, 1, steps=12, end_reason="success")
        self.add_attempt(r, 2, steps=15)
        self.assertTrue(self.update(r))
        self.assertEqual(self.run_row(r).progress, 45)

    def test_three_parallel_open_attempts(self):
        # floor(90 × (10/30 × 3) / 3) = 30
        r = self.make_run()
        for i in (1, 2, 3):
            self.add_attempt(r, i, steps=10)
        self.update(r)
        self.assertEqual(self.run_row(r).progress, 30)

    def test_open_attempt_steps_capped_at_30(self):
        # 31 step이어도 30으로 자름: floor(90 × 1 / 3) = 30
        r = self.make_run()
        self.add_attempt(r, 1, steps=31)
        self.update(r)
        self.assertEqual(self.run_row(r).progress, 30)

    def test_never_decreases(self):
        # 새 계산 45 < 기존 50 → 50 유지
        r = self.make_run(progress=50)
        self.add_attempt(r, 1, steps=0, end_reason="success")
        self.add_attempt(r, 2, steps=15)
        self.update(r)
        self.assertEqual(self.run_row(r).progress, 50)

    def test_finished_sets_100(self):
        r = self.make_run()
        self.update(r, finished=True)
        self.assertEqual(self.run_row(r).progress, 100)

    def test_not_running_returns_false_and_keeps_progress(self):
        r = self.make_run(status="completed", progress=70)
        self.add_attempt(r, 1, steps=30, end_reason="success")
        self.assertFalse(self.update(r))
        self.assertEqual(self.run_row(r).progress, 70)

    # --- attempt.steps_count ---
    def steps_counts(self, run_id: int) -> list[int]:
        from sqlalchemy import text

        with self.engine.connect() as c:
            q = "SELECT steps_count FROM attempt WHERE run_id = :r ORDER BY index"
            return [row[0] for row in c.execute(text(q), {"r": run_id})]

    def test_steps_count_per_attempt_including_finished(self):
        # 병렬 3회: attempt마다 자기 step 행 수. 끝난 attempt(마지막 step과 종료가 같은 트랜잭션)도 센다
        r = self.make_run()
        self.add_attempt(r, 1, steps=12, end_reason="success")
        self.add_attempt(r, 2, steps=7)
        self.add_attempt(r, 3, steps=0)
        self.update(r)
        self.assertEqual(self.steps_counts(r), [12, 7, 0])

    def test_steps_count_same_after_repeated_calls(self):
        # 다시 세서 덮어쓰므로 여러 번 불러도 같다 (+1이 아님)
        r = self.make_run()
        self.add_attempt(r, 1, steps=5)
        for _ in range(3):
            self.update(r)
        self.assertEqual(self.steps_counts(r), [5])

    def test_steps_count_updated_after_cancel(self):
        # 취소된 run: 진행률은 그대로(False)지만 step 수는 실제 값으로
        r = self.make_run(status="canceled", progress=20)
        self.add_attempt(r, 1, steps=4)
        self.assertFalse(self.update(r))
        self.assertEqual((self.run_row(r).progress, self.steps_counts(r)), (20, [4]))

    def test_steps_count_parallel_workers(self):
        # 실제 병렬: attempt 3개가 각자 트랜잭션에서 step 저장 + update_progress를 20번씩. 교착 없이 20, 20, 20
        from concurrent.futures import ThreadPoolExecutor

        from sqlalchemy import text
        from sqlalchemy.orm import Session

        r = self.make_run()
        attempts = []
        for i in (1, 2, 3):
            self.add_attempt(r, i, steps=0)
            attempts.append(self.sql("SELECT id FROM attempt WHERE run_id = :r AND index = :i", r=r, i=i)[0])

        def worker(attempt_id: int) -> None:
            for idx in range(20):
                with Session(self.engine) as s, s.begin():
                    s.execute(
                        text(
                            "INSERT INTO step (attempt_id, idx, action, thought, url, state_hash, changed, effect_type) "
                            "VALUES (:a, :i, '{}', 't', 'https://a.example', 'h', true, 'no_change')"
                        ),
                        {"a": attempt_id, "i": idx},
                    )
                    runs.update_progress(s, r)

        with ThreadPoolExecutor(3) as pool:
            list(pool.map(worker, attempts))
        self.assertEqual(self.steps_counts(r), [20, 20, 20])

    def test_steps_count_only_this_run(self):
        r, other = self.make_run(), self.make_run()
        self.add_attempt(r, 1, steps=3)
        self.add_attempt(other, 1, steps=6)
        self.update(r)
        self.assertEqual((self.steps_counts(r), self.steps_counts(other)), ([3], [0]))

    # --- 취소 ---
    def test_cancel_running(self):
        r = self.make_run(progress=20)
        with mock.patch.object(runs.Queue, "remove"):
            self.assertTrue(self.cancel(r))
        row = self.run_row(r)
        self.assertEqual(row.status, "canceled")
        self.assertIsNotNone(row.finished_at)
        # 워커는 진행 중 step을 저장한 뒤 False를 받고 멈춘다
        self.add_attempt(r, 1, steps=15)
        self.assertFalse(self.update(r))
        self.assertEqual(self.run_row(r).progress, 20)

    def test_cancel_completed_does_nothing(self):
        r = self.make_run(status="completed")
        self.assertFalse(self.cancel(r))
        self.assertEqual(self.run_row(r).status, "completed")
        self.assertIsNone(self.run_row(r).finished_at)

    def test_job_failure_marks_running_run_failed(self):
        # 워커 함수가 예외로 끝나거나 30분을 넘기면 RQ가 부르는 콜백
        r = self.make_run()
        runs._mark_failed(mock.Mock(args=(r,)), None, None, None, None)
        self.assertEqual(self.run_row(r).status, "failed")
        self.assertIsNotNone(self.run_row(r).finished_at)

    @unittest.skipUnless(REDIS_URL, "TEST_REDIS_URL 없음")
    def test_cancel_queued_removes_job(self):
        from redis import Redis
        from rq import Queue

        os.environ["REDIS_URL"] = REDIS_URL
        Redis.from_url(REDIS_URL).flushdb()
        r = self.make_run(status="queued")
        runs.enqueue_run(r)
        self.assertTrue(self.cancel(r))
        self.assertEqual(self.run_row(r).status, "canceled")
        self.assertNotIn(f"run-{r}", Queue("runs", connection=Redis.from_url(REDIS_URL)).job_ids)


@unittest.skipUnless(REDIS_URL, "TEST_REDIS_URL 없음")
class EnqueueTests(unittest.TestCase):
    def test_enqueue_puts_only_run_id(self):
        from redis import Redis
        from rq import Queue
        from rq.job import Job

        os.environ["REDIS_URL"] = REDIS_URL
        conn = Redis.from_url(REDIS_URL)
        conn.flushdb()
        runs.enqueue_run(7)
        self.assertEqual(Queue("runs", connection=conn).job_ids, ["run-7"])
        job = Job.fetch("run-7", connection=conn)
        self.assertEqual(tuple(job.args), (7,))
        self.assertEqual(job.timeout, 1800)


if __name__ == "__main__":
    unittest.main()
