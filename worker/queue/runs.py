"""측정 작업 큐 (docs/worker_api_spec.md).

큐에는 run_id만 넣는다. 진행률·상태 등 나머지는 모두 DB로 주고받는다.
session을 받는 함수는 commit하지 않는다. 부르는 쪽이 자기 트랜잭션에서 commit한다.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from redis import Redis
from rq import Callback, Queue
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

QUEUE_NAME = "runs"
JOB_TIMEOUT = 30 * 60  # 1회 약 5분 × 3회 병렬 + 여유 (개발계획서 4.6)
STEPS_PER_ATTEMPT = 30  # 실행 1회 step 상한 (4.5)
# 큐가 부를 워커 함수. 이름은 에이전트 코어와 맞춘다 (가칭)
JOB_FUNC = "worker.agent.run.run"
SCREENSHOT_DIR = Path("data/screenshots")


def _redis() -> Redis:
    return Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _job_id(run_id: int) -> str:
    return f"run-{run_id}"


def enqueue_run(run_id: int) -> None:
    Queue(QUEUE_NAME, connection=_redis()).enqueue(
        JOB_FUNC,
        run_id,
        job_id=_job_id(run_id),
        job_timeout=JOB_TIMEOUT,
        on_failure=Callback(_mark_failed),
    )


def _mark_failed(job, connection, exc_type, exc_value, tb) -> None:
    """워커 함수가 예외로 끝나거나 제한 시간을 넘기면 RQ가 부른다."""
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE run SET status = 'failed', finished_at = now() WHERE id = :id AND status = 'running'"),
                {"id": job.args[0]},
            )
    finally:
        engine.dispose()


def cancel_run(session: Session, run_id: int) -> bool:
    """queued·running인 run을 canceled로 바꾼다. 바꿨으면 True.

    실행 중인 워커는 강제로 끄지 않는다. 진행 중 step을 끝내고 update_progress가
    False를 돌려주면 스스로 멈춘다.
    """
    changed = session.execute(
        text(
            "UPDATE run SET status = 'canceled', finished_at = now() "
            "WHERE id = :id AND status IN ('queued', 'running') RETURNING id"
        ),
        {"id": run_id},
    ).first()
    if changed:
        # 아직 꺼내지 않은 작업이면 큐에서 뺀다. 이미 꺼냈으면 아무 일도 없다
        Queue(QUEUE_NAME, connection=_redis()).remove(_job_id(run_id))
    return changed is not None


def update_progress(session: Session, run_id: int, finished: bool = False) -> bool:
    """step 행을 모아 run.progress를 한 문장으로 다시 계산한다. run이 running이면 True.

    floor(90 × (끝난 attempt 수 + Σ 진행 중 attempt의 step 수 ÷ 30) ÷ repeat_n),
    finished=True(후처리까지 끝남)면 100. 이전 값보다 작아지지 않는다.
    워커는 step 행을 추가한 같은 트랜잭션에서 부르고, False면 멈춘다(취소됨).
    같이 그 run의 모든 attempt.steps_count를 실제 step 행 수로 다시 센다 (run 상태와 상관없이).
    """
    # 병렬 attempt가 동시에 불러도 한 번에 하나씩: run 행을 먼저 잠근다.
    # NO KEY UPDATE라 다른 트랜잭션의 attempt 추가(run FK)는 막지 않는다
    session.execute(text("SELECT id FROM run WHERE id = :id FOR NO KEY UPDATE"), {"id": run_id})
    # 끝난 attempt도 센다: 마지막 step 저장과 end_reason 기록이 같은 트랜잭션일 수 있다
    session.execute(
        text(
            "UPDATE attempt SET steps_count = (SELECT count(*) FROM step s WHERE s.attempt_id = attempt.id) "
            "WHERE run_id = :id"
        ),
        {"id": run_id},
    )
    row = session.execute(
        text(
            """
            UPDATE run SET progress = GREATEST(run.progress, CASE WHEN :finished THEN 100 ELSE LEAST(90, floor(
                90 * (
                    (SELECT count(*) FROM attempt a WHERE a.run_id = run.id AND a.end_reason IS NOT NULL)
                    + (SELECT coalesce(sum(LEAST(n, :cap)), 0) FROM (
                        SELECT count(s.id) AS n FROM attempt a JOIN step s ON s.attempt_id = a.id
                        WHERE a.run_id = run.id AND a.end_reason IS NULL GROUP BY a.id
                      ) open_steps) / CAST(:cap AS numeric)
                ) / run.repeat_n
            )) END)
            WHERE id = :id AND status = 'running'
            RETURNING id
            """
        ),
        {"id": run_id, "finished": finished, "cap": STEPS_PER_ATTEMPT},
    ).first()
    return row is not None


def save_screenshot(data: bytes) -> str:
    """스크린샷을 저장하고 key를 돌려준다. 워커는 key를 step.screenshot_key에 적는다.

    ponytail: 로컬 디스크만. 스테이징·운영의 R2 전환은 W2 "스크린샷 저장"에서
    """
    key = f"{uuid.uuid4().hex}.png"
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SCREENSHOT_DIR / key).write_bytes(data)
    return key
