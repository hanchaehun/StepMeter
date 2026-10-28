"""Validated agent action requests for the MVP."""

from __future__ import annotations

import json
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


PositiveIndex: TypeAlias = Annotated[int, Field(gt=0, strict=True)]


class ActionInputError(ValueError):
    """Safe parser error that never includes the submitted payload."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    thought: str = Field(min_length=1, max_length=500)
    expectation: str = Field(min_length=1, max_length=500)
    confusion: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("thought", "expectation", "confusion")
    @classmethod
    def reject_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("blank explanation")
        return value


class ClickAction(_ActionBase):
    action: Literal["click"]
    target: PositiveIndex


class TypeAction(_ActionBase):
    action: Literal["type"]
    target: PositiveIndex
    text: str = Field(max_length=4096, repr=False)


class SelectAction(_ActionBase):
    action: Literal["select"]
    target: PositiveIndex
    option: PositiveIndex


class ScrollAction(_ActionBase):
    action: Literal["scroll"]
    direction: Literal["up", "down"]


class BackAction(_ActionBase):
    action: Literal["back"]


class WaitAction(_ActionBase):
    action: Literal["wait"]


class DoneAction(_ActionBase):
    action: Literal["done"]
    reason: Literal["goal_reached", "safety_stop"]


class FailAction(_ActionBase):
    action: Literal["fail"]


ActionRequest: TypeAlias = Annotated[
    ClickAction
    | TypeAction
    | SelectAction
    | ScrollAction
    | BackAction
    | WaitAction
    | DoneAction
    | FailAction,
    Field(discriminator="action"),
]
ACTION_ADAPTER = TypeAdapter(ActionRequest)
ACTION_NAMES = frozenset({"click", "type", "select", "scroll", "back", "wait", "done", "fail"})


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ActionInputError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ActionInputError("invalid_json")


def parse_action_json(payload: str | bytes) -> ActionRequest:
    """Parse one JSON object, rejecting ambiguity and coercion before execution."""

    if not isinstance(payload, (str, bytes)):
        raise ActionInputError("invalid_json")
    try:
        raw = json.loads(payload, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except ActionInputError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, RecursionError):
        raise ActionInputError("invalid_json") from None
    if not isinstance(raw, dict):
        raise ActionInputError("invalid_shape")
    action_name = raw.get("action")
    if not isinstance(action_name, str) or action_name not in ACTION_NAMES:
        raise ActionInputError("invalid_action")
    try:
        return ACTION_ADAPTER.validate_python(raw)
    except ValidationError:
        raise ActionInputError("invalid_fields") from None


# ---------------------------------------------------------------------------
# 측정 훅 ElementSnapshot (수집·매칭 담당, docs/element_snapshot_spec.md)
# ---------------------------------------------------------------------------

FiniteFloat: TypeAlias = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFloat: TypeAlias = Annotated[float, Field(ge=0, allow_inf_nan=False)]
UnitInterval: TypeAlias = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

Landmark: TypeAlias = Literal[
    "banner", "navigation", "main", "complementary", "contentinfo", "search", "form", "region"
]
ElementContext: TypeAlias = Literal["document", "open_shadow", "same_origin_iframe"]


class _SnapshotBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Viewport(_SnapshotBase):
    """뷰포트 크기 (CSS px)."""

    width: PositiveIndex
    height: PositiveIndex


class ScrollPosition(_SnapshotBase):
    """window.scrollX, window.scrollY (CSS px)."""

    x: FiniteFloat
    y: FiniteFloat


class BBox(_SnapshotBase):
    """getBoundingClientRect() 결과. 최상위 뷰포트 기준 좌표 (CSS px)."""

    x: FiniteFloat
    y: FiniteFloat
    width: NonNegativeFloat
    height: NonNegativeFloat

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


class ComputedStyle(_SnapshotBase):
    """getComputedStyle() 값. 색은 브라우저가 돌려준 문자열 그대로 (예: "rgb(0, 0, 0)")."""

    color: str
    background_color: str
    background_image: str
    font_size: NonNegativeFloat  # px
    font_weight: Annotated[int, Field(ge=1, le=1000, strict=True)]
    opacity: UnitInterval


class BackgroundLayer(_SnapshotBase):
    """배경 계보 한 층. 대상 요소 자신부터 위로 올라가며 기록한다."""

    tag: str = Field(min_length=1)
    background_color: str
    background_image: str
    opacity: UnitInterval


class Occluder(_SnapshotBase):
    """대상 중심점을 찍었을 때 대신 잡힌 요소 (쿠키 배너, 채팅 버튼 등)."""

    tag: str = Field(min_length=1)
    role: str | None
    name: str = Field(max_length=1000)
    bbox: BBox


class NearbyTarget(_SnapshotBase):
    """대상 중심에서 48px 안에 들어오는 다른 상호작용 요소 (간격 예외 판정용)."""

    role: str | None
    name: str = Field(max_length=1000)
    bbox: BBox


class ElementSnapshot(_SnapshotBase):
    """click·type 직전 대상 요소에 대해 측정 훅이 저장하는 값 (개발계획서 5.1)."""

    el_id: PositiveIndex
    tag: str = Field(min_length=1)
    role: str | None
    name: str = Field(max_length=1000)
    landmark: Landmark | None
    label_text: str | None = Field(max_length=200)
    inline_in_text: bool
    context: ElementContext
    viewport: Viewport
    scroll: ScrollPosition
    bbox: BBox
    style: ComputedStyle
    bg_chain: list[BackgroundLayer] = Field(min_length=1)
    occluded: bool
    occluder: Occluder | None
    in_first_view: bool
    first_view_scroll_px: NonNegativeFloat | None
    nearby_targets: list[NearbyTarget]

    @field_validator("tag")
    @classmethod
    def lowercase_tag(cls, value: str) -> str:
        if value != value.lower():
            raise ValueError("tag must be lowercase")
        return value

    @model_validator(mode="after")
    def check_consistency(self) -> ElementSnapshot:
        if self.occluder is not None and not self.occluded:
            raise ValueError("occluder without occlusion")
        if self.in_first_view and self.first_view_scroll_px not in (None, 0):
            raise ValueError("first view element needs no scroll")
        return self
