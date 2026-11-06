"""Internal rule output, before the separate issue scoring stage."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    severity: Literal["high", "medium", "low"]
    explanation: str
    measured: float | None = None
    threshold: float | None = None
    is_reference: bool = False
    step_id: int | None = None
    element_key: str | None = None
