"""Effect observation without extending the frozen Step schema."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


class EffectObservationError(RuntimeError):
    """An unsuccessful observation must never be persisted as no_change."""


@dataclass(frozen=True)
class EffectResult:
    effect_type: str
    meaningful_network_count: int = 0

    def as_step_effect(self) -> dict:
        if self.effect_type == 'no_change' and self.meaningful_network_count:
            return {'effect_type': 'dom_mutation', 'changed': True}
        return {'effect_type': self.effect_type, 'changed': self.effect_type != 'no_change'}


def url_identity(url: str, *, ignored_query_keys=(), hash_routes=False):
    p = urlsplit(url)
    return (p.scheme, p.netloc, p.path,
            tuple(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                         if k not in ignored_query_keys)), p.fragment if hash_routes else '')


class NetworkFilter:
    """Retains only request timestamps, never headers, bodies or query values."""
    def __init__(self, domains=None):
        if domains is None:
            domains = Path(__file__).with_name('analytics_domains.txt').read_text(encoding='utf-8').splitlines()
        self.domains = tuple(d.strip().lower() for d in domains if d.strip() and not d.startswith('#'))
        self.recent_gets = {}

    def classify(self, url, method, resource_type, now):
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        method = method.upper()
        key = (p.scheme, host, p.port, p.path)
        previous = self.recent_gets.get(key)
        self.recent_gets = {k: t for k, t in self.recent_gets.items() if now-t <= 3}
        if method == 'GET':
            self.recent_gets[key] = now
        if resource_type not in ('fetch', 'xhr', 'document'):
            return False
        if any(host == d or host.endswith('.'+d) for d in self.domains):
            return False
        return not (method == 'GET' and previous is not None and now-previous <= 3)


class EffectObserver:
    """One observer per page, created before polling begins; serialized actions.

    The window starts immediately before invoking action. Prepare scroll and
    actionability before observe(); pass target rechecks as `prepare`, which runs
    after observer installation and before the window. Failed actions/closed
    pages propagate errors.
    """
    def __init__(self, page, *, window_ms=3000, ignored_query_keys=(), hash_routes=False,
                 analytics_domains=None):
        if not 0 < window_ms <= 3000:
            raise ValueError('window_ms must be in (0, 3000]')
        self.page = page
        self.window_ms = window_ms
        # Browser-side timeout for the input call itself (2500 ms for the 3 s window), so a
        # timed-out click is cancelled in the browser instead of landing late. The window's
        # asyncio.wait_for stays as a slightly longer safety net.
        self.action_timeout_ms = window_ms * 5 / 6
        self.ignored_query_keys = ignored_query_keys
        self.hash_routes = hash_routes
        self.network = NetworkFilter(analytics_domains)
        self.pending = {}
        self.count = 0
        self.urls = []
        self.navigated_frames = set()  # subframes that loaded a new document inside the window
        self.attached_frames = set()  # frames attached during installation, preparation or the window
        self.deadline = 0.0
        self.started = 0.0
        self.busy = False
        self.closed = False
        self._request_listener = self._request
        self._response_listener = self._response
        self._failed_listener = self._failed
        self._navigation_listener = self._navigation
        self._attached_listener = self._attached
        page.on('request', self._request_listener)
        page.on('response', self._response_listener)
        page.on('requestfailed', self._failed_listener)
        page.on('framenavigated', self._navigation_listener)
        page.on('frameattached', self._attached_listener)

    def _request(self, request):
        now = time.monotonic()
        meaningful = self.network.classify(request.url, request.method, request.resource_type, now)
        if self.started <= now <= self.deadline and meaningful:
            self.pending[request] = True

    def _response(self, response):
        meaningful = self.pending.pop(response.request, False)
        if meaningful and time.monotonic() <= self.deadline and 200 <= response.status < 400:
            self.count += 1

    def _navigation(self, frame):
        if self.started <= time.monotonic() <= self.deadline:
            if frame == self.page.main_frame:
                self.urls.append(frame.url)
            else:
                self.navigated_frames.add(frame)

    async def _frame_shown(self, frame):
        """Whether a subframe's element is visible and overlaps the viewport; None if it is gone."""
        try:
            element = await frame.frame_element()
        except Exception:
            return None  # detached from the page
        try:
            if not await element.is_visible():
                return False
            box = await element.bounding_box()
            size = self.page.viewport_size or await self.page.evaluate(
                '() => ({width: innerWidth, height: innerHeight})')
            return bool(box) and (box['x'] < size['width'] and box['x'] + box['width'] > 0
                                  and box['y'] < size['height'] and box['y'] + box['height'] > 0)
        except Exception:
            return None  # visibility could not be read; stay fail-closed
        finally:
            try:
                await element.dispose()
            except Exception:
                pass

    def _attached(self, frame):
        if self.busy and (not self.started or time.monotonic() <= self.deadline):
            self.attached_frames.add(frame)

    def _failed(self, request):
        self.pending.pop(request, None)

    async def aclose(self):
        if self.busy:
            raise EffectObservationError('Cancel and await the active action before closing observer')
        if not self.closed:
            self.closed = True
            self.page.remove_listener('request', self._request_listener)
            self.page.remove_listener('response', self._response_listener)
            self.page.remove_listener('requestfailed', self._failed_listener)
            self.page.remove_listener('framenavigated', self._navigation_listener)
            self.page.remove_listener('frameattached', self._attached_listener)
            self.pending.clear()

    async def observe(self, action, *, target=None, prepare=None):
        """Install → prepare() (untimed) → start window → action(). Errors from prepare propagate."""
        if self.closed or self.busy:
            raise EffectObservationError('Observer closed or action already active')
        self.busy = True
        key = '__stepmeter_effect_' + uuid.uuid4().hex
        frames = []
        before = self.page.url
        self.count = 0
        self.urls.clear()
        self.navigated_frames.clear()
        self.attached_frames.clear()
        self.pending.clear()
        script = Path(__file__).with_name('effect_observer.js').read_text(encoding='utf-8')
        try:
            # Observe hidden frames too: their ancestors can move/show during the action.
            target_frame = await target.owner_frame() if target is not None else None
            for frame in self.page.frames:
                await frame.evaluate(script, {'key': key, 'target': target if frame == target_frame else None,
                                              'duration': self.window_ms})
                frames.append(frame)
            # Installation and preparation (target recheck, safety guard) do not consume the window.
            if prepare is not None:
                await prepare()
            await asyncio.gather(*(frame.evaluate('(key) => globalThis[key].start()', key) for frame in frames))
            self.started = time.monotonic()
            self.deadline = self.started + self.window_ms / 1000
            await asyncio.wait_for(action(), timeout=self.window_ms / 1000)
            remaining = self.deadline-time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
            if self.page.is_closed():
                raise EffectObservationError('Page closed during observation')
            dom = modal = False
            lost_context = False
            for frame in frames:
                try:
                    result = await frame.evaluate('(key) => globalThis[key]?.stop() ?? null', key)
                    if result is not None:
                        lost_context |= result.get('incomplete', False)
                        dom |= result['dom']
                        modal |= result['modal']
                        continue
                except Exception:
                    pass
                if frame != self.page.main_frame and frame in self.navigated_frames:
                    # A subframe given a new document inside the window (e.g. a booking calendar
                    # iframe): its observer is gone, so judge what the user sees, the frame element.
                    shown = await self._frame_shown(frame)
                    if shown is None:
                        lost_context = True
                    elif shown:
                        dom = True
                else:
                    lost_context = True
            opts = dict(ignored_query_keys=self.ignored_query_keys, hash_routes=self.hash_routes)
            url_changed = any(url_identity(before, **opts) != url_identity(url, **opts) for url in self.urls)
            unobserved_frame = False
            if not url_changed:
                # A frame attached inside the window has no observer of its own (e.g. a booking
                # calendar iframe created on click): judge its frame element the same way.
                for frame in list(self.attached_frames):
                    shown = await self._frame_shown(frame)
                    if shown is None:
                        unobserved_frame = True
                        break
                    if shown:
                        dom = True
            if url_changed:
                effect = 'url_change'
            elif unobserved_frame:
                raise EffectObservationError('Frame attached during observation; inner activity is not fully observed')
            elif lost_context:
                raise EffectObservationError('Frame context or visibility incomplete without a classifiable URL change')
            elif modal:
                effect = 'modal_change'
            elif dom:
                effect = 'dom_mutation'
            else:
                effect = 'no_change'
            return EffectResult(effect, self.count)
        finally:
            self.deadline = self.started = 0
            self.pending.clear()
            self.urls.clear()
            self.navigated_frames.clear()
            self.attached_frames.clear()
            for frame in frames:
                try:
                    await frame.evaluate('(key) => globalThis[key]?.stop()', key)
                except Exception:
                    pass  # Navigation/closure has already destroyed its listeners.
            self.busy = False

    async def click(self, locator):
        """Prepare scrolling before baseline; preserve the exact target handle."""
        await locator.scroll_into_view_if_needed()
        await locator.click(trial=True)
        handle = await locator.element_handle()
        if handle is None:
            raise EffectObservationError('Click target disappeared')
        try:
            # Playwright's actionability wait (visible, enabled, stable, hit target) is preparation:
            # run it as a trial before the window, then dispatch without waiting again.
            return await self.observe(lambda: handle.click(force=True, timeout=self.action_timeout_ms),
                                      target=handle, prepare=lambda: handle.click(trial=True))
        finally:
            await handle.dispose()
