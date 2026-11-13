"""Read-only click extraction and down/up supplementation for HumanEvent records."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

MAX_CLICK_MATCH_MS = 500
MAX_SUPPLEMENT_DURATION_MS = 1000
MAX_POINTER_DISTANCE_PX = 5.0

VALID_EVENT_TYPES = frozenset({"move", "down", "up", "click", "scroll", "key", "stable"})
BOUNDARY_TYPES = frozenset({"down", "key", "scroll"})
GESTURE_BREAKER_TYPES = frozenset({"key", "scroll"})
POINTER_POSITION_TYPES = frozenset({"move", "click"})

TargetSource = Literal["click", "up", "target_from_down", "unknown"]
Point = tuple[int | float, int | float]


def _validate_number(value: Any, *, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Event {field} must be a finite number")
    return value


def _validate_optional_number(value: Any, *, field: str) -> int | float | None:
    if value is None:
        return None
    return _validate_number(value, field=field)


def _point(event: Mapping[str, Any]) -> Point | None:
    x = _validate_optional_number(event.get("x"), field="x")
    y = _validate_optional_number(event.get("y"), field="y")
    if x is None or y is None:
        return None
    return (x, y)


def _validate_events(events: Sequence[Mapping[str, Any]]) -> None:
    previous = -1.0
    for event in events:
        timestamp = _validate_number(event["t_ms"], field="t_ms")
        if timestamp < 0 or timestamp < previous:
            raise ValueError("Event times must be finite, nonnegative and chronological")
        previous = timestamp
        kind = event["type"]
        if kind not in VALID_EVENT_TYPES:
            raise ValueError("Unknown HumanEvent type")
        _point(event)
        target_key = event.get("target_key")
        if target_key is not None and not isinstance(target_key, str):
            raise ValueError("Event target_key must be a string or None")


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _pair_down_up(events: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Rule 1: pair each down with the next up; a new down leaves the prior down incomplete."""
    paired: dict[int, int] = {}
    active_down: int | None = None
    for idx, event in enumerate(events):
        kind = event["type"]
        if kind == "down":
            active_down = idx
        elif kind == "up" and active_down is not None:
            paired[idx] = active_down
            active_down = None
    return paired


def _match_real_clicks(events: Sequence[Mapping[str, Any]]) -> tuple[dict[int, int], dict[int, int]]:
    """Rule 2: match each up to a real click within 500ms and 5px before next down/key/scroll."""
    up_for_click: dict[int, int] = {}
    click_for_up: dict[int, int] = {}
    for u_idx, up in enumerate(events):
        if up["type"] != "up":
            continue
        up_point = _point(up)
        if up_point is None:
            continue
        for c_idx in range(u_idx + 1, len(events)):
            candidate = events[c_idx]
            if candidate["type"] in BOUNDARY_TYPES:
                break
            if candidate["t_ms"] - up["t_ms"] > MAX_CLICK_MATCH_MS:
                break
            if candidate["type"] != "click" or c_idx in up_for_click:
                continue
            click_point = _point(candidate)
            if click_point is not None and _distance(up_point, click_point) <= MAX_POINTER_DISTANCE_PX:
                up_for_click[c_idx] = u_idx
                click_for_up[u_idx] = c_idx
                break
    return up_for_click, click_for_up


def _resolve_supplemented_target(
    down: Mapping[str, Any], up: Mapping[str, Any]
) -> tuple[str | None, TargetSource] | None:
    """Rule 4: prefer up.target_key, fall back to down, reject mismatched targets."""
    up_target = up.get("target_key")
    down_target = down.get("target_key")
    if up_target is not None and down_target is not None and up_target != down_target:
        return None
    if up_target is not None:
        return up_target, "up"
    if down_target is not None:
        return down_target, "target_from_down"
    return None, "unknown"


def _supplement_click(
    events: Sequence[Mapping[str, Any]],
    up_idx: int,
    down_idx: int | None,
) -> dict[str, Any] | None:
    """Rules 3-5: synthesize a click at up when paired down->up qualifies."""
    if down_idx is None:
        return None
    down = events[down_idx]
    up = events[up_idx]
    if up["t_ms"] - down["t_ms"] > MAX_SUPPLEMENT_DURATION_MS:
        return None
    down_point = _point(down)
    up_point = _point(up)
    if down_point is None or up_point is None:
        return None
    for idx in range(down_idx + 1, up_idx):
        mid = events[idx]
        if mid["type"] in GESTURE_BREAKER_TYPES:
            return None
        if mid["type"] in POINTER_POSITION_TYPES:
            mid_point = _point(mid)
            if mid_point is None or _distance(down_point, mid_point) > MAX_POINTER_DISTANCE_PX:
                return None
    if _distance(down_point, up_point) > MAX_POINTER_DISTANCE_PX:
        return None
    target = _resolve_supplemented_target(down, up)
    if target is None:
        return None
    target_key, target_source = target
    return {
        "t_ms": up["t_ms"],
        "type": "click",
        "x": up_point[0],
        "y": up_point[1],
        "target_key": target_key,
        "supplemented": True,
        "down_index": down_idx,
        "up_index": up_idx,
        "click_index": None,
        "target_source": target_source,
    }


def click_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Extract real clicks and supplement missing clicks from down/up pairs per README section 2."""
    _validate_events(events)
    paired_down_for_up = _pair_down_up(events)
    up_for_click, click_for_up = _match_real_clicks(events)

    result: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        kind = event["type"]
        if kind == "click":
            up_idx = up_for_click.get(idx)
            down_idx = paired_down_for_up.get(up_idx) if up_idx is not None else None
            target_key = event.get("target_key")
            target_source: TargetSource = "click" if target_key is not None else "unknown"
            result.append({
                "t_ms": event["t_ms"],
                "type": "click",
                "x": event.get("x"),
                "y": event.get("y"),
                "target_key": target_key,
                "supplemented": False,
                "down_index": down_idx,
                "up_index": up_idx,
                "click_index": idx,
                "target_source": target_source,
            })
        elif kind == "up" and idx not in click_for_up:
            supplemented = _supplement_click(events, idx, paired_down_for_up.get(idx))
            if supplemented is not None:
                result.append(supplemented)
    return result
