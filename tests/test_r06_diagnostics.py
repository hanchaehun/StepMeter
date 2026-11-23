"""R06 traces describe executed predicates, not inferred model behavior."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark.evidence_capture import EvidenceSink
from benchmark.review_r06 import review


class R06DiagnosticsTests(unittest.TestCase):
    def test_reasons_and_predicate_disagreement(self):
        base=dict(action='click',is_first_target=True,in_first_view=False,
                  first_view_scroll_px=160,candidate_created=True)
        rows=[base,dict(base,is_first_target=False,candidate_created=False),
              dict(base,in_first_view=True,candidate_created=False),
              dict(base,first_view_scroll_px=None,candidate_created=False)]
        result=review(dict(version=1,observations=rows))
        self.assertEqual(result['reasons'],dict(eligible_offscreen_first_target=1,
            earlier_target_on_screen=1,target_in_first_view=1,absent_at_load=1))
        self.assertEqual(result['disagreements'],0)
        result=review(dict(version=1,observations=[dict(base,candidate_created=False)]))
        self.assertEqual(result['disagreements'],1)

    def test_export_retains_non_issues_and_target_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'dom'
            sink=EvidenceSink(directory)
            snapshot=SimpleNamespace(tag='button',role='button',name='Open',label_text=None,
                                     landmark='main',in_first_view=True,first_view_scroll_px=0,occluded=False)
            sink.record_r06(1,10,1,'select','http://local.test/products',snapshot,
                            True,False,{'action_selector':'#category'})
            payload=json.loads((directory/'r06.json').read_text(encoding='utf-8'))
            self.assertEqual(payload['observations'][0]['selector'],'#category')
            self.assertFalse(payload['observations'][0]['candidate_created'])
            self.assertEqual(review(payload)['reasons'],{'target_in_first_view':1})

    def test_invalid_inputs_are_not_empty_success(self):
        with self.assertRaises(ValueError):review(dict(version=2,observations=[]))
        for patch in [dict(action='scroll'),dict(is_first_target=1)]:
            row=dict(action='click',is_first_target=True,in_first_view=True,
                     candidate_created=False,first_view_scroll_px=0)
            row.update(patch)
            with self.assertRaises(ValueError):review(dict(version=1,observations=[row]))


if __name__=='__main__':
    unittest.main()
