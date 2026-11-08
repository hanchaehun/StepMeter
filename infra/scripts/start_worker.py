"""Do not consume jobs until the agreed agent entry point is importable."""
import importlib
import os

from worker.queue.runs import JOB_FUNC, QUEUE_NAME


def main():
    module, function = JOB_FUNC.rsplit('.', 1)
    try:
        target = getattr(importlib.import_module(module), function)
    except (ImportError, AttributeError) as error:
        raise SystemExit(f'Agent entry point {JOB_FUNC} is unavailable: {error}. See infra/m2.md.') from None
    if not callable(target):
        raise SystemExit(f'{JOB_FUNC} must be callable')
    os.execvp('rq', ['rq', 'worker', '--url', os.environ['REDIS_URL'], QUEUE_NAME])


if __name__ == '__main__':
    main()
