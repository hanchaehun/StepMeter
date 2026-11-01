"""Save full axe evidence and rendered pages for development baselines only."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def audit(app: str, origin: str, phase: str) -> None:
    paths = {"sb-admin-2": ["login.html", "register.html"],
             "material-kit-react": ["sign-in", "products"]}[app]
    output = ROOT / "benchmark" / "evidence" / app / phase
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for path in paths:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                response = await page.goto(origin.rstrip("/") + "/" + path)
                if response is None or not response.ok:
                    raise RuntimeError(f"Failed page: {path}")
                await page.wait_for_timeout(2500)
                await page.add_script_tag(path=str(ROOT / "node_modules/axe-core/axe.min.js"))
                result = await page.evaluate("async () => await axe.run()")
                (output / (path + ".json")).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                await page.screenshot(path=str(output / (path + ".png")), full_page=True)
                print(f"{app}/{path}: {len(result['violations'])} violation rules; "
                      f"{len(result['incomplete'])} incomplete rules")
                await page.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", choices=["sb-admin-2", "material-kit-react"])
    parser.add_argument("origin", help="Local development server origin")
    parser.add_argument("phase", choices=["before", "after"])
    args = parser.parse_args()
    asyncio.run(audit(args.app, args.origin, args.phase))
