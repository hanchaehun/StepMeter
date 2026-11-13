"""Real axe against local HTML, without network or fixed violation counts."""

import unittest

from playwright.async_api import async_playwright

from tests.test_a11y_axe import AXE_SCRIPT
from worker.a11y.scan import scan_page
from worker.rules.engine import evaluate_axe


class ScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_size_is_enabled_without_disabling_other_rules(self):
        await self.page.set_content('''<button id="tiny" style="position:absolute;
            left:100px;top:100px;width:16px;height:20px;padding:0;border:0"></button>
            <a href="#" style="position:absolute;left:100px;top:121px;
            width:345px;height:30px">Forgot Password</a>''')
        result = await scan_page(self.page, AXE_SCRIPT, {0: self.page.locator("#tiny")})
        ids = {rule["id"] for rule in result["violations"]}
        self.assertIn("target-size", ids)
        self.assertIn("button-name", ids)

    async def asyncSetUp(self):
        pw = await async_playwright().start()
        self.addAsyncCleanup(pw.stop)
        browser = await pw.chromium.launch()
        self.addAsyncCleanup(browser.close)
        self.page = await browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())
        await self.page.set_content('''<!doctype html><html lang="en"><head><title>Local</title>
            <style>button {width:100px;height:50px;margin:20px}
            .contrast {color:#777;background:#fff;font:16px Arial}</style></head>
            <body><main><button id="on"></button><button id="off"></button>
            <button id="contrast" class="contrast">Continue</button>
            <p class="contrast" id="reference">Reference text</p></main></body></html>''')

    async def test_path_and_reference_nodes_keep_distinct_bindings(self):
        results = await scan_page(self.page, AXE_SCRIPT, {
            0: self.page.locator("#on"), 1: self.page.locator("#contrast"),
        })
        names = next(v for v in results["violations"] if v["id"] == "button-name")
        nodes = {node["target"][0]: node for node in names["nodes"]}
        self.assertEqual(nodes["#on"]["path_keys"], [0])
        self.assertFalse(nodes["#on"]["is_reference"])
        self.assertTrue(nodes["#off"]["is_reference"])
        candidates = evaluate_axe(results, {0: 11, 1: 12})
        self.assertTrue(any(c.rule_id == "R10" and c.step_id == 11 for c in candidates))
        self.assertTrue(any(c.rule_id == "R10" and c.is_reference for c in candidates))
        # #777 on white ≈4.478: below normal-text AA 4.5.
        self.assertTrue(any(c.rule_id == "R02" and c.step_id == 12 for c in candidates))
        self.assertTrue(any(c.rule_id == "R02" and c.is_reference for c in candidates))
        self.assertIn("incomplete", results)

    async def test_missing_ambiguous_and_iframe_targets_fail_explicitly(self):
        for selector in ("#missing", "button"):
            with self.assertRaises(ValueError):
                await scan_page(self.page, AXE_SCRIPT, {1: self.page.locator(selector)})
        await self.page.set_content('<iframe srcdoc="<button>Inside</button>"></iframe>')
        with self.assertRaisesRegex(ValueError, "main-frame"):
            await scan_page(self.page, AXE_SCRIPT, {
                1: self.page.frame_locator("iframe").locator("button"),
            })

    async def test_shadow_target_is_bound_by_identity(self):
        await self.page.evaluate('''() => {
            const host = document.createElement('div'); document.body.append(host);
            host.attachShadow({mode:'open'}).innerHTML = '<button id="shadow"></button>';
        }''')
        results = await scan_page(self.page, AXE_SCRIPT, {20: self.page.locator("#shadow")})
        names = next(v for v in results["violations"] if v["id"] == "button-name")
        self.assertTrue(any(node["path_keys"] == [20] for node in names["nodes"]))

    async def test_file_failure_is_not_clean_scan(self):
        with self.assertRaises(FileNotFoundError):
            await scan_page(self.page, AXE_SCRIPT.with_name("missing.js"), {})

    async def test_associated_labels_are_on_path_but_independent_links_are_not(self):
        await self.page.set_content('''<html lang="en"><title>Labels</title><main>
            <label for="control" id="caption" style="color:#777;background:white;font:16px Arial">
              Remember <span id="text">me</span><a id="other" href="#"></a>
            </label><input type="checkbox" id="control">
            <label for="unrelated" style="color:#777;background:white;font:16px Arial">Other</label>
            <input id="unrelated"></main></html>''')
        result = await scan_page(self.page, AXE_SCRIPT, {7: self.page.locator('#control')})
        contrast = next(v for v in result['violations'] if v['id'] == 'color-contrast')
        self.assertTrue(any(n['path_keys'] == [7] for n in contrast['nodes']))
        self.assertTrue(any(n['is_reference'] for n in contrast['nodes']))
        links = next(v for v in result['violations'] if v['id'] == 'link-name')
        self.assertTrue(all(n['is_reference'] for n in links['nodes']))
        issues = evaluate_axe(result, {7: 12})
        self.assertTrue(any(c.rule_id == 'R02' and c.step_id == 12 and not c.is_reference for c in issues))

    async def test_strict_csp_allows_evaluate_injection(self):
        await self.page.set_content('''<meta http-equiv="Content-Security-Policy"
            content="script-src 'none'"><button></button>''')
        result = await scan_page(self.page, AXE_SCRIPT, {})
        self.assertIn('button-name', {v['id'] for v in result['violations']})
