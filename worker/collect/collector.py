"""Playwright 페이지에 수집 JS를 주입해 요소 목록과 ElementSnapshot을 얻는다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import ElementHandle, Page

from worker.schemas import ElementSnapshot

BUNDLE = Path(__file__).resolve().parent / "dist" / "collect.js"


async def _inject(page: Page) -> None:
    if await page.evaluate("() => !!globalThis.__stepmeter"):
        return
    if not BUNDLE.exists():
        raise FileNotFoundError(f"{BUNDLE} 없음: `npm run build:collect` 먼저 실행")
    await page.evaluate(BUNDLE.read_text(encoding="utf-8"))


async def record_first_view(page: Page) -> None:
    """페이지 로드 직후 1회 호출한다. 이동하면 기록이 사라지므로 새 페이지마다 다시 부른다."""
    await _inject(page)
    await page.evaluate("() => __stepmeter.recordFirstView()")


async def observe(page: Page) -> list[dict[str, Any]]:
    """뷰포트 안의 보이는 상호작용 요소 (가려진 요소 포함, `occluded`로 표시).

    LLM용 목록(가림 표시 포함, 최대 30개, ADR 0010)은 에이전트 코어가 이 결과를 잘라 만든다.
    """
    await _inject(page)
    return await page.evaluate("() => __stepmeter.observe()")


async def snapshot(page: Page, el_id: int) -> ElementSnapshot:
    """마지막 observe()의 `el_id` 요소에 대한 측정 훅 값."""
    await _inject(page)
    raw = await page.evaluate("id => __stepmeter.snapshot(id)", el_id)
    return ElementSnapshot.model_validate(raw)


async def click_point(page: Page, el_id: int) -> dict[str, float] | None:
    """Validated label-proxy activation point in top-level viewport coordinates."""
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
