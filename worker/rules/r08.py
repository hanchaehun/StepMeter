"""Backtracking across repeated agent attempts (development plan chapter 6)."""

from collections.abc import Sequence
from math import ceil

from worker.rules.candidate import Candidate


def evaluate(back_counts: Sequence[int]) -> Candidate | None:
    """At least 3 ended attempts; back in >=2/3, counting each attempt once.

    Extra repetitions retain the 2/3 threshold. Fewer than three provide
    insufficient evidence. Success is not required; replay must be excluded.
    """
    if any(type(count) is not int or count < 0 for count in back_counts):
        raise ValueError("Back counts must be nonnegative integers")
    affected = sum(count > 0 for count in back_counts)
    threshold = ceil(len(back_counts) * 2 / 3)
    if len(back_counts) < 3 or affected < threshold:
        return None
    return Candidate("R08", "medium", "여러 시도에서 뒤로 가기가 반복되었습니다.",
                     float(affected), float(threshold), is_reference=True)
