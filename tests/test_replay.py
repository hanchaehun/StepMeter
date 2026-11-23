"""Synthetic replay contracts from ADR 0011 section 8 and worker/replay/README.md."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.async_api import async_playwright
from playwright.async_api import Error as PlaywrightError
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import AccessCode, Attempt, Base, ElementSnapshot, Issue, LlmCall, Metric, Project, Run, Step, Task
from worker.agent.run import execute_run
from worker.llm.fake import FakeAdapter


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _progress(session, run_id, finished=False):
    session.flush()
    row = session.get(Run, run_id)
    for attempt in session.scalars(select(Attempt).where(Attempt.run_id == run_id)):
        attempt.steps_count = session.scalar(select(func.count(Step.id)).where(Step.attempt_id == attempt.id))
    if row.status != "running":
        return False
    row.progress = 100 if finished else 20
    return True


def _action(name, **fields):
    return json.dumps(dict(action=name, thought="test decision", expectation="test outcome", **fields))


class ReplayIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.page_path = Path(self.tmp.name) / "page.html"
        self.base_html = ('<!doctype html><title>Replay</title><main>'
                          '<button onclick="document.querySelector(\'#result\').textContent=\'Complete\'">Next</button>'
                          '<p id="result"></p></main>')
        self.page_path.write_text(self.base_html, encoding="utf-8")
        self.engine = create_engine("sqlite:///" + self.tmp.name + "/db.sqlite")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        with self.factory.begin() as session:
            code = AccessCode(code_hash="replay-test")
            session.add(code)
            session.flush()
            project = Project(owner_id=code.id, name="Replay", base_url=self.page_path.as_uri())
            session.add(project)
            session.flush()
            task = Task(project_id=project.id, description="Click Next", success_condition={"text_present": "Complete"})
            session.add(task)
            session.flush()
            self.task_id = task.id
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.patches = [
            patch("worker.agent.persistence.update_progress", _progress),
            patch("worker.agent.run.update_progress", _progress),
            patch("worker.queue.runs.SCREENSHOT_DIR", Path(self.tmp.name) / "shots"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    def create_run(self, mode, *, base_run_id=None, repeat_n=1, viewport="desktop"):
        with self.factory.begin() as session:
            row = Run(task_id=self.task_id, mode=mode, base_run_id=base_run_id,
                      viewport=viewport, repeat_n=repeat_n, model="fake", status="queued")
            session.add(row)
            session.flush()
            return row.id

    async def make_base(self):
        run_id = self.create_run("agent")
        await execute_run(run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([
                              _action("click", target=1), _action("done", reason="goal_reached")]))
        with self.factory() as session:
            self.assertEqual(session.get(Run, run_id).status, "completed")
        return run_id

    async def test_full_auto_replay_records_steps_without_llm_or_agent_attempt(self):
        base_id = await self.make_base()
        run_id = self.create_run("auto", base_run_id=base_id, repeat_n=3)
        await execute_run(run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: self.fail("full replay called an LLM adapter"))
        with self.factory() as session:
            run = session.get(Run, run_id)
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id)))
            self.assertEqual((run.status, run.progress), ("completed", 100))
            self.assertEqual(len(attempts), 1)
            self.assertEqual((attempts[0].kind, attempts[0].replay_status, attempts[0].success,
                              attempts[0].steps_count), ("replay", "full", True, 2))
            self.assertEqual(run.representative_attempt_id, attempts[0].id)
            self.assertEqual(session.scalar(select(func.count(LlmCall.id)).where(LlmCall.run_id == run_id)), 0)
            self.assertEqual(session.scalar(select(Metric.value).where(
                Metric.run_id == run_id, Metric.attempt_id.is_(None), Metric.key == "click_count")), 1)

    async def test_missing_target_records_partial_before_action_and_falls_back_from_start(self):
        base_id = await self.make_base()
        self.page_path.write_text("<!doctype html><title>Replay</title><p>Complete</p>", encoding="utf-8")
        run_id = self.create_run("auto", base_run_id=base_id, repeat_n=2)
        await execute_run(run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([_action("done", reason="goal_reached")]))
        with self.factory() as session:
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id).order_by(Attempt.index)))
            self.assertEqual([(a.index, a.kind) for a in attempts], [(1, "replay"), (2, "agent"), (3, "agent")])
            self.assertEqual((attempts[0].replay_status, attempts[0].diverged_at_step, attempts[0].steps_count),
                             ("partial", 0, 0))
            self.assertEqual([a.success for a in attempts[1:]], [True, True])
            self.assertEqual(session.get(Run, run_id).status, "completed")

    async def test_replay_only_stops_at_divergence(self):
        base_id = await self.make_base()
        self.page_path.write_text("<!doctype html><title>Replay</title><p>Changed</p>", encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: self.fail("replay_only called an LLM adapter"))
        with self.factory() as session:
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id)))
            self.assertEqual(len(attempts), 1)
            self.assertEqual((attempts[0].replay_status, attempts[0].diverged_at_step), ("partial", 0))
            self.assertEqual((session.get(Run, run_id).status, session.get(Run, run_id).prompt_version),
                             ("completed", None))
            self.assertEqual(list(session.scalars(select(Metric).where(
                Metric.run_id == run_id, Metric.attempt_id.is_(None)))), [])

    async def test_ambiguous_target_stops_before_action(self):
        base_id = await self.make_base()
        self.page_path.write_text('<!doctype html><title>Replay</title><main>'
                                  '<button>Next</button><button>Next</button><p id="result"></p></main>',
                                  encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.end_detail),
                             ("partial", 0, "target_ambiguous"))
            self.assertEqual(session.scalar(select(func.count(Step.id)).where(Step.attempt_id == attempt.id)), 0)

    async def test_renamed_duplicate_does_not_redirect_replay_to_remaining_name(self):
        def catalog(first_name):
            return (
                '<!doctype html><main>'
                f'<button onclick="result.textContent=\'Complete: intended product\'">{first_name}</button>'
                '<button onclick="result.textContent=\'Complete: other product\'">Next</button>'
                '<p id="result"></p></main>'
            )

        self.page_path.write_text(catalog("Next"), encoding="utf-8")
        base_id = await self.make_base()
        self.page_path.write_text(catalog("Continue"), encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)

        await execute_run(run_id, self.factory, browser=self.browser)

        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.end_detail),
                             ("partial", 0, "target_identity_unverified"))
            self.assertFalse(attempt.success)
            self.assertEqual(session.scalar(select(func.count(Step.id)).where(Step.attempt_id == attempt.id)), 0)

    async def test_single_target_rename_replays_when_other_observed_names_match(self):
        base_id = await self.make_base()
        self.page_path.write_text(self.base_html.replace(">Next<", ">Next step<"), encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)

        await execute_run(run_id, self.factory, browser=self.browser)

        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.success), ("full", True))

    async def test_effect_change_keeps_executed_divergent_step(self):
        base_id = await self.make_base()
        self.page_path.write_text('<!doctype html><title>Replay</title><main>'
                                  '<button>Next</button><p id="result"></p></main>', encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            steps = list(session.scalars(select(Step).where(Step.attempt_id == attempt.id)))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step), ("partial", 0))
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0].effect_type, "no_change")

    async def test_url_path_change_keeps_executed_divergent_step(self):
        next_page = Path(self.tmp.name) / "next.html"
        next_page.write_text("<!doctype html><p>Complete</p>", encoding="utf-8")
        self.page_path.write_text('<!doctype html><a href="next.html">Next</a>', encoding="utf-8")
        base_id = await self.make_base()
        other_page = Path(self.tmp.name) / "other.html"
        other_page.write_text("<!doctype html><p>Complete</p>", encoding="utf-8")
        self.page_path.write_text('<!doctype html><a href="other.html">Next</a>', encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            steps = list(session.scalars(select(Step).where(Step.attempt_id == attempt.id)))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.end_detail),
                             ("partial", 0, "url_path_changed"))
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0].effect_type, "url_change")

    async def test_cancel_during_replay_preserves_canceled_status(self):
        base_id = await self.make_base()
        run_id = self.create_run("replay_only", base_run_id=base_id)

        def cancel_after_step(session, current_run_id, finished=False):
            if not finished and session.scalar(select(func.count(Step.id)).join(
                    Attempt, Step.attempt_id == Attempt.id).where(
                    Attempt.run_id == current_run_id, Attempt.kind == "replay")):
                session.get(Run, current_run_id).status = "canceled"
                return False
            return _progress(session, current_run_id, finished)

        with patch("worker.agent.persistence.update_progress", cancel_after_step):
            await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual(session.get(Run, run_id).status, "canceled")
            self.assertEqual(session.scalar(select(func.count(Step.id)).where(Step.attempt_id == attempt.id)), 1)

    async def test_replay_only_requires_matching_completed_base(self):
        incomplete = self.create_run("agent")
        run_id = self.create_run("replay_only", base_run_id=incomplete)
        with self.assertRaisesRegex(ValueError, "completed matching base"):
            await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            self.assertEqual(session.get(Run, run_id).status, "failed")
            self.assertEqual(session.scalar(select(func.count(Attempt.id)).where(Attempt.run_id == run_id)), 0)

    async def test_invalid_recorded_action_stops_replay_as_partial(self):
        base_id = await self.make_base()
        with self.factory.begin() as session:
            base = session.get(Run, base_id)
            first = session.scalar(select(Step).where(
                Step.attempt_id == base.representative_attempt_id, Step.idx == 0))
            first.action = {"action": "unknown"}
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.steps_count),
                             ("partial", 0, 0))
            self.assertEqual(session.get(Run, run_id).status, "completed")

    async def test_recorded_target_without_snapshot_stops_replay_as_partial(self):
        base_id = await self.make_base()
        with self.factory.begin() as session:
            base = session.get(Run, base_id)
            first = session.scalar(select(Step).where(
                Step.attempt_id == base.representative_attempt_id, Step.idx == 0))
            session.delete(session.scalar(select(ElementSnapshot).where(ElementSnapshot.step_id == first.id)))
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.steps_count),
                             ("partial", 0, 0))
            self.assertEqual(session.get(Run, run_id).status, "completed")

    async def test_full_replay_evaluates_target_rules(self):
        # WCAG 2.5.8: two 10x10 targets touching one another have overlapping 24px circles.
        self.page_path.write_text('<!doctype html><title>Replay</title><main>'
                                  '<button style="width:10px;height:10px;padding:0" '
                                  'onclick="document.querySelector(\'#result\').textContent=\'Complete\'">Next</button>'
                                  '<button style="width:10px;height:10px;padding:0">Other</button>'
                                  '<p id="result"></p></main>', encoding="utf-8")
        base_id = await self.make_base()
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual(attempt.replay_status, "full")
            rules = set(session.scalars(select(Issue.rule_id).where(Issue.run_id == run_id)))
            self.assertIn("R01", rules)
            r07 = session.scalar(select(Issue).where(Issue.run_id == run_id, Issue.rule_id == "R07"))
            first = session.scalar(select(Step).where(Step.attempt_id == attempt.id, Step.idx == 0))
            self.assertIsNotNone(r07)
            self.assertEqual(r07.step_id, first.id)

    async def test_safety_guard_stops_replay_as_partial_before_click(self):
        base_id = await self.make_base()
        self.page_path.write_text('<!doctype html><title>Replay</title><main>'
                                  '<button aria-label="Next">Pay now</button><p id="result"></p></main>',
                                  encoding="utf-8")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.steps_count),
                             ("partial", 0, 0))
            self.assertEqual(session.get(Run, run_id).status, "completed")

    async def test_replay_password_without_current_task_value_blocks_before_typing(self):
        self.page_path.write_text('<!doctype html><title>Replay</title><main>'
                                  '<input type="password" aria-label="Password"></main>', encoding="utf-8")
        with self.factory.begin() as session:
            task = session.get(Task, self.task_id)
            task.description = "Type abc123 in Password"
            task.success_condition = None
        base_id = self.create_run("agent")
        await execute_run(base_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _: FakeAdapter([
                              _action("type", target=1, text="abc123"),
                              _action("done", reason="goal_reached")]))
        with self.factory.begin() as session:
            session.get(Task, self.task_id).description = "Type the password"
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.end_reason,
                              attempt.end_detail, attempt.steps_count),
                             ("partial", "blocked", "login_wall", 0))

    async def test_observation_error_marks_partial_and_auto_still_retries(self):
        base_id = await self.make_base()
        self.page_path.write_text("<!doctype html><title>Replay</title><p>Complete</p>", encoding="utf-8")
        run_id = self.create_run("auto", base_run_id=base_id)
        with patch("worker.replay.runner.observe", side_effect=PlaywrightError("rerendered during observation")):
            await execute_run(run_id, self.factory, browser=self.browser,
                              adapter_factory=lambda _model: FakeAdapter([_action("done", reason="goal_reached")]))
        with self.factory() as session:
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id).order_by(Attempt.index)))
            self.assertEqual([(a.kind, a.replay_status, a.diverged_at_step) for a in attempts],
                             [("replay", "partial", 0), ("agent", None, None)])
            self.assertEqual(session.get(Run, run_id).status, "completed")

    async def test_select_option_inspection_error_marks_partial(self):
        self.page_path.write_text('<!doctype html><title>Replay</title><main>'
                                  '<select onchange="document.querySelector(\'#result\').textContent=\'Complete\'">'
                                  '<option>Choose</option><option>Second</option></select>'
                                  '<p id="result"></p></main>', encoding="utf-8")
        base_id = self.create_run("agent")
        await execute_run(base_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([
                              _action("select", target=1, option=2),
                              _action("done", reason="goal_reached")]))
        with self.factory() as session:
            self.assertEqual(session.get(Run, base_id).status, "completed")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        with patch("worker.replay.runner.PlaywrightDriver.select_options",
                   side_effect=ValueError("numbered target did not resolve")):
            await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.diverged_at_step, attempt.steps_count),
                             ("partial", 0, 0))
            self.assertEqual(session.get(Run, run_id).status, "completed")

    # #75: 실행 버튼이 없는 폼은 Enter(암묵적 제출)로만 "Complete"가 된다.
    ENTER_ONLY = ('<!doctype html><title>Replay</title><main>'
                  '<form onsubmit="event.preventDefault();document.querySelector(\'#result\').textContent=\'Complete\'">'
                  '<input name="q" aria-label="Search"></form><p id="result"></p></main>')

    async def test_replay_reproduces_submit(self):
        self.page_path.write_text(self.ENTER_ONLY, encoding="utf-8")
        base_id = self.create_run("agent")
        await execute_run(base_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([
                              _action("type", target=1, text="shoes", submit=True),
                              _action("done", reason="goal_reached")]))
        with self.factory() as session:
            self.assertEqual(session.get(Run, base_id).status, "completed")
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: self.fail("replay_only called an LLM adapter"))
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            # Without Enter the success text never appears, so a full verified replay proves submit ran.
            self.assertEqual((attempt.replay_status, attempt.success), ("full", True))
            first = session.scalar(select(Step).where(Step.attempt_id == attempt.id, Step.idx == 0))
            self.assertEqual((first.action["action"], first.action["submit"]), ("type", True))

    async def test_old_record_without_submit_replays_as_false(self):
        # Typing alone completes the task; an Enter would replace the text with "Submitted".
        self.page_path.write_text(
            '<!doctype html><title>Replay</title><main>'
            '<form onsubmit="event.preventDefault();document.querySelector(\'#result\').textContent=\'Submitted\'">'
            '<input name="q" aria-label="Search" '
            'oninput="document.querySelector(\'#result\').textContent=\'Complete\'"></form>'
            '<p id="result"></p></main>', encoding="utf-8")
        base_id = self.create_run("agent")
        await execute_run(base_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([
                              _action("type", target=1, text="shoes"),
                              _action("done", reason="goal_reached")]))
        with self.factory.begin() as session:
            self.assertEqual(session.get(Run, base_id).status, "completed")
            base_attempt = session.get(Run, base_id).representative_attempt_id
            step = session.scalar(select(Step).where(Step.attempt_id == base_attempt, Step.idx == 0))
            # A record saved before #75 has no submit key.
            step.action = {k: v for k, v in step.action.items() if k != "submit"}
        with self.factory() as session:
            stored = session.scalar(select(Step).where(Step.attempt_id == base_attempt, Step.idx == 0))
            self.assertNotIn("submit", stored.action)
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            self.assertEqual((attempt.replay_status, attempt.success), ("full", True))
            first = session.scalar(select(Step).where(Step.attempt_id == attempt.id, Step.idx == 0))
            self.assertIs(first.action["submit"], False)


    # 재생 측정의 KLM 예상 시간 (ADR 0011 3번). 예: 새 화면에서 16자 type = 2M+P+2B+H+16K = 8.88초,
    # 이어서 click = H+M+P+2B = 3.05초, done = 0, 합 11.93초. 화면이 바뀌면 그 화면의 첫 행동에 M을 더한다.
    KLM_PAGE = ('<!doctype html><title>Replay</title><main><input aria-label="Name">'
                '<button onclick="document.querySelector(&quot;#result&quot;).textContent=&quot;Complete&quot;">'
                'Next</button><p id="result"></p></main>')
    KLM_REPLIES = [("type", {"target": 1, "text": "abcdefghijklmnop"}), ("click", {"target": 2}),
                   ("done", {"reason": "goal_reached"})]

    async def klm_base_and_replay(self, viewport):
        self.page_path.write_text(self.KLM_PAGE, encoding="utf-8")
        base_id = self.create_run("agent", viewport=viewport)
        await execute_run(base_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([_action(n, **f) for n, f in self.KLM_REPLIES]))
        run_id = self.create_run("replay_only", base_run_id=base_id, viewport=viewport)
        await execute_run(run_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: self.fail("replay_only called an LLM adapter"))
        return base_id, run_id

    def replay_klm(self, run_id):
        with self.factory() as session:
            attempt = session.scalar(select(Attempt).where(Attempt.run_id == run_id))
            steps = [s.est_seconds for s in session.scalars(
                select(Step).where(Step.attempt_id == attempt.id).order_by(Step.idx))]
            total = session.scalar(select(Metric.value).where(
                Metric.attempt_id == attempt.id, Metric.key == "est_task_time"))
            return attempt.replay_status, steps, total

    async def test_replay_stores_literature_klm_per_step_and_attempt(self):
        _, run_id = await self.klm_base_and_replay("desktop")
        status, steps, total = self.replay_klm(run_id)
        self.assertEqual(status, "full")
        self.assertEqual(len(steps), 3)
        for got, want in zip(steps, [8.88, 3.05, 0.0]):
            self.assertAlmostEqual(got, want, places=6)
        self.assertAlmostEqual(total, 11.93, places=6)

    async def test_mobile_replay_has_no_time_estimate(self):
        _, run_id = await self.klm_base_and_replay("mobile")
        status, steps, total = self.replay_klm(run_id)
        self.assertEqual((status, steps, total), ("full", [None, None, None], None))

    async def test_compare_replay_block_judges_est_task_time(self):
        from worker.compare.service import compare_runs
        base_id, run_id = await self.klm_base_and_replay("desktop")
        with self.factory.begin() as session:
            result = compare_runs(session, session.get(Run, base_id), session.get(Run, run_id))
        row = next(m for m in result["replay"]["metric_changes"] if m["key"] == "est_task_time")
        self.assertEqual(row["threshold"], 0.1)
        self.assertNotEqual(row["verdict"], "not_comparable")
        self.assertAlmostEqual(row["target"], 11.93, places=6)

    async def test_new_screen_during_replay_adds_mental_step_again(self):
        # 첫 화면 링크 click = M(새 화면) + M+P+2B = 4.0, 두 번째 화면의 첫 click도 M이 다시 붙어 4.0, done 0
        second = Path(self.tmp.name) / "second.html"
        second.write_text('<!doctype html><title>Second</title><main><button onclick="document.querySelector'
                          '(&quot;#result&quot;).textContent=&quot;Complete&quot;">Finish</button>'
                          '<p id="result"></p></main>', encoding="utf-8")
        self.page_path.write_text('<!doctype html><title>Replay</title><main><a href="second.html">Next page</a></main>',
                                  encoding="utf-8")
        base_id = self.create_run("agent")
        await execute_run(base_id, self.factory, browser=self.browser,
                          adapter_factory=lambda _model: FakeAdapter([
                              _action("click", target=1), _action("click", target=1),
                              _action("done", reason="goal_reached")]))
        run_id = self.create_run("replay_only", base_run_id=base_id)
        await execute_run(run_id, self.factory, browser=self.browser)
        status, steps, total = self.replay_klm(run_id)
        self.assertEqual(status, "full")
        for got, want in zip(steps, [4.0, 4.0, 0.0]):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(len(steps), 3)
        self.assertAlmostEqual(total, 8.0, places=6)


if __name__ == "__main__":
    unittest.main()
