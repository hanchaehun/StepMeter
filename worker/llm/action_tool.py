"""행동 응답을 받기 위한 도구 정의 (개발계획서 4.3 "구조화 출력").

모델에게 choose_action 도구를 반드시 쓰게 하면, 답이 자유로운 글이 아니라
아래 항목을 가진 JSON 객체로 온다. 최종 검사는 worker/schemas.py의
parse_action_json이 한다. 여기는 모델이 그 형식에 맞게 답하도록 돕는 안내일 뿐이다.
"""

from __future__ import annotations

ACTION_TOOL_NAME = "choose_action"

ACTION_TOOL = {
    "name": ACTION_TOOL_NAME,
    "description": (
        "다음에 할 행동 하나를 고른다. action에 맞는 필드만 넣는다. "
        "click: target / type: target, text / select: target, option / "
        "scroll: direction / done: reason / back, wait, fail: 추가 필드 없음."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "type", "select", "scroll", "back", "wait", "done", "fail"],
            },
            "target": {"type": "integer", "minimum": 1, "description": "요소 번호"},
            "text": {"type": "string", "description": "type일 때 입력할 글자 전체"},
            "option": {"type": "integer", "minimum": 1, "description": "select일 때 옵션 번호"},
            "direction": {"type": "string", "enum": ["up", "down"]},
            "reason": {"type": "string", "enum": ["goal_reached", "safety_stop"]},
            "thought": {"type": "string", "description": "이 행동을 고른 이유"},
            "expectation": {"type": "string", "description": "행동 뒤에 일어날 것으로 기대하는 일"},
            "confusion": {"type": "string", "description": "헷갈린 점. 없으면 넣지 않는다"},
        },
        "required": ["action", "thought", "expectation"],
    },
}
