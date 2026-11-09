"""사람 데이터 수집 세션 러너 (개발계획서 9.1, 동의서 3·4절, ADR 0001).

진행자가 실행하면 Playwright가 화면 있는 Chromium을 띄우고, 참가자가 그 창에서 과업을 한다.
페이지마다 수집 번들(worker/collect/dist/collect.js)과 human-study/collect.js를 init script로 넣고,
브라우저가 보내는 이벤트를 expose_function으로 바로 받는다(전체 페이지 이동 뒤에도 유지).
결함판은 benchmark/mutate.py 설정을 로드 직후 적용한다. 끝나면 HumanSessionCreate 형식 dict를 만든다.

데이터 보호:
  - 이벤트는 다섯 칸(t_ms, type, x, y, target_key)만 받아 적는다. 다른 칸은 버린다
  - 이벤트를 받을 때마다 .partial.jsonl에 덧붙여 둔다 (크래시·Ctrl+C에도 그때까지의 기록이 남는다)
  - 참가자가 창을 닫으면 바로 미완료로 저장한다

실행 예 (human-study/README.md):
  python human-study/session.py --participant P01 --page-id sb-admin-2/register/baseline \
      --url http://127.0.0.1:8766/register.html --device mouse --hours 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from playwright.async_api import Page, async_playwright  # noqa: E402

from benchmark.mutate import apply as apply_mutation, load_config  # noqa: E402
from schema import validate_session  # noqa: E402

BUNDLE = ROOT / "worker" / "collect" / "dist" / "collect.js"
COLLECT = HERE / "collect.js"
DEVICES = ("mouse", "trackpad", "touch")
DEFAULT_VIEWPORT = (1280, 800)  # 개발계획서 4.2 desktop
FIELDS = ("t_ms", "type", "x", "y", "target_key")  # openapi HumanEvent. 이 밖의 칸은 받지 않는다
BROWSER_CHROME_PX = 100  # 탭·주소창 높이 어림. 뷰포트 + 이만큼이 화면에 들어가야 한다
DEFAULT_OUT = ROOT / "data" / "human"  # .gitignore의 data/ 아래. 참가자 데이터는 커밋하지 않는다


@dataclass(frozen=True)
class SessionMeta:
    participant_code: str
    page_id: str
    device: str
    daily_computer_hours: float
    viewport: tuple[int, int] = DEFAULT_VIEWPORT

    def __post_init__(self) -> None:
        if self.device not in DEVICES:
            raise ValueError(f"device는 {DEVICES} 중 하나: {self.device!r}")
        if not (1 <= len(self.participant_code) <= 20):
            raise ValueError("participant_code는 1~20자")
        if not (0 <= self.daily_computer_hours <= 24):
            raise ValueError("daily_computer_hours는 0~24")


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _origin_of(url: str) -> str:
    """연구용 페이지 출처. file://은 브라우저 origin이 'null'이라 'file://'로 표시한다."""
    u = urlparse(url)
    return "file://" if u.scheme == "file" else f"{u.scheme}://{u.netloc}"


def build_session(meta: SessionMeta, events: list[dict[str, Any]], completed: bool, started_at: datetime) -> dict[str, Any]:
    """HumanSessionCreate 형식 dict. 이름·연락처·입력 내용은 들어갈 자리가 없다 (9.1)."""
    w, h = meta.viewport
    return {
        "participant_code": meta.participant_code,
        "page_id": meta.page_id,
        "device": meta.device,
        "viewport": {"width": w, "height": h},
        "daily_computer_hours": meta.daily_computer_hours,
        "started_at": _iso_z(started_at),
        "completed": completed,
        "events": sorted(events, key=lambda e: e["t_ms"]),
    }


def _init_script(start_ms: int, origin: str) -> str:
    if not BUNDLE.exists():
        raise FileNotFoundError(f"{BUNDLE} 없음: 저장소 루트에서 `npm run build:collect` 먼저 실행")
    header = f"window.__hsStart = {start_ms}; window.__hsOrigin = {json.dumps(origin)};\n"
    return header + BUNDLE.read_text(encoding="utf-8") + "\n" + COLLECT.read_text(encoding="utf-8")


Interact = Callable[[Page], Awaitable[bool]]


def _ask_in_thread(prompt: str, loop: asyncio.AbstractEventLoop) -> asyncio.Future:
    """input()을 데몬 스레드에서 받는다. 창이 닫혀 먼저 끝나도 이 스레드가 종료를 막지 않는다."""
    fut: asyncio.Future = loop.create_future()

    def worker() -> None:
        try:
            answer = input(prompt)
        except EOFError:
            answer = ""
        loop.call_soon_threadsafe(lambda: fut.done() or fut.set_result(answer))

    threading.Thread(target=worker, daemon=True).start()
    return fut


async def _wait_for_operator(closed: asyncio.Event) -> bool:
    """진행자가 Enter를 누르거나 참가자가 창을 닫을 때까지 기다린다. 창이 닫히면 바로 False."""
    if closed.is_set():
        print("참가자가 창을 닫았습니다. 미완료로 저장합니다.", flush=True)
        return False
    loop = asyncio.get_running_loop()
    print("\n참가자가 과업을 하는 동안 기다립니다. 끝나면 이 창에서 Enter를 누르세요.", flush=True)
    enter = _ask_in_thread("", loop)
    close = asyncio.ensure_future(closed.wait())
    done, pending = await asyncio.wait({enter, close}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    if close in done:
        print("참가자가 창을 닫았습니다. 미완료로 저장합니다.", flush=True)
        return False
    answer = await _ask_in_thread("과업을 끝냈나요? [y/N] ", loop)
    return answer.strip().lower() in ("y", "yes")


async def run_session_async(
    meta: SessionMeta,
    url: str,
    *,
    mutation: Path | None = None,
    headless: bool = False,
    interact: Interact | None = None,
    partial_path: Path | None = None,
) -> dict[str, Any]:
    """세션 한 번. interact가 있으면(테스트) 그것이 참가자 역할을 하고 완료 여부를 돌려준다.

    반환값은 build_session 결과이며 검증은 save_session에서 한다.
    """
    config = load_config(mutation) if mutation else None
    events: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc)
    start_ms = int(time.time() * 1000)
    partial = partial_path.open("a", encoding="utf-8") if partial_path else None

    def on_push(ev: Any) -> None:
        if not isinstance(ev, dict):
            return
        clean = {k: ev.get(k) for k in FIELDS}  # 다섯 칸만. 글자·이름 등 다른 칸은 여기서 버린다
        events.append(clean)
        if partial:
            partial.write(json.dumps(clean, ensure_ascii=False) + "\n")
            partial.flush()

    reapplies: list[asyncio.Task] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            try:
                w, h = meta.viewport
                context = await browser.new_context(viewport={"width": w, "height": h})
                await context.expose_function("__hsPush", on_push)
                await context.add_init_script(_init_script(start_ms, _origin_of(url)))
                page = await context.new_page()
                closed = asyncio.Event()
                page.on("close", lambda _: closed.set())

                if not headless:
                    avail = await page.evaluate("() => screen.availHeight")
                    if avail < h + BROWSER_CHROME_PX:
                        print(
                            f"[경고] 화면 높이 {avail}px가 뷰포트 {h}px + 브라우저 UI보다 작습니다. "
                            "창이 잘리면 참가자가 보는 첫 화면이 기록과 달라집니다. --viewport를 줄이거나 배율을 낮추세요.",
                            flush=True,
                        )

                await page.goto(url)
                if config is not None:
                    # 셀렉터가 안 맞으면 여기서 멈춘다. 참가자가 정상판을 결함판인 줄 알고 하지 않게
                    try:
                        await apply_mutation(page, config)
                    except Exception as e:  # noqa: BLE001
                        raise SystemExit(f"결함 설정 적용 실패, 세션을 시작하지 않음: {e}") from e

                    async def reapply() -> None:
                        try:
                            await apply_mutation(page, config)
                        except Exception as e:  # noqa: BLE001
                            print(f"[경고] 페이지 이동 뒤 결함 재적용 실패: {e}", flush=True)

                    page.on("load", lambda _: reapplies.append(asyncio.ensure_future(reapply())))

                if interact is not None:
                    completed = bool(await interact(page))
                else:
                    completed = await _wait_for_operator(closed)
                if closed.is_set():
                    completed = False  # 참가자가 창을 닫았으면 진행자 답과 무관하게 미완료
                for t in reapplies:
                    t.cancel()
            finally:
                await browser.close()
    finally:
        if partial:
            partial.close()

    return build_session(meta, events, completed, started_at)


def _stamp(data: dict[str, Any]) -> str:
    return datetime.fromisoformat(data["started_at"].replace("Z", "+00:00")).strftime("%Y%m%d-%H%M%S")


def _safe(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", text)


def save_session(data: dict[str, Any], out_dir: Path) -> Path:
    """검증 후 저장. 파일명 human-session-{참가자}-{page_id의 / → -}-{시작 시각}.json"""
    errors = validate_session(data)
    if errors:
        raise ValueError("HumanSessionCreate 스키마에 맞지 않음:\n" + "\n".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"human-session-{data['participant_code']}-{_safe(data['page_id'])}-{_stamp(data)}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_session_or_dump(data: dict[str, Any], out_dir: Path, name_hint: str) -> Path:
    """검증에 실패해도 데이터를 버리지 않는다: .invalid.json으로 남기고 오류를 출력한다."""
    try:
        return save_session(data, out_dir)
    except (ValueError, KeyError) as e:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = out_dir / f"human-session-{_safe(name_hint)}-{stamp}.invalid.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[경고] 스키마 검증 실패. 원본을 {path.name}에 남겼습니다.\n{e}", flush=True)
        return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사람 데이터 수집 세션 (개발계획서 9.1)")
    parser.add_argument("--participant", required=True, help="참가자 코드 (이름·연락처 아님), 1~20자")
    parser.add_argument("--page-id", required=True, help='"<앱 id>/<페이지>/<변이>" 예: sb-admin-2/register/baseline')
    parser.add_argument("--url", required=True, help="참가자가 시작할 페이지 주소. 이 출처 밖은 기록하지 않는다")
    parser.add_argument("--device", required=True, choices=DEVICES)
    parser.add_argument("--hours", required=True, type=float, help="평소 하루 컴퓨터 사용 시간 (0~24)")
    parser.add_argument("--mutation", type=Path, help="결함판이면 benchmark/mutations/<앱>/<변이>.yaml")
    parser.add_argument("--viewport", default="1280x800", help="기본 1280x800")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"저장 폴더 (기본 {DEFAULT_OUT})")
    parser.add_argument("--headless", action="store_true", help="테스트용. 참가자 세션에서는 쓰지 않는다")
    args = parser.parse_args(argv)

    w, h = (int(v) for v in args.viewport.lower().split("x"))
    meta = SessionMeta(args.participant, args.page_id, args.device, args.hours, (w, h))
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    partial = args.out / f".partial-{_safe(meta.participant_code)}-{_safe(meta.page_id)}-{stamp}.jsonl"

    data = asyncio.run(run_session_async(meta, args.url, mutation=args.mutation, headless=args.headless, partial_path=partial))
    path = save_session_or_dump(data, args.out, f"{meta.participant_code}-{meta.page_id}")
    if path.suffix == ".json" and not path.name.endswith(".invalid.json"):
        partial.unlink(missing_ok=True)
    print(f"저장: {path}  (이벤트 {len(data['events'])}개, 완료={data['completed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
