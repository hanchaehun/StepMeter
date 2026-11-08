from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot


def evaluate(snapshot: ElementSnapshot, *, action: str = "click",
             is_first_target: bool = True) -> Candidate | None:
    # null means it was absent at load; it does not prove an offscreen target.
    if action == "click" and not snapshot.in_first_view and snapshot.first_view_scroll_px is not None:
        return Candidate("R06", "medium", "핵심 행동 대상이 페이지 로드 시 첫 화면 밖에 있었습니다.",
                         snapshot.first_view_scroll_px, 0)
    return None
