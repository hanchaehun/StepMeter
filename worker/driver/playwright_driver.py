"""Numbered-action adapter; orchestration/persistence remains the agent's job."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from worker.collect.collector import resolve_element, snapshot
from worker.driver.effects import EffectObserver, EffectObservationError, EffectResult
from worker.schemas import ActionRequest, ElementSnapshot


@dataclass(frozen=True)
class ActionResult:
    element: ElementSnapshot | None
    effect: EffectResult


class PlaywrightDriver:
    """Use after observe(); never reinterpret an old number after another observe.

    Caller owns page/attempt lifecycle, goal checks, cancellation and Step storage.
    Call effect.as_step_effect() before storage: network-only evidence may raise.
    Terminal done/fail actions are agent decisions, not browser actions.
    """
    def __init__(self, page, **effect_options):
        self.page = page
        self.effects = EffectObserver(page, **effect_options)
        self._busy = False

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
        if kind in ('click', 'type', 'select'):
            handle = await resolve_element(self.page, action.target)
            try:
                await handle.scroll_into_view_if_needed()
                if kind == 'click':
                    await handle.click(trial=True)
                if kind == 'type' and not await handle.is_editable():
                    raise EffectObservationError('Type target is not editable')
                if kind == 'select' and not await handle.is_enabled():
                    raise EffectObservationError('Select target is disabled')
                # Revalidate after preparation: scrolling can recycle virtual rows.
                validated = await resolve_element(self.page, action.target)
                await validated.dispose()
                element = await snapshot(self.page, action.target)
                if element.occluded:
                    raise EffectObservationError('Numbered action target is occluded')
                if kind == 'click':
                    callback = lambda: handle.click()
                elif kind == 'type':
                    callback = lambda: handle.fill(action.text)
                else:
                    options = await handle.evaluate('(el) => el.tagName === "SELECT" && !el.multiple ? [...el.options].map(o => ({disabled:o.disabled || o.parentElement?.disabled, value:o.value})) : null')
                    index = action.option - 1
                    if options is None or index >= len(options) or options[index]['disabled']:
                        raise EffectObservationError('Native select option unavailable')
                    callback = lambda: handle.select_option(index=index)
                async def checked_action():
                    current = await resolve_element(self.page, action.target)
                    try:
                        if not await handle.evaluate('(el, current) => el === current', current):
                            raise EffectObservationError('Numbered target changed during preparation')
                    finally:
                        await current.dispose()
                    await callback()
                return ActionResult(element, await self.effects.observe(checked_action, target=handle))
            finally:
                await handle.dispose()
        if kind == 'scroll':
            sign = 1 if action.direction == 'down' else -1
            callback = lambda: self.page.evaluate('(s) => window.scrollBy(0, s * innerHeight * 0.8)', sign)
        elif kind == 'back':
            callback = lambda: self.page.go_back(wait_until='commit')
        elif kind == 'wait':
            callback = lambda: asyncio.sleep(1)
        else:
            raise ValueError('Unsupported browser action')
        return ActionResult(None, await self.effects.observe(callback))
