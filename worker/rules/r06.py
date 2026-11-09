"""R06: 화면이 로드된 뒤 처음 행동하는 대상이 로드 시 첫 화면 밖 (ADR 0009).

화면은 페이지 로드나 SPA 라우트 변경으로 바뀐다. 화면이 바뀔 때마다 첫 행동 대상을 다시 센다.
행동은 click·type·select만 센다. scroll·back·wait·done·fail은 대상 행동이 아니다.
"""

from urllib.parse import urlsplit

from worker.rules.candidate import Candidate
from worker.schemas import ElementSnapshot

TARGET_ACTIONS = frozenset({"click", "type", "select"})


def screen_key(url: str, *, hash_routes: bool = False) -> str:
    """화면 식별자: 출처와 경로. 쿼리 변화(필터 등)는 같은 화면으로 본다.

    해시는 해시 라우터로 확인한 앱(hash_routes=True)에서만 화면으로 센다(EffectObserver와 같은 정책).
    """
    parts = urlsplit(url)
    key = f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"
    return f"{key}#{parts.fragment}" if hash_routes and parts.fragment else key


class FirstTargetTracker:
    """시도 하나에서 행동마다 그 화면의 첫 행동 대상인지 센다. 행동 직전 URL을 순서대로 넣는다."""

    def __init__(self, *, hash_routes: bool = False) -> None:
        self._hash_routes = hash_routes
        self._screen: str | None = None
        self._acted = False

    def new_screen(self) -> None:
        """URL이 같아도 문서를 다시 불러왔을 때(새로고침, 같은 주소로 제출) 부른다."""
        self._screen, self._acted = None, False

    def is_first_target(self, url: str, action: str) -> bool:
        screen = screen_key(url, hash_routes=self._hash_routes)
        if screen != self._screen:
            self._screen, self._acted = screen, False
        if action not in TARGET_ACTIONS:
            return False
        first = not self._acted
        self._acted = True
        return first


def evaluate(snapshot: ElementSnapshot, *, action: str, is_first_target: bool) -> Candidate | None:
    # null means it was absent at load; it does not prove an offscreen target.
    if (is_first_target and action in TARGET_ACTIONS and not snapshot.in_first_view
            and snapshot.first_view_scroll_px is not None):
        return Candidate("R06", "medium", "화면이 로드된 뒤 처음 행동한 대상이 로드 시 첫 화면 밖에 있었습니다.",
                         snapshot.first_view_scroll_px, 0)
    return None
