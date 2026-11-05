"""Directional target width and Shannon ID (development plan 5.3)."""

import math
from collections.abc import Sequence

from worker.schemas import BBox, ElementSnapshot


def fitts_id(start: tuple[float, float], target: BBox) -> float | None:
    """Return bits; a zero-area target is unmeasurable, not an infinite metric."""
    if target.width == 0 or target.height == 0:
        return None
    x, y = target.center
    dx, dy = x - start[0], y - start[1]
    distance = math.hypot(dx, dy)
    if distance == 0:
        return 0.0
    widths = []
    if dx:
        widths.append(target.width * distance / abs(dx))
    if dy:
        widths.append(target.height * distance / abs(dy))
    return math.log2(1 + distance / min(widths))


def calculate_fitts_ids(snapshots: Sequence[ElementSnapshot]) -> list[float | None]:
    """Same click/type path and initial cursor convention as cursor_distance."""
    if not snapshots:
        return []
    start = (snapshots[0].viewport.width / 2, snapshots[0].viewport.height / 2)
    result = []
    for snapshot in snapshots:
        result.append(fitts_id(start, snapshot.bbox))
        start = snapshot.bbox.center
    return result
