"""Playwright 페이지에 수집 JS를 주입해 요소 목록과 ElementSnapshot을 얻는다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Page

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

    반환 형식은 임시다. LLM용 목록(가림 제외, 60개 제한)은 에이전트 코어와 정한다.
    """
    await _inject(page)
    return await page.evaluate("() => __stepmeter.observe()")


async def snapshot(page: Page, el_id: int) -> ElementSnapshot:
    """마지막 observe()의 `el_id` 요소에 대한 측정 훅 값."""
    await _inject(page)
    raw = await page.evaluate("id => __stepmeter.snapshot(id)", el_id)
    return ElementSnapshot.model_validate(raw)
