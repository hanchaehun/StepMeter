"""Numbered-action adapter; orchestration/persistence remains the agent's job."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from worker.agent.safety import guard_target
from worker.collect.collector import click_point, resolve_element, snapshot, scroll_target_into_view
from worker.driver.effects import EffectObserver, EffectObservationError, EffectResult
from worker.schemas import ActionRequest, ElementSnapshot, ClickAction, TypeAction, SelectAction, ScrollAction


@dataclass(frozen=True)
class ActionResult:
    element: ElementSnapshot | None
    effect: EffectResult
    screenshot: bytes
    auto_scrolled: bool = False


SCROLL_STATE = """el => {
    const positions = [];
    for (let node = el; node; node = node.parentNode || node.host) {
        if (node.nodeType === 1) positions.push([node.scrollLeft, node.scrollTop]);
    }
    let win = el.ownerDocument.defaultView;
    while (win) {
        positions.push([win.scrollX, win.scrollY]);
        try { if (win === win.parent) break; win = win.parent; } catch (_) { break; }
    }
    return positions;
}"""


async def enabled_select_options(handle):
    """Enabled single-select options, in model order; index is native zero-based.

    Share this projection with observation formatting. Disabled options and
    options inside disabled optgroups do not consume a model option number.
    """
    return await handle.evaluate("""el => el.tagName === 'SELECT' && !el.multiple
        ? [...el.options].map((o, index) => ({index, label: o.label, value: o.value,
            disabled: o.disabled || !!o.closest('optgroup')?.disabled}))
          .filter(o => !o.disabled).map(({disabled, ...o}) => o)
        : null""")


class PlaywrightDriver:
    """Use after observe(); never reinterpret an old number after another observe.

    Caller owns page/attempt lifecycle, goal checks, cancellation and Step storage.
    Call effect.as_step_effect() before storage so network-only evidence maps
    to the ADR 0011 persisted effect.
    Terminal done/fail actions are agent decisions, not browser actions.
    """
    def __init__(self, page, *, task_description='', **effect_options):
        self.page = page
        self.task_description = task_description
        self.effects = EffectObserver(page, **effect_options)
        self._busy = False
        self._select_options = {}

    async def select_options(self, target):
        """Capture the enabled-option mapping used in the current observation."""
        handle = await resolve_element(self.page, target)
        try:
            options = await enabled_select_options(handle)
            self._select_options[target] = options
            return options
        finally:
            await handle.dispose()

    async def aclose(self):
        await self.effects.aclose()

    async def perform(self, action: ActionRequest) -> ActionResult:
        if self._busy:
            raise EffectObservationError('Driver action already active')
        self._busy = True
        try:
            return await self._perform(action)
        finally:
            self._busy = False

    async def _perform(self, action: ActionRequest) -> ActionResult:
        kind = action.action
        if kind in ('done', 'fail'):
            raise ValueError('Terminal actions must be handled by the agent')
        if isinstance(action, (ClickAction, TypeAction, SelectAction)):
            handle = await resolve_element(self.page, action.target)
            try:
                before_scroll = await handle.evaluate(SCROLL_STATE)
                await scroll_target_into_view(self.page, action.target)
                auto_scrolled = before_scroll != await handle.evaluate(SCROLL_STATE)
                # Revalidate after preparation: scrolling can recycle virtual rows.
                validated = await resolve_element(self.page, action.target)
                try:
                    if not await handle.evaluate('(el, current) => el === current', validated):
                        raise EffectObservationError('Numbered target changed during preparation')
                finally:
                    await validated.dispose()
                element = await snapshot(self.page, action.target)
                screenshot = await self.page.screenshot(type='jpeg', quality=70, caret='initial')
                if element.occluded:
                    return ActionResult(element, EffectResult('no_change'), screenshot, auto_scrolled)
                if isinstance(action, TypeAction) and not await handle.is_editable():
                    raise EffectObservationError('Type target is not editable')
                if isinstance(action, SelectAction) and not await handle.is_enabled():
                    raise EffectObservationError('Select target is disabled')
                # Input calls get a browser-side timeout shorter than the window (cancelled there, never late).
                timeout = self.effects.action_timeout_ms
                prepared = {}
                if isinstance(action, ClickAction):
                    # Actionability (visible, enabled, stable, hit target) and the click point are
                    # preparation; inside the window only the input is dispatched.
                    async def prepare_input():
                        prepared['point'] = await click_point(self.page, action.target)
                        if prepared['point'] is None:
                            await handle.click(trial=True)
                        elif not await handle.is_enabled():
                            raise EffectObservationError('Click target is disabled')
                    async def callback():
                        point = prepared['point']
                        if point is None:
                            await handle.click(force=True, timeout=timeout)
                        else:
                            await self.page.mouse.click(point['x'], point['y'])
                elif isinstance(action, TypeAction):
                    async def callback():
                        # fill and Enter share one deadline so their sum stays inside the window.
                        started = time.monotonic()
                        await handle.fill(action.text, timeout=timeout)
                        if action.submit:
                            # #75: Enter on the same element, inside the same effect observation.
                            left = max(100, timeout - (time.monotonic() - started) * 1000)
                            await handle.press('Enter', timeout=left)
                else:
                    options = await enabled_select_options(handle)
                    index = action.option - 1
                    if options is None or index >= len(options):
                        raise EffectObservationError('Native select option unavailable')
                    if (action.target in self._select_options
                            and self._select_options[action.target] != options):
                        raise EffectObservationError('Native select options changed since observation')
                    native_index = options[index]['index']
                    callback = lambda: handle.select_option(index=native_index, timeout=timeout)
                # submit=true (Enter) gets the same irreversible-control check as click (ADR 0011 10).
                await guard_target(handle, kind, task_description=self.task_description,
                                   text=action.text if isinstance(action, TypeAction) else None,
                                   submit=isinstance(action, TypeAction) and action.submit)
                # Preparation runs after observer installation and before the 3 s window starts;
                # SafetyStop / EffectObservationError from it propagate unchanged.
                async def prepare():
                    current = await resolve_element(self.page, action.target)
                    try:
                        if not await handle.evaluate('(el, current) => el === current', current):
                            raise EffectObservationError('Numbered target changed during preparation')
                    finally:
                        await current.dispose()
                    if isinstance(action, SelectAction) and await enabled_select_options(handle) != options:
                        raise EffectObservationError('Native select options changed during preparation')
                    # Re-check right before acting: the form may change during preparation.
                    await guard_target(handle, kind, task_description=self.task_description,
                                       text=action.text if isinstance(action, TypeAction) else None,
                                       submit=isinstance(action, TypeAction) and action.submit)
                    if isinstance(action, ClickAction):
                        await prepare_input()
                effect = await self.effects.observe(callback, target=handle, prepare=prepare)
                return ActionResult(element, effect, screenshot, auto_scrolled)
            finally:
                await handle.dispose()
        if isinstance(action, ScrollAction):
            sign = 1 if action.direction == 'down' else -1
            callback = lambda: self.page.evaluate('(s) => window.scrollBy(0, s * innerHeight * 0.8)', sign)
        elif kind == 'back':
            callback = lambda: self.page.go_back(wait_until='commit', timeout=self.effects.action_timeout_ms)
        elif kind == 'wait':
            callback = lambda: asyncio.sleep(1)
        else:
            raise ValueError('Unsupported browser action')
        screenshot = await self.page.screenshot(type='jpeg', quality=70, caret='initial')
        return ActionResult(None, await self.effects.observe(callback), screenshot)
