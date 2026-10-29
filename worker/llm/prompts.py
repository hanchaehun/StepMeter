"""prompts/ 폴더의 프롬프트 파일을 읽는다 (개발계획서 4.4: 버전 번호를 붙여 파일로 둔다)."""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(version: str) -> str:
    """예: load_prompt("action_v1") → prompts/action_v1.md 내용.

    LLMRequest.prompt_version에는 같은 version 글자를 넣어 기록에 남긴다.
    """

    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
