"""Numbered-action adapter; orchestration/persistence remains the agent's job."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from worker.agent.safety import guard_target
from worker.collect.collector import click_point, resolve_element, snapshot, scroll_target_into_view
from worker.driver.effects import EffectObserver, EffectObservationError, EffectResult
from worker.schemas import ActionRequest, ElementSnapshot


@dataclass(frozen=True)
class ActionResult:
    element: ElementSnapshot | None
    effect: EffectResult
    screenshot: bytes


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
    Call effect.as_step_effect() before storage: network-only evidence may raise.
    Terminal done/fail actions are agent decisions, not browser actions.
    """
    def __init__(self, page, **effect_options):
        self.page = page
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
        if kind in ('click', 'type', 'select'):
            handle = await resolve_element(self.page, action.target)
            try:
                await scroll_target_into_view(self.page, action.target)
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
                    return ActionResult(element, EffectResult('no_change'), screenshot)
                if kind == 'type' and not await handle.is_editable():
                    raise EffectObservationError('Type target is not editable')
                if kind == 'select' and not await handle.is_enabled():
                    raise EffectObservationError('Select target is disabled')
                if kind == 'click':
                    async def callback():
                        point = await click_point(self.page, action.target)
                        if point is None:
                            await handle.click()
                        else:
                            if not await handle.is_enabled():
                                raise EffectObservationError('Click target is disabled')
                            await self.page.mouse.click(point['x'], point['y'])
                elif kind == 'type':
                    callback = lambda: handle.fill(action.text)
                else:
                    options = await enabled_select_options(handle)
                    index = action.option - 1
                    if options is None or index >= len(options):
                        raise EffectObservationError('Native select option unavailable')
                    if (action.target in self._select_options
                            and self._select_options[action.target] != options):
                        raise EffectObservationError('Native select options changed since observation')
                    native_index = options[index]['index']
                    callback = lambda: handle.select_option(index=native_index)
                await guard_target(handle, kind)
                async def checked_action():
                    current = await resolve_element(self.page, action.target)
                    try:
                        if not await handle.evaluate('(el, current) => el === current', current):
                            raise EffectObservationError('Numbered target changed during preparation')
                    finally:
                        await current.dispose()
                    if kind == 'select' and await enabled_select_options(handle) != options:
                        raise EffectObservationError('Native select options changed during preparation')
                    await guard_target(handle, kind)
                    await callback()
                return ActionResult(element, await self.effects.observe(checked_action, target=handle), screenshot)
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
        screenshot = await self.page.screenshot(type='jpeg', quality=70, caret='initial')
        return ActionResult(None, await self.effects.observe(callback), screenshot)
