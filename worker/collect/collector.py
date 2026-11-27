"""Playwright 페이지에 수집 JS를 주입해 요소 목록과 ElementSnapshot을 얻는다."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from playwright.async_api import ElementHandle, Page
from playwright.async_api import Error as PlaywrightError

from worker.schemas import ElementSnapshot

BUNDLE = Path(__file__).resolve().parent / "dist" / "collect.js"


async def _inject(page: Page) -> None:
    if await page.evaluate("() => !!globalThis.__stepmeter"):
        return
    if not BUNDLE.exists():
        raise FileNotFoundError(f"{BUNDLE} 없음: `npm run build:collect` 먼저 실행")
    await page.evaluate(BUNDLE.read_text(encoding="utf-8"))


_DOM_QUIET = """({quiet, min, max}) => new Promise(resolve => {
  const start = performance.now();
  let last = start;
  const observer = new MutationObserver(() => { last = performance.now(); });
  observer.observe(document, {subtree: true, childList: true, attributes: true});
  const tick = () => {
    const now = performance.now();
    if (now - start >= max ||
        (now - start >= min && now - last >= quiet && document.readyState === "complete")) {
      observer.disconnect();
      resolve();
    } else {
      setTimeout(tick, 20);
    }
  };
  setTimeout(tick, 20);
})"""


async def wait_for_dom_quiet(page: Page, quiet_ms: int = 200, min_ms: int = 400, max_ms: int = 1500) -> None:
    """첫 화면 안정화 대기 (ADR 0011 11번). goto 직후, record_first_view 앞에서 부른다.

    시작 후 min_ms 이상 지났고, 마지막 DOM 변화(추가·삭제·속성 변경) 뒤 quiet_ms 동안 조용하고,
    document.readyState가 complete면 끝난다. max_ms가 되면 조건과 상관없이 끝난다.
    min_ms보다 오래 아무 변화가 없다가 그 뒤에 그려지는 내용은 첫 관찰에 안 잡힐 수 있다.
    대기 중 문서가 바뀌면(클라이언트 이동) 남은 시간 안에서 새 문서로 다시 기다린다.
    """
    deadline = time.monotonic() + max_ms / 1000
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            # Python-side net in case page timers are starved; the page resolves by max itself.
            await asyncio.wait_for(page.evaluate(_DOM_QUIET, {
                'quiet': quiet_ms, 'min': min(min_ms, remaining * 1000), 'max': remaining * 1000}),
                timeout=remaining + 1)
            return
        except asyncio.TimeoutError:
            return
        except PlaywrightError:
            if page.is_closed():
                raise
            # The execution context was replaced by a navigation; wait on the new document.
            try:
                await page.wait_for_load_state('domcontentloaded', timeout=max(1, remaining * 1000))
            except PlaywrightError:
                return


async def record_first_view(page: Page) -> None:
    """페이지 로드 직후 1회 호출한다. 이동하면 기록이 사라지므로 새 페이지마다 다시 부른다."""
    await _inject(page)
    await page.evaluate("() => __stepmeter.recordFirstView()")


async def wait_for_first_elements(page: Page, max_ms: int = 3000, step_ms: int = 250) -> bool:
    """로딩 중 페이지 전체를 숨기는 사이트용(예: body opacity 0). record_first_view 바로 뒤에 부른다.

    observe(page)가 처음부터 요소를 돌려주면 바로 False. 0개면 step_ms 간격으로 다시 observe 하다가
    요소가 나오면 True(부른 쪽이 record_first_view를 다시 부른다), max_ms가 지나도 0개면 False.
    정말로 첫 화면 밖에만 요소가 있는 페이지는 max_ms만 기다리고 그대로 둔다.
    중간에 PlaywrightError(페이지 이동 등)가 나면 False.
    """
    deadline = time.monotonic() + max_ms / 1000
    try:
        if await observe(page):
            return False
        while (remaining := deadline - time.monotonic()) > 0:
            await asyncio.sleep(min(step_ms / 1000, remaining))
            if await observe(page):
                return True
    except PlaywrightError:
        return False
    return False


async def observe(page: Page) -> list[dict[str, Any]]:
    """뷰포트 안의 보이는 상호작용 요소 (가려진 요소 포함, `occluded`로 표시).

    LLM용 목록(가림 표시 포함, 최대 60개, ADR 0010·ADR 0011 11번)은 에이전트 코어가 이 결과를 잘라 만든다.
    """
    await _inject(page)
    return await page.evaluate("() => __stepmeter.observe()")


async def snapshot(page: Page, el_id: int) -> ElementSnapshot:
    """마지막 observe()의 `el_id` 요소에 대한 측정 훅 값."""
    await _inject(page)
    raw = await page.evaluate("id => __stepmeter.snapshot(id)", el_id)
    return ElementSnapshot.model_validate(raw)


async def click_point(page: Page, el_id: int) -> dict[str, float] | None:
    """Validated label/SVG activation point in top-level viewport coordinates."""
    await _inject(page)
    return await page.evaluate("id => __stepmeter.clickPoint(id)", el_id)


async def scroll_target_into_view(page: Page, el_id: int) -> None:
    """Prepare the actual action surface without changing the semantic target."""
    await _inject(page)
    handle = await page.evaluate_handle("id => __stepmeter.scrollTarget(id)", el_id)
    try:
        element = handle.as_element()
        if element is None:
            raise ValueError("No action surface")
        # An empty Bootstrap label may paint only ::before and have a zero
        # border box. Scroll its anchor without Playwright's nonempty-box gate.
        has_box = await element.evaluate('''el => {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return true;
            el.scrollIntoView({block: 'center', inline: 'center'});
            return false;
        }''')
        if has_box:
            await element.scroll_into_view_if_needed()
    finally:
        await handle.dispose()



async def resolve_element(page: Page, el_id: int) -> ElementHandle:
    """Return the original numbered node, rejecting disconnected/recycled targets.

    Caller owns handle disposal. This does not run observe or remap IDs. Observe
    again after navigation, scrolling/rerender or a stale-target error.
    """
    if type(el_id) is not int or el_id < 1:
        raise ValueError("el_id must be a positive integer")
    await _inject(page)
    handle = await page.evaluate_handle("id => __stepmeter.resolveElement(id)", el_id)
    element = handle.as_element()
    if element is None:
        await handle.dispose()
        raise ValueError("numbered target did not resolve to an element")
    # A node reached through contentDocument is initially a handle in the main
    # frame execution context. Adopt it into its owning frame so Playwright's
    # actionability/hit-testing uses the correct iframe coordinates.
    owner = await element.owner_frame()
    if owner is not None and owner != page.main_frame:
        try:
            adopted = await owner.evaluate_handle("el => el", element)
        finally:
            await element.dispose()
        resolved = adopted.as_element()
        if resolved is None:
            await adopted.dispose()
            raise ValueError("numbered iframe target did not resolve to an element")
        return resolved
    return element
