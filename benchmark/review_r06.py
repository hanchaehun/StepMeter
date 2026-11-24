"""Read explicit label-free R06 diagnostics. Does not infer historical model paths."""
import argparse
import json
from collections import Counter
from pathlib import Path


def review(payload):
    if payload.get('version') != 1:
        raise ValueError('Unsupported R06 trace version')
    rows=[]
    for row in payload['observations']:
        for field in ['is_first_target','in_first_view','candidate_created']:
            if type(row[field]) is not bool:
                raise ValueError('R06 predicate flags must be boolean')
        if row['action'] not in {'click','type','select'}:
            raise ValueError('Expected an executed target action')
        if not row['is_first_target']:reason='earlier_target_on_screen'
        elif row['in_first_view']:reason='target_in_first_view'
        elif row['first_view_scroll_px'] is None:reason='absent_at_load'
        else:reason='eligible_offscreen_first_target'
        eligible=reason=='eligible_offscreen_first_target'
        rows.append(dict(**row,reason=reason,predicate_consistent=eligible==row['candidate_created']))
    return dict(observations=rows,reasons=dict(Counter(r['reason'] for r in rows)),
                disagreements=sum(not r['predicate_consistent'] for r in rows),
                scope='target_action_results_only; occluded targets may not be operated; missing historical traces remain unresolved')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve()==args.trace.resolve():raise ValueError('Cannot overwrite input')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(review(json.loads(args.trace.read_text(encoding='utf-8'))),ensure_ascii=False,indent=2),encoding='utf-8')
