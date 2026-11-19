"""Offline #77 reclassification of the public breakdown ZIP, not a new model run."""
import argparse
import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


def review(path: Path) -> dict:
    reports = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith('.json'):
                continue
            data = json.loads(archive.read(name))
            before = defaultdict(Counter)
            after = defaultdict(Counter)
            high = []
            success_r03 = []
            for row in data['rows']:
                before[row['rule']][row['outcome']] += 1
                if not (row['rule'] == 'R01' and row['severity'] == 'low' and not row['mixed_severity']):
                    after[row['rule']][row['outcome']] += 1
                if row['rule'] == 'R01' and row['severity'] == 'high' and row['outcome'] == 'FP':
                    high.append(row)
                if row['rule'] == 'R03' and row['outcome'] == 'FP' and row['end_reason_class'] != 'failure_only':
                    success_r03.append(row)
            reports.append(dict(run=data['run'], before=dict(before), after=dict(after),
                                r01_high_fp=high, r03_with_success=success_r03))
    return dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                mode='archived_reclassification_not_rerun', runs=reports)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.zip.resolve():
        raise ValueError('Output must not overwrite source')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(review(args.zip),ensure_ascii=False,indent=2),encoding='utf-8')
