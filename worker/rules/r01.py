"""Target size and spacing exception (WCAG 2.5.8)."""

from math import hypot

from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot


def evaluate(snapshot: ElementSnapshot, *, mobile: bool = False,
             axe_violation: bool | None = None) -> Candidate | None:
    if snapshot.inline_in_text:
        return None
    size = min(snapshot.bbox.width, snapshot.bbox.height)
    x, y = snapshot.bbox.center
    overlapping = any(
        # Every neighboring target contributes its actual rectangular area.
        hypot(max(target.bbox.x - x, 0, x - target.bbox.x - target.bbox.width),
              max(target.bbox.y - y, 0, y - target.bbox.y - target.bbox.height)) < 12
        or (min(target.bbox.width, target.bbox.height) < 24
            and hypot(x - target.bbox.center[0], y - target.bbox.center[1]) < 24)
        for target in snapshot.nearby_targets
    )
    # None = axe did not decide; use the documented fallback.
    fails_minimum = axe_violation if axe_violation is not None else size < 24 and overlapping
    if fails_minimum:
        return Candidate("R01", "high", "타겟이 24px 최소 크기·간격 기준에 미달합니다.", size, 24)
    if 24 <= size < 44 or mobile and size < 44:
        return Candidate("R01", "medium" if mobile else "low",
                         "타겟이 44px 권장 크기보다 작습니다.", size, 44)
    return None
