from worker.rules.candidate import Candidate


def evaluate(end_reason: str | None) -> Candidate | None:
    """Repeated clicks alone are not the core's loop termination decision."""
    if end_reason == "loop":
        return Candidate("R05", "high", "반복 루프가 감지되어 실행이 종료되었습니다.")
    return None
