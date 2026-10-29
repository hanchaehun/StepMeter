"""Local Chromium integration tests; no remote page or runtime CDN required."""

import os
import tempfile
import unittest
from pathlib import Path

from playwright.async_api import Error, async_playwright

from worker.a11y.axe import run_axe

ROOT = Path(__file__).resolve().parents[1]
AXE_SCRIPT = Path(os.environ.get("AXE_CORE_PATH", ROOT / "node_modules/axe-core/axe.min.js"))
HTML = ROOT / "tests/fixtures/a11y/unnamed_button.html"


class AxeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.browser = await self.playwright.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())
        await self.page.set_content(HTML.read_text(encoding="utf-8"))

    async def test_unnamed_button_and_named_control(self):
        violations = await run_axe(self.page, AXE_SCRIPT)
        self.assertIn("button-name", {violation["id"] for violation in violations})
        button_issue = next(v for v in violations if v["id"] == "button-name")
        self.assertTrue(any("#unnamed" in node["target"] for node in button_issue["nodes"]))

        await self.page.locator("#unnamed").evaluate(
            'button => button.setAttribute("aria-label", "Continue")'
        )
        violations = await run_axe(self.page, AXE_SCRIPT)
        self.assertNotIn("button-name", {violation["id"] for violation in violations})

    async def test_missing_script_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                await run_axe(self.page, Path(directory) / "missing-axe.min.js")

    async def test_injection_error_propagates(self):
        await self.page.close()
        with self.assertRaises(Error):
            await run_axe(self.page, AXE_SCRIPT)

    async def test_run_rejection_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "rejecting-axe.js"
            script.write_text(
                'window.axe = {run: () => Promise.reject(new Error("axe POC failure"))};',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Error, "axe POC failure"):
                await run_axe(self.page, script)
