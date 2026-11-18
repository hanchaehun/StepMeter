"""Cohen's kappa for paired spreadsheet judgments; no participant data."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

LABELS = frozenset({'real', 'false', 'unsure'})


def agreement(rows):
    rows = list(rows)
    seen, pairs, missing = set(), [], 0
    for row in rows:
        if set(row) != {'issue_id', 'label_a', 'label_b'} or not row['issue_id'].strip():
            raise ValueError('CSV columns: issue_id,label_a,label_b')
        if row['issue_id'] in seen:
            raise ValueError('Duplicate issue ID')
        seen.add(row['issue_id'])
        a, b = row['label_a'], row['label_b']
        if a not in LABELS | {''} or b not in LABELS | {''}:
            raise ValueError('Judgments must be real, false, unsure or blank')
        if not a or not b:
            missing += 1
        else:
            pairs.append((a, b))
    n = len(pairs)
    a, b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    observed = sum(x == y for x, y in pairs)/n if n else None
    expected = sum(a[x]*b[x] for x in LABELS)/(n*n) if n else None
    return {'paired': n, 'incomplete': missing, 'agreement': observed,
            'chance_agreement': expected,
            'kappa': (observed-expected)/(1-expected) if n and expected < 1 else None,
            'disagreements': [r['issue_id'] for r in rows
                              if r['label_a'] and r['label_b'] and r['label_a'] != r['label_b']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.input.open(encoding='utf-8-sig', newline='') as f:
        result = agreement(list(csv.DictReader(f)))
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
