# worker/llm/

- **담당 역할:** LLM·프롬프트
- **하는 일:** 모델 어댑터(Claude), LLM 호출·비용 기록(llm_call). 모델은 `claude-haiku-5-5`(개발·반복)와 `claude-sonnet-5-5`(결과를 내는 측정)만 쓴다(`claude.py`의 `ALLOWED_MODELS`, [ADR 0002](../../docs/adr/0002-llm-models.md)). `gemini.py`는 구현이 없는 자리다.
- **참고:** 개발계획서 3장, 16장

## 어댑터 고르기 (가짜 LLM 모드)

워커는 attempt마다 `make_adapter(run.model)`을 한 번 불러 어댑터를 받는다(`select.py`). 크레딧 없이 E2E를 돌릴 때는 워커 환경 변수로 가짜 어댑터를 고른다([tests/e2e/README.md](../../tests/e2e/README.md) "가짜 LLM으로 돌리기").

| 환경 변수 | 값 | 뜻 |
|---|---|---|
| `STEPMETER_LLM` | `fake` / 없음·`claude` | 가짜 어댑터 / Claude |
| `STEPMETER_FAKE_REPLIES` | 파일 경로 | 가짜 모드 답 목록. `worker/schemas.py` 행동 JSON 객체의 배열. 시작할 때 전부 스키마로 검사한다 |
| `STEPMETER_ENV` | `staging`, `production` | 이 값이면 가짜 모드를 거절한다. 스테이징·운영 워커에 설정해야 차단이 동작한다 |

- `make_adapter`를 부를 때마다 새 `FakeAdapter`가 생겨 답 목록을 처음부터 돌려준다. 반복 실행끼리 답 순서가 섞이지 않는다.
- 가짜 모드는 `ANTHROPIC_API_KEY` 없이 시작한다. 기록에는 `model=fake`, `cost_usd=0`이 남는다.
- 행동 선택이 아닌 호출(설명 생성 등)에는 고정 문장을 돌려주고, 행동 답 순서는 건드리지 않는다.
