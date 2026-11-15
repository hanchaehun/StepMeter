"""worker/agent/run.py 병렬 반복 실행 검사 (개발계획서 4.6, 이슈 #55).

기대값은 계획서 4.6에서 가져왔다: 최대 3개 동시 실행, 호출 한도에 걸리면 순차 실행.
한도 뒤에는 실행 중이던 attempt가 모두 끝난 뒤 하나씩 (#58 리뷰), 재생이 끝난 뒤 에이전트 시작 (ADR 0011 8번).
브라우저·LLM 없이 execute_attempt를 "잠깐 기다렸다 끝나는 가짜"로 바꿔 동시에 몇 개가 돌았는지 본다.
SQLite라 PostgreSQL 잠금은 검사하지 않는다 (update_progress는 tests/test_queue.py가 검사).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import AccessCode, Attempt, Base, Project, Run, Task
from worker.agent import run as run_module
from worker.agent.persistence import Canceled


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(_type, _compiler, **kw):
    return "JSON"


class FakePage:
    def set_default_timeout(self, _ms):
        pass

    def set_default_navigation_timeout(self, _ms):
        pass


class FakeContext:
    async def new_page(self):
        return FakePage()

    async def close(self):
        pass


class FakeBrowser:
    async def new_context(self, **_kw):
        return FakeContext()


class ParallelAttemptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.axe = Path(tmp.name) / "axe.min.js"
        self.axe.write_text("")
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        # 후처리는 이 테스트의 관심 밖이라 비운다 (진행률은 running이면 True)
        for target, fake in (
            ("update_progress", lambda session, run_id, finished=False: session.get(Run, run_id).status == "running"),
            ("finalize_run_metrics", lambda session, run_id, kind="agent": None),
            ("save_run_medians", lambda session, run_id, kind="agent": []),
            ("execute_attempt", self.fake_attempt),
        ):
            p = patch.object(run_module, target, fake)
            p.start()
            self.addCleanup(p.stop)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("STEPMETER_MAX_PARALLEL_ATTEMPTS", None)  # 기본값 3으로 검사
        self.running_now, self.max_running = 0, 0
        self.spans: dict[int, tuple[float, float]] = {}  # attempt index → (시작, 끝)
        self.plan: dict[int, dict] = {}  # attempt index → {"seconds", "detail", "cancel"}

    def make_run(self, repeat_n: int, *, replay: bool = False) -> int:
        with self.factory.begin() as s:
            code = AccessCode(code_hash="h")
            s.add(code)
            s.flush()
            project = Project(owner_id=code.id, name="p", base_url="https://a.example")
            s.add(project)
            s.flush()
            task = Task(project_id=project.id, description="t")
            s.add(task)
            s.flush()
            base_id = None
            if replay:
                # 재생 조건(run.py): 같은 과업·화면 크기의 completed 기준 run과 대표 attempt
                base = Run(task_id=task.id, mode="agent", viewport="desktop", repeat_n=1, model="fake",
                           status="completed")
                s.add(base)
                s.flush()
                path = Attempt(run_id=base.id, index=1, kind="agent", end_reason="success", success=True)
                s.add(path)
                s.flush()
                base.representative_attempt_id, base_id = path.id, base.id
            run = Run(task_id=task.id, mode="auto" if replay else "agent", base_run_id=base_id,
                      viewport="desktop", repeat_n=repeat_n, model="fake", status="queued")
            s.add(run)
            s.flush()
            return run.id

    async def fake_attempt(self, page, factory, config, attempt_id, adapter, *, axe_path, evidence_sink=None):
        with factory() as s:
            index = s.get(Attempt, attempt_id).index
        plan = self.plan.get(index, {})
        loop = asyncio.get_running_loop()
        start = loop.time()
        self.running_now += 1
        self.max_running = max(self.max_running, self.running_now)
        try:
            await asyncio.sleep(plan.get("seconds", 0.05))
            if plan.get("cancel"):
                with factory.begin() as s:
                    s.get(Run, config["id"]).status = "canceled"
                raise Canceled()
            with factory.begin() as s:
                attempt = s.get(Attempt, attempt_id)
                attempt.end_reason, attempt.success = ("error", False) if plan.get("detail") else ("gave_up", False)
                attempt.end_detail = plan.get("detail")
        finally:
            self.running_now -= 1
            self.spans[index] = (start, loop.time())

    async def fake_replay(self, page, factory, config, attempt_id, base_attempt_id, *, axe_path):
        # 재생이 첫 행동에서 끊긴 것처럼 (replay_status=partial) 끝낸다
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.sleep(0.1)
        with factory.begin() as s:
            attempt = s.get(Attempt, attempt_id)
            attempt.replay_status, attempt.diverged_at_step = "partial", 0
            attempt.end_reason, attempt.success = "gave_up", False
        self.replay_span = (start, loop.time())
        return False

    async def execute(self, run_id: int) -> None:
        await run_module.execute_run(run_id, self.factory, adapter_factory=lambda _model: None,
                                     browser=FakeBrowser(), axe_path=self.axe)

    def run_state(self, run_id: int) -> tuple[str, list[int]]:
        with self.factory() as s:
            indexes = list(s.scalars(select(Attempt.index).where(Attempt.run_id == run_id).order_by(Attempt.index)))
            return s.get(Run, run_id).status, indexes

    async def test_three_attempts_run_at_once(self):
        run_id = self.make_run(repeat_n=3)
        await self.execute(run_id)
        self.assertEqual(self.max_running, 3)  # 4.6: 3회를 동시에
        self.assertEqual(self.run_state(run_id), ("completed", [1, 2, 3]))

    async def test_five_attempts_at_most_three_at_once(self):
        run_id = self.make_run(repeat_n=5)
        await self.execute(run_id)
        self.assertEqual(self.max_running, 3)  # 4.6: 최대 3개
        self.assertEqual(self.run_state(run_id), ("completed", [1, 2, 3, 4, 5]))

    async def test_after_rate_limit_later_attempts_one_by_one(self):
        # 1번이 먼저 한도로 실패 → 그 뒤 시작하는 4·5번은 서로 겹치지 않는다 (4.6 "순차 실행으로 바꾼다")
        run_id = self.make_run(repeat_n=5)
        self.plan[1] = {"seconds": 0.01, "detail": "LLMRateLimitError"}
        await self.execute(run_id)
        (start4, end4), (start5, end5) = self.spans[4], self.spans[5]
        self.assertTrue(end4 <= start5 or end5 <= start4, self.spans)
        self.assertEqual(self.run_state(run_id), ("completed", [1, 2, 3, 4, 5]))

    async def test_without_rate_limit_later_attempts_overlap(self):
        # 대조군: 한도 실패가 없으면 4·5번은 다른 attempt와 겹쳐 돈다 (위 테스트가 우연히 통과하지 않게)
        run_id = self.make_run(repeat_n=5)
        self.plan[1] = {"seconds": 0.01}
        self.plan[2] = {"seconds": 0.01}
        await self.execute(run_id)
        (start4, end4), (start5, end5) = self.spans[4], self.spans[5]
        self.assertTrue(start5 < end4 and start4 < end5, self.spans)

    async def test_cancel_stops_run_without_completing(self):
        run_id = self.make_run(repeat_n=3)
        self.plan[2] = {"seconds": 0.01, "cancel": True}
        await self.execute(run_id)  # Canceled는 밖으로 나오지 않는다
        status, indexes = self.run_state(run_id)
        self.assertEqual(status, "canceled")  # completed로 덮어쓰지 않음
        self.assertEqual(indexes, [1, 2, 3])

    async def test_after_rate_limit_waits_for_running_attempts_then_one_by_one(self):
        # 리뷰(#58): 1번이 한도로 먼저 끝나도 2·3번이 실행 중이면 4번은 시작하지 않는다.
        # 2·3번이 모두 끝난 뒤 4번 → 5번을 하나씩 (계획서 4.6 "순차 실행으로 바꾼다")
        run_id = self.make_run(repeat_n=5)
        self.plan[1] = {"seconds": 0.01, "detail": "LLMRateLimitError"}
        self.plan[2] = {"seconds": 0.15}
        self.plan[3] = {"seconds": 0.2}
        await self.execute(run_id)
        spans = self.spans
        self.assertGreaterEqual(spans[4][0], max(spans[2][1], spans[3][1]), spans)  # 2·3번 종료 뒤 4번 시작
        self.assertGreaterEqual(spans[5][0], spans[4][1], spans)  # 4번 종료 뒤 5번 시작
        self.assertEqual(self.run_state(run_id), ("completed", [1, 2, 3, 4, 5]))  # 1번은 다시 재지 않음

    async def test_interrupted_replay_then_parallel_agent_attempts(self):
        # ADR 0011 8번: 재생 1회가 끝난 뒤에 에이전트 repeat_n회가 시작하고, 그 에이전트 attempt는 병렬
        run_id = self.make_run(repeat_n=3, replay=True)
        with patch.object(run_module, "execute_replay", self.fake_replay):
            await self.execute(run_id)
        replay_end = self.replay_span[1]
        self.assertTrue(all(start >= replay_end for start, _ in self.spans.values()), (self.replay_span, self.spans))
        self.assertEqual(self.max_running, 3)
        self.assertEqual(self.run_state(run_id), ("completed", [1, 2, 3, 4]))  # 1 = 재생, 2~4 = 에이전트
        with self.factory() as s:
            kinds = list(s.scalars(select(Attempt.kind).where(Attempt.run_id == run_id).order_by(Attempt.index)))
        self.assertEqual(kinds, ["replay", "agent", "agent", "agent"])

    async def test_max_parallel_one_runs_sequentially(self):
        os.environ["STEPMETER_MAX_PARALLEL_ATTEMPTS"] = "1"
        run_id = self.make_run(repeat_n=3)
        await self.execute(run_id)
        self.assertEqual(self.max_running, 1)
        spans = [self.spans[i] for i in (1, 2, 3)]
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), spans)
        self.assertEqual(self.run_state(run_id), ("completed", [1, 2, 3]))

    def test_max_parallel_setting_range(self):
        # 기본 3, 1~3 밖이면 가까운 끝으로, 숫자가 아니면 기본값
        for value, expected in ((None, 3), ("1", 1), ("2", 2), ("3", 3), ("0", 1), ("9", 3), ("x", 3)):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop("STEPMETER_MAX_PARALLEL_ATTEMPTS", None)
                else:
                    os.environ["STEPMETER_MAX_PARALLEL_ATTEMPTS"] = value
                self.assertEqual(run_module.max_parallel_attempts(), expected)


if __name__ == "__main__":
    unittest.main()
