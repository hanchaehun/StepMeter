"""Replay one recorded representative path without consulting an LLM."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from playwright.async_api import Error as PlaywrightError
from pydantic import ValidationError
from sqlalchemy import select

from apps.api.db.models import Attempt, ElementSnapshot as StoredSnapshot, Step
from worker.a11y.scan import scan_page
from worker.agent import persistence
from worker.agent.observation import state_hash
from worker.agent.safety import LoginWall, SafetyStop
from worker.agent.termination import verify_success
from worker.collect.collector import observe, record_first_view, resolve_element
from worker.driver.effects import EffectObservationError, EffectResult
from worker.driver.playwright_driver import ActionResult, PlaywrightDriver
from worker.matching.match import fingerprint, match
from worker.metrics.cursor_distance import calculate_cursor_distance
from worker.metrics.fitts import calculate_fitts_ids
from worker.metrics.klm import MOTOR_ACTIONS, estimate_step
from worker.metrics.interactions import (calculate_scroll_distance, count_interactions,
    count_no_response_clicks, count_page_transitions, count_repeated_clicks)
from worker.metrics.persistence import save_attempt_metrics
from worker.rules.engine import axe_target_size_result, evaluate_axe, evaluate_step, element_key
from worker.rules.persistence import save_candidates
from worker.rules.r07 import evaluate as target_difficulty_candidates
from worker.rules.r06 import FirstTargetTracker, screen_key
from worker.schemas import ACTION_ADAPTER, ElementSnapshot


@dataclass(frozen=True)
class RecordedStep:
    idx: int
    action: dict
    url: str
    effect_type: str
    snapshot: dict | None


def load_path(session, base_attempt_id: int) -> list[RecordedStep]:
    rows = session.execute(select(Step, StoredSnapshot.data).outerjoin(
        StoredSnapshot, StoredSnapshot.step_id == Step.id).where(
        Step.attempt_id == base_attempt_id).order_by(Step.idx))
    path = [RecordedStep(step.idx, step.action, step.url, step.effect_type, snapshot)
            for step, snapshot in rows]
    if not path or [step.idx for step in path] != list(range(len(path))):
        raise ValueError("Base representative path is empty or has nonconsecutive steps")
    return path


def _metrics(actions, effects, identities, targets, urls, scrolls, est_task_time=None):
    values = count_interactions(actions)
    values.update(no_response_click_count=count_no_response_clicks(actions, effects),
                  repeated_click_count=count_repeated_clicks(actions, identities),
                  page_transition_count=count_page_transitions(urls),
                  scroll_distance=calculate_scroll_distance(scrolls),
                  travel_distance=calculate_cursor_distance(targets))
    fitts_values = calculate_fitts_ids(targets)
    if all(value is not None for value in fitts_values):
        values["fitts_id_sum"] = sum(fitts_values)
    if est_task_time is not None:
        values["est_task_time"] = est_task_time  # replayed steps' KLM sum; desktop only (ADR 0011 3)
    return values


def _finish(factory, run_id, attempt_id, *, full, diverged_at, detail, success, estimated,
            actions, effects, identities, targets, target_step_ids, urls, scrolls, est_task_time=None):
    with factory.begin() as session:
        persistence.running(session, run_id)
        attempt = session.get(Attempt, attempt_id)
        attempt.replay_status = "full" if full else "partial"
        attempt.diverged_at_step = diverged_at
        attempt.end_reason = ("success" if full and success else
                              "blocked" if detail == "LoginWall" else
                              "safety_stop" if detail == "SafetyStop" else "gave_up")
        attempt.end_detail = "login_wall" if detail == "LoginWall" else detail
        attempt.success = bool(full and success)
        attempt.success_estimated = bool(full and estimated)
        save_attempt_metrics(session, attempt_id, _metrics(
            actions, effects, identities, targets, urls, scrolls, est_task_time))
        candidates = [replace(candidate, step_id=step_id, element_key=element_key(snapshot))
                      for snapshot, step_id, candidate in zip(
                          targets, target_step_ids,
                          target_difficulty_candidates(targets, calculate_fitts_ids(targets)))
                      if candidate is not None]
        if candidates:
            save_candidates(session, run_id, candidates, confidence=1.0)
        session.flush()
        if not persistence.update_progress(session, run_id):
            raise persistence.Canceled()


async def execute_replay(page, factory, config, attempt_id: int, base_attempt_id: int, *, axe_path) -> bool:
    """Persist a replay attempt; return True only for a full, verified path."""
    with factory() as session:
        path = load_path(session, base_attempt_id)
    driver = PlaywrightDriver(page, task_description=config["description"])
    first = FirstTargetTracker()
    actions, effects, identities, targets = [], [], [], []
    target_step_ids = []
    urls, scrolls = [], []
    klm_values, klm_first = [], True  # same KLM rules as worker/agent/loop.py
    full, diverged_at, detail, success, estimated = True, None, None, False, False
    try:
        await page.goto(config["base_url"], wait_until="domcontentloaded")
        await record_first_view(page)
        urls.append(page.url)
        scrolls.append(await page.evaluate("scrollY"))
        for position, recorded in enumerate(path):
            with factory.begin() as session:
                persistence.running(session, config["id"])
            if screen_key(page.url) != screen_key(recorded.url):
                full, diverged_at, detail = False, recorded.idx, "url_path_changed"
                break
            try:
                action = ACTION_ADAPTER.validate_python(recorded.action)
                if hasattr(action, "target") and recorded.snapshot is None:
                    raise ValueError("Recorded target has no snapshot")
                elements = await observe(page)
                identity = None
                if hasattr(action, "target"):
                    found = match(recorded.snapshot, elements)
                    if found.status != "matched":
                        full, diverged_at, detail = False, recorded.idx, "target_" + found.status
                        break
                    target = found.element["el_id"]
                    action = action.model_copy(update={"target": target})
                    identity = json.dumps(fingerprint(found.element), sort_keys=True, ensure_ascii=False)
                    if action.action == "select":
                        await driver.select_options(target)
            except (PlaywrightError, EffectObservationError, LoginWall, SafetyStop, ValidationError, ValueError) as error:
                full, diverged_at, detail = False, recorded.idx, type(error).__name__
                break
            url = page.url
            state = state_hash(url, elements)
            try:
                axe = None
                if hasattr(action, "target"):
                    handle = await resolve_element(page, action.target)
                    try:
                        if await handle.owner_frame() == page.main_frame:
                            axe = await scan_page(page, axe_path, {recorded.idx: handle})
                    finally:
                        await handle.dispose()
                if action.action in ("done", "fail"):
                    result = ActionResult(None, EffectResult("no_change"),
                                          await page.screenshot(type="jpeg", quality=70, caret="initial"))
                else:
                    result = await driver.perform(action)
                effect = result.effect.as_step_effect()["effect_type"]
            except (PlaywrightError, EffectObservationError, LoginWall, SafetyStop, ValueError) as error:
                full, diverged_at, detail = False, recorded.idx, type(error).__name__
                break
            metric_targets = targets + ([result.element] if result.element and action.action in
                                         ("click", "type", "select") else [])
            fitts = calculate_fitts_ids(metric_targets)[-1] if len(metric_targets) > len(targets) else None
            est_seconds = estimate_step(action.model_dump(), first_action=klm_first,
                                        previous_action=actions[-1] if actions else None,
                                        auto_scrolled=result.auto_scrolled,
                                        mobile=config["viewport"] == "mobile")
            with factory.begin() as session:
                step_id, active = persistence.save_step(session, config["id"], attempt_id,
                                                        recorded.idx, action, url, state, result, fitts=fitts,
                                                        est_seconds=est_seconds)
                if result.element:
                    candidates = evaluate_step(result.element, step_id=step_id, action=action.action,
                        effect_type=effect, is_first_target=first.is_first_target(url, action.action),
                        mobile=config["viewport"] == "mobile",
                        axe_target_size=axe_target_size_result(axe, recorded.idx) if axe else None)
                    if axe:
                        candidates += evaluate_axe(axe, {recorded.idx: step_id}, {step_id: result.element})
                    save_candidates(session, config["id"], candidates, confidence=1.0)
            if not active:
                raise persistence.Canceled()
            if est_seconds is not None:
                klm_values.append(est_seconds)
            if action.action in MOTOR_ACTIONS:
                klm_first = False
            actions.append(action.action)
            effects.append(effect)
            identities.append(identity)
            targets = metric_targets
            if len(metric_targets) > len(target_step_ids):
                target_step_ids.append(step_id)
            urls.append(page.url)
            if result.element:
                scrolls.append(result.element.scroll.y)
            scrolls.append(await page.evaluate("scrollY"))
            if effect != recorded.effect_type:
                full, diverged_at, detail = False, recorded.idx, "effect_changed"
                break
            if position + 1 < len(path) and screen_key(page.url) != screen_key(path[position + 1].url):
                full, diverged_at, detail = False, recorded.idx, "url_path_changed"
                break
            if action.action == "fail":
                full, diverged_at, detail = False, recorded.idx, "recorded_fail"
                break
            if action.action == "done":
                if action.reason != "goal_reached":
                    full, diverged_at, detail = False, recorded.idx, "recorded_safety_stop"
                    break
                try:
                    success, estimated = await verify_success(page, config["success_condition"])
                except PlaywrightError as error:
                    full, diverged_at, detail = False, recorded.idx, type(error).__name__
                    break
                if not success:
                    full, diverged_at, detail = False, recorded.idx, "goal_not_confirmed"
                    break
            if position + 1 < len(path) and screen_key(page.url) != screen_key(url):
                await record_first_view(page)
                first.new_screen()
                klm_first = True
        if full and not success:
            try:
                success, estimated = await verify_success(page, config["success_condition"])
            except PlaywrightError as error:
                full, diverged_at, detail = False, path[-1].idx, type(error).__name__
            if full and not success:
                full, diverged_at, detail = False, path[-1].idx, "goal_not_confirmed"
        _finish(factory, config["id"], attempt_id, full=full, diverged_at=diverged_at,
                detail=detail, success=success, estimated=estimated, actions=actions,
                effects=effects, identities=identities, targets=targets,
                target_step_ids=target_step_ids, urls=urls, scrolls=scrolls,
                est_task_time=None if config["viewport"] == "mobile" else sum(klm_values))
        return full
    finally:
        await driver.aclose()
