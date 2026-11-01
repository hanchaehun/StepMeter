# worker/llm/

- **담당 역할:** LLM·프롬프트
- **하는 일:** 모델 어댑터(Claude), LLM 호출·비용 기록(llm_call). 모델은 `claude-haiku-5-5`(개발·반복)와 `claude-sonnet-5-5`(결과를 내는 측정)만 쓴다(`claude.py`의 `ALLOWED_MODELS`, [ADR 0002](../../docs/adr/0002-llm-models.md)). `gemini.py`는 구현이 없는 자리다.
- **참고:** 개발계획서 3장, 16장
