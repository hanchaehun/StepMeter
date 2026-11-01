"""Minimal axe-core POC for an already loaded Playwright page."""

from pathlib import Path
from typing import Any

from playwright.async_api import Page


async def run_axe(page: Page, axe_script_path: str | Path) -> list[dict[str, Any]]:
    """Inject a local axe-core script and return its unmodified violations.

    The caller owns page loading and browser lifetime. File, injection and
    axe.run errors propagate to the caller; an error is never a clean result.
    This W1 POC injects into the main frame only.
    """
    await page.add_script_tag(path=axe_script_path)
    results = await page.evaluate("() => axe.run()")
    return results["violations"]
