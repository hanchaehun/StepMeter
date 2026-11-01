"""Smoke-check the W1 mock report in a real browser; save a screenshot."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def check(url: str, output: Path) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            response = await page.goto(url, wait_until="networkidle")
            if response is None or not response.ok:
                raise RuntimeError("Web response failed")
            await page.get_by_role("heading", name="리포트 요약", exact=True).wait_for()
            await page.get_by_role("link", name="단계 상세", exact=True).click()
            await page.get_by_role("heading", name="단계 상세", exact=True).wait_for()
            await page.get_by_role("link", name="리포트 요약", exact=True).click()
            if errors:
                raise RuntimeError(f"Browser errors: {errors}")
            output.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output), full_page=True)
            print(f"PASS: report summary/detail navigation at {url}; screenshot: {output}")
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--screenshot", type=Path, default=Path("screenshots/w1-report.png"))
    args = parser.parse_args()
    asyncio.run(check(args.url, args.screenshot))
