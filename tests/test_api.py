"""apps/api/main.py 검사. 기대값(상태 코드, 응답 형식)은 apps/api/openapi.yaml에서 가져왔다.

DB를 비우므로 테스트 전용 주소를 준다. 없으면 건너뛴다.
    TEST_DATABASE_URL=postgresql+psycopg://stepmeter:stepmeter@localhost:5434/stepmeter_test
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml
from sqlalchemy import select
from jsonschema import Draft202012Validator

from tests import test_openapi_schema as openapi_test

DB_URL = os.environ.get("TEST_DATABASE_URL")
INI = Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic.ini"
SPEC = yaml.safe_load(openapi_test.SPEC_PATH.read_text(encoding="utf-8"))
# 스키마를 통과하는 step 예시 (목 JSON). action·element_snapshot을 테스트 데이터로 쓴다
MOCK_STEPS = json.loads((openapi_test.MOCK_API / "steps.json").read_text(encoding="utf-8"))


def schema_errors(data, path: str, method: str, status: str) -> list[str]:
    """응답 본문이 openapi.yaml의 해당 응답 스키마를 통과하는지. E2E와 같은 방식 (format은 검사 안 함)."""
    body = openapi_test.OpenApiSchemaTests.body_schema(SimpleNamespace(spec=SPEC), path, method, status)
    return [e.message for e in Draft202012Validator({**body, "components": SPEC["components"]}).iter_errors(data)]


@unittest.skipUnless(DB_URL, "TEST_DATABASE_URL 없음")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config

        os.environ["DATABASE_URL"] = DB_URL  # main.py가 import될 때 읽는다
        cfg = Config(str(INI))
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        from fastapi.testclient import TestClient

        from apps.api import main

        cls.main = main
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.main.engine.dispose()

    def setUp(self):
        from apps.api.db.models import AccessCode

        with self.main.engine.begin() as c:
            c.exec_driver_sql("TRUNCATE access_code RESTART IDENTITY CASCADE")
        with self.main.SessionLocal.begin() as db:
            db.add_all([
                AccessCode(code_hash=self.main.hash_code("code-a")),
                AccessCode(code_hash=self.main.hash_code("code-b")),
                AccessCode(code_hash=self.main.hash_code("code-off"), active=False),
            ])

    def call(self, method: str, url: str, code: str | None = "code-a", **kw):
        headers = {"X-Access-Code": code} if code else {}
        return self.client.request(method, url, headers=headers, **kw)

    def make_project(self, code: str = "code-a") -> dict:
        r = self.call("POST", "/projects", code, json={"name": "p", "base_url": "http://site.example/start"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def make_task(self, code: str = "code-a") -> int:
        pid = self.make_project(code)["id"]
        r = self.call("POST", f"/projects/{pid}/tasks", code, json={"description": "t"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def insert_run(self, task_id: int, status: str = "completed", viewport: str = "desktop") -> int:
        from apps.api.db.models import Run

        with self.main.SessionLocal.begin() as db:
            r = Run(task_id=task_id, viewport=viewport, mode="agent", repeat_n=3, model="claude-haiku-5-5", status=status)
            db.add(r)
            db.flush()
            return r.id

    def post_run(self, task_id: int, body: dict, code: str = "code-a"):
        """enqueue_run은 가짜로 바꾸고 넘겨받은 run_id를 기록한다 (Redis 없이)."""
        with mock.patch.object(self.main, "enqueue_run") as enqueue:
            r = self.call("POST", f"/tasks/{task_id}/runs", code, json=body)
        return r, [c.args[0] for c in enqueue.call_args_list]

    def add_attempt(self, run_id: int, index: int, **cols) -> int:
        from apps.api.db.models import Attempt

        with self.main.SessionLocal.begin() as db:
            a = Attempt(run_id=run_id, index=index, kind="agent", **cols)
            db.add(a)
            db.flush()
            return a.id

    def add_step(self, attempt_id: int, idx: int, key: str | None = None, thought: str = "생각", **cols) -> int:
        """워커처럼 step 저장과 update_progress를 한 트랜잭션에서 한다 (steps_count 갱신)."""
        from apps.api.db.models import Attempt, Step
        from worker.queue.runs import update_progress

        mock_step = MOCK_STEPS[idx % len(MOCK_STEPS)]
        with self.main.SessionLocal.begin() as db:
            st = Step(
                attempt_id=attempt_id, idx=idx, action=mock_step["action"], thought=thought, screenshot_key=key,
                url=mock_step["url"], state_hash="h", changed=True, effect_type="dom_mutation", **cols,
            )
            db.add(st)
            db.flush()
            update_progress(db, db.get(Attempt, attempt_id).run_id)
            return st.id

    # --- 초대 코드 (F17) ---

    def test_401_without_wrong_or_inactive_code(self):
        for code in (None, "nope", "code-off"):
            with self.subTest(code=code):
                r = self.call("GET", "/projects", code)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(schema_errors(r.json(), "/projects", "get", "401"), [])

    # --- project ---

    def test_create_project(self):
        r = self.call("POST", "/projects", json={"name": "p", "base_url": "http://site.example/start"})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(schema_errors(body, "/projects", "post", "201"), [])
        self.assertEqual(body["base_url"], "http://site.example/start")  # 받은 그대로
        self.assertEqual(body["daily_run_limit"], 10)  # 기본 10 (F17)

    def test_create_project_422(self):
        bad = [
            {"name": "", "base_url": "http://a.example"},  # minLength 1
            {"name": "p", "base_url": "not a url"},  # format uri
            {"name": "p", "base_url": "http://a.example", "extra": 1},  # additionalProperties false
            {"name": "p"},  # base_url 필수
        ]
        for body in bad:
            with self.subTest(body=body):
                r = self.call("POST", "/projects", json=body)
                self.assertEqual(r.status_code, 422)
                self.assertEqual(schema_errors(r.json(), "/projects", "post", "422"), [])

    def test_list_projects_only_own_code(self):
        mine = self.make_project("code-a")
        self.make_project("code-b")
        r = self.call("GET", "/projects")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(schema_errors(body, "/projects", "get", "200"), [])
        self.assertEqual([p["id"] for p in body], [mine["id"]])
        self.assertIsNone(body[0]["latest_run"])  # 측정이 없으면 null

    # --- task ---

    def test_create_task(self):
        pid = self.make_project()["id"]
        cases = [
            ({"description": "가입한다", "success_condition": {"url_contains": "/done.html"}}, {"url_contains": "/done.html"}),
            ({"description": "가입한다"}, None),  # success_condition 기본 null
        ]
        for req, cond in cases:
            with self.subTest(req=req):
                r = self.call("POST", f"/projects/{pid}/tasks", json=req)
                self.assertEqual(r.status_code, 201)
                body = r.json()
                self.assertEqual(schema_errors(body, "/projects/{id}/tasks", "post", "201"), [])
                self.assertEqual((body["project_id"], body["success_condition"]), (pid, cond))

    def test_create_task_404_other_code_or_missing(self):
        other = self.make_project("code-b")["id"]
        for pid in (other, 9999):
            with self.subTest(pid=pid):
                r = self.call("POST", f"/projects/{pid}/tasks", json={"description": "t"})
                self.assertEqual(r.status_code, 404)
                self.assertEqual(schema_errors(r.json(), "/projects/{id}/tasks", "post", "404"), [])

    def test_create_task_422(self):
        pid = self.make_project()["id"]
        bad = [
            {"description": ""},  # minLength 1
            {"description": "x" * 1001},  # maxLength 1000
            {"description": "t", "success_condition": {}},  # minProperties 1
            {"description": "t", "success_condition": {"url_contains": ""}},  # minLength 1
            {"description": "t", "success_condition": {"other": "x"}},  # additionalProperties false
            {"description": "t", "success_condition": {"url_contains": "/done", "text_present": None}},  # type string
            {"description": "t", "extra": 1},
        ]
        for body in bad:
            with self.subTest(body=body):
                r = self.call("POST", f"/projects/{pid}/tasks", json=body)
                self.assertEqual(r.status_code, 422)
                self.assertEqual(schema_errors(r.json(), "/projects/{id}/tasks", "post", "422"), [])

    def test_get_task(self):
        pid = self.make_project()["id"]
        req = {"description": "가입한다", "success_condition": {"url_contains": "/done.html"}}
        tid = self.call("POST", f"/projects/{pid}/tasks", json=req).json()["id"]
        r = self.call("GET", f"/tasks/{tid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(schema_errors(body, "/tasks/{id}", "get", "200"), [])
        self.assertEqual(body, {"id": tid, "project_id": pid, **req})

    def test_get_task_404_other_code_or_missing(self):
        other = self.make_task("code-b")
        for tid in (other, 9999):
            with self.subTest(tid=tid):
                r = self.call("GET", f"/tasks/{tid}")
                self.assertEqual(r.status_code, 404)
                self.assertEqual(schema_errors(r.json(), "/tasks/{id}", "get", "404"), [])

    # --- run ---

    def test_create_run_defaults_and_enqueue(self):
        tid = self.make_task()
        r, enqueued = self.post_run(tid, {})
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertEqual(schema_errors(body, "/tasks/{id}/runs", "post", "202"), [])
        # openapi RunCreate 기본값, 202 = status queued
        expected = {"viewport": "desktop", "repeat_n": 3, "model": "claude-haiku-5-5", "mode": "auto",
                    "base_run_id": None, "status": "queued", "progress": 0, "started_at": None, "finished_at": None}
        self.assertEqual({k: body[k] for k in expected}, expected)
        self.assertEqual(enqueued, [body["id"]])

    def test_create_run_e2e_request(self):
        tid = self.make_task()
        req = {"viewport": "desktop", "repeat_n": 3, "model": "claude-haiku-5-5", "mode": "agent"}  # tests/e2e RUN_REQUEST
        r, _ = self.post_run(tid, req)
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["mode"], "agent")

    def test_base_run_defaults_to_latest_completed_same_viewport(self):
        tid = self.make_task()
        old = self.insert_run(tid)
        latest = self.insert_run(tid)
        self.insert_run(tid, status="running")  # 완료 아님
        self.insert_run(tid, viewport="mobile")  # 뷰포트 다름
        self.insert_run(self.make_task())  # 다른 과업
        r, _ = self.post_run(tid, {})
        self.assertEqual(r.json()["base_run_id"], latest)
        r, _ = self.post_run(tid, {"base_run_id": old})  # 직접 주면 그 값
        self.assertEqual(r.json()["base_run_id"], old)

    def test_base_run_explicit_null_stays_null(self):
        tid = self.make_task()
        self.insert_run(tid)
        r, _ = self.post_run(tid, {"base_run_id": None})
        self.assertIsNone(r.json()["base_run_id"])

    def test_create_run_404(self):
        mine, other = self.make_task(), self.make_task("code-b")
        other_run = self.insert_run(other)
        cases = [(other, {}), (9999, {}), (mine, {"base_run_id": other_run}), (mine, {"base_run_id": 9999})]
        for tid, body in cases:
            with self.subTest(tid=tid, body=body):
                r, enqueued = self.post_run(tid, body)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(schema_errors(r.json(), "/tasks/{id}/runs", "post", "404"), [])
                self.assertEqual(enqueued, [])

    def test_create_run_422(self):
        tid = self.make_task()
        bad = [
            {"repeat_n": 4}, {"repeat_n": "3"}, {"viewport": "tablet"}, {"model": "gpt"},
            {"mode": "ci"}, {"base_run_id": "1"}, {"extra": 1},
        ]
        for body in bad:
            with self.subTest(body=body):
                r, enqueued = self.post_run(tid, body)
                self.assertEqual(r.status_code, 422)
                self.assertEqual(schema_errors(r.json(), "/tasks/{id}/runs", "post", "422"), [])
                self.assertEqual(enqueued, [])

    def test_enqueue_failure_marks_run_failed(self):
        from apps.api.db.models import Run

        tid = self.make_task()
        with mock.patch.object(self.main, "enqueue_run", side_effect=ConnectionError("redis down")):
            r = self.call("POST", f"/tasks/{tid}/runs", json={})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(schema_errors(r.json(), "/tasks/{id}/runs", "post", "500"), [])
        with self.main.SessionLocal() as db:
            run = db.scalars(select(Run).where(Run.task_id == tid)).one()
            self.assertEqual(run.status, "failed")
            self.assertIsNotNone(run.finished_at)

    # --- GET /runs/{id} ---

    def get_run(self, run_id: int, code: str = "code-a") -> dict:
        r = self.call("GET", f"/runs/{run_id}", code)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(schema_errors(r.json(), "/runs/{id}", "get", "200"), [])
        return r.json()

    def test_get_run_without_steps(self):
        run = self.insert_run(self.make_task(), status="queued")
        body = self.get_run(run)
        self.assertEqual((body["id"], body["status"]), (run, "queued"))
        self.assertIsNone(body["latest_step"])  # 아직 없으면 null

    def test_get_run_latest_step_across_attempts(self):
        run = self.insert_run(self.make_task(), status="running")
        a1, a2 = self.add_attempt(run, 1), self.add_attempt(run, 2)
        self.add_step(a1, 0, "a.png")
        self.add_step(a2, 0, "b.png")
        self.add_step(a1, 1, "c.png", thought="마지막")  # 가장 최근에 저장된 step
        latest = self.get_run(run)["latest_step"]
        self.assertEqual(
            {k: latest[k] for k in ("attempt_index", "idx", "thought")},
            {"attempt_index": 1, "idx": 1, "thought": "마지막"},
        )
        self.assertTrue(latest["screenshot_url"].endswith("/screenshots/c.png"))

    def test_get_run_step_without_screenshot(self):
        run = self.insert_run(self.make_task(), status="running")
        self.add_step(self.add_attempt(run, 1), 0, None)
        self.assertIsNone(self.get_run(run)["latest_step"]["screenshot_url"])

    def test_get_run_representative_attempt_index(self):
        from apps.api.db.models import Run

        run = self.insert_run(self.make_task())
        self.add_attempt(run, 1)
        a2 = self.add_attempt(run, 2)
        with self.main.SessionLocal.begin() as db:
            db.get(Run, run).representative_attempt_id = a2
        self.assertEqual(self.get_run(run)["representative_attempt_index"], 2)  # DB id가 아니라 index

    def test_get_run_404(self):
        other = self.insert_run(self.make_task("code-b"))
        for run in (other, 9999):
            with self.subTest(run=run):
                r = self.call("GET", f"/runs/{run}")
                self.assertEqual(r.status_code, 404)
                self.assertEqual(schema_errors(r.json(), "/runs/{id}", "get", "404"), [])

    # --- GET /runs/{id}/report ---

    def get_report(self, run_id: int) -> dict:
        r = self.call("GET", f"/runs/{run_id}/report")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(schema_errors(r.json(), "/runs/{id}/report", "get", "200"), [])
        return r.json()

    def make_finished_run(self, viewport: str = "desktop") -> tuple[int, dict]:
        """완료 run: attempt 2개(1 실패, 2 성공·대표), 대표 경로 step 5개, 지표, 이슈."""
        from apps.api.db.models import Issue, Metric, Run

        run = self.insert_run(self.make_task(), viewport=viewport)
        a1 = self.add_attempt(run, 1, end_reason="gave_up", end_detail="버튼 없음", success=False)
        a2 = self.add_attempt(run, 2, end_reason="success", success=True)
        self.add_step(a1, 0, fitts_id=9.0, est_seconds=9.0)  # 대표 경로가 아님 → 상위 목록에서 빠져야 함
        # (idx, fitts_id, est_seconds)
        values = [(0, 1.0, 2.0), (1, 3.0, None), (2, None, 5.0), (3, 2.0, 1.0), (4, 3.0, 4.0)]
        step_ids = [self.add_step(a2, idx, fitts_id=f, est_seconds=e) for idx, f, e in values]
        with self.main.SessionLocal.begin() as db:
            db.get(Run, run).representative_attempt_id = a2
            db.add_all([
                Metric(run_id=run, key="click_count", value=2, unit="count", spread=0.0, spread_quality="weak"),
                Metric(run_id=run, attempt_id=a1, key="click_count", value=9, unit="count"),  # attempt별 값 → 제외
                Issue(run_id=run, rule_id="R02", severity="low", confidence=0.9, explanation="e"),
                Issue(run_id=run, rule_id="R01", severity="high", confidence=0.5, step_id=step_ids[3], explanation="e"),
                Issue(run_id=run, rule_id="R03", severity="high", confidence=0.8, explanation="e"),
                Issue(run_id=run, rule_id="R04", severity="medium", confidence=0.99, explanation="e"),
            ])
        return run, {"a1": a1, "a2": a2}

    def test_report(self):
        run, _ = self.make_finished_run()
        body = self.get_report(run)
        self.assertEqual(body["run"]["representative_attempt_index"], 2)
        self.assertEqual([(a["index"], a["end_reason"], a["steps_count"]) for a in body["attempts"]],
                         [(1, "gave_up", 1), (2, "success", 5)])
        self.assertEqual([(m["key"], m["value"]) for m in body["metrics"]], [("click_count", 2)])  # attempt_id null만
        # 심각도(high → medium → low) → 점수 내림차순
        self.assertEqual([i["rule_id"] for i in body["issues"]], ["R03", "R01", "R04", "R02"])
        self.assertEqual(body["issues"][1]["step"], {"attempt_index": 2, "idx": 3})
        self.assertIsNone(body["issues"][0]["step"])
        # 대표 경로 attempt만, 값 내림차순 최대 3개, null 제외. 같은 값이면 idx 순 (fitts 3.0 두 개)
        self.assertEqual([(s["idx"], s["value"]) for s in body["top_fitts_steps"]], [(1, 3.0), (4, 3.0), (3, 2.0)])
        self.assertEqual([(s["idx"], s["value"]) for s in body["slowest_steps"]], [(2, 5.0), (4, 4.0), (0, 2.0)])

    def test_report_mobile_has_no_slowest_steps(self):
        run, _ = self.make_finished_run(viewport="mobile")
        self.assertEqual(self.get_report(run)["slowest_steps"], [])

    def test_report_without_representative_attempt(self):
        run = self.insert_run(self.make_task())
        self.add_step(self.add_attempt(run, 1, end_reason="gave_up", success=False), 0, fitts_id=1.0)
        body = self.get_report(run)
        self.assertEqual((body["top_fitts_steps"], body["slowest_steps"]), ([], []))

    def test_report_409_unless_completed(self):
        # openapi NotFinished: queued·running(진행 중), failed·canceled(리포트 안 만듦)
        for status in ("queued", "running", "failed", "canceled"):
            with self.subTest(status=status):
                r = self.call("GET", f"/runs/{self.insert_run(self.make_task(), status=status)}/report")
                self.assertEqual(r.status_code, 409)
                self.assertEqual(schema_errors(r.json(), "/runs/{id}/report", "get", "409"), [])

    def test_report_404(self):
        r = self.call("GET", f"/runs/{self.insert_run(self.make_task('code-b'))}/report")
        self.assertEqual(r.status_code, 404)

    # --- GET /runs/{id}/attempts/{n}/steps (+ /{idx}) ---

    def add_snapshot(self, step_id: int, data: dict) -> None:
        from apps.api.db.models import ElementSnapshot

        with self.main.SessionLocal.begin() as db:
            db.add(ElementSnapshot(
                step_id=step_id, data=data, bbox=data["bbox"], style=data["style"], bg_chain=data["bg_chain"],
                occluded=data["occluded"], in_first_view=data["in_first_view"], name=data["name"], role=data["role"],
            ))

    def make_steps_run(self) -> int:
        """attempt 1: 목 steps.json 3개를 idx 2, 0, 1 순서로 저장 (정렬 확인). attempt 2: step 1개."""
        run = self.insert_run(self.make_task(), status="running")
        a1, a2 = self.add_attempt(run, 1), self.add_attempt(run, 2)
        for idx in (2, 0, 1):
            sid = self.add_step(a1, idx, f"s{idx}.png" if idx != 1 else None, fitts_id=1.5 if idx == 0 else None)
            if MOCK_STEPS[idx]["element_snapshot"] is not None:
                self.add_snapshot(sid, MOCK_STEPS[idx]["element_snapshot"])
        self.add_step(a2, 0)
        return run

    def test_list_steps(self):
        run = self.make_steps_run()
        r = self.call("GET", f"/runs/{run}/attempts/1/steps")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(schema_errors(body, "/runs/{id}/attempts/{n}/steps", "get", "200"), [])
        self.assertEqual([s["idx"] for s in body], [0, 1, 2])  # idx 오름차순, attempt 1만
        for s in body:
            mock_step = MOCK_STEPS[s["idx"]]
            self.assertEqual((s["action"], s["element_snapshot"]), (mock_step["action"], mock_step["element_snapshot"]))
        self.assertTrue(body[0]["screenshot_url"].endswith("/screenshots/s0.png"))
        self.assertIsNone(body[1]["screenshot_url"])
        self.assertEqual((body[0]["fitts_id"], body[2]["fitts_id"]), (1.5, None))
        self.assertIsNone(body[2]["element_snapshot"])  # done 행동은 스냅샷 없음

    def test_get_one_step(self):
        run = self.make_steps_run()
        r = self.call("GET", f"/runs/{run}/attempts/1/steps/1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(schema_errors(r.json(), "/runs/{id}/attempts/{n}/steps/{idx}", "get", "200"), [])
        self.assertEqual(r.json()["action"], MOCK_STEPS[1]["action"])

    def test_steps_404(self):
        run = self.make_steps_run()
        other = self.insert_run(self.make_task("code-b"))
        self.add_step(self.add_attempt(other, 1), 0)
        cases = [
            (f"/runs/{other}/attempts/1/steps", "/runs/{id}/attempts/{n}/steps"),  # 다른 코드
            (f"/runs/{run}/attempts/3/steps", "/runs/{id}/attempts/{n}/steps"),  # 없는 attempt
            (f"/runs/{run}/attempts/0/steps", "/runs/{id}/attempts/{n}/steps"),  # attempt.index는 1부터
            (f"/runs/{run}/attempts/1/steps/9", "/runs/{id}/attempts/{n}/steps/{idx}"),  # 없는 단계
            (f"/runs/{other}/attempts/1/steps/0", "/runs/{id}/attempts/{n}/steps/{idx}"),
        ]
        for url, path in cases:
            with self.subTest(url=url):
                r = self.call("GET", url)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(schema_errors(r.json(), path, "get", "404"), [])

    # --- POST /runs/{id}/cancel ---

    def cancel(self, run_id: int, code: str = "code-a"):
        from worker.queue import runs

        with mock.patch.object(runs.Queue, "remove") as remove:  # Redis 없이
            r = self.call("POST", f"/runs/{run_id}/cancel", code)
        return r, remove

    def test_cancel_queued_or_running(self):
        for status in ("queued", "running"):
            with self.subTest(status=status):
                run = self.insert_run(self.make_task(), status=status)
                r, remove = self.cancel(run)
                self.assertEqual(r.status_code, 202)
                body = r.json()
                self.assertEqual(schema_errors(body, "/runs/{id}/cancel", "post", "202"), [])
                self.assertEqual(body["status"], "canceled")
                self.assertIsNotNone(body["finished_at"])
                remove.assert_called_once_with(f"run-{run}")  # 아직 큐에 있으면 지운다
                self.assertEqual(self.get_run(run)["status"], "canceled")  # DB에 저장됨

    def test_cancel_finished_409(self):
        for status in ("completed", "failed", "canceled"):
            with self.subTest(status=status):
                r, remove = self.cancel(self.insert_run(self.make_task(), status=status))
                self.assertEqual(r.status_code, 409)
                self.assertEqual(schema_errors(r.json(), "/runs/{id}/cancel", "post", "409"), [])
                remove.assert_not_called()

    def test_cancel_queue_failure_500_keeps_status(self):
        from worker.queue import runs

        run = self.insert_run(self.make_task(), status="queued")
        with mock.patch.object(runs.Queue, "remove", side_effect=ConnectionError("redis down")):
            r = self.call("POST", f"/runs/{run}/cancel")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(schema_errors(r.json(), "/runs/{id}/cancel", "post", "500"), [])
        self.assertEqual(self.get_run(run)["status"], "queued")  # 바뀌지 않음

    def test_cancel_404(self):
        other = self.insert_run(self.make_task("code-b"), status="queued")
        for run in (other, 9999):
            with self.subTest(run=run):
                r, _ = self.cancel(run)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(schema_errors(r.json(), "/runs/{id}/cancel", "post", "404"), [])
        r = self.call("GET", f"/runs/{other}", "code-b")
        self.assertEqual(r.json()["status"], "queued")  # 다른 코드의 run은 그대로


if __name__ == "__main__":
    unittest.main()
