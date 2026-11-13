"""Comparison of measured runs; contracts: plan 7.3–7.5 and frozen OpenAPI.

Inputs are measurement-only dictionaries. No LLM, labels or positional matching.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from statistics import median
from urllib.parse import urlsplit

from worker.matching.match import match


def screen(url: str) -> str:
    parts = urlsplit(url)
    # Hash routers identify a screen; ordinary fragment anchors do not.
    origin = f'{parts.scheme}://{parts.netloc}' if parts.netloc else ''
    return origin + parts.path + ('#' + parts.fragment if parts.fragment.startswith('/') else '')


def fingerprint(key: str | None) -> dict | None:
    if key is None:
        return None
    fields = key.split('|')
    if len(fields) != 5:
        return None
    return dict(zip(('tag', 'role', 'name', 'label_text', 'landmark'),
                    (fields[0], fields[1] or None, fields[2], fields[3] or None, fields[4] or None)))


def align_paths(base: list[dict], target: list[dict]) -> list[dict]:
    def signature(step):
        fp = step.get('fingerprint') or {}
        return (step['action']['action'], fp.get('role'), ''.join(fp.get('name', '').split()).casefold())
    a, b = [signature(s) for s in base], [signature(s) for s in target]
    rows = []
    for op, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'equal':
            rows.extend({'op': 'kept', 'base_idx': base[x]['idx'], 'target_idx': target[y]['idx']}
                        for x, y in zip(range(i, j), range(k, l)))
        else:
            rows.extend({'op': 'removed', 'base_idx': s['idx'], 'target_idx': None} for s in base[i:j])
            rows.extend({'op': 'added', 'base_idx': None, 'target_idx': s['idx']} for s in target[k:l])
    return rows


def issue_changes(base: list[dict], target: list[dict]) -> tuple[list, list, list]:
    def unique(rows):
        seen, result = set(), []
        for row in rows:
            if row['is_reference']:
                continue
            # Unknown identity must not collapse unrelated issues.
            key = (row['rule_id'], row.get('screen'), row.get('_identity', row.get('element_key')) or ('unknown', row['id']))
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result
    old, new = unique(base), unique(target)
    proposals = {}
    for i, row in enumerate(old):
        identity = row.get('_identity', row.get('element_key'))
        fp = fingerprint(identity)
        candidates = [(j, item) for j, item in enumerate(new)
                      if item['rule_id'] == row['rule_id'] and item.get('screen') == row.get('screen')]
        # Missing page identity cannot prove the same element across screens.
        if row.get('screen') is None:
            continue
        if isinstance(identity, str) and identity.startswith('axe:'):
            exact = [j for j, item in candidates if item.get('_identity') == identity]
            if len(exact) == 1:
                proposals[i] = exact[0]
            continue
        if fp is None:
            continue
        mapped = [{**fingerprint(item['element_key']), '_index': j} for j, item in candidates
                  if fingerprint(item.get('element_key')) is not None]
        found = match(fp, mapped)
        if found.status == 'matched':
            proposals[i] = found.element['_index']
    # Require a one-to-one match. Ambiguity is never silently resolved by order.
    matches = {i: j for i, j in proposals.items() if list(proposals.values()).count(j) == 1}
    return ([row for j, row in enumerate(new) if j not in matches.values()],
            [row for i, row in enumerate(old) if i not in matches],
            [new[j] for j in matches.values()])


def metric_changes(base: dict[str, list[float]], target: dict[str, list[float]], *,
                   replay: bool = False, comparable: bool = True) -> list[dict]:
    rows = []
    for key in sorted(base.keys() | target.keys()):
        a, b = base.get(key, []), target.get(key, [])
        before, after = (float(median(a)) if a else None), (float(median(b)) if b else None)
        delta = after - before if before is not None and after is not None else None
        rate = delta / before if delta is not None and before else None
        spread = (max(a) - min(a)) / before if len(a) >= 2 and before else None
        threshold = None
        verdict = 'not_comparable'
        if key in ('click_count', 'travel_distance', 'est_task_time') and comparable and delta is not None:
            if replay:
                threshold = 1.0 if key == 'click_count' else 0.1
                if key == 'click_count':
                    verdict = 'worse' if delta >= 1 else 'better' if delta <= -1 else 'unchanged'
                elif rate is not None:
                    verdict = 'worse' if rate >= threshold else 'better' if rate <= -threshold else 'unchanged'
                elif before == after == 0:
                    verdict = 'unchanged'
            elif len(a) >= 2 and len(b) >= 2:
                if key == 'click_count':
                    threshold = max(0.2, 2 * spread) if spread is not None else None
                    if before == after == 0:
                        verdict = 'unchanged'
                    elif rate is not None and spread is not None:
                        verdict = ('worse' if delta >= 1 and rate > threshold else
                                   'better' if delta <= -1 and -rate > threshold else 'unchanged')
                elif spread is not None:
                    threshold = max(0.2, 2 * spread)
                    verdict = 'worse' if rate > threshold else 'better' if rate < -threshold else 'unchanged'
                elif before == after == 0:
                    verdict = 'unchanged'
        rows.append({'key': key, 'base': before, 'target': after, 'delta': delta,
                     'change_rate': rate, 'threshold': threshold, 'verdict': verdict})
    return rows
