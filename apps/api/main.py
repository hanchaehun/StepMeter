"""StepMeter API. 요청·응답 형식은 apps/api/openapi.yaml 합의본을 따른다.

실행 (레포 루트): uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
환경 변수: DATABASE_URL, REDIS_URL
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter
from pydantic import field_validator, model_validator
from sqlalchemy import case, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.db.models import AccessCode, Attempt, ElementSnapshot, Issue, Metric, Project, Run, Step, Task
from worker.queue.runs import SCREENSHOT_DIR, cancel_run, enqueue_run

SPEC = yaml.safe_load(Path(__file__).with_name("openapi.yaml").read_text(encoding="utf-8"))

engine = create_engine(os.environ["DATABASE_URL"])
SessionLocal = sessionmaker(engine)

app = FastAPI(title=SPEC["info"]["title"], version=SPEC["info"]["version"])
app.openapi = lambda: SPEC  # type: ignore[method-assign]  # /docs에 합의본을 그대로 보여준다
# 로컬 스크린샷. 워커가 save_screenshot으로 저장한 파일을 그대로 내준다
# ponytail: 초대 코드 확인 없이 무작위 key(uuid4)로만 보호. 스테이징은 R2 서명 URL로 바꾼다 (W2 스크린샷 저장)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOT_DIR, check_dir=False), name="screenshots")


# --- 공통: DB 세션, 초대 코드 ---


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


def hash_code(code: str) -> str:
    """초대 코드 → DB에 저장하는 지문. 서버가 만든 무작위 코드라 salt 없이 sha256 (F17)."""
    return hashlib.sha256(code.encode()).hexdigest()


def current_code(db: DB, x_access_code: Annotated[str | None, Header()] = None) -> int:
    """X-Access-Code를 확인하고 access_code.id를 돌려준다. 없거나 틀리거나 active=false면 401."""
    if x_access_code:
        code_id = db.scalar(
            select(AccessCode.id).where(AccessCode.code_hash == hash_code(x_access_code), AccessCode.active)
        )
        if code_id is not None:
            return code_id
    raise HTTPException(401, "초대 코드가 없거나 틀렸습니다")


Code = Annotated[int, Depends(current_code)]


def own_project(db: Session, code: int, project_id: int) -> Project:
    """요청한 초대 코드의 project만 돌려준다. 없거나 다른 코드 것이면 404 (F17)."""
    p = db.get(Project, project_id)
    if p is None or p.owner_id != code:
        raise HTTPException(404, "프로젝트가 없습니다")
    return p


# --- project ---


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)  # openapi보다 느슨하게 받지 않게 (예: "41" → 41 변환 안 함)

    name: str = Field(min_length=1, max_length=100)
    base_url: str

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        TypeAdapter(AnyHttpUrl).validate_python(v)  # 형식만 검사하고, 저장은 받은 문자열 그대로
        return v


def project_out(p: Project) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "daily_run_limit": p.daily_run_limit,
        "created_at": p.created_at,
    }


def run_summary(db: Session, r: Run) -> dict[str, Any]:
    return {
        "id": r.id,
        "task_id": r.task_id,
        "viewport": r.viewport,
        "status": r.status,
        "created_at": r.created_at,
        "success_count": db.scalar(select(func.count()).where(Attempt.run_id == r.id, Attempt.success)),
        "repeat_n": r.repeat_n,
        "issue_count": db.scalar(select(func.count()).where(Issue.run_id == r.id, Issue.is_reference.is_(False))),
    }


@app.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: DB, code: Code) -> dict[str, Any]:
    p = Project(name=body.name, base_url=body.base_url, owner_id=code)
    db.add(p)
    db.commit()
    db.refresh(p)  # created_at, daily_run_limit는 DB 기본값
    return project_out(p)


@app.get("/projects")
def list_projects(db: DB, code: Code) -> list[dict[str, Any]]:
    # ponytail: 프로젝트마다 쿼리 몇 번(N+1). 프로젝트가 수백 개가 되면 한 쿼리로 합친다
    out = []
    for p in db.scalars(select(Project).where(Project.owner_id == code).order_by(Project.created_at.desc(), Project.id.desc())):
        latest = db.scalar(
            select(Run).join(Task).where(Task.project_id == p.id).order_by(Run.created_at.desc(), Run.id.desc())
        )
        out.append({**project_out(p), "latest_run": run_summary(db, latest) if latest else None})
    return out


# --- task ---


class SuccessCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # 칸을 빼는 건 되고 null은 안 됨 (openapi: type string). 기본값 None은 검사하지 않는다
    url_contains: str = Field(None, min_length=1)  # type: ignore[assignment]
    text_present: str = Field(None, min_length=1)  # type: ignore[assignment]

    @model_validator(mode="after")
    def _at_least_one(self) -> SuccessCondition:
        if self.url_contains is None and self.text_present is None:
            raise ValueError("url_contains, text_present 중 하나는 있어야 합니다")
        return self


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str = Field(min_length=1, max_length=1000)
    success_condition: SuccessCondition | None = None


def task_out(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "project_id": t.project_id,
        "description": t.description,
        "success_condition": t.success_condition,
    }


@app.post("/projects/{id}/tasks", status_code=201)
def create_task(id: int, body: TaskCreate, db: DB, code: Code) -> dict[str, Any]:
    own_project(db, code, id)
    cond = body.success_condition.model_dump(exclude_none=True) if body.success_condition else None
    t = Task(project_id=id, description=body.description, success_condition=cond)
    db.add(t)
    db.commit()
    return task_out(t)


@app.get("/tasks/{id}")
def get_task(id: int, db: DB, code: Code) -> dict[str, Any]:
    return task_out(own_task(db, code, id))


# --- run ---


def own_task(db: Session, code: int, task_id: int) -> Task:
    """요청한 초대 코드의 task만. 없거나 다른 코드 것이면 404 (F17)."""
    t = db.scalar(select(Task).join(Project).where(Task.id == task_id, Project.owner_id == code))
    if t is None:
        raise HTTPException(404, "과업이 없습니다")
    return t


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    viewport: Literal["desktop", "mobile"] = "desktop"
    repeat_n: Literal[3, 5] = 3
    model: Literal["claude-haiku-5-5", "claude-sonnet-5-5"] = "claude-haiku-5-5"
    mode: Literal["auto", "agent", "replay_only"] = "auto"
    base_run_id: int | None = None


def run_out(db: Session, r: Run) -> dict[str, Any]:
    rep = r.representative_attempt_id
    return {
        "id": r.id,
        "task_id": r.task_id,
        "viewport": r.viewport,
        "mode": r.mode,
        "base_run_id": r.base_run_id,
        "repeat_n": r.repeat_n,
        "model": r.model,
        "prompt_version": r.prompt_version,
        "status": r.status,
        "progress": r.progress,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        # DB는 attempt.id, API는 attempt.index (openapi Run.representative_attempt_index)
        "representative_attempt_index": db.scalar(select(Attempt.index).where(Attempt.id == rep)) if rep else None,
    }


@app.post("/tasks/{id}/runs", status_code=202)
def create_run(id: int, body: RunCreate, db: DB, code: Code) -> dict[str, Any]:
    # ponytail: 일일 측정 상한(429, F17)은 W4에서
    own_task(db, code, id)
    if "base_run_id" not in body.model_fields_set:
        # 생략하면 같은 과업·뷰포트의 직전 완료 run (openapi RunCreate.base_run_id)
        base_run_id = db.scalar(
            select(Run.id)
            .where(Run.task_id == id, Run.viewport == body.viewport, Run.status == "completed")
            .order_by(Run.created_at.desc(), Run.id.desc())
        )
    else:
        base_run_id = body.base_run_id
        if base_run_id is not None and db.scalar(select(Run.task_id).where(Run.id == base_run_id)) != id:
            raise HTTPException(404, "기준 run이 없습니다")

    r = Run(
        task_id=id, viewport=body.viewport, mode=body.mode, base_run_id=base_run_id,
        repeat_n=body.repeat_n, model=body.model,
    )
    db.add(r)
    db.commit()  # 워커가 run을 찾을 수 있게 큐에 넣기 전에 저장한다
    try:
        enqueue_run(r.id)
    except Exception:
        # 큐에 못 넣은 run이 queued로 영원히 남지 않게 한다
        r.status, r.finished_at = "failed", func.now()
        db.commit()
        raise HTTPException(500, "측정 작업을 큐에 넣지 못했습니다") from None
    return run_out(db, r)


def own_run(db: Session, code: int, run_id: int) -> Run:
    """요청한 초대 코드의 run만. 없거나 다른 코드 것이면 404 (F17)."""
    r = db.scalar(select(Run).join(Task).join(Project).where(Run.id == run_id, Project.owner_id == code))
    if r is None:
        raise HTTPException(404, "측정이 없습니다")
    return r


def screenshot_url(request: Request, key: str | None) -> str | None:
    return str(request.url_for("screenshots", path=key)) if key else None


@app.get("/runs/{id}")
def get_run(id: int, request: Request, db: DB, code: Code) -> dict[str, Any]:
    r = own_run(db, code, id)
    # 가장 최근에 저장된 step (병렬 실행 중이면 attempt 상관없이 마지막 행)
    latest = db.execute(
        select(Attempt.index, Step.idx, Step.screenshot_key, Step.thought)
        .join(Attempt, Step.attempt_id == Attempt.id)
        .where(Attempt.run_id == id)
        .order_by(Step.id.desc())
        .limit(1)
    ).first()
    return {
        **run_out(db, r),
        "latest_step": {
            "attempt_index": latest.index,
            "idx": latest.idx,
            "screenshot_url": screenshot_url(request, latest.screenshot_key),
            "thought": latest.thought,
        } if latest else None,
    }


# --- report ---


def attempt_out(db: Session, a: Attempt) -> dict[str, Any]:
    return {
        "index": a.index,
        "kind": a.kind,
        "replay_status": a.replay_status,
        "diverged_at_step": a.diverged_at_step,
        "end_reason": a.end_reason,
        "end_detail": a.end_detail,
        "success": a.success,
        "success_estimated": a.success_estimated,
        "steps_count": a.steps_count,  # update_progress가 step을 저장할 때마다 다시 센다
    }


def top_steps(db: Session, r: Run, column: Any) -> list[dict[str, Any]]:
    """대표 경로 attempt에서 column 값이 큰 단계 최대 3개 (openapi Report.top_fitts_steps·slowest_steps)."""
    if r.representative_attempt_id is None:
        return []
    rows = db.execute(
        select(Attempt.index, Step.idx, column)
        .join(Attempt, Step.attempt_id == Attempt.id)
        .where(Step.attempt_id == r.representative_attempt_id, column.is_not(None))
        .order_by(column.desc(), Step.idx)
        .limit(3)
    )
    return [{"attempt_index": n, "idx": idx, "value": v} for n, idx, v in rows]


SEVERITY_ORDER = case({"high": 0, "medium": 1, "low": 2}, value=Issue.severity)


@app.get("/runs/{id}/report")
def get_report(id: int, db: DB, code: Code) -> dict[str, Any]:
    r = own_run(db, code, id)
    if r.status != "completed":
        # queued·running은 진행 중, failed·canceled는 리포트를 만들지 않는다 (openapi NotFinished)
        raise HTTPException(409, "리포트가 없습니다 (측정이 완료되지 않음)")

    # 끝난 attempt(end_reason 있음)만. openapi Attempt.end_reason·success는 null 불가
    attempts = db.scalars(
        select(Attempt).where(Attempt.run_id == id, Attempt.end_reason.is_not(None)).order_by(Attempt.index)
    )
    metrics = db.scalars(select(Metric).where(Metric.run_id == id, Metric.attempt_id.is_(None)).order_by(Metric.id))
    issues = db.execute(
        select(Issue, Attempt.index, Step.idx)
        .outerjoin(Step, Issue.step_id == Step.id)
        .outerjoin(Attempt, Step.attempt_id == Attempt.id)
        .where(Issue.run_id == id)
        .order_by(SEVERITY_ORDER, Issue.confidence.desc(), Issue.id)  # 심각도 → 점수 순 (6.2)
    )
    return {
        "run": run_out(db, r),
        "attempts": [attempt_out(db, a) for a in attempts],
        "metrics": [
            {
                "key": m.key,
                "value": m.value,
                "unit": m.unit,
                "spread": m.spread,
                "spread_quality": m.spread_quality,
                "model_version_id": m.model_version_id,
            }
            for m in metrics
        ],
        "issues": [
            {
                "id": i.id,
                "rule_id": i.rule_id,
                "severity": i.severity,
                "confidence": i.confidence,
                "step": {"attempt_index": n, "idx": idx} if i.step_id is not None else None,
                "element_key": i.element_key,
                "measured": i.measured,
                "threshold": i.threshold,
                "explanation": i.explanation,
                "suggestion": i.suggestion,
                "score_reason": i.score_reason,
                "is_reference": i.is_reference,
            }
            for i, n, idx in issues
        ],
        "top_fitts_steps": top_steps(db, r, Step.fitts_id),
        "slowest_steps": [] if r.viewport == "mobile" else top_steps(db, r, Step.est_seconds),  # 모바일은 빈 배열
    }


# --- steps ---


def step_out(request: Request, st: Step, snapshot: dict | None) -> dict[str, Any]:
    return {
        "idx": st.idx,
        "action": st.action,  # worker/schemas.py Action (thought 포함)
        "url": st.url,
        "screenshot_url": screenshot_url(request, st.screenshot_key),
        "changed": st.changed,
        "effect_type": st.effect_type,
        "fitts_id": st.fitts_id,
        "est_seconds": st.est_seconds,
        "element_snapshot": snapshot,  # click·type·select일 때만 행이 있다
    }


def attempt_steps(db: Session, code: int, run_id: int, n: int, idx: int | None = None) -> list[Any]:
    """run_id의 n번째 attempt의 (step, 스냅샷 data) 목록, idx 오름차순. run·attempt가 없으면 404."""
    own_run(db, code, run_id)
    attempt_id = db.scalar(select(Attempt.id).where(Attempt.run_id == run_id, Attempt.index == n))
    if attempt_id is None:
        raise HTTPException(404, "반복 실행(attempt)이 없습니다")
    q = (
        select(Step, ElementSnapshot.data)
        .outerjoin(ElementSnapshot, ElementSnapshot.step_id == Step.id)
        .where(Step.attempt_id == attempt_id)
        .order_by(Step.idx)
    )
    if idx is not None:
        q = q.where(Step.idx == idx)
    return list(db.execute(q))


@app.get("/runs/{id}/attempts/{n}/steps")
def list_steps(id: int, n: int, request: Request, db: DB, code: Code) -> list[dict[str, Any]]:
    return [step_out(request, st, snap) for st, snap in attempt_steps(db, code, id, n)]


@app.get("/runs/{id}/attempts/{n}/steps/{idx}")
def get_step(id: int, n: int, idx: int, request: Request, db: DB, code: Code) -> dict[str, Any]:
    rows = attempt_steps(db, code, id, n, idx)
    if not rows:
        raise HTTPException(404, "단계가 없습니다")
    return step_out(request, *rows[0])


# --- cancel ---


@app.post("/runs/{id}/cancel", status_code=202)
def cancel(id: int, db: DB, code: Code) -> dict[str, Any]:
    r = own_run(db, code, id)
    # queued면 큐에서도 지운다. 실행 중 워커는 다음 update_progress에서 False를 받고 스스로 멈춘다
    try:
        changed = cancel_run(db, id)
    except Exception:
        db.rollback()  # 큐에서 못 지웠으면 DB 상태도 바꾸지 않는다
        raise HTTPException(500, "큐에 연결하지 못해 취소하지 못했습니다") from None
    if not changed:
        raise HTTPException(409, "이미 끝난 측정입니다")
    db.commit()
    db.refresh(r)
    return run_out(db, r)
