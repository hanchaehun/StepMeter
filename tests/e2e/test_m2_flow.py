"""M2(11/8 "첫 전체 흐름") 합격 기준 E2E 테스트 (개발계획서 14장 W2, 15.3 E2E).

흐름: 프로젝트 생성 → 과업 생성 → POST /tasks/{id}/runs → GET /runs/{id}를 끝날 때까지 폴링
→ GET /runs/{id}/report → GET /runs/{id}/attempts/{n}/steps.
모든 요청·응답은 apps/api/openapi.yaml 스키마로 검사한다(tests/test_openapi_schema.py와 같은 방식).
합격 조건은 tests/e2e/README.md "M2 합격 기준" 5개이고, 조건마다 test_m2_N_ 메서드가 하나씩 있다.

STEPMETER_API_URL이 없으면 M2FlowTests 전체를 건너뛴다. API 서버가 아직 없어 지금 CI에서는 항상 건너뛴다.
FixtureReplyTests는 API 없이 돈다: 가짜 LLM 답 목록이 고정 페이지에서 성공 조건까지 가는지만 확인한다.
실행 방법과 환경 변수는 tests/e2e/README.md.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml
from jsonschema import Draft202012Validator
from playwright.async_api import async_playwright
from pydantic import ValidationError

from tests import test_openapi_schema as openapi_test
from worker.collect.collector import observe, record_first_view
from worker.schemas import ACTION_ADAPTER, ClickAction, DoneAction, ElementSnapshot, TypeAction, parse_action_json

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "e2e"

API_URL = os.environ.get("STEPMETER_API_URL", "").rstrip("/")
ACCESS_CODE = os.environ.get("STEPMETER_ACCESS_CODE", "")
SITE_URL = os.environ.get("STEPMETER_E2E_SITE_URL", "")
TIMEOUT_S = float(os.environ.get("STEPMETER_E2E_TIMEOUT_S", "600"))
LOG_DIR = Path(os.environ.get("STEPMETER_E2E_LOG_DIR", REPO / "screenshots" / "e2e"))  # screenshots/는 git 제외

POLL_S = 2  # 대시보드와 같은 2초 폴링 (openapi.yaml GET /runs/{id})
HTTP_TIMEOUT_S = 30
TERMINAL = {"completed", "failed", "canceled"}  # openapi.yaml RunStatus 중 끝난 상태

# M2는 데스크톱 첫 측정이다. 새 과업이라 재생할 기준 run이 없으므로 mode=agent (openapi.yaml RunMode).
# model은 API가 받는 두 값 중 기본값이다(ADR 0002). 가짜 LLM을 쓸지는 워커 설정이 정한다(README "가짜 LLM").
RUN_REQUEST = {"viewport": "desktop", "repeat_n": 3, "model": "claude-haiku-5-5", "mode": "agent"}


@dataclass(frozen=True)
class E2EPage:
    """측정할 페이지 하나."""

    id: str  # 결과·로그 이름. 고정 HTML이면 tests/fixtures/e2e/{id}/ 폴더 이름
    path: str  # 사이트 주소 뒤에 붙는 경로. 합친 주소가 project.base_url(워커가 처음 여는 주소)이 된다
    task: dict[str, Any]  # POST /projects/{id}/tasks 본문 (TaskCreate)
    site_env: str | None = None  # None이면 고정 HTML 사이트. 벤치마크 앱이면 그 앱 주소를 담은 환경 변수 이름


PAGES = [
    E2EPage(
        id="signup",
        path="signup/index.html",
        task={
            "description": "이름을 입력하고 스터디 모임 참가 신청을 마친다",
            "success_condition": {"url_contains": "/done.html"},
        },
    ),
    # 벤치마크 페이지 3개로 늘릴 자리 (개발계획서 15.3). benchmark/apps.json의 split=development 앱만 쓴다.
    # 홀드아웃 앱은 11/30–12/1 최종 평가 전에는 돌리지 않는다 (ADR 0003, ADR 0008). 앱 주소를 환경 변수로 받고, 없으면 그 페이지만 건너뛴다.
    # E2EPage(
    #     id="<앱 id>-<과업>",
    #     path="<앱 안 경로>",
    #     task={"description": "<benchmark/apps.json tasks 중 하나>", "success_condition": {...}},
    #     site_env="STEPMETER_E2E_<앱>_URL",
    # ),
]


def load_replies(page_id: str) -> list[dict[str, Any]]:
    """가짜 LLM 답 목록 (README "가짜 LLM"의 제안 형식: 행동 JSON 객체 배열)."""
    return json.loads((FIXTURES / page_id / "fake_replies.json").read_text(encoding="utf-8"))


# --- API 호출과 스키마 검사 ---


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, access_code: str):
        self.base_url = base_url
        self.access_code = access_code

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"X-Access-Code": self.access_code, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:500]
            raise ApiError(f"{method} {path} → {e.code} {text}") from None


class Spec:
    """openapi.yaml. 본문 스키마는 tests/test_openapi_schema.py의 body_schema를 그대로 쓴다."""

    def __init__(self):
        self.spec = yaml.safe_load(openapi_test.SPEC_PATH.read_text(encoding="utf-8"))

    def errors(self, data: Any, path: str, method: str, status: str) -> list[str]:
        body = openapi_test.OpenApiSchemaTests.body_schema(self, path, method, status)
        schema = {**body, "components": self.spec["components"]}
        return [
            f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in Draft202012Validator(schema).iter_errors(data)
        ]


@dataclass
class FlowResult:
    page: E2EPage
    url: str
    project: dict | None = None
    task: dict | None = None
    run: dict | None = None  # POST /tasks/{id}/runs 응답
    final: dict | None = None  # 마지막 GET /runs/{id} 응답
    timeline: list[list] = field(default_factory=list)  # [status, progress]가 바뀔 때마다 한 줄
    report: dict | None = None
    steps: dict[int, list] = field(default_factory=dict)  # attempt.index → steps API 응답
    schema_errors: dict[str, list[str]] = field(default_factory=dict)  # "GET /runs/{id} 200" → 오류 목록
    error: str | None = None  # 흐름이 끝까지 못 간 이유
    skipped: str | None = None

    def summary(self) -> str:
        attempts = (self.report or {}).get("attempts") or []
        reasons = [(a.get("index"), a.get("end_reason"), a.get("end_detail")) for a in attempts]
        return f"error={self.error} timeline={self.timeline} attempts={reasons}"


class Flow:
    def __init__(self, api: ApiClient, spec: Spec, result: FlowResult):
        self.api, self.spec, self.result = api, spec, result

    def check(self, label: str, data: Any, path: str, method: str, status: str) -> None:
        errors = self.spec.errors(data, path, method, status)
        if errors:
            bucket = self.result.schema_errors.setdefault(label, [])
            bucket.extend(e for e in errors if e not in bucket)  # 폴링마다 같은 오류가 쌓이지 않게

    def call(self, method: str, path: str, status: str, body: Any = None, **ids: int) -> Any:
        if body is not None:
            self.check(f"{method} {path} 요청", body, path, method.lower(), "request")
        got, data = self.api.request(method, path.format(**ids), body)
        if str(got) != status:
            raise ApiError(f"{method} {path.format(**ids)} → {got}, 기대 {status}")
        self.check(f"{method} {path} {status}", data, path, method.lower(), status)
        return data

    def run(self) -> None:
        r, page = self.result, self.result.page
        stamp = time.strftime("%Y%m%d-%H%M%S")
        r.project = self.call("POST", "/projects", "201", {"name": f"E2E M2 {page.id} {stamp}", "base_url": r.url})
        r.task = self.call("POST", "/projects/{id}/tasks", "201", page.task, id=r.project["id"])
        r.run = self.call("POST", "/tasks/{id}/runs", "202", RUN_REQUEST, id=r.task["id"])
        run_id = r.run["id"]

        deadline = time.monotonic() + TIMEOUT_S
        while True:
            r.final = self.call("GET", "/runs/{id}", "200", id=run_id)
            point = [r.final["status"], r.final["progress"]]
            if not r.timeline or r.timeline[-1] != point:
                r.timeline.append(point)
            if r.final["status"] in TERMINAL:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"run {run_id}가 {TIMEOUT_S:.0f}초 안에 끝나지 않음")
            time.sleep(POLL_S)

        r.report = self.call("GET", "/runs/{id}/report", "200", id=run_id)
        for attempt in r.report["attempts"]:
            n = attempt["index"]
            r.steps[n] = self.call("GET", "/runs/{id}/attempts/{n}/steps", "200", id=run_id, n=n)
            for step in r.steps[n]:
                self.check_worker_models(step)

    def check_worker_models(self, step: dict) -> None:
        # JSON Schema로 못 거르는 동결 모델 규칙까지 (test_openapi_schema.test_step_mock_passes_worker_models와 같음)
        try:
            ACTION_ADAPTER.validate_python(step["action"])
            if step.get("element_snapshot") is not None:
                ElementSnapshot.model_validate(step["element_snapshot"])
        except (KeyError, ValidationError) as e:
            label = "steps의 worker/schemas.py 모델"
            self.result.schema_errors.setdefault(label, []).append(f"idx={step.get('idx')}: {e}")


def run_flow(api: ApiClient, spec: Spec, page: E2EPage, url: str) -> FlowResult:
    result = FlowResult(page=page, url=url)
    try:
        Flow(api, spec, result).run()
    except Exception as e:  # 흐름이 끊겨도 조건별 테스트가 어디까지 됐는지 보여주게 한다
        result.error = f"{type(e).__name__}: {e}"
    return result


def write_log(result: FlowResult) -> None:
    """에이전트 실행 기록 (AGENTS.md "실행 로그를 남긴다"). 초대 코드는 넣지 않는다."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"m2_{result.page.id}.json"
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # 테스트 출력에 접속 기록을 남기지 않는다
        pass


# --- 테스트 ---


@unittest.skipUnless(API_URL, "STEPMETER_API_URL 없음: API 서버가 생기기 전에는 건너뛴다 (tests/e2e/README.md)")
class M2FlowTests(unittest.TestCase):
    """페이지마다 흐름을 한 번 돌리고(setUpClass), 합격 조건을 하나씩 확인한다."""

    results: list[FlowResult]

    @classmethod
    def setUpClass(cls):
        if not ACCESS_CODE:
            raise RuntimeError("STEPMETER_ACCESS_CODE 없음: STEPMETER_API_URL을 줬으면 초대 코드도 줘야 한다")
        api, spec = ApiClient(API_URL, ACCESS_CODE), Spec()
        fixture_site = SITE_URL or cls.serve_fixtures()
        cls.results = []
        for page in PAGES:
            site = os.environ.get(page.site_env, "") if page.site_env else fixture_site
            if not site:
                cls.results.append(FlowResult(page=page, url="", skipped=f"{page.site_env} 없음"))
                continue
            result = run_flow(api, spec, page, urljoin(site.rstrip("/") + "/", page.path))
            write_log(result)
            cls.results.append(result)

    @classmethod
    def serve_fixtures(cls) -> str:
        """tests/fixtures/e2e/를 127.0.0.1의 빈 포트로 띄운다. 워커가 같은 컴퓨터에서 돌 때만 닿는다."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(FIXTURES)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(server.shutdown)
        host, port = server.server_address[:2]
        return f"http://{host}:{port}/"

    def for_each_page(self, check) -> None:
        for r in self.results:
            with self.subTest(page=r.page.id):
                if r.skipped:
                    self.skipTest(r.skipped)
                check(r)

    def report_of(self, r: FlowResult) -> dict:
        self.assertIsNotNone(r.report, f"리포트를 받지 못함: {r.summary()}")
        return r.report

    # 합격 조건 1~5 (README "M2 합격 기준")

    def test_m2_1_run_completed(self):
        def check(r):
            self.assertIsNotNone(r.final, f"run 상태를 받지 못함: {r.summary()}")
            self.assertEqual(r.final["status"], "completed", r.summary())

        self.for_each_page(check)

    # 리포트 칸이 빠져도 KeyError가 아니라 조건 실패로 보이게 .get을 쓴다 (칸 누락 자체는 조건 5가 잡는다)

    def test_m2_2_has_attempt(self):
        self.for_each_page(lambda r: self.assertGreaterEqual(len(self.report_of(r).get("attempts", [])), 1, r.summary()))

    def test_m2_3_has_step(self):
        def check(r):
            counted = sum(a.get("steps_count", 0) for a in self.report_of(r).get("attempts", []))
            stored = sum(len(steps) for steps in r.steps.values())
            self.assertGreaterEqual(counted, 1, f"리포트 attempts의 steps_count 합이 0: {r.summary()}")
            self.assertGreaterEqual(stored, 1, f"steps API로 받은 step이 0개: {r.summary()}")

        self.for_each_page(check)

    def test_m2_4_has_metric(self):
        self.for_each_page(lambda r: self.assertGreaterEqual(len(self.report_of(r).get("metrics", [])), 1, r.summary()))

    def test_m2_5_report_matches_schema(self):
        def check(r):
            self.report_of(r)
            self.assertEqual(r.schema_errors.get("GET /runs/{id}/report 200", []), [])

        self.for_each_page(check)

    # 보조 확인: 어디서 막혔는지 바로 보이게

    def test_flow_finished_without_error(self):
        self.for_each_page(lambda r: self.assertIsNone(r.error))

    def test_all_requests_and_responses_match_schema(self):
        self.for_each_page(lambda r: self.assertEqual(r.schema_errors, {}))


class FixtureReplyTests(unittest.IsolatedAsyncioTestCase):
    """가짜 LLM 답 목록이 고정 페이지에서 과업 성공 조건까지 가는지 확인한다 (API·워커 없이).

    target 번호는 signup/index.html을 사람이 읽고 정했다. 상호작용 요소는 문서 순서로
    입력칸 "이름"(label for) 1번, 버튼 "신청" 2번뿐이다 (worker/collect: el_id는 1부터 문서 순서).
    실행 전 `npm run build:collect` 필요.
    """

    async def test_signup_replies_reach_success_condition(self):
        page_def = next(p for p in PAGES if p.id == "signup")
        replies = [parse_action_json(json.dumps(r, ensure_ascii=False)) for r in load_replies("signup")]
        self.assertIsInstance(replies[-1], DoneAction)
        self.assertEqual(replies[-1].reason, "goal_reached")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})  # desktop (ViewportPreset)
                await page.goto((FIXTURES / page_def.path).as_uri())
                await record_first_view(page)
                items = {i["el_id"]: i for i in await observe(page)}
                self.assertEqual({k: v["name"] for k, v in items.items()}, {1: "이름", 2: "신청"})

                for action in replies[:-1]:
                    self.assertIsInstance(action, (TypeAction, ClickAction))
                    item = items[action.target]
                    target = page.get_by_role(item["role"], name=item["name"], exact=True)
                    if isinstance(action, TypeAction):
                        await target.fill(action.text)
                    else:
                        await target.click()

                url_part = page_def.task["success_condition"]["url_contains"]
                await page.wait_for_url(re.compile(re.escape(url_part)), timeout=5000)
            finally:
                await browser.close()


if __name__ == "__main__":
    unittest.main()
