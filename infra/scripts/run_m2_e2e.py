"""Run genuine M2 E2E with an ephemeral code; refuse missing agent, never fake success."""
import importlib
import os
import subprocess
import sys

from sqlalchemy import update

from apps.api.db.models import AccessCode
from apps.api.main import SessionLocal, hash_code
from worker.queue.runs import JOB_FUNC


def main():
    module, attribute = JOB_FUNC.rsplit('.', 1)
    try:
        function = getattr(importlib.import_module(module), attribute)
    except (ImportError, AttributeError) as error:
        print(f'M2 BLOCKED: {JOB_FUNC} is not available ({error}); requires agent owner issue #26.', file=sys.stderr)
        return 2
    if not callable(function):
        raise RuntimeError('Configured agent entry point is not callable')
    code = subprocess.check_output(
        [sys.executable, '-m', 'apps.api.issue_code', 'local genuine M2 E2E'], text=True, timeout=30).strip()
    if not code:
        raise RuntimeError('Code issuance failed')
    env = {**os.environ, 'STEPMETER_ACCESS_CODE': code,
           'STEPMETER_API_URL': os.environ.get('STEPMETER_API_URL', 'http://api:8000'),
           'STEPMETER_E2E_SITE_URL': os.environ.get('STEPMETER_E2E_SITE_URL', 'http://m2-fixtures:8765/'),
           'STEPMETER_E2E_LOG_DIR': 'data/screenshots/m2-e2e'}
    try:
        return subprocess.run([sys.executable, '-m', 'unittest', 'tests.e2e.test_m2_flow', '-v'], env=env).returncode
    finally:
        with SessionLocal.begin() as db:
            db.execute(update(AccessCode).where(AccessCode.code_hash == hash_code(code)).values(active=False))


if __name__ == '__main__':
    raise SystemExit(main())
