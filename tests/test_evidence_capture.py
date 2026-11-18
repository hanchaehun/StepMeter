"""Independent completion check for every worker success (benchmark-only sidecar).

Expected values follow the W3 rule: verified = check passed and every milestone seen,
on the page the attempt ended on; worker code is not involved in the decision.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.async_api import async_playwright

from benchmark.evidence_capture import EvidenceSink
from benchmark.run_development import verified_success
from worker.collect.collector import observe, record_first_view
from worker.schemas import parse_action_json

CHECK = "document.querySelector('#state')?.textContent === 'Finished'"
MILESTONE = "document.querySelector('#seen') !== null"


def done(reason):
    return parse_action_json(json.dumps({'action': 'done', 'reason': reason,
                                         'thought': 'Stop', 'expectation': 'Stopped'}))


class EvidenceSinkCompletion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch()
        self.page = await self.browser.new_page()
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = EvidenceSink(Path(self.tmp.name)/'dom', CHECK, [MILESTONE])

    async def asyncTearDown(self):
        await self.browser.close()
        await self.pw.stop()
        self.tmp.cleanup()

    async def click_capture(self, html):
        await self.page.set_content(html)
        await record_first_view(self.page)
        elements = await observe(self.page)
        target = next(e['el_id'] for e in elements if e['name'] == 'Pay now')
        action = parse_action_json(json.dumps({'action': 'click', 'target': target,
                                               'thought': 'Pay', 'expectation': 'Paid'}))
        await self.sink.capture(self.page, action, None, 'https://example.test/cart', 1)

    async def test_done_safety_stop_check_and_milestones_met_is_true(self):
        await self.page.set_content('<p id="seen"></p><p id="state">Finished</p>')
        await self.sink.capture(self.page, done('safety_stop'), None, 'https://example.test/', 1)
        self.assertIs(self.sink.verified(1, True), True)
        # Worker kept safety_stop: the page check is still recorded for done.
        self.assertIs(self.sink.verified(1, False), True)

    async def test_done_safety_stop_check_failed_is_false(self):
        await self.page.set_content('<p id="seen"></p><p id="state">Started</p>')
        await self.sink.capture(self.page, done('safety_stop'), None, 'https://example.test/', 1)
        self.assertIs(self.sink.verified(1, True), False)

    async def test_done_goal_reached_unchanged(self):
        await self.page.set_content('<p id="seen"></p><p id="state">Finished</p>')
        await self.sink.capture(self.page, done('goal_reached'), None, 'https://example.test/', 1)
        self.assertIs(self.sink.verified(1, True), True)
        self.assertEqual(self.sink.completions, {1: True})
        # Milestone never seen in attempt 2: the check alone is not enough.
        await self.page.set_content('<p id="state">Finished</p>')
        await self.sink.capture(self.page, done('goal_reached'), None, 'https://example.test/', 2)
        self.assertIs(self.sink.verified(2, True), False)
        # goal_reached that the worker judged gave_up keeps its check result.
        await self.page.set_content('<p id="seen"></p><p id="state">Started</p>')
        await self.sink.capture(self.page, done('goal_reached'), None, 'https://example.test/', 3)
        self.assertIs(self.sink.verified(3, False), False)

    async def test_exception_end_uses_last_capture_for_worker_success(self):
        # Milestone seen on the first page, check met only on the last captured page.
        await self.click_capture('<p id="seen"></p><p id="state">Started</p><button>Pay now</button>')
        await self.click_capture('<p id="state">Finished</p><button>Pay now</button>')
        self.assertIs(self.sink.verified(1, True), True)
        self.assertNotIn(1, self.sink.completions)
        # Not a worker success and no done: not checked, as before.
        self.assertIsNone(self.sink.verified(1, False))
        attempt = SimpleNamespace(id=1, success=True, success_estimated=False)
        self.assertIs(verified_success({'check': CHECK}, self.sink, attempt), True)
        self.assertIs(verified_success({'check': CHECK}, self.sink, SimpleNamespace(id=1, success=False, success_estimated=False)), None)

    async def test_exception_end_last_capture_failed_is_false(self):
        await self.click_capture('<p id="seen"></p><p id="state">Finished</p><button>Pay now</button>')
        await self.click_capture('<p id="state">Started</p><button>Pay now</button>')
        self.assertIs(self.sink.verified(1, True), False)

    async def test_task_without_check_keeps_worker_rule(self):
        sink = EvidenceSink(Path(self.tmp.name)/'none')
        await self.page.set_content('<p>Finished</p>')
        await sink.capture(self.page, done('safety_stop'), None, 'https://example.test/', 1)
        self.assertIsNone(sink.verified(1, True))
        self.assertIs(verified_success({}, sink, SimpleNamespace(id=1, success=True, success_estimated=False)), True)
        self.assertIs(verified_success({}, sink, SimpleNamespace(id=1, success=True, success_estimated=True)), False)


class WorkerSafetyStopIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_safety_stop_exception_success_gets_last_capture_check(self):
        """Real worker loop with a fake model: SafetyStop is raised after the pre-action capture."""
        from sqlalchemy import create_engine, select
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.orm import sessionmaker

        from apps.api.db.models import AccessCode, Attempt, Base, Project, Run, Task
        from benchmark.serve import serve
        from tests.test_agent_core import progress
        from worker.agent.run import execute_run
        from worker.llm.fake import FakeAdapter

        @compiles(JSONB, 'sqlite')
        def jsonb_sqlite(_type, _compiler, **kw):
            return 'JSON'

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'index.html').write_text('<main><p id="seen"></p><p id="state">Finished</p><button>Pay now</button></main>')
            engine = create_engine('sqlite:///'+str(root/'test.db'))
            Base.metadata.create_all(engine)
            factory = sessionmaker(engine, expire_on_commit=False)
            with serve(root) as origin:
                with factory.begin() as db:
                    owner = AccessCode(code_hash='synthetic', active=False);db.add(owner);db.flush()
                    project = Project(owner_id=owner.id, name='Synthetic', base_url=origin+'/index.html');db.add(project);db.flush()
                    task = Task(project_id=project.id, description='Finish the order', success_condition={'text_present': 'Finished'})
                    db.add(task);db.flush()
                    run = Run(task_id=task.id, viewport='desktop', mode='agent', repeat_n=3, model='claude-haiku-5-5')
                    db.add(run);db.flush();rid = run.id
                replies = [json.dumps({'action': 'click', 'target': 1, 'thought': 'Pay', 'expectation': 'Paid'})]
                sink = EvidenceSink(root/'dom', CHECK, [MILESTONE])
                with patch('worker.agent.persistence.update_progress', progress), patch('worker.agent.run.update_progress', progress):
                    await execute_run(rid, factory, adapter_factory=lambda _: FakeAdapter(replies), evidence_sink=sink)
                with factory() as db:
                    attempts = list(db.scalars(select(Attempt).where(Attempt.run_id == rid)))
                    self.assertEqual([(a.end_reason, a.success) for a in attempts], [('success', True)]*3)
                    self.assertEqual(sink.completions, {})
                    self.assertEqual([verified_success({'check': CHECK}, sink, a) for a in attempts], [True]*3)
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
