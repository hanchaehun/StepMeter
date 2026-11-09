"""Real API/DB/Redis integration before the agent exists; never log access codes."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from redis import Redis
from sqlalchemy import update

from apps.api.db.models import AccessCode
from apps.api.main import SessionLocal, hash_code
from tests.e2e.test_m2_flow import Spec
from worker.queue.runs import QUEUE_NAME, SCREENSHOT_DIR, save_screenshot


def check() -> dict:
    origin = os.environ.get('STEPMETER_API_URL', 'http://api:8000').rstrip('/')
    spec = Spec()
    codes = []
    screenshot = None

    def request(method, route, expected, body=None, code=None, schema_path=None):
        headers = {'Content-Type': 'application/json'}
        if code:
            headers['X-Access-Code'] = code
        raw = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(origin + route, data=raw, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status, payload = response.code, json.load(response)
        if status != expected:
            raise RuntimeError(f'{method} {route}: expected {expected}, got {status}')
        if schema_path:
            if body is not None:
                assert not spec.errors(body, schema_path, method.lower(), 'request')
            assert not spec.errors(payload, schema_path, method.lower(), str(expected))
        return payload

    def issue_code():
        code = subprocess.check_output(
            [sys.executable, '-m', 'apps.api.issue_code', 'local M2 infrastructure check'],
            text=True, timeout=30).strip()
        if not code:
            raise RuntimeError('Access code issuance returned empty output')
        codes.append(code)
        return code

    try:
        request('GET', '/projects', 401)
        code = issue_code()
        with SessionLocal() as db:
            from sqlalchemy import select
            assert db.scalar(select(AccessCode.id).where(AccessCode.code_hash == hash_code(code)))
        project = request('POST', '/projects', 201, {
            'name': 'M2 infrastructure API check',
            'base_url': 'http://m2-fixtures:8765/signup/index.html'}, code, '/projects')
        pid = project['id']
        task = request('POST', f'/projects/{pid}/tasks', 201, {
            'description': '이름을 입력하고 참가 신청을 마친다',
            'success_condition': {'url_contains': '/done.html'}}, code, '/projects/{id}/tasks')
        tid = task['id']
        run = request('POST', f'/tasks/{tid}/runs', 202, {
            'viewport': 'desktop', 'repeat_n': 3, 'model': 'claude-haiku-5-5', 'mode': 'agent'},
            code, '/tasks/{id}/runs')
        rid = run['id']
        state = request('GET', f'/runs/{rid}', 200, code=code, schema_path='/runs/{id}')
        assert state['status'] == 'queued'
        client = Redis.from_url(os.environ['REDIS_URL'])
        try:
            from rq import Queue
            queue = Queue(QUEUE_NAME, connection=client)
            assert f'run-{rid}' in queue.job_ids
            request('GET', f'/runs/{rid}/report', 409, code=code)
            request('POST', f'/runs/{rid}/cancel', 202, code=code,
                    schema_path='/runs/{id}/cancel')
            assert f'run-{rid}' not in queue.job_ids
            state = request('GET', f'/runs/{rid}', 200, code=code, schema_path='/runs/{id}')
            assert state['status'] == 'canceled'
        finally:
            client.close()
        other = issue_code()
        request('POST', f'/projects/{pid}/tasks', 404, {'description': 'not owned'}, other)
        data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1kAAAAASUVORK5CYII=')
        screenshot = save_screenshot(data)
        with urllib.request.urlopen(origin + '/screenshots/' + screenshot, timeout=15) as response:
            assert response.read() == data
            assert response.headers.get_content_type() == 'image/png'
        return {'scope': 'real API/DB/queue and queued cancellation; not agent M2 E2E',
                'project_id': pid, 'run_id': rid, 'api': 'ok', 'queue': 'ok',
                'queued_cancellation': 'ok', 'code_isolation': 'ok', 'screenshot_http': 'ok'}
    finally:
        if screenshot:
            Path(SCREENSHOT_DIR, screenshot).unlink(missing_ok=True)
        if codes:
            with SessionLocal.begin() as db:
                db.execute(update(AccessCode).where(
                    AccessCode.code_hash.in_([hash_code(c) for c in codes])).values(active=False))


if __name__ == '__main__':
    print(json.dumps(check()))
