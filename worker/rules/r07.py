import math
from collections.abc import Sequence

from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot


def evaluate(snapshots: Sequence[ElementSnapshot], ids: Sequence[float | None]) -> list[Candidate | None]:
    """Top ceil(N/10) measurable targets; ties at the cutoff are included."""
    if len(snapshots) != len(ids):
        raise ValueError("One Fitts ID is required per target")
    valid = sorted(value for value in ids if value is not None)
    if any(not math.isfinite(value) or value < 0 for value in valid):
        raise ValueError("Fitts IDs must be finite and nonnegative")
    if not valid:
        return [None] * len(ids)
    cutoff = valid[len(valid) - math.ceil(len(valid) / 10)]
    return [
        Candidate("R07", "medium", "작은 타겟의 이동 난이도가 경로의 상위 10%에 속합니다.", value, cutoff)
        if value is not None and value > 0 and value >= cutoff
        and min(snapshot.bbox.width, snapshot.bbox.height) < 32 else None
        for snapshot, value in zip(snapshots, ids)
    ]
