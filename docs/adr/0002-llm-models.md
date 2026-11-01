# 0002. LLM은 Claude Haiku 5.5와 Sonnet 5.5만 쓴다

- **날짜:** 2026-10-29 (PM 결정)
- **근거 기록:** [worker/llm/claude.py](../../worker/llm/claude.py) `ALLOWED_MODELS`, [tests/test_llm_claude.py](../../tests/test_llm_claude.py)

## 배경

개발계획서 3장은 Claude API와 Gemini API를 교체 가능한 어댑터로 두고 모델별 비용·성능을 비교하도록 했다.
16장은 반복 실행이 많은 작업을 소형 모델로 돌리도록 했다.

## 결정

| 모델 | 쓰는 곳 |
|---|---|
| `claude-haiku-5-5` | 개발·반복 실행 (어댑터 기본값) |
| `claude-sonnet-5-5` | 결과를 내는 측정 |

다른 모델 이름은 `ClaudeAdapter`가 거절한다.

## 대안

- Gemini 어댑터 병행 (계획서 3장): 쓰지 않는다. `worker/llm/gemini.py`는 구현이 없는 자리다.
