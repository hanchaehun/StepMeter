from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot


def evaluate(snapshot: ElementSnapshot) -> Candidate | None:
    if snapshot.occluded:
        return Candidate("R04", "high", "행동 대상의 중심점이 다른 요소에 가려져 있습니다.")
    return None
