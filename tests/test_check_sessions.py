"""human-study/check_sessions.py: 세션 직후 참가자 파일 6개 검사.

기대값은 session-procedure.md 규칙(6페이지 각 1개, 뷰포트 1280×800, 페이지당 3분)에서 가져왔다.
human-study/ 폴더는 하이픈이 있어 모듈로 import할 수 없으므로 파일 경로로 불러온다.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("human_study_check_sessions", ROOT / "human-study" / "check_sessions.py")
check = importlib.util.module_from_spec(SPEC)
sys.modules["human_study_check_sessions"] = check
SPEC.loader.exec_module(check)

PAGES = [
    "sb-admin-2/register/baseline",
    "material-kit-react/products/baseline",
    "material-kit-react/sign-in/baseline",
    "sb-admin-2/login/small",
    "shadcn-admin/tasks/contrast",
    "shadcn-admin/users/below-fold",
]


def session(page_id: str, **over) -> dict:
    data = {
        "participant_code": "P01",
        "page_id": page_id,
        "device": "mouse",
        "viewport": {"width": 1280, "height": 800},
        "daily_computer_hours": 4,
        "started_at": "2026-11-11T01:00:00Z",
        "completed": True,
        "events": [
            {"t_ms": 0, "type": "stable", "x": None, "y": None, "target_key": None},
            {"t_ms": 1500, "type": "click", "x": 100, "y": 200, "target_key": "button|button|OK||main"},
        ],
    }
    data.update(over)
    return data


class CheckSessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data: dict, suffix: str = ".json") -> None:
        name = f"human-session-{data['participant_code']}-{data['page_id'].replace('/', '-')}-x{suffix}"
        (self.dir / name).write_text(json.dumps(data), encoding="utf-8")

    def test_page_list_matches_pages_md(self):
        self.assertEqual(sorted(check.expected_pages()), sorted(PAGES))

    def test_six_good_files_pass(self):
        for p in PAGES:
            self.write(session(p))
        errors, warnings, rows = check.check_participant("P01", self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 6)

    def test_missing_page_is_error(self):
        for p in PAGES[:-1]:
            self.write(session(p))
        errors, _, _ = check.check_participant("P01", self.dir)
        self.assertEqual(errors, ["shadcn-admin/users/below-fold: 파일 없음"])

    def test_other_participant_files_are_ignored(self):
        for p in PAGES:
            self.write(session(p))
        self.write(session(PAGES[0], participant_code="P02"))
        errors, _, rows = check.check_participant("P01", self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 6)

    def test_wrong_viewport_is_error(self):
        for p in PAGES:
            self.write(session(p, viewport={"width": 1280, "height": 720}) if p == PAGES[0] else session(p))
        errors, _, _ = check.check_participant("P01", self.dir)
        self.assertEqual(len(errors), 1)
        self.assertIn("뷰포트", errors[0])

    def test_invalid_file_is_error(self):
        for p in PAGES:
            self.write(session(p))
        self.write(session(PAGES[0]), suffix=".invalid.json")
        errors, _, _ = check.check_participant("P01", self.dir)
        self.assertEqual(len(errors), 1)
        self.assertIn("invalid", errors[0])

    def test_over_three_minutes_and_null_click_are_warnings(self):
        long_events = [
            {"t_ms": 0, "type": "stable", "x": None, "y": None, "target_key": None},
            {"t_ms": 180_001, "type": "click", "x": 707, "y": 294, "target_key": None},
        ]
        for p in PAGES:
            self.write(session(p, events=long_events) if p == PAGES[3] else session(p))
        errors, warnings, _ = check.check_participant("P01", self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)

    def test_exactly_three_minutes_is_not_a_warning(self):
        events = [{"t_ms": 180_000, "type": "click", "x": 1, "y": 1, "target_key": "a|link|x||"}]
        _, warnings = check.check_file(session(PAGES[0], events=events))
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
