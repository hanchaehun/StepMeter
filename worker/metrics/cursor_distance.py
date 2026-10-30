"""Cursor travel between target centers, measured in CSS pixels."""

from collections.abc import Sequence
from math import hypot

from worker.schemas import ElementSnapshot


def calculate_cursor_distance(snapshots: Sequence[ElementSnapshot]) -> float:
    """Sum travel from the first viewport center through each bbox center.

    Snapshots are assumed to share one viewport/session. Coordinates are already
    viewport-relative; do not add scroll offsets or clamp off-screen centers.
    """
    if not snapshots:
        return 0.0

    viewport = snapshots[0].viewport
    previous_x, previous_y = viewport.width / 2, viewport.height / 2
    distance = 0.0
    for snapshot in snapshots:
        x, y = snapshot.bbox.center
        distance += hypot(x - previous_x, y - previous_y)
        previous_x, previous_y = x, y
    return distance
