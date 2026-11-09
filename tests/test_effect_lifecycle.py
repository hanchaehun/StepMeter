import asyncio
import unittest
from types import SimpleNamespace
from worker.driver.effects import EffectObserver, EffectObservationError


class Frame:
    def __init__(self):
        self.url = 'https://example.test/'
        self.installed = False
        self.started = False
        self.dom = False
        self.modal = False
        self.lose = False
        self.calls = []

    async def evaluate(self, script, arg=None):
        self.calls.append(script)
        if script.startswith('({width:'):
            return {'width': 1200, 'height': 800}
        if 'MutationObserver' in script:
            self.installed = True
        elif '.start()' in script:
            assert self.installed
            self.started = True
        elif '.stop()' in script:
            self.installed = False
            return None if self.lose else {'dom': self.dom, 'modal': self.modal}


class Page(Frame):
    def __init__(self):
        super().__init__()
        self.main_frame = self
        self.frames = [self]
        self.listeners = {}
        self.closed = False

    def on(self, name, callback):
        self.listeners.setdefault(name, []).append(callback)

    def remove_listener(self, name, callback):
        self.listeners[name].remove(callback)

    def is_closed(self):
        return self.closed


class EffectLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_prearm_priority_and_disposal(self):
        p = Page()
        observer = EffectObserver(p, window_ms=10)
        async def action():
            self.assertTrue(p.started)
            p.dom = p.modal = True
            p.url = 'https://example.test/next'
            p.listeners['framenavigated'][0](p)
        result = await observer.observe(action)
        self.assertEqual(result.effect_type, 'url_change')
        self.assertFalse(p.installed)
        await observer.aclose()
        self.assertTrue(all(not listeners for listeners in p.listeners.values()))

    async def test_error_cancellation_timeout_and_reuse(self):
        p = Page()
        observer = EffectObserver(p, window_ms=20)
        async def fail():
            raise ValueError('action failed')
        with self.assertRaises(ValueError):
            await observer.observe(fail)
        self.assertFalse(p.installed)
        with self.assertRaises(TimeoutError):
            await observer.observe(lambda: asyncio.sleep(1))
        self.assertFalse(p.installed)
        task = asyncio.create_task(observer.observe(lambda: asyncio.sleep(1)))
        await asyncio.sleep(.001)
        with self.assertRaises(EffectObservationError):
            await observer.observe(lambda: asyncio.sleep(0))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(p.installed)
        self.assertEqual((await observer.observe(lambda: asyncio.sleep(0))).effect_type, 'no_change')
        await observer.aclose()

    async def test_lost_context_and_closed_page_are_errors(self):
        for kind in ('lose', 'closed'):
            p = Page()
            observer = EffectObserver(p, window_ms=1)
            async def action():
                setattr(p, kind, True)
            with self.assertRaises(EffectObservationError):
                await observer.observe(action)
            await observer.aclose()

    async def test_http_failures_are_not_success(self):
        p = Page()
        observer = EffectObserver(p, window_ms=10)
        request = SimpleNamespace(url='https://app.test/write', method='POST', resource_type='xhr')
        # Real requests are hashable; use a small hashable test double.
        class Request:
            url, method, resource_type = request.url, request.method, request.resource_type
        req = Request()
        async def action():
            observer._request(req)
            observer._response(SimpleNamespace(request=req,status=500))
        result = await observer.observe(action)
        self.assertEqual(result.meaningful_network_count, 0)
        await observer.aclose()
