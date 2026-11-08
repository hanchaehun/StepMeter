"""LLM 베이스라인의 답 해석·번호 변환·다수결 테스트. 브라우저와 LLM 없이 손으로 만든 값을 넣는다."""
import unittest

from benchmark.baseline_llm import majority, parse_answer, read_array, to_keys

MARKS = [
    [{'number': 1, 'selector': '#email'}, {'number': 2, 'selector': '#signup'}],
    [{'number': 1, 'selector': '#plans'}],
    [],
]


class ParseAnswerTests(unittest.TestCase):
    def test_reads_json_array_inside_text(self):
        text = '찾은 문제입니다.\n[{"screen": 1, "number": 2, "rule": "R02", "reason": "흐리다"}]'
        self.assertEqual(parse_answer(text), [{'screen': 1, 'number': 2, 'rule': 'R02', 'reason': '흐리다'}])

    def test_empty_or_broken_answer_is_no_finding(self):
        for text in ('[]', '문제가 없습니다', '[{"screen": 1,', ''):
            with self.subTest(text=text):
                self.assertEqual(parse_answer(text), [])

    def test_drops_items_with_unknown_rule_or_bad_fields(self):
        text = ('[{"screen": 1, "number": 2, "rule": "R05"},'
                ' {"screen": "1", "number": 2, "rule": "R02"},'
                ' {"screen": 1, "number": 2, "rule": "R10"}]')
        self.assertEqual(parse_answer(text), [{'screen': 1, 'number': 2, 'rule': 'R10'}])


class ReadArrayTests(unittest.TestCase):
    def test_cut_off_or_empty_answer_is_unreadable(self):
        # 답 길이 상한에 걸려 잘린 답과 빈 답은 '문제 없음([])'과 구분해야 한다.
        for text in ('', '[{"screen": 1, "number": 3, "rule": "R10", "reason": "가입 버튼에 글자가'):
            with self.subTest(text=text):
                self.assertIsNone(read_array(text))
        self.assertEqual(read_array('[]'), [])


class ToKeysTests(unittest.TestCase):
    def test_screen_and_number_become_selector(self):
        items = [{'screen': 1, 'number': 2, 'rule': 'R02'}, {'screen': 2, 'number': 1, 'rule': 'R04'}]
        self.assertEqual(to_keys(items, MARKS), {('R02', '#signup'), ('R04', '#plans')})

    def test_unknown_screen_or_number_is_dropped(self):
        items = [{'screen': 4, 'number': 1, 'rule': 'R02'}, {'screen': 1, 'number': 9, 'rule': 'R02'},
                 {'screen': 0, 'number': 1, 'rule': 'R02'}]
        self.assertEqual(to_keys(items, MARKS), set())


class MajorityTests(unittest.TestCase):
    def test_keeps_findings_seen_in_more_than_half_of_runs(self):
        runs = [{('R02', '#signup'), ('R01', '#email')}, {('R02', '#signup')}, set()]
        self.assertEqual(majority(runs), [{'rule': 'R02', 'target': '#signup'}])

    def test_single_run_keeps_everything(self):
        self.assertEqual(majority([{('R10', '#signup')}]), [{'rule': 'R10', 'target': '#signup'}])


if __name__ == '__main__':
    unittest.main()
