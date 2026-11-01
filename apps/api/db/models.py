"""DB 스키마 v1: 개발계획서 10장 테이블 16개 + 추가 칸 10개.

칸 설명과 근거는 apps/api/db/db-columns.md, enum 값은 apps/api/openapi.yaml과 같게 둔다.
enum은 Postgres 고유 enum 대신 VARCHAR + CHECK로 둔다 (값 추가가 마이그레이션 한 줄로 끝난다).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 제약 이름을 고정해 두면 나중 마이그레이션에서 이름으로 지우고 바꿀 수 있다.
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def enum(name: str, *values: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --- 접근 ---
class AccessCode(Base):
    __tablename__ = "access_code"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True)
    label: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = now()


# --- 측정 요청 ---
class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(Text)
    # 초대 코드별 분리: 이 코드로 요청할 때만 보인다. 코드는 지우지 않고 active=false로 막는다
    owner_id: Mapped[int] = mapped_column(ForeignKey("access_code.id"), index=True)
    created_at: Mapped[datetime] = now()
    daily_run_limit: Mapped[int] = mapped_column(Integer, server_default="10")


class Task(Base):
    __tablename__ = "task"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    success_condition: Mapped[dict | None] = mapped_column(JSONB)
    # credentials_ref: 암호화 저장소가 정해지면 추가 (M3 이후, db-columns.md)


class Run(Base):
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    viewport: Mapped[str] = mapped_column(enum("viewport", "desktop", "mobile"))
    mode: Mapped[str] = mapped_column(enum("mode", "auto", "agent", "replay_only"))
    base_run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    repeat_n: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        enum("status", "queued", "running", "completed", "failed", "canceled"), server_default="queued"
    )
    progress: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, server_default="0")
    created_at: Mapped[datetime] = now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # run ↔ attempt가 서로 가리키므로 테이블을 다 만든 뒤 FK를 건다 (use_alter)
    representative_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempt.id", ondelete="SET NULL", use_alter=True)
    )


# --- 측정 실행 ---
class Attempt(Base):
    __tablename__ = "attempt"
    __table_args__ = (UniqueConstraint("run_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer)  # 1부터
    kind: Mapped[str] = mapped_column(enum("kind", "replay", "agent"))
    replay_status: Mapped[str | None] = mapped_column(enum("replay_status", "full", "partial"))
    diverged_at_step: Mapped[int | None] = mapped_column(Integer)
    # 실행 중에는 아직 끝난 이유·성공 여부가 없다
    end_reason: Mapped[str | None] = mapped_column(
        enum("end_reason", "success", "gave_up", "loop", "budget_exceeded", "blocked", "error", "safety_stop")
    )
    end_detail: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool | None] = mapped_column(Boolean)
    success_estimated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    steps_count: Mapped[int] = mapped_column(Integer, server_default="0")


class Step(Base):
    __tablename__ = "step"
    __table_args__ = (UniqueConstraint("attempt_id", "idx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempt.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)  # 0부터
    action: Mapped[dict] = mapped_column(JSONB)  # worker/schemas.py Action
    thought: Mapped[str] = mapped_column(Text)
    screenshot_key: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    state_hash: Mapped[str] = mapped_column(String(64))
    changed: Mapped[bool] = mapped_column(Boolean)
    effect_type: Mapped[str] = mapped_column(
        enum("effect_type", "url_change", "modal_change", "dom_mutation", "no_change")
    )
    fitts_id: Mapped[float | None] = mapped_column(Float)
    est_seconds: Mapped[float | None] = mapped_column(Float)


class ElementSnapshot(Base):
    __tablename__ = "element_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("step.id", ondelete="CASCADE"), unique=True)
    data: Mapped[dict] = mapped_column(JSONB)  # 검증된 ElementSnapshot 전체
    # 아래는 조회용으로 data에서 꺼내 둔 칸
    bbox: Mapped[dict] = mapped_column(JSONB)
    style: Mapped[dict] = mapped_column(JSONB)
    bg_chain: Mapped[list] = mapped_column(JSONB)
    occluded: Mapped[bool] = mapped_column(Boolean)
    in_first_view: Mapped[bool] = mapped_column(Boolean)
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(String(50))


# --- 결과 ---
class ModelVersion(Base):
    __tablename__ = "model_version"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    version: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    artifact_key: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Metric(Base):
    __tablename__ = "metric"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    # null이면 run 전체 중앙값 행
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempt.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    spread: Mapped[float | None] = mapped_column(Float)
    spread_quality: Mapped[str | None] = mapped_column(enum("spread_quality", "ok", "weak", "pooled"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_version.id", ondelete="SET NULL"))


class Issue(Base):
    __tablename__ = "issue"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String(3))  # R01~R11
    severity: Mapped[str] = mapped_column(enum("severity", "high", "medium", "low"))
    confidence: Mapped[float] = mapped_column(Float)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("step.id", ondelete="SET NULL"))
    element_key: Mapped[str | None] = mapped_column(Text)  # tag|role|name|label_text|landmark
    measured: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    is_reference: Mapped[bool] = mapped_column(Boolean, server_default="false")
    suggestion: Mapped[str | None] = mapped_column(Text)
    score_reason: Mapped[str | None] = mapped_column(Text)


class LlmCall(Base):
    __tablename__ = "llm_call"

    # 칸 이름은 worker/llm/call_log.py JsonlCallLog 항목과 같다
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # worker/llm/base.py Purpose
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = now()


# --- 비교·재생 ---
class Comparison(Base):
    __tablename__ = "comparison"
    __table_args__ = (UniqueConstraint("base_run_id", "target_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    base_run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    target_run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    summary: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = now()


class ElementAlias(Base):
    __tablename__ = "element_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), index=True)
    from_fingerprint: Mapped[dict] = mapped_column(JSONB)
    to_fingerprint: Mapped[dict] = mapped_column(JSONB)
    confirmed_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = now()


# --- 라벨 ---
class IssueLabel(Base):
    __tablename__ = "issue_label"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issue.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(enum("label", "real", "false", "unsure"))
    labeler: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(enum("source", "benchmark", "review"))


# --- 사람 데이터 (9.1) ---
class HumanSession(Base):
    __tablename__ = "human_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_code: Mapped[str] = mapped_column(String(20), index=True)
    page_id: Mapped[str] = mapped_column(String(100))
    device: Mapped[str] = mapped_column(enum("device", "mouse", "trackpad", "touch"))
    viewport: Mapped[dict] = mapped_column(JSONB)  # {"width", "height"}
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed: Mapped[bool] = mapped_column(Boolean)
    daily_computer_hours: Mapped[float] = mapped_column(Float)


class HumanEvent(Base):
    __tablename__ = "human_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 참가자 삭제 요청 시 세션을 지우면 이벤트도 함께 지워진다
    session_id: Mapped[int] = mapped_column(ForeignKey("human_session.id", ondelete="CASCADE"), index=True)
    t_ms: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(
        enum("type", "move", "down", "up", "click", "scroll", "key", "stable")
    )
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    target_key: Mapped[str | None] = mapped_column(Text)
