"""Termination is verified from page evidence, not the model's assertion."""
import asyncio
import json
from collections import Counter
from statistics import median

GOAL_CHECK_SECONDS = 10


class LoopGuard:
    def __init__(self):
        self.seen = Counter()

    def repeated(self, state, action):
        payload = action.model_dump(exclude={'thought', 'expectation', 'confusion'})
        key = (state, json.dumps(payload, sort_keys=True))
        self.seen[key] += 1
        return self.seen[key] >= 3


async def verify_success(page, condition):
    if condition is None:
        return True, True
    if not isinstance(condition, dict) or not condition or set(condition) - {'url_contains', 'text_present'}:
        raise ValueError('Unsupported success condition')
    if any(not isinstance(v, str) or not v for v in condition.values()):
        raise ValueError('Success conditions must be nonempty strings')
    checks = []
    if 'url_contains' in condition:
        checks.append(condition['url_contains'] in page.url)
    if 'text_present' in condition:
        checks.append(condition['text_present'] in await page.locator('body').inner_text())
    return all(checks), False


async def goal_already_met(page, condition):
    """Before ending with safety_stop/blocked: has the page already met the configured goal?

    Only a configured success condition counts (never an estimated success when it is None).
    If the check itself fails (closed page, timeout, invalid condition), the original stop stands.
    """
    if condition is None:
        return False
    try:
        async with asyncio.timeout(GOAL_CHECK_SECONDS):
            success, _ = await verify_success(page, condition)
    except Exception:
        return False
    return success


def representative(attempts, counts):
    successful = [a for a in attempts if a.success is True]
    if not successful:
        return None
    middle = median(counts[a.id] for a in successful)
    return min(successful, key=lambda a: (abs(counts[a.id] - middle), a.index)).id
