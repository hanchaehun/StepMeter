"""Validated agent action requests for the MVP."""

from __future__ import annotations

import json
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator


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
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
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
