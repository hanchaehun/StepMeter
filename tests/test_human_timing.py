"""Synthetic timing records; no participant files. Frozen README arithmetic."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ml.timing.analyze import analyze_session, summarize, main


def event(kind, ms, target=None):
    return dict(type=kind,t_ms=ms,x=10,y=20,target_key=target)


def fixture(events=None):
    session=dict(participant_code='SYNTHETIC',page_id='app/task/baseline',completed=True,
                 viewport=dict(width=1280,height=800),events=events or [event('stable',1000),event('click',3000,'button|First'),event('stable',3800),event('stable',4200),event('click',6000,'button|Done'),event('move',7000)])
    notes=dict(session=dict(participant_code='SYNTHETIC',procedure_version='self_guided_v1'),
               pages=[dict(page_id=session['page_id'],issue=False,issue_codes=[],note='',completed_confirmed=True)])
    return session,notes


def analyze(session,notes,index=4,**kwargs):
    return analyze_session(session,notes,completion_index=index,completion_reason='Synthetic reviewer verified Done',**kwargs)


class HumanTimingTests(unittest.TestCase):
    def test_frozen_example_ignores_post_completion_events(self):
        session,notes=fixture(); original=copy.deepcopy((session,notes))
        result=analyze(session,notes)
        self.assertEqual((result['observed_seconds'],result['response_seconds'],result['adjusted_seconds']),(5,.8,4.2))
        self.assertEqual(result['response_intervals'],[dict(action_index=1,stable_index=2,start_ms=3000,end_ms=3800)])
        self.assertEqual((session,notes),original)

    def test_no_completion_guess_or_unknown_target(self):
        session,notes=fixture()
        self.assertIn('end_unresolved',analyze_session(session,notes)['exclusion_reasons'])
        self.assertIn('end_unresolved',analyze(session,notes,5)['exclusion_reasons'])
        session['events'][4]['target_key']=None
        self.assertIn('end_unresolved',analyze(session,notes)['exclusion_reasons'])

    def test_key_continuation_and_simultaneous_stable_are_unresolved(self):
        session,notes=fixture([event('stable',0),event('key',1000,'input'),event('key',1100,'input'),event('stable',1400),event('click',2000,'Done')])
        r=analyze(session,notes)
        self.assertEqual(r['response_seconds'],.3)
        self.assertEqual(r['unresolved_waits'],[1])
        session['events'][3]['t_ms']=2000
        self.assertEqual(analyze(session,notes)['response_seconds'],0)

    def test_down_up_supplement_and_pair_dedup(self):
        events=[event('stable',0),event('down',1000,'A'),event('up',1100,'A'),event('stable',1500),event('down',2000,'Done'),event('up',2100,'Done')]
        session,notes=fixture(events)
        r=analyze(session,notes,5)
        self.assertAlmostEqual(r['adjusted_seconds'],1.7)
        self.assertEqual(len(r['clicks']),2)
        events.insert(3,event('click',1120,'A'))
        r=analyze(session,notes,6)
        self.assertAlmostEqual(r['response_seconds'],.38)

    def test_notes_exclusions_and_validation(self):
        session,notes=fixture()
        notes['pages'][0]['issue']=True
        self.assertIn('notes_issue',analyze(session,notes)['exclusion_reasons'])
        self.assertIn('notes_missing',analyze(session,None)['exclusion_reasons'])
        notes['pages'][0]['issue']=None
        self.assertIn('notes_unconfirmed',analyze(session,notes)['exclusion_reasons'])
        notes['session']['participant_code']='other'
        with self.assertRaises(ValueError): analyze(session,notes)
        session,notes=fixture();session['completed']=False;notes['pages'][0]['completed_confirmed']=False
        self.assertIn('incomplete',analyze(session,notes)['exclusion_reasons'])
        session,notes=fixture();session['events'].insert(0,event('down',0,'A'))
        self.assertIn('early_action',analyze(session,notes,5)['exclusion_reasons'])
        session,notes=fixture();session['events'][2]['t_ms']=2000
        with self.assertRaises(ValueError):analyze(session,notes)

    def test_page_threshold_versions_and_duplicate_guard(self):
        session,notes=fixture(); results=[]
        for i in range(3):
            row=analyze(session,notes);row['participant_code']=f'SYNTHETIC-{i}';results.append(row)
        page=next(r for r in summarize(results) if r['procedure_version']=='all')
        self.assertEqual((page['eligible_successes'],page['adjusted_median']),(3,4.2))
        self.assertTrue(all(r['report']=='completion_only' for r in summarize(results[:2])))
        with self.assertRaises(ValueError):summarize([results[0],results[0]])
        prior=analyze(session,notes,prior_procedure=True);prior['participant_code']='SYNTHETIC-old'
        page=next(r for r in summarize(results[:2]+[prior]) if r['procedure_version']=='all')
        self.assertIsNone(page['adjusted_median'])
        self.assertEqual(page['prior_procedure_included']['adjusted_median'],4.2)

    def test_cli_writes_analysis_but_never_overwrites_inputs(self):
        session,notes=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'session.json').write_text(json.dumps(session),encoding='utf-8')
            (root/'notes.json').write_text(json.dumps(notes),encoding='utf-8')
            manifest=[dict(session='session.json',notes='notes.json',completion_index=4,completion_reason='Verified synthetic Done')]
            (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with patch('sys.argv',['analyze','--manifest',str(root/'manifest.json'),'--output',str(root/'result.json')]):main()
            self.assertEqual(json.loads((root/'result.json').read_text())['sessions'][0]['adjusted_seconds'],4.2)
            with patch('sys.argv',['analyze','--manifest',str(root/'manifest.json'),'--output',str(root/'session.json')]):
                with self.assertRaises(ValueError):main()

    def test_missing_start_confirmation_and_next_scroll_boundary(self):
        session,notes=fixture([event('click',1000,'A'),event('click',2000,'Done')])
        self.assertIn('start_missing',analyze(session,notes,1)['exclusion_reasons'])
        session,notes=fixture();notes['pages'][0]['completed_confirmed']=None
        self.assertIn('completion_unconfirmed',analyze(session,notes)['exclusion_reasons'])
        session,notes=fixture([event('stable',0),event('click',1000,'A'),event('scroll',1100),event('stable',1400),event('click',2000,'Done')])
        result=analyze(session,notes)
        self.assertEqual(result['response_seconds'],0)
        self.assertEqual(result['unresolved_waits'],[1])
