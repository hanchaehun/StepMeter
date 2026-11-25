"""첫 화면 안정화 대기 (ADR 0011 11번).

기대값은 PM 결정에서 가져왔다(구현을 보고 만들지 않았다).
wait_for_dom_quiet(page, quiet_ms=200, min_ms=400, max_ms=1500): 시작 후 400ms 이상 지났고, 마지막 DOM 변화(추가·삭제·
속성 변경) 뒤 200ms 동안 조용하고, document.readyState가 complete면 끝난다. 1500ms가 되면 조건과 상관없이 끝난다.
- 300ms 뒤에 버튼 5개가 추가되는 페이지: 대기 후 observe()에 5개가 모두 있다.
- 정적 페이지: 600ms 안에 끝나고, 350ms보다 일찍 끝나지 않는다(최소 대기).
- 50ms마다 계속 바뀌는 페이지: 2500ms 안에 끝난다(멈추지 않는다).
에이전트와 같이 goto(domcontentloaded) 직후에 부른다. 실행 전 `npm run build:collect` 필요.
"""
import time
import unittest

from playwright.async_api import async_playwright

from worker.collect.collector import observe, wait_for_dom_quiet

LATE = ('<!doctype html><html lang="en"><body><main></main><script>'
        'setTimeout(()=>{for(let i=1;i<=5;i++){const b=document.createElement("button");'
        'b.textContent="B"+i;document.querySelector("main").append(b)}},300)</script></body></html>')
STATIC = '<!doctype html><html lang="en"><body><main><button>Only</button></main></body></html>'
TICKING = ('<!doctype html><html lang="en"><body><main><button>Go</button><p id="t">0</p></main><script>'
           'let n=0;setInterval(()=>{document.getElementById("t").textContent=String(++n)},50)</script></body></html>')


class DomQuietTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch()
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context(viewport={'width': 1280, 'height': 800})
        self.html = STATIC
        async def route(route):
            await route.fulfill(content_type='text/html', body=self.html)
        await self.context.route('**/*', route)
        self.page = await self.context.new_page()

    async def open_and_wait(self, html):
        self.html = html
        await self.page.goto('http://quiet.test/', wait_until='domcontentloaded')
        started = time.monotonic()
        await wait_for_dom_quiet(self.page)
        return (time.monotonic() - started) * 1000

    async def test_late_buttons_are_observed_after_wait(self):
        await self.open_and_wait(LATE)
        names = [row['name'] for row in await observe(self.page)]
        self.assertEqual(names, ['B1', 'B2', 'B3', 'B4', 'B5'])

    async def test_static_page_ends_within_600ms(self):
        self.assertLess(await self.open_and_wait(STATIC), 600)

    async def test_static_page_does_not_end_before_350ms(self):
        self.assertGreaterEqual(await self.open_and_wait(STATIC), 350)

    async def test_continuously_changing_page_still_ends_within_2500ms(self):
        self.assertLess(await self.open_and_wait(TICKING), 2500)


if __name__ == '__main__':
    unittest.main()
