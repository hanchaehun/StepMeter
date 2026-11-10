"""One isolated attempt. Only adapter.ask is model-dependent; tests inject FakeAdapter."""
import json
import asyncio
import uuid
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from worker.a11y.scan import scan_page
from worker.agent.action_feedback import failure_code, missing_fields, retry_message
from worker.agent.observation import describe, labeled_screenshot, state_hash
from worker.agent.persistence import Canceled, finish_attempt, log_call, running, save_step
from worker.agent.safety import SafetyStop, blocked_reason
from worker.agent.termination import LoopGuard, verify_success
from worker.collect.collector import observe, record_first_view, resolve_element
from worker.driver.effects import EffectResult
from worker.driver.playwright_driver import ActionResult, PlaywrightDriver
from worker.llm.base import LLMRequest
from worker.metrics.cursor_distance import calculate_cursor_distance
from worker.metrics.fitts import calculate_fitts_ids
from worker.metrics.interactions import (calculate_scroll_distance, count_interactions,
    count_no_response_clicks, count_page_transitions, count_repeated_clicks)
from worker.metrics.persistence import save_attempt_metrics
from worker.rules.engine import evaluate_step, evaluate_axe, axe_target_size_result
from worker.rules.persistence import save_candidates
from worker.rules.r05 import evaluate as loop_candidate
from worker.rules.r06 import FirstTargetTracker, screen_key
from worker.schemas import ActionInputError, parse_action_json

PROMPT = Path(__file__).resolve().parents[2] / 'prompts/action_v1.md'


async def execute_attempt(page, factory, config, attempt_id, adapter, *, axe_path, max_steps=30, max_seconds=300):
    driver = PlaywrightDriver(page)
    guard, first = LoopGuard(), FirstTargetTracker()
    actions, effects, identities, targets, history = [], [], [], [], []
    urls, scrolls = [], []
    navigation = {'changed': False}
    def navigated(frame):
        if frame == page.main_frame:
            navigation['changed'] = True
    page.on('framenavigated', navigated)
    reason, success, estimated, detail = 'budget_exceeded', False, False, None
    budget = asyncio.timeout(max_seconds)
    try:
        async with budget:
            await page.goto(config['base_url'], wait_until='domcontentloaded')
            await record_first_view(page)
            navigation['changed'] = False
            urls.append(page.url)
            scrolls.append(await page.evaluate('scrollY'))
            idx, stale_retries = 0, 0
            while idx < max_steps:
                with factory.begin() as session:
                    running(session, config['id'])
                block = await blocked_reason(page)
                if block:
                    reason, detail = 'blocked', block
                    break
                elements = await observe(page)
                rows = await describe(elements, driver)
                state, url = state_hash(page.url, elements), page.url
                document_id = await page.evaluate('(nonce) => globalThis.__stepmeterDocumentId ||= nonce', uuid.uuid4().hex)
                context = {'task': config['description'], 'elements': rows,
                           'recent_actions': history[-5:]}
                screenshot = await labeled_screenshot(page, rows)
                for retry in range(3):
                    request = LLMRequest(purpose='action', prompt_version='action_v1',
                        system=PROMPT.read_text(encoding='utf-8'),
                        user_text=json.dumps(context, ensure_ascii=False),
                        image_jpeg=screenshot, run_id=config['id'])
                    response = await adapter.ask(request)
                    log_call(factory, config['id'], response)
                    with factory.begin() as session:
                        running(session, config['id'])
                    try:
                        action = parse_action_json(response.text)
                        break
                    except ActionInputError as error:
                        # Only field names are derived from the reply; never its values or text.
                        name, missing = (missing_fields(response.text)
                                         if error.code == 'invalid_fields' else (None, ()))
                        if retry == 2:
                            raise ActionInputError(failure_code(error.code, missing)) from None
                        context['invalid_action'] = retry_message(error.code, name, missing)
                if hasattr(action, 'target') and action.target not in {r['el_id'] for r in rows}:
                    raise ValueError('Target is outside the advertised observation')
                repeated = guard.repeated(state, action)
                axe = None
                identity = None
                if hasattr(action, 'target'):
                    try:
                        handle = await resolve_element(page, action.target)
                    except PlaywrightError as error:
                        if 'stale el_id' not in str(error) or stale_retries >= 3:
                            raise
                        stale_retries += 1
                        continue
                    try:
                        identity = await handle.evaluate('''(el, nonce) => {
                            const win=el.ownerDocument.defaultView;
                            const store=win.__stepmeterAgentIdentity ||= {nodes:new WeakMap(),count:0,nonce};
                            if (!store.nodes.has(el)) store.nodes.set(el,++store.count);
                            return store.nonce+':'+store.nodes.get(el);
                        }''', uuid.uuid4().hex)
                        # Frames are not claimed as scanned by the W2 axe interface.
                        if await handle.owner_frame() == page.main_frame:
                            await handle.scroll_into_view_if_needed()
                            axe = await scan_page(page, axe_path, {idx: handle})
                    finally:
                        await handle.dispose()
                if action.action in ('done', 'fail'):
                    result = ActionResult(None, EffectResult('no_change'),
                        await page.screenshot(type='jpeg', quality=70, caret='initial'))
                else:
                    try:
                        result = await driver.perform(action)
                    except PlaywrightError as error:
                        if 'stale el_id' not in str(error) or stale_retries >= 3:
                            raise
                        stale_retries += 1
                        continue
                effect = result.effect.as_step_effect()['effect_type']
                metric_targets = targets + ([result.element] if result.element and action.action in ('click','type') else [])
                fid = calculate_fitts_ids(metric_targets)[-1] if len(metric_targets) > len(targets) else None
                with factory.begin() as session:
                    step_id, active = save_step(session, config['id'], attempt_id, idx, action,
                                                url, state, result, fitts=fid)
                    if result.element:
                        candidates = evaluate_step(result.element, step_id=step_id, action=action.action,
                            effect_type=effect, is_first_target=first.is_first_target(url, action.action),
                            mobile=config['viewport']=='mobile',
                            axe_target_size=axe_target_size_result(axe, idx) if axe else None)
                        if axe:
                            candidates += evaluate_axe(axe, {idx: step_id}, {step_id: result.element})
                        save_candidates(session, config['id'], candidates, confidence=1.0)
                if not active:
                    raise Canceled()
                actions.append(action.action)
                effects.append(effect)
                identities.append(identity)
                targets = metric_targets
                history.append({'action': action.model_dump(), 'effect': effect})
                idx += 1
                stale_retries = 0
                urls.append(page.url)
                # Include automatic pre-action scrolling plus resulting page scroll.
                if result.element:
                    scrolls.append(result.element.scroll.y)
                scrolls.append(await page.evaluate('scrollY'))
                if action.action == 'done':
                    if action.reason == 'safety_stop':
                        reason = 'safety_stop'
                    else:
                        success, estimated = await verify_success(page, config['success_condition'])
                        reason = 'success' if success else 'gave_up'
                        if not success:
                            detail = 'goal_reached was not confirmed by the configured condition'
                    break
                if action.action == 'fail':
                    reason = 'gave_up'
                    break
                if repeated:
                    reason = 'loop'
                    break
                await page.wait_for_load_state('domcontentloaded', timeout=4500)
                await asyncio.sleep(0.5)
                current_document = await page.evaluate('globalThis.__stepmeterDocumentId || null')
                if current_document != document_id or screen_key(page.url) != screen_key(url):
                    await record_first_view(page)
                    first.new_screen()
                    navigation['changed'] = False
        finish_attempt(factory, config['id'], attempt_id, reason, success, estimated, detail)
    except TimeoutError:
        reason = 'budget_exceeded' if budget.expired() else 'error'
        detail = f'{max_seconds} second attempt budget exceeded' if budget.expired() else 'TimeoutError'
        finish_attempt(factory, config['id'], attempt_id, reason, detail=detail)
    except SafetyStop:
        reason = 'safety_stop'
        finish_attempt(factory, config['id'], attempt_id, reason, detail='Unsafe control blocked before execution')
    except Canceled:
        raise
    except Exception as error:
        # Exception messages from browser/SDK may include credentials or payloads.
        reason = 'error'
        detail = type(error).__name__ + (':' + error.code if hasattr(error, 'code') else '')
        finish_attempt(factory, config['id'], attempt_id, reason, detail=detail)
    finally:
        page.remove_listener('framenavigated', navigated)
        await driver.aclose()
    values = count_interactions(actions)
    values.update(no_response_click_count=count_no_response_clicks(actions, effects),
                  repeated_click_count=count_repeated_clicks(actions, identities),
                  page_transition_count=count_page_transitions(urls),
                  scroll_distance=calculate_scroll_distance(scrolls),
                  travel_distance=calculate_cursor_distance(targets))
    fitts_values = calculate_fitts_ids(targets)
    if all(v is not None for v in fitts_values):
        values['fitts_id_sum'] = sum(fitts_values)
    with factory.begin() as session:
        running(session, config['id'])
        save_attempt_metrics(session, attempt_id, values)
        candidate = loop_candidate(reason)
        if candidate:
            save_candidates(session, config['id'], [candidate], confidence=1.0)
