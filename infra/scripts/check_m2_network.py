"""Check worker-container dependencies without pretending to run the missing API/agent."""
import asyncio
import json
import os
import re
from pathlib import Path

from playwright.async_api import async_playwright
from redis import Redis
from sqlalchemy import create_engine, text

from worker.collect.collector import observe
from worker.llm.select import make_adapter
from worker.queue.runs import save_screenshot


async def check():
    engine = create_engine(os.environ['DATABASE_URL'])
    try:
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT 1')) == 1
    finally:
        engine.dispose()
    client = Redis.from_url(os.environ['REDIS_URL'])
    try:
        assert client.ping()
    finally:
        client.close()
    make_adapter('claude-haiku-5-5')  # validates fake reply file, requires no API key
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})
            response = await page.goto(os.environ['STEPMETER_E2E_SITE_URL'].rstrip('/') + '/signup/index.html')
            assert response and response.ok
            items = await observe(page)
            assert {item['name'] for item in items} == {'이름', '신청'}
            await page.get_by_role('textbox', name='이름').fill('M2 demo')
            await page.get_by_role('button', name='신청', exact=True).click()
            await page.wait_for_url(re.compile(r'/done\.html(?:\?|$)'))
            key = save_screenshot(await page.screenshot())
            assert Path('data/screenshots', key).is_file()
            print(json.dumps({'database': 'ok', 'redis': 'ok', 'fixture': 'signup/done.html',
                              'browser': 'ok', 'screenshot_key': key,
                              'scope': 'container network smoke only; not M2 API E2E'}))
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(check())
