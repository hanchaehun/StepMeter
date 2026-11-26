"""RQ entrypoint for agent and replay runs; no implicit benchmark or credential setup."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from apps.api.db.models import Attempt, Metric, Project, Run, Task
from ml.issue_clf.runtime import finalize_scores
from ml.issue_clf.scoring import ScoreConfig
from worker.agent.loop import execute_attempt
from worker.agent.persistence import Canceled, running, start
from worker.agent.termination import representative
from worker.compare.service import save_agent_spread
from worker.llm.explain import explain_run
from worker.llm.select import make_adapter
from worker.metrics.persistence import save_run_medians
from worker.metrics.postprocess import finalize_run_metrics
from worker.queue.runs import update_progress
from worker.replay.runner import execute_replay

ROOT = Path(__file__).resolve().parents[2]
VIEWPORTS = {'desktop': {'width': 1280, 'height': 800}, 'mobile': {'width': 390, 'height': 844}}
MAX_PARALLEL = 3  # 계획서 4.6 "LLM API 호출 한도 안에서 최대 3개를 동시에 실행"
# #55: LLM 어댑터가 429(호출 한도)면 던지는 예외 이름. execute_attempt가 attempt.end_detail에 예외 이름을 적는다
RATE_LIMITED = 'LLMRateLimitError'


def max_parallel_attempts():
    """동시에 돌릴 에이전트 attempt 수. STEPMETER_MAX_PARALLEL_ATTEMPTS(1~3, 기본 3)로 줄일 수 있다(스테이징 메모리).

    숫자가 아니면 기본값, 범위를 벗어나면 1~3으로 맞춘다.
    """
    try:
        value = int(os.environ.get('STEPMETER_MAX_PARALLEL_ATTEMPTS', MAX_PARALLEL))
    except ValueError:
        return MAX_PARALLEL
    return min(MAX_PARALLEL, max(1, value))


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
            replay = row.mode == 'replay_only' or (row.mode == 'auto' and row.base_run_id is not None)
            base_attempt_id = None
            if replay:
                base = session.get(Run, row.base_run_id) if row.base_run_id else None
                if (base is None or base.status != 'completed' or base.task_id != row.task_id
                        or base.viewport != row.viewport or base.representative_attempt_id is None):
                    raise ValueError('Replay requires a completed matching base with a representative path')
                base_attempt_id = base.representative_attempt_id
            if row.mode == 'replay_only':
                row.prompt_version = None
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
        replay_full = False
        if replay:
            with factory.begin() as session:
                running(session, run_id)
                attempt = Attempt(run_id=run_id, index=1, kind='replay')
                session.add(attempt)
                session.flush()
                replay_attempt_id = attempt.id
            context = await browser.new_context(viewport=VIEWPORTS[config['viewport']],
                                                device_scale_factor=3 if config['viewport']=='mobile' else 1,
                                                is_mobile=config['viewport']=='mobile',
                                                has_touch=config['viewport']=='mobile')
            try:
                page = await context.new_page()
                page.set_default_timeout(10000)
                page.set_default_navigation_timeout(30000)
                replay_full = await execute_replay(page, factory, config, replay_attempt_id,
                                                   base_attempt_id, axe_path=axe_path)
            finally:
                await context.close()
        agent_needed = row.mode == 'agent' or (row.mode == 'auto' and (not replay or not replay_full))
        score_path = os.environ.get('STEPMETER_ISSUE_SCORE_CONFIG') if agent_needed else None
        config['issue_score'] = (ScoreConfig.from_dict(json.loads(
            Path(score_path).read_text(encoding='utf-8'))) if score_path else None)
        config['score_evidence'] = {}

        adapters = []  # 설명 생성에 마지막 attempt의 어댑터를 다시 쓴다 (adapter_factory를 더 부르지 않는다)

        async def attempt_once(index):
            """attempt 하나를 돌리고, 호출 한도(LLMRateLimitError)로 끝났으면 True."""
            with factory.begin() as session:
                running(session, run_id)
                attempt = Attempt(run_id=run_id, index=index + (1 if replay else 0), kind='agent')
                session.add(attempt)
                session.flush()
                attempt_id = attempt.id
            adapter = adapter_factory(config['model'])
            adapters.append(adapter)
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
            with factory() as session:
                # 예외에 code가 있으면 loop.py가 'LLMRateLimitError:<code>'로 적는다
                return (session.get(Attempt, attempt_id).end_detail or '').startswith(RATE_LIMITED)

        # 계획서 4.6: attempt를 최대 max_parallel_attempts()개 동시에. 재생이 끝난 뒤에 시작한다 (ADR 0011 8번).
        # 호출 한도로 끝난 attempt가 하나라도 나오면, 그때 실행 중인 attempt가 모두 끝난 뒤 남은 attempt를 하나씩 돌린다.
        # 실행 중인 attempt는 멈추지 않고, 한도로 끝난 attempt는 다시 재지 않는다.
        # 한 attempt의 예외(취소 포함)는 실행 중인 attempt가 모두 끝난 뒤에 올리고, 그 뒤로는 새 attempt를 시작하지 않는다
        # (취소면 각 attempt가 다음 step에서 스스로 멈춘다).
        pending = list(range(1, config['repeat_n'] + 1)) if agent_needed else []
        limit, rate_limited, failure = max_parallel_attempts(), False, None
        tasks: dict[asyncio.Task, int] = {}  # 실행 중 task → attempt 번호
        try:
            while tasks or (pending and failure is None):
                while pending and failure is None and len(tasks) < (1 if rate_limited else limit):
                    index = pending.pop(0)
                    tasks[asyncio.create_task(attempt_once(index))] = index
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in sorted(done, key=tasks.__getitem__):
                    del tasks[task]
                    if task.exception() is not None:
                        failure = failure or task.exception()
                    elif task.result():
                        rate_limited = True
        finally:
            for task in tasks:  # execute_run 자체가 취소된 경우에만 남는다
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if failure is not None:
            raise failure
        with factory.begin() as session:
            row = running(session, run_id)
            kind = 'agent' if agent_needed else 'replay'
            finalize_run_metrics(session, run_id, kind=kind)
            save_run_medians(session, run_id, kind=kind)
            if agent_needed and config['issue_score'] is not None:
                finalize_scores(session, run_id, config['issue_score'], config['score_evidence'])
            attempts = list(session.scalars(select(Attempt).where(Attempt.run_id == run_id)))
            counts = dict(session.execute(select(Metric.attempt_id, Metric.value).where(
                Metric.run_id == run_id, Metric.attempt_id.is_not(None), Metric.key == 'step_count')).all())
            row.representative_attempt_id = representative(attempts, counts)
            if agent_needed and row.representative_attempt_id is not None:
                save_agent_spread(session, row)
            if all(attempt.end_reason == 'error' for attempt in attempts):
                # ADR 0010 #8: every attempt errored -> system failure, not a UX result.
                row.status, row.finished_at = 'failed', datetime.now(timezone.utc)
                return
        # 설명 생성(개발계획서 6.1): 이슈가 모두 저장된 뒤 한 번. LLM 호출은 잠금 밖에서 한다 (worker/llm/explain.py)
        if agent_needed and adapters:
            await explain_run(factory, run_id, adapters[-1])
        with factory.begin() as session:
            row = running(session, run_id)
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
