"""워커가 쓸 어댑터를 고른다 (tests/e2e/README.md "가짜 LLM으로 돌리기").

크레딧 없이 E2E를 돌리려면 워커가 Claude 대신 FakeAdapter를 써야 한다.
run.model은 claude-haiku-5-5·claude-sonnet-5-5만 받으므로(ADR 0002) 가짜 모드는
run 값이 아니라 워커 환경 변수로 고른다.

환경 변수
    STEPMETER_LLM            "fake"면 가짜 어댑터, 없거나 "claude"면 ClaudeAdapter
    STEPMETER_FAKE_REPLIES   가짜 모드의 답 목록 JSON 파일 경로 (행동 JSON 객체의 배열)
    STEPMETER_ENV            "staging"·"production"이면 가짜 모드를 거절한다

에이전트 코어는 attempt마다 make_adapter()를 한 번씩 부른다. 가짜 모드에서는 부를 때마다
새 FakeAdapter를 만들어 답 목록을 처음부터 돌려주므로, 반복 실행(repeat_n)끼리 답 순서가 섞이지 않는다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from worker.llm.base import LLMAdapter
from worker.llm.fake import FakeAdapter
from worker.schemas import ActionInputError, parse_action_json

ENV_LLM = "STEPMETER_LLM"
ENV_FAKE_REPLIES = "STEPMETER_FAKE_REPLIES"
ENV_STAGE = "STEPMETER_ENV"
BLOCKED_STAGES = frozenset({"staging", "production"})


class LLMSelectError(RuntimeError):
    """어댑터 설정이 잘못됐을 때. 워커는 측정을 시작하지 않고 멈춘다."""


def make_adapter(model: str, env: Mapping[str, str] | None = None) -> LLMAdapter:
    """run.model과 워커 환경 변수로 어댑터 하나를 만든다."""

    env = os.environ if env is None else env
    mode = env.get(ENV_LLM, "").strip().lower()

    if mode == "fake":
        stage = env.get(ENV_STAGE, "").strip().lower()
        if stage in BLOCKED_STAGES:
            raise LLMSelectError(f"{ENV_STAGE}={stage}에서는 가짜 LLM을 켤 수 없다")
        path = env.get(ENV_FAKE_REPLIES, "").strip()
        if not path:
            raise LLMSelectError(f"{ENV_LLM}=fake에는 {ENV_FAKE_REPLIES}(답 목록 파일)가 필요하다")
        return FakeAdapter(load_fake_replies(Path(path)))

    if mode in ("", "claude"):
        from worker.llm.claude import ClaudeAdapter  # 가짜 모드에서는 anthropic·키 없이 시작하도록 여기서 불러온다

        return ClaudeAdapter(model=model)

    raise LLMSelectError(f"{ENV_LLM}는 fake 또는 claude여야 한다")


def load_fake_replies(path: Path) -> list[str]:
    """답 목록 파일을 읽어 FakeAdapter에 넘길 JSON 글자 목록으로 바꾼다.

    파일은 worker/schemas.py 행동 JSON 객체의 배열이다. 측정을 시작하기 전에
    모든 답을 스키마로 검사해, 틀린 답이 측정 도중에 드러나지 않게 한다.
    """

    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LLMSelectError(f"답 목록 파일이 없다: {path}") from None
    except json.JSONDecodeError:
        raise LLMSelectError(f"답 목록 파일이 JSON이 아니다: {path}") from None
    if not isinstance(items, list) or not items:
        raise LLMSelectError("답 목록은 행동 객체가 하나 이상 든 배열이어야 한다")

    replies = []
    for index, item in enumerate(items, start=1):
        text = json.dumps(item, ensure_ascii=False)
        try:
            parse_action_json(text)
        except ActionInputError as error:
            raise LLMSelectError(f"답 목록 {index}번째가 행동 형식에 맞지 않는다 ({error.code})") from None
        replies.append(text)
    return replies
