"""Read-only click extraction from chronological HumanEvent records."""

import math
from collections.abc import Mapping, Sequence
from typing import Any


def click_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Use each pointer up once; suppress its following click notification.

    A new down/key/scroll ends the pending gesture. move/stable do not.
    Standalone click records remain usable for old click-only recordings.
    Coordinates/target may differ as a popup disappears: do not require equality.
    Returns copies of original events, retaining up timestamps and null targets.
    """
    result = []
    pending_up = False
    previous = -1.0
    for event in events:
        timestamp = event['t_ms']
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp) or timestamp < 0 or timestamp < previous):
            raise ValueError("Event times must be finite, nonnegative and chronological")
        previous = timestamp
        kind = event['type']
        if kind not in {'move', 'down', 'up', 'click', 'scroll', 'key', 'stable'}:
            raise ValueError("Unknown HumanEvent type")
        if kind == 'up':
            result.append(dict(event))
            pending_up = True
        elif kind == 'click':
            if not pending_up:
                result.append(dict(event))
            pending_up = False
        elif kind in {'down', 'key', 'scroll'}:
            pending_up = False
    return result
