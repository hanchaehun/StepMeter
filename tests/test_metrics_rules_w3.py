"""Plan-derived R08 thresholds and hand-counted synthetic human events."""
import copy
import unittest
from ml.timing.human import click_events
from worker.metrics.interactions import count_interactions, count_no_response_clicks, count_repeated_clicks
from worker.rules.r08 import evaluate

class W3Tests(unittest.TestCase):
    def test_r08_counts_attempts_not_back_presses(self):
        for counts in ([], [1], [1, 1], [4, 0, 0], [0, 0, 0]):
            self.assertIsNone(evaluate(counts))
        candidate = evaluate([1, 3, 0])
        self.assertEqual((candidate.rule_id, candidate.measured, candidate.threshold), ('R08', 2, 2))
        self.assertEqual(candidate.severity, 'medium')
        self.assertTrue(candidate.is_reference)
        self.assertIsNotNone(evaluate([1, 1, 1]))
        self.assertIsNone(evaluate([1, 1, 0, 0]))
        for counts in ([-1, 0, 0], [True, 1, 0]):
            with self.assertRaises(ValueError): evaluate(counts)

    def test_select_is_one_click_equivalent(self):
        self.assertEqual(count_interactions(['select', 'click', 'done', 'select'])['click_count'], 2)
        self.assertEqual(count_no_response_clicks(['select'], ['no_change']), 1)
        self.assertEqual(count_repeated_clicks(['select', 'select'], ['A', 'A']), 1)

    def test_real_click_uses_click_without_duplicate_and_preserves_original(self):
        kinds = ['down', 'up', 'move', 'stable', 'click']
        events = [
            dict(
                type=k,
                t_ms=i * 10,
                x=None if k == 'stable' else 10,
                y=None if k == 'stable' else 20,
                target_key='A' if k in {'down', 'up'} else None,
            )
            for i, k in enumerate(kinds)
        ]
        original = copy.deepcopy(events)
        clicks = click_events(events)
        self.assertEqual(events, original)  # 2절 서두: 원본 이벤트 미변경
        self.assertEqual(len(clicks), 1)  # 2절 2번: 실제 click이 있으면 보완하지 않음
        self.assertEqual(
            clicks[0],
            {
                't_ms': 40,
                'type': 'click',
                'x': 10,
                'y': 20,
                'target_key': None,
                'supplemented': False,
                'down_index': 0,
                'up_index': 1,
                'click_index': 4,
                'target_source': 'unknown',
            },
        )  # 2절 2번·5번: 실제 click 유지 및 down/up/click 원본 인덱스·출처 기록

        dup_events = [
            dict(type='down', t_ms=0, x=10, y=20, target_key='A'),
            dict(type='up', t_ms=20, x=10, y=20, target_key='A'),
            dict(type='click', t_ms=30, x=10, y=20, target_key='A'),
            dict(type='click', t_ms=40, x=10, y=20, target_key='A'),
        ]
        dup_clicks = click_events(dup_events)
        self.assertEqual([c['supplemented'] for c in dup_clicks], [False, False])  # 2절 2번: 중복 보완 없음
        self.assertEqual(
            [(c['down_index'], c['up_index'], c['click_index']) for c in dup_clicks],
            [(0, 1, 2), (None, None, 3)],
        )  # 2절 2번·5번: 첫 실제 click이 up과 짝을 이루고 보완은 추가하지 않음

    def test_click_match_time_and_distance_boundaries_and_breakers(self):
        # 2절 2번: up 이후 다음 down/key/scroll 전 500ms 이내, 5px 이내 실제 click 매칭
        for dt_ms in (499, 500):
            matched = click_events([
                dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
                dict(type='up', t_ms=100, x=10, y=10, target_key='A'),
                dict(type='click', t_ms=100 + dt_ms, x=10, y=10, target_key='A'),
            ])
            self.assertEqual(len(matched), 1)  # 2절 2번: 499ms·500ms는 실제 click 사용
            self.assertFalse(matched[0]['supplemented'])  # 2절 2번
            self.assertEqual(matched[0]['t_ms'], 100 + dt_ms)  # 2절 2번

        over_time = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=100, x=10, y=10, target_key='A'),
            dict(type='click', t_ms=601, x=10, y=10, target_key='A'),
        ])
        self.assertEqual([c['supplemented'] for c in over_time], [True, False])  # 2절 2번·3번: 501ms는 매칭 제외되어 up 보완
        self.assertEqual([c['t_ms'] for c in over_time], [100, 601])  # 2절 3번·5번

        # up(10,10)에서 3-4-5 직각삼각형 거리 5px vs 5.1px
        within_5px = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=100, x=10, y=10, target_key='A'),
            dict(type='click', t_ms=120, x=13, y=14, target_key='A'),
        ])
        self.assertEqual(len(within_5px), 1)  # 2절 2번: 5px 이내 실제 click 사용
        self.assertFalse(within_5px[0]['supplemented'])  # 2절 2번

        over_5px = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=100, x=10, y=10, target_key='A'),
            dict(type='click', t_ms=120, x=15.1, y=10, target_key='A'),
        ])
        self.assertEqual([c['supplemented'] for c in over_5px], [True, False])  # 2절 2번·3번: 5.1px는 매칭 안 되어 up 보완

        # up 뒤 다음 key/scroll/down이 먼저 오면 뒤따르는 click은 그 up과 매칭되지 않음
        for breaker in ('key', 'scroll', 'down'):
            broken = click_events([
                dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
                dict(type='up', t_ms=50, x=10, y=10, target_key='A'),
                dict(type=breaker, t_ms=60, x=10 if breaker != 'key' else None, y=10 if breaker != 'key' else None, target_key=None),
                dict(type='click', t_ms=70, x=10, y=10, target_key='A'),
            ])
            self.assertEqual([c['supplemented'] for c in broken], [True, False])  # 2절 2번·3번: 경계 뒤 click과 분리
            self.assertIsNone(broken[1]['up_index'])  # 2절 2번·5번

    def test_supplement_duration_drag_and_intervening_events(self):
        # 2절 1번·3번: 0ms(동일 시각 인덱스 순서)와 1000ms 보완, 1001ms 미보완
        same_ts = click_events([
            dict(type='down', t_ms=50, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=50, x=10, y=10, target_key='A'),
        ])
        self.assertEqual(len(same_ts), 1)  # 2절 1번·3번: 0ms 보완
        self.assertTrue(same_ts[0]['supplemented'])  # 2절 5번
        self.assertEqual((same_ts[0]['down_index'], same_ts[0]['up_index']), (0, 1))  # 2절 1번·5번

        at_1000ms = click_events([
            dict(type='down', t_ms=100, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=1100, x=10, y=10, target_key='A'),
        ])
        self.assertEqual(len(at_1000ms), 1)  # 2절 3번: 1000ms 경계 보완
        self.assertEqual(at_1000ms[0]['t_ms'], 1100)  # 2절 3번: up 시각에 보완

        over_1000ms = click_events([
            dict(type='down', t_ms=100, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=1101, x=10, y=10, target_key='A'),
        ])
        self.assertEqual(over_1000ms, [])  # 2절 3번: 1001ms 초과 미보완

        # 2절 3번: down 기준 5px 경계(보완), 5.1px 초과(미보완), 끌기 6px 이동(미보완)
        within_5px = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='move', t_ms=20, x=13, y=14, target_key=None),
            dict(type='up', t_ms=40, x=15, y=10, target_key='A'),
        ])
        self.assertEqual(len(within_5px), 1)  # 2절 3번: 모든 포인터 위치가 5px 이내

        over_5px = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=40, x=15.1, y=10, target_key='A'),
        ])
        self.assertEqual(over_5px, [])  # 2절 3번: 5.1px 초과 미보완

        drag_6px = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='move', t_ms=20, x=16, y=10, target_key=None),
            dict(type='up', t_ms=40, x=16, y=10, target_key='A'),
        ])
        self.assertEqual(drag_6px, [])  # 2절 3번: 끌기(6px 이동) 미보완

        drag_6px_return = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='move', t_ms=20, x=16, y=10, target_key=None),
            dict(type='up', t_ms=40, x=10, y=10, target_key='A'),
        ])
        self.assertEqual(drag_6px_return, [])  # 2절 3번: 중간 move가 6px 벗어나면 돌아와도 미보완

        # 2절 3번: 사이에 key/scroll 끼면 미보완, stable은 허용
        for blocker in ('key', 'scroll'):
            blocked = click_events([
                dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
                dict(type=blocker, t_ms=20, x=None if blocker == 'key' else 10, y=None if blocker == 'key' else 10, target_key=None),
                dict(type='up', t_ms=40, x=10, y=10, target_key='A'),
            ])
            self.assertEqual(blocked, [])  # 2절 3번: 사이에 key/scroll 끼면 미보완

        with_stable = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='stable', t_ms=20, x=None, y=None, target_key=None),
            dict(type='up', t_ms=40, x=10, y=10, target_key='A'),
        ])
        self.assertEqual(len(with_stable), 1)  # 2절 3번: stable은 포인터/key/scroll 방해 아님

        # 2절 1번: 새 down이 오면 앞 down은 미완성
        restarted_down = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='down', t_ms=20, x=10, y=10, target_key='B'),
            dict(type='up', t_ms=40, x=10, y=10, target_key='B'),
        ])
        self.assertEqual(len(restarted_down), 1)  # 2절 1번
        self.assertEqual((restarted_down[0]['down_index'], restarted_down[0]['up_index']), (1, 2))  # 2절 1번·5번

        # 2절 3번: 짝 없는 up과 좌표 누락 미보완
        self.assertEqual(click_events([dict(type='up', t_ms=10, x=10, y=10, target_key='A')]), [])  # 2절 3번: 짝 없는 up
        self.assertEqual(
            click_events([
                dict(type='down', t_ms=0, x=None, y=10, target_key='A'),
                dict(type='up', t_ms=20, x=10, y=10, target_key='A'),
            ]),
            [],
        )  # 2절 3번: 좌표 누락 미보완
        self.assertEqual(
            click_events([
                dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
                dict(type='move', t_ms=10, x=None, y=None, target_key=None),
                dict(type='up', t_ms=20, x=10, y=10, target_key='A'),
            ]),
            [],
        )  # 2절 3번: 중간 move 좌표 누락 미보완

    def test_supplement_target_priority_mismatch_and_unknown(self):
        # 2절 4번·5번: up.target_key 우선
        from_up = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key=None),
            dict(type='up', t_ms=20, x=10, y=10, target_key='B'),
        ])
        self.assertEqual((from_up[0]['target_key'], from_up[0]['target_source']), ('B', 'up'))  # 2절 4번·5번

        # 2절 4번·5번: up이 null이고 down에 있으면 target_from_down
        from_down = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=20, x=10, y=10, target_key=None),
        ])
        self.assertEqual(
            (from_down[0]['target_key'], from_down[0]['target_source']),
            ('A', 'target_from_down'),
        )  # 2절 4번·5번

        # 2절 4번: 둘 다 있고 다르면 미보완
        mismatch = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key='A'),
            dict(type='up', t_ms=20, x=10, y=10, target_key='B'),
        ])
        self.assertEqual(mismatch, [])  # 2절 4번: up·down 대상 불일치 미보완

        # 2절 4번·5번: 둘 다 null이면 대상 미상으로 보존
        both_null = click_events([
            dict(type='down', t_ms=0, x=10, y=10, target_key=None),
            dict(type='up', t_ms=20, x=10, y=10, target_key=None),
        ])
        self.assertEqual(len(both_null), 1)  # 2절 4번
        self.assertIsNone(both_null[0]['target_key'])  # 2절 4번
        self.assertEqual(both_null[0]['target_source'], 'unknown')  # 2절 4번·5번

    def test_click_only_legacy_and_validation_errors(self):
        legacy = click_events([
            dict(type='click', t_ms=10, x=5, y=6, target_key='btn'),
            dict(type='click', t_ms=25, x=7, y=8, target_key=None),
        ])
        self.assertEqual(
            legacy,
            [
                {
                    't_ms': 10,
                    'type': 'click',
                    'x': 5,
                    'y': 6,
                    'target_key': 'btn',
                    'supplemented': False,
                    'down_index': None,
                    'up_index': None,
                    'click_index': 0,
                    'target_source': 'click',
                },
                {
                    't_ms': 25,
                    'type': 'click',
                    'x': 7,
                    'y': 8,
                    'target_key': None,
                    'supplemented': False,
                    'down_index': None,
                    'up_index': None,
                    'click_index': 1,
                    'target_source': 'unknown',
                },
            ],
        )  # 2절 5번: click-only 이전 기록 유지 및 인덱스·출처 기록
        self.assertEqual(click_events([]), [])
        self.assertEqual(click_events([dict(type='down', t_ms=1, x=0, y=0, target_key=None)]), [])  # 2절 1번: 미완성 down

        for bad_events in (
            [dict(type='up', t_ms=3), dict(type='up', t_ms=2)],
            [dict(type='click', t_ms=-1)],
            [dict(type='click', t_ms=True)],
            [dict(type='click', t_ms=float('nan'))],
            [dict(type='hover', t_ms=1)],
            [dict(type='click', t_ms=1, x=float('inf'), y=0)],
        ):
            with self.assertRaises(ValueError):
                click_events(bad_events)
