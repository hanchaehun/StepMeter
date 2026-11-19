"""Hand arithmetic from ADR 0011 section 3, not production-derived expectations."""
import unittest
from worker.metrics.klm import estimate_step
from tests.test_rules_w2 import target
from worker.rules import r01

class KLMTests(unittest.TestCase):
    def test_adr_example(self):
        typing = estimate_step(dict(action="type", text="x"*16), first_action=True)
        click = estimate_step(dict(action="click"), first_action=False, previous_action="type")
        self.assertAlmostEqual(typing, 8.88)
        self.assertAlmostEqual(click, 3.05)
        self.assertAlmostEqual(typing + click, 11.93)

    def test_actions_transitions_scroll_and_enter(self):
        for action, expected in [('click',2.65),('back',2.65),('select',3.95),('scroll',2.45)]:
            self.assertAlmostEqual(estimate_step(dict(action=action), first_action=False), expected)
            self.assertAlmostEqual(estimate_step(dict(action=action), first_action=True), expected+1.35)
        self.assertAlmostEqual(estimate_step(dict(action='click'), first_action=False, auto_scrolled=True),3.75)
        self.assertAlmostEqual(estimate_step(dict(action='type',text='',submit=True),first_action=False),3.33)
        self.assertAlmostEqual(estimate_step(dict(action='type',text='가나'),first_action=False,previous_action='type'),4.01)
        for action in ['wait','done','fail']:
            self.assertEqual(estimate_step(dict(action=action),first_action=True,previous_action='type',auto_scrolled=True),0)
        self.assertIsNone(estimate_step(dict(action='click'),first_action=True,mobile=True))
        for action in [dict(action='unknown'),dict(action='type',text=3),dict(action='type',text='',submit=1)]:
            with self.assertRaises(ValueError): estimate_step(action,first_action=False)

    def test_r01_reference_boundaries(self):
        for size in [24,43.9]:
            desktop=r01.evaluate(target(size)); mobile=r01.evaluate(target(size),mobile=True)
            self.assertEqual((desktop.severity,desktop.is_reference),('low',True))
            self.assertEqual((mobile.severity,mobile.is_reference),('medium',False))
        item=r01.evaluate(target(23.9),axe_violation=True)
        self.assertEqual((item.severity,item.is_reference),('high',False))
        self.assertIsNone(r01.evaluate(target(44)))
        self.assertIsNone(r01.evaluate(target(44),mobile=True))
        self.assertIsNone(r01.evaluate(target(20))) # spacing exception unchanged

    def test_screen_reset_and_partial_attempt_sums(self):
        # First click 4s, another click 2.65s, new-screen click 4s.
        values=[estimate_step(dict(action='click'),first_action=first) for first in [True,False,True]]
        self.assertEqual(values,[4,2.65,4])
        self.assertAlmostEqual(sum(values),10.65)
