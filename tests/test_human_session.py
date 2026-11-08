"""사람 데이터 세션 JSON 검증·조립·저장 테스트 (개발계획서 9.1, openapi HumanSessionCreate).

human-study/ 폴더는 하이픈이 있어 모듈로 import할 수 없으므로 파일 경로로 불러온다.
기대값은 tests/fixtures/mock/api/human_session_request.json과 openapi.yaml을 사람이 읽고 정했다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = ROOT / "human-study"
MOCK = ROOT / "tests" / "fixtures" / "mock" / "api" / "human_session_request.json"


def load(name: str):
    modname = f"human_study_{name}"  # 'schema' 같은 일반 이름이 PyPI 패키지·다른 테스트와 겹치지 않게
    spec = importlib.util.spec_from_file_location(modname, HS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


schema = load("schema")


class ValidateSessionTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(MOCK.read_text(encoding="utf-8"))

    def test_mock_request_passes(self):
        self.assertEqual(schema.validate_session(self.data), [])

    def test_extra_event_field_fails(self):
        # HumanEvent는 additionalProperties: false → 글자 같은 다른 칸이 섞이면 422
        self.data["events"][0]["text"] = "a"
        errors = schema.validate_session(self.data)
        self.assertTrue(any("text" in e for e in errors), errors)

    def test_missing_participant_code_fails(self):
        del self.data["participant_code"]
        errors = schema.validate_session(self.data)
        self.assertTrue(any("participant_code" in e for e in errors), errors)

    def test_bad_event_type_fails(self):
        self.data["events"][1]["type"] = "hover"   # enum: move down up click scroll key stable
        self.assertNotEqual(schema.validate_session(self.data), [])

    def test_device_enum(self):
        self.data["device"] = "pen"                 # enum: mouse trackpad touch
        self.assertNotEqual(schema.validate_session(self.data), [])



# ---------------- Task 3: 세션 러너 ----------------
from datetime import datetime, timezone  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "human-study" / "page.html"
session = load("session")


def meta(**over):
    base = dict(participant_code="P01", page_id="sb-admin-2/baseline", device="mouse", daily_computer_hours=6)
    base.update(over)
    return session.SessionMeta(**base)


class BuildSessionTests(unittest.TestCase):
    def test_build_session_validates_and_copies_meta(self):
        events = [
            {"t_ms": 0, "type": "stable", "x": None, "y": None, "target_key": None},
            {"t_ms": 640, "type": "move", "x": 610, "y": 400, "target_key": None},
            {"t_ms": 1291, "type": "click", "x": 420, "y": 272, "target_key": "a|link|러닝화 A||main"},
        ]
        started = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
        data = session.build_session(meta(), events, completed=True, started_at=started)
        self.assertEqual(schema.validate_session(data), [], schema.validate_session(data))
        self.assertEqual(data["participant_code"], "P01")
        self.assertEqual(data["page_id"], "sb-admin-2/baseline")
        self.assertEqual(data["device"], "mouse")
        self.assertEqual(data["viewport"], {"width": 1280, "height": 800})  # 기본 뷰포트 (개발계획서 4.2 desktop)
        self.assertEqual(data["daily_computer_hours"], 6)
        self.assertEqual(data["started_at"], "2026-11-10T06:00:00Z")
        self.assertTrue(data["completed"])
        self.assertEqual(data["events"], events)

    def test_build_session_rejects_bad_device(self):
        with self.assertRaises(ValueError):
            session.build_session(meta(device="pen"), [], completed=False, started_at=datetime.now(timezone.utc))


class RunSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_session_headless_records_click_and_validates(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            await page.mouse.click(160, 120)  # 구매 버튼 중심
            return True

        data = await session.run_session_async(meta(), FIXTURE.as_uri(), headless=True, interact=interact)
        self.assertEqual(schema.validate_session(data), [], schema.validate_session(data))
        self.assertTrue(data["completed"])
        self.assertEqual(data["events"][0]["type"], "stable")
        clicks = [e for e in data["events"] if e["type"] == "click"]
        self.assertEqual(clicks[0]["target_key"], "button|button|구매||main")
        self.assertEqual(data["viewport"], {"width": 1280, "height": 800})

    async def test_events_survive_navigation(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            async with page.expect_navigation():
                await page.click("#next")          # next.html로 전체 이동
            await page.wait_for_timeout(400)      # 새 문서의 stable
            await page.mouse.click(180, 120)      # 다음 페이지 버튼 중심 (100+80, 100+20)
            return True

        data = await session.run_session_async(meta(), FIXTURE.as_uri(), headless=True, interact=interact)
        types = [e["type"] for e in data["events"]]
        self.assertGreaterEqual(types.count("stable"), 2, types)  # 이동 전·후 각각
        keys = [e["target_key"] for e in data["events"] if e["type"] == "click"]
        self.assertIn("a|link|다음 페이지||main", keys)
        self.assertIn("button|button|다음 페이지 버튼||main", keys)
        self.assertTrue(all(isinstance(e["t_ms"], int) for e in data["events"]))
        self.assertEqual(data["events"], sorted(data["events"], key=lambda e: e["t_ms"]))

    async def test_interact_false_marks_incomplete(self):
        async def interact(page):
            return False

        data = await session.run_session_async(meta(), FIXTURE.as_uri(), headless=True, interact=interact)
        self.assertFalse(data["completed"])
        self.assertEqual(schema.validate_session(data), [])


# ---------------- Task 4: 저장·종료·결함 적용·업로드 ----------------
import http.server  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402

BAD_MUTATION = ROOT / "tests" / "fixtures" / "human-study" / "bad-mutation.yaml"
upload = load("upload")


class SaveSessionTests(unittest.TestCase):
    def test_save_filename_has_participant_and_page_without_slash(self):
        data = session.build_session(meta(page_id="shadcn-admin/contrast"), [], completed=True,
                                     started_at=datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as tmp:
            path = session.save_session(data, Path(tmp))
            self.assertEqual(path.parent, Path(tmp))
            self.assertEqual(path.name, "human-session-P01-shadcn-admin-contrast-20261110-060000.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)

    def test_save_refuses_invalid_session(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            session.save_session({"participant_code": "P01"}, Path(tmp))


class SessionEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_mutation_aborts_before_start(self):
        called = False

        async def interact(page):
            nonlocal called
            called = True
            return True

        with self.assertRaises(SystemExit):
            await session.run_session_async(meta(), FIXTURE.as_uri(), mutation=BAD_MUTATION, headless=True, interact=interact)
        self.assertFalse(called)  # 참가자 차례가 오기 전에 멈춘다

    async def test_closed_window_saves_incomplete(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            await page.close()      # 참가자가 창을 닫음
            return True             # 진행자가 완료라고 해도 창이 닫혔으면 미완료

        data = await session.run_session_async(meta(), FIXTURE.as_uri(), headless=True, interact=interact)
        self.assertFalse(data["completed"])
        self.assertEqual(data["events"][0]["type"], "stable")  # 닫기 전 이벤트는 남는다
        self.assertEqual(schema.validate_session(data), [])


class _Handler(http.server.BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _Handler.received.append({"path": self.path, "code": self.headers.get("X-Access-Code"), "body": body})
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": len(_Handler.received)}).encode())

    def log_message(self, *_):
        pass


class UploadTests(unittest.TestCase):
    def setUp(self):
        _Handler.received = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.api = f"http://127.0.0.1:{self.server.server_port}"

    def test_upload_posts_and_marks(self):
        data = json.loads(MOCK.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = session.save_session(data, Path(tmp))
            results = upload.upload_files([path], api=self.api, access_code="secret")
            self.assertEqual(results, [(path, 1)])
            self.assertEqual(_Handler.received[0]["path"], "/human-sessions")
            self.assertEqual(_Handler.received[0]["code"], "secret")
            self.assertEqual(_Handler.received[0]["body"]["participant_code"], "P07")
            self.assertTrue(path.with_suffix(".json.uploaded").exists())
            # 이미 올린 파일은 건너뛴다
            self.assertEqual(upload.upload_files([path], api=self.api, access_code="secret"), [])
            self.assertEqual(len(_Handler.received), 1)


# ---------------- 리뷰 수정 패스 ----------------
import asyncio  # noqa: E402
import functools  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "human-study"


def _serve(directory: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class SessionHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_keeps_only_the_five_fields(self):
        async def interact(page):
            await page.wait_for_timeout(400)
            await page.evaluate("() => window.__hsPush({t_ms: 1, type: 'move', x: 1, y: 2, target_key: null, text: 'secret'})")
            return True

        data = await session.run_session_async(meta(), FIXTURE.as_uri(), headless=True, interact=interact)
        self.assertNotIn("secret", json.dumps(data, ensure_ascii=False))
        self.assertTrue(all(set(e) == {"t_ms", "type", "x", "y", "target_key"} for e in data["events"]))

    async def test_events_outside_start_origin_are_not_recorded(self):
        a, b = _serve(FIXTURE_DIR), _serve(FIXTURE_DIR)
        for srv in (a, b):
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        other = f"http://127.0.0.1:{b.server_port}/next.html"

        async def interact(page):
            await page.wait_for_timeout(400)
            await page.goto(other)                 # 다른 출처(포트)로 이동 = 연구용 페이지 밖
            await page.wait_for_timeout(400)
            await page.mouse.click(180, 120)       # 다음 페이지 버튼
            return True

        data = await session.run_session_async(meta(), f"http://127.0.0.1:{a.server_port}/page.html", headless=True, interact=interact)
        keys = [e["target_key"] for e in data["events"]]
        self.assertNotIn("button|button|다음 페이지 버튼||main", keys)
        self.assertEqual([e for e in data["events"] if e["type"] == "click"], [])

    async def test_partial_file_grows_during_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial = Path(tmp) / "p.partial.jsonl"

            async def interact(page):
                await page.wait_for_timeout(400)
                await page.mouse.click(160, 120)
                await page.wait_for_timeout(100)
                lines = partial.read_text(encoding="utf-8").splitlines()
                self.assertGreaterEqual(len(lines), 4)  # stable + down/up/click: 세션 도중에 이미 디스크에 있다
                return True

            data = await session.run_session_async(meta(), FIXTURE.as_uri(), headless=True, interact=interact, partial_path=partial)
            lines = [json.loads(line) for line in partial.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(lines, data["events"])

    async def test_wait_for_operator_returns_immediately_when_window_closed(self):
        closed = asyncio.Event()
        closed.set()
        result = await asyncio.wait_for(session._wait_for_operator(closed), timeout=2)
        self.assertFalse(result)

    def test_save_invalid_dumps_to_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = session.save_session_or_dump({"participant_code": "P01", "events": []}, Path(tmp), name_hint="P01-x")
            self.assertTrue(path.name.endswith(".invalid.json"))
            self.assertIn("participant_code", json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
