"""Expected values hand-calculated from plan 7.3–7.5, not implementation output."""
import unittest

from worker.compare.engine import align_paths, issue_changes, metric_changes, screen


def issue(n, name='Save', *, reference=False, page='/form'):
    return {'id': n, 'rule_id': 'R01', 'element_key': f'button|button|{name}||main',
            'screen': page, 'is_reference': reference}


class CompareTests(unittest.TestCase):
    def test_screen_identity_keeps_origin_and_hash_routes(self):
        self.assertNotEqual(screen('https://a.test/form'), screen('https://b.test/form'))
        self.assertEqual(screen('https://a.test/form?q=2#help'), 'https://a.test/form')
        self.assertEqual(screen('https://a.test/#/users'), 'https://a.test/#/users')

    def test_spread_and_strict_agent_boundary(self):
        # Baseline median 100, spread (110-90)/100=.2; threshold .4.
        rows = metric_changes({'travel_distance': [90, 100, 110]}, {'travel_distance': [140, 140, 140]})
        self.assertEqual(rows[0]['threshold'], .4)
        self.assertEqual(rows[0]['verdict'], 'unchanged')
        rows = metric_changes({'travel_distance': [90, 100, 110]}, {'travel_distance': [141, 141, 141]})
        self.assertEqual(rows[0]['delta'], 41)
        self.assertEqual(rows[0]['verdict'], 'worse')

    def test_replay_inclusive_boundary_and_missing(self):
        rows = metric_changes({'travel_distance': [100], 'click_count': [2]},
                              {'travel_distance': [110], 'click_count': [3]}, replay=True)
        self.assertEqual([r['verdict'] for r in rows], ['worse', 'worse'])
        self.assertEqual(metric_changes({'click_count': [2]}, {}, replay=True)[0]['verdict'], 'not_comparable')
        self.assertEqual(metric_changes({'travel_distance': [0, 0]},
                         {'travel_distance': [3, 3]})[0]['verdict'], 'not_comparable')

    def test_no_single_attempt_dispersion_or_partial_replay_verdict(self):
        self.assertEqual(metric_changes({'click_count': [2]}, {'click_count': [4]})[0]['verdict'], 'not_comparable')
        self.assertEqual(metric_changes({'click_count': [2]}, {'click_count': [4]},
                         replay=True, comparable=False)[0]['verdict'], 'not_comparable')

    def test_issue_dedupe_reference_and_page_identity(self):
        new, resolved, kept = issue_changes([issue(1), issue(2)],
            [issue(3), issue(4, reference=True), issue(5, page='/other')])
        self.assertEqual([i['id'] for i in kept], [3])
        self.assertEqual([i['id'] for i in new], [5])
        self.assertEqual(resolved, [])

    def test_ambiguous_targets_are_not_arbitrarily_paired(self):
        new, resolved, kept = issue_changes([issue(1)], [issue(2, 'Save item'), issue(3, 'Save draft')])
        self.assertEqual(len(new), 2)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(kept, [])

    def test_path_add_remove_preserves_indices_and_normalizes_name(self):
        def step(idx, name):
            return {'idx': idx, 'action': {'action': 'click'}, 'fingerprint': {'role': 'button', 'name': name}}
        self.assertEqual(align_paths([step(0, 'Save'), step(2, 'Next')],
                                    [step(0, ' SAVE '), step(1, 'Confirm'), step(3, 'Next')]), [
            {'op': 'kept', 'base_idx': 0, 'target_idx': 0},
            {'op': 'added', 'base_idx': None, 'target_idx': 1},
            {'op': 'kept', 'base_idx': 2, 'target_idx': 3}])
