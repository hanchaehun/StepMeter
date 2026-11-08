"""사람 데이터 세션 JSON을 apps/api/openapi.yaml의 HumanSessionCreate로 검사한다.

tests/test_openapi_schema.py와 같은 방식: 요청 스키마에 components를 붙여 Draft 2020-12로 검사하고,
format(date-time 등)은 검사하지 않는다. 공용 스키마(openapi.yaml)는 읽기만 한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "apps" / "api" / "openapi.yaml"


def _drop_titles(node):
    if isinstance(node, dict):
        return {k: _drop_titles(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_drop_titles(v) for v in node]
    return node


@lru_cache(maxsize=1)
def human_session_schema() -> dict:
    """POST /human-sessions 요청 본문 스키마 (components 포함)."""
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    body = spec["paths"]["/human-sessions"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    return _drop_titles({**body, "components": spec["components"]})


def validate_session(data: dict) -> list[str]:
    """오류 메시지 목록. 비어 있으면 통과."""
    validator = Draft202012Validator(human_session_schema())
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(data)]
