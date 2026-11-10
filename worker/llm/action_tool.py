"""행동 응답을 받기 위한 도구 정의 (개발계획서 4.3 "구조화 출력").

모델에게 choose_action 도구를 반드시 쓰게 하면, 답이 자유로운 글이 아니라
아래 항목을 가진 JSON 객체로 온다. 최종 검사는 worker/schemas.py의
parse_action_json이 한다. 여기는 모델이 그 형식에 맞게 답하도록 돕는 안내일 뿐이다.

strict: true면 도구 입력이 아래 스키마를 반드시 지킨다. strict 모드는 minimum 같은
숫자 제약을 지원하지 않으므로 넣지 않는다 (양의 정수 검사는 parse_action_json이 한다).

모든 필드를 required로 두어 모델이 행동마다 필요한 필드를 빠뜨리지 못하게 한다.
행동별 필드(target, text, option, direction, reason)와 confusion은 null을 받고, 고른 행동에
쓰지 않는 필드는 null로 둔다. null 허용은 속성 단위 anyOf로 쓴다 ("type": [..., "null"]과
enum을 함께 쓰면 API가 400으로 거절한다, 2026-11-10 확인). action, thought, expectation은 null을 받지 않는다.
null 항목은 claude.extract_text가 빼므로 parse_action_json에는 행동에 맞는 필드만 간다.
"""

from __future__ import annotations

ACTION_TOOL_NAME = "choose_action"

ACTION_TOOL = {
    "name": ACTION_TOOL_NAME,
    "strict": True,
    "description": (
        "다음에 할 행동 하나를 고른다. action에 맞는 필드는 값을 채우고, 다른 행동의 필드는 null로 둔다. "
        "click: target / type: target, text / select: target, option / scroll: direction / "
        "done: reason / back, wait, fail: 모두 null. confusion은 헷갈렸을 때만 채우고 아니면 null."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "type", "select", "scroll", "back", "wait", "done", "fail"],
            },
            "target": {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "요소 번호"},
            "text": {"anyOf": [{"type": "string"}, {"type": "null"}],
                     "description": "type일 때 입력할 글자 전체"},
            "option": {"anyOf": [{"type": "integer"}, {"type": "null"}],
                       "description": "select일 때 옵션 번호"},
            "direction": {"anyOf": [{"type": "string", "enum": ["up", "down"]}, {"type": "null"}]},
            "reason": {"anyOf": [{"type": "string", "enum": ["goal_reached", "safety_stop"]},
                                 {"type": "null"}]},
            "thought": {"type": "string", "description": "이 행동을 고른 이유"},
            "expectation": {"type": "string", "description": "행동 뒤에 일어날 것으로 기대하는 일"},
            "confusion": {"anyOf": [{"type": "string"}, {"type": "null"}],
                          "description": "헷갈린 점. 없으면 null"},
        },
        "required": ["action", "target", "text", "option", "direction", "reason",
                     "thought", "expectation", "confusion"],
        "additionalProperties": False,
    },
}
