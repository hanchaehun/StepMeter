"""RQ entrypoint. Agent mode only; no implicit benchmark launch or credential setup."""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import Attempt, Metric, Project, Run, Task
from worker.agent.loop import execute_attempt
from worker.agent.persistence import Canceled, running, start
from worker.agent.termination import representative
from worker.llm.select import make_adapter
from worker.metrics.persistence import save_run_medians
from worker.metrics.postprocess import finalize_run_metrics
from worker.queue.runs import update_progress

ROOT = Path(__file__).resolve().parents[2]
VIEWPORTS = {'desktop': {'width': 1280, 'height': 800}, 'mobile': {'width': 390, 'height': 844}}


async def execute_run(run_id, factory, *, adapter_factory=make_adapter, browser=None, axe_path=None, evidence_sink=None):
    """Inject a browser/adapter for synthetic tests; default performs normal agent work."""
    with factory.begin() as session:
        if not start(session, run_id):
            return
    owned_playwright = owned_browser = None
    try:
        with factory.begin() as session:
            row = running(session, run_id)
            task = session.get(Task, row.task_id)
            project = session.get(Project, task.project_id)
            if row.mode == 'replay_only' or (row.mode == 'auto' and row.base_run_id is not None):
                raise ValueError('Replay dispatch is not implemented by the agent entrypoint')
            config = dict(id=run_id, model=row.model, viewport=row.viewport,
                          repeat_n=row.repeat_n, base_url=project.base_url,
                          description=task.description, success_condition=task.success_condition)
        axe_path = Path(axe_path or os.environ.get('AXE_CORE_PATH', ROOT/'node_modules/axe-core/axe.min.js'))
        if not axe_path.is_file():
            raise FileNotFoundError('Install root npm dependencies for axe-core')
        if browser is None:
            owned_playwright = await async_playwright().start()
            owned_browser = await owned_playwright.chromium.launch(headless=True)
            browser = owned_browser
        for index in range(1, config['repeat_n'] + 1):
            with factory.begin() as session:
                running(session, run_id)
                attempt = Attempt(run_id=run_id, index=index, kind='agent')
                session.add(attempt)
                session.flush()
                attempt_id = attempt.id
            adapter = adapter_factory(config['model'])
            context = await browser.new_context(viewport=VIEWPORTS[config['viewport']],
                                                device_scale_factor=3 if config['viewport']=='mobile' else 1,
                                                is_mobile=config['viewport']=='mobile',
                                                has_touch=config['viewport']=='mobile')
            try:
                page = await context.new_page()
                page.set_default_timeout(10000)
                page.set_default_navigation_timeout(30000)
                await execute_attempt(page, factory, config, attempt_id, adapter, axe_path=axe_path, evidence_sink=evidence_sink)
            finally:
                await context.close()
        with factory.begin() as session:
            row = running(session, run_id)
            finalize_run_metrics(session, run_id)
            save_run_medians(session, run_id)
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id)))
            counts = dict(session.execute(select(Metric.attempt_id, Metric.value).where(
                Metric.run_id == run_id, Metric.attempt_id.is_not(None), Metric.key == 'step_count')).all())
            row.representative_attempt_id = representative(attempts, counts)
            if all(attempt.end_reason == 'error' for attempt in attempts):
                # ADR 0010 #8: every attempt errored -> system failure, not a UX result.
                row.status, row.finished_at = 'failed', datetime.now(timezone.utc)
                return
            if not update_progress(session, run_id, finished=True):
                raise Canceled()
            row.status, row.finished_at = 'completed', datetime.now(timezone.utc)
    except Canceled:
        return
    except Exception:
        with factory.begin() as session:
            session.execute(update(Run).where(Run.id == run_id, Run.status == 'running').values(
                status='failed', finished_at=datetime.now(timezone.utc)))
        raise
    finally:
        if owned_browser:
            await owned_browser.close()
        if owned_playwright:
            await owned_playwright.stop()


def run(run_id):
    """Queue contract: only run_id is passed; DB owns all run configuration."""
    engine = create_engine(os.environ['DATABASE_URL'])
    try:
        asyncio.run(execute_run(run_id, sessionmaker(engine, expire_on_commit=False)))
    finally:
        engine.dispose()
