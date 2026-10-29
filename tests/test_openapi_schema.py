"""apps/api/openapi.yaml 검사: 개발계획서 11장의 엔드포인트, $ref, worker/schemas.py와의 일치.

worker/schemas.py가 바뀌면 `python -m tests.test_openapi_schema`로 생성 부분을 출력해
openapi.yaml 맨 끝 "worker/schemas.py에서 생성" 아래를 바꿔 넣는다.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from worker.schemas import ACTION_ADAPTER, ElementSnapshot

SPEC_PATH = Path(__file__).resolve().parents[1] / "apps" / "api" / "openapi.yaml"
MOCK_API = Path(__file__).resolve().parent / "fixtures" / "mock" / "api"
REF = "#/components/schemas/{model}"

# 목 JSON → (경로, 메서드, 응답 코드). 응답 코드 대신 "request"면 요청 본문
MOCKS = {
    "project.json": ("/projects", "post", "201"),
    "error_422.json": ("/projects", "post", "422"),
    "projects.json": ("/projects", "get", "200"),
    "task.json": ("/projects/{id}/tasks", "post", "201"),
    "run_queued.json": ("/tasks/{id}/runs", "post", "202"),
    "task_runs.json": ("/tasks/{id}/runs", "get", "200"),
    "run_progress.json": ("/runs/{id}", "get", "200"),
    "report.json": ("/runs/{id}/report", "get", "200"),
    "steps.json": ("/runs/{id}/attempts/{n}/steps", "get", "200"),
    "comparison.json": ("/compare", "get", "200"),
    "run_canceled.json": ("/runs/{id}/cancel", "post", "202"),
    "issue_label.json": ("/issues/{id}/label", "post", "201"),
    "human_session_request.json": ("/human-sessions", "post", "request"),
    "human_session_created.json": ("/human-sessions", "post", "201"),
    "element_alias.json": ("/tasks/{id}/aliases", "post", "201"),
}

# 개발계획서 11장 API 표
PLANNED = {
    ("post", "/projects"),
    ("get", "/projects"),
    ("post", "/projects/{id}/tasks"),
    ("post", "/tasks/{id}/runs"),
    ("get", "/runs/{id}"),
    ("get", "/runs/{id}/report"),
    ("get", "/runs/{id}/attempts/{n}/steps"),
    ("get", "/tasks/{id}/runs"),
    ("get", "/compare"),
    ("post", "/runs/{id}/cancel"),
    ("post", "/issues/{id}/label"),
    ("post", "/human-sessions"),
    ("post", "/tasks/{id}/aliases"),
}


def _drop_titles(node):
    if isinstance(node, dict):
        return {k: _drop_titles(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_drop_titles(v) for v in node]
    return node


def worker_schemas() -> dict:
    out: dict = {}
    for name, schema in (
        ("Action", ACTION_ADAPTER.json_schema(ref_template=REF)),
        ("ElementSnapshot", ElementSnapshot.model_json_schema(ref_template=REF)),
    ):
        out.update(schema.pop("$defs", {}))
        out[name] = schema
    return _drop_titles(out)


def _refs(node):
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            yield node["$ref"]
        for v in node.values():
            yield from _refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v)


class OpenApiSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

    def test_planned_endpoints(self):
        methods = {"get", "post", "put", "patch", "delete"}
        actual = {(m, p) for p, item in self.spec["paths"].items() for m in item if m in methods}
        self.assertEqual(actual, PLANNED)

    def test_refs_resolve(self):
        comps = self.spec["components"]
        for ref in set(_refs(self.spec)):
            _, _, kind, name = ref.split("/")
            self.assertIn(name, comps[kind], ref)

    def test_worker_schemas_match(self):
        schemas = self.spec["components"]["schemas"]
        for name, schema in worker_schemas().items():
            self.assertEqual(schemas.get(name), schema, f"{name}가 worker/schemas.py와 다름")

    def body_schema(self, path, method, status):
        op = self.spec["paths"][path][method]
        node = op["requestBody"] if status == "request" else op["responses"][status]
        if "$ref" in node:
            node = self.spec["components"]["responses"][node["$ref"].rsplit("/", 1)[1]]
        return node["content"]["application/json"]["schema"]

    def test_mocks_match_spec(self):
        self.assertEqual({p.name for p in MOCK_API.glob("*.json")}, set(MOCKS), "목 파일 목록과 MOCKS가 다름")
        for name, target in MOCKS.items():
            with self.subTest(mock=name):
                schema = {**self.body_schema(*target), "components": self.spec["components"]}
                data = json.loads((MOCK_API / name).read_text(encoding="utf-8"))
                errors = [e.message for e in Draft202012Validator(schema).iter_errors(data)]
                self.assertEqual(errors, [])

    def test_step_mock_passes_worker_models(self):
        # JSON Schema로는 못 거르는 동결 모델 규칙(occluder·첫 화면 일관성 등)까지 확인
        for step in json.loads((MOCK_API / "steps.json").read_text(encoding="utf-8")):
            ACTION_ADAPTER.validate_python(step["action"])
            if step["element_snapshot"] is not None:
                ElementSnapshot.model_validate(step["element_snapshot"])


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    text = yaml.safe_dump(worker_schemas(), allow_unicode=True, sort_keys=False, width=100)
    print("".join("    " + line if line.strip() else line for line in text.splitlines(True)), end="")
