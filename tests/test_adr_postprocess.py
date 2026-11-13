"""ADR 0010 contracts with hand-counted paths and explicit live-handle ownership."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from playwright.async_api import ElementHandle, Locator
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.db.models import AccessCode, Attempt, Base, Metric, Project, Run, Step, Task
from tests.test_measurement_persistence import jsonb_for_sqlite  # noqa: F401
from tests.test_rules_w2 import target
from worker.a11y.scan import scan_page
from worker.metrics.persistence import save_run_medians
from worker.metrics.postprocess import finalize_run_metrics
from worker.rules.engine import evaluate_axe, evaluate_step


class AttemptMetricsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.session = Session(engine)
        self.addCleanup(self.session.close)
        code = AccessCode(code_hash="adr-test")
        self.session.add(code)
        self.session.flush()
        project = Project(owner_id=code.id, name="Local", base_url="https://local.invalid")
        self.session.add(project)
        self.session.flush()
        task = Task(project_id=project.id, description="Synthetic path")
        self.session.add(task)
        self.session.flush()
        self.run = Run(task_id=task.id, viewport="desktop", mode="agent", repeat_n=3,
                       model="fake", status="running")
        self.session.add(self.run)
        self.session.flush()

    def add_attempt(self, index, actions, success, kind="agent"):
        attempt = Attempt(run_id=self.run.id, index=index, kind=kind, success=success,
                          end_reason="success" if success else "gave_up")
        self.session.add(attempt)
        self.session.flush()
        for idx, action in enumerate(actions):
            self.session.add(Step(attempt_id=attempt.id, idx=idx, action={"action": action},
                                  thought="fixture", url="https://local.invalid", state_hash="x",
                                  changed=False, effect_type="no_change"))
        return attempt

    def aggregates(self):
        return list(self.session.scalars(select(Metric).where(Metric.attempt_id.is_(None))))

    def test_attempt_only_then_successful_median_and_idempotency(self):
        # Successful paths have 2 and 4 actions. Failure has 1. Median must be 3, not 2.
        a = self.add_attempt(1, ["click", "type", "done"], True)
        b = self.add_attempt(2, ["click", "wait", "scroll", "back", "done"], True)
        c = self.add_attempt(3, ["click"], False)
        self.add_attempt(4, ["click"] * 9, True, kind="replay")
        rows = finalize_run_metrics(self.session, self.run.id)
        self.assertEqual({r.attempt_id: r.value for r in rows}, {a.id: 2, b.id: 4, c.id: 1})
        self.assertEqual(self.aggregates(), [])
        saved_ids = {r.id for r in rows}
        self.assertEqual({r.id for r in finalize_run_metrics(self.session, self.run.id)}, saved_ids)
        median = save_run_medians(self.session, self.run.id)
        self.assertEqual([(r.key, r.value) for r in median], [("step_count", 3)])
        finalize_run_metrics(self.session, self.run.id)
        self.assertEqual([(r.key, r.value) for r in self.aggregates()], [("step_count", 3)])

    def test_all_failed_has_attempt_values_but_no_run_metric(self):
        self.add_attempt(1, [], False)
        self.add_attempt(2, ["click", "done"], False)
        self.assertEqual(sorted(r.value for r in finalize_run_metrics(self.session, self.run.id)), [0, 1])
        self.assertEqual(save_run_medians(self.session, self.run.id), [])
        self.assertEqual(self.aggregates(), [])


class OcclusionTests(unittest.TestCase):
    def test_occluded_click_reports_r04_not_r03(self):
        for occluded, expected in ((True, ["R04"]), (False, ["R03"])):
            candidates = evaluate_step(target(44, occluded=occluded), step_id=12,
                                       action="click", effect_type="no_change", is_first_target=False)
            self.assertEqual([c.rule_id for c in candidates], expected)
            self.assertTrue(all(c.step_id == 12 for c in candidates))


class HandleOwnershipTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.script = Path(directory.name) / "axe.js"
        self.script.write_text("window.axe = {}", encoding="utf-8")

    def page(self):
        return Mock(main_frame=object(), add_script_tag=AsyncMock(), evaluate=AsyncMock(return_value={}))

    def handle(self, frame):
        return Mock(spec=ElementHandle, owner_frame=AsyncMock(return_value=frame), dispose=AsyncMock())

    async def test_mixed_locator_and_borrowed_handle(self):
        page = self.page()
        borrowed, owned = self.handle(page.main_frame), self.handle(page.main_frame)
        locator = Mock(spec=Locator, count=AsyncMock(return_value=1),
                       element_handle=AsyncMock(return_value=owned))
        await scan_page(page, self.script, {0: borrowed, 1: locator})
        self.assertEqual(page.evaluate.call_args.args[1], {"ids": [0, 1], "elements": [borrowed, owned]})
        borrowed.dispose.assert_not_awaited()
        owned.dispose.assert_awaited_once()

    async def test_borrowed_iframe_handle_is_rejected_not_disposed(self):
        page = self.page()
        borrowed = self.handle(object())
        with self.assertRaisesRegex(ValueError, "main-frame"):
            await scan_page(page, self.script, {0: borrowed})
        borrowed.dispose.assert_not_awaited()
        page.evaluate.assert_not_awaited()

    async def test_scan_failure_disposes_only_owned_handles(self):
        page = self.page()
        page.evaluate.side_effect = RuntimeError("Detached path target")
        borrowed, owned = self.handle(page.main_frame), self.handle(page.main_frame)
        locator = Mock(spec=Locator, count=AsyncMock(return_value=1),
                       element_handle=AsyncMock(return_value=owned))
        with self.assertRaisesRegex(RuntimeError, "Detached"):
            await scan_page(page, self.script, {0: borrowed, 1: locator})
        borrowed.dispose.assert_not_awaited()
        owned.dispose.assert_awaited_once()


class ContrastMeasurementTests(unittest.TestCase):
    def test_axe_check_data_is_preserved_with_ratio_threshold(self):
        node = {"is_reference": False, "path_keys": [0], "target": ["#label"],
                "any": [{"id": "color-contrast", "data": {
                    "contrastRatio": 3.2, "expectedContrastRatio": "4.5:1"}}]}
        candidates = evaluate_axe({"violations": [{"id": "color-contrast", "nodes": [node]}]},
                                  {0: 12})
        self.assertEqual([(c.rule_id, c.measured, c.threshold, c.step_id) for c in candidates],
                         [("R02", 3.2, 4.5, 12)])

    def test_reference_missing_data_stays_unknown_without_element_key(self):
        node = {"is_reference": True, "in_viewport": True, "path_keys": [], "target": ["p"]}
        candidate = evaluate_axe({"violations": [{"id": "color-contrast", "nodes": [node]}]}, {})[0]
        self.assertIsNone(candidate.measured)
        self.assertIsNone(candidate.threshold)
        self.assertIsNone(candidate.step_id)
        self.assertIsNone(candidate.element_key)


class RealHandleTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_document_handle_binding_and_lifetime(self):
        from playwright.async_api import async_playwright

        from tests.test_a11y_axe import AXE_SCRIPT

        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch()
        self.addAsyncCleanup(browser.close)
        page = await browser.new_page()
        await page.route("**/*", lambda route: route.abort())
        await page.set_content('<html lang="en"><title>Local</title><button id="on"></button>'
                               '<button id="off"></button></html>')
        handle = await page.locator("#on").element_handle()
        self.addAsyncCleanup(handle.dispose)
        results = await scan_page(page, AXE_SCRIPT, {7: handle})
        rule = next(rule for rule in results["violations"] if rule["id"] == "button-name")
        nodes = {node["target"][0]: node for node in rule["nodes"]}
        self.assertEqual(nodes["#on"]["path_keys"], [7])
        self.assertEqual(nodes["#off"]["path_keys"], [])
        self.assertEqual(await handle.get_attribute("id"), "on")
        await handle.evaluate("el => el.remove()")
        with self.assertRaisesRegex(Exception, "Detached path target"):
            await scan_page(page, AXE_SCRIPT, {7: handle})
        self.assertEqual(await handle.get_attribute("id"), "on")
