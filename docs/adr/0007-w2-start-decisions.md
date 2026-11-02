# 0007. W2 시작 전 정리한 결정

- **날짜:** 2026-11-02 (PM 결정)
- **근거 기록:** 아래 표의 "반영한 곳"

## 배경

W1을 마치고 저장소를 점검하니 개발계획서·ADR과 다른 값과 서로 맞지 않는 문서가 남아 있었다. W2를 시작하기 전에 한 번에 정리한다.

## 결정

| # | 결정 | 반영한 곳 |
|---|---|---|
| 1 | LLM에 보내는 요소 목록은 최대 30개다(개발계획서 4.2). 30개로 자르는 코드는 에이전트 코어가 만든다 | `worker/collect/README.md`, `worker/collect/collector.py` 주석 |
| 2 | `run.model`은 `claude-haiku-5-5`, `claude-sonnet-5-5`만 받고 기본값은 `claude-haiku-5-5`다([ADR 0002](0002-llm-models.md)) | `apps/api/openapi.yaml`의 `LlmModel`·`RunCreate`·`Run`, `tests/fixtures/mock/api/`, `apps/web/src/api/types.ts` |
| 3 | 사람 세션 API는 동의서를 받은 참가자 데이터만 받는다. IRB 조건은 지운다([ADR 0001](0001-no-irb.md)) | `apps/api/openapi.yaml`의 `/human-sessions`, `apps/web/src/api/types.ts` |
| 4 | anthropic SDK를 개발 의존성에 넣는다. `worker/llm/claude.py`가 실제 호출 때 불러오는데 의존성에 없었다 | `requirements-dev.in`, `requirements-dev.txt` |
| 5 | 홀드아웃 앱의 결함 주입·정답·최종 평가는 회귀 비교·인프라 담당 혼자 맡는다 | `benchmark/README.md`, [ADR 0003](0003-holdout-private.md) |
| 6 | 동결 날짜는 실제 머지 날짜로 적는다. 행동 스키마·ElementSnapshot은 10/27 동결, OpenAPI·목 JSON은 10/30 동결(계획 10/27) | `README.md`, `apps/api/README.md`, `apps/web/README.md`, `apps/web/src/api/mock.ts`, `docs/wireframes/f06-report.md` |
| 7 | 동의서 본문의 "학부 프로젝트 과제"를 "학회 프로젝트"로 고친다 | `human-study/consent-form.md` |

## 담당 결정 대기

- **진행률(progress) 저장 위치와 계산식 (플랫폼 백엔드, W2 큐 구현 때):** 지금 `docs/worker_api_spec.md` 2절, `apps/api/db/models.py`·`apps/api/db/db-columns.md`의 `run.progress`, `apps/api/openapi.yaml`의 `progress` 설명이 서로 다르다. 정한 뒤 세 문서를 맞춘다. `worker/queue/README.md`와 `apps/api/README.md`에 할 일로 적어 두었다.

## 대안

- 항목마다 ADR을 따로 만든다: 하나하나가 작아 한 파일로 묶었다.
