# tests/e2e/

- **담당 역할:** PM (통합·QA)
- **하는 일:** 측정 전체 흐름 E2E 테스트 (벤치마크 페이지 3개로 요청→리포트).
- **참고:** 개발계획서 14장 W2 "데스크톱 전체 흐름(API·큐·DB 연결)", 15.3

## M2 합격 기준 (11/8 "첫 전체 흐름")

`test_m2_flow.py`가 고정 페이지마다 아래 흐름을 한 번 돌리고 조건을 하나씩 확인한다.

프로젝트 생성 → 과업 생성 → `POST /tasks/{id}/runs` → `GET /runs/{id}`를 끝날 때까지 2초마다 폴링 → `GET /runs/{id}/report` → `GET /runs/{id}/attempts/{n}/steps`

| # | 조건 | 테스트 | 확인하는 값 |
|---|---|---|---|
| 1 | run이 `completed`로 끝난다 | `test_m2_1_run_completed` | 마지막 `GET /runs/{id}`의 `status` |
| 2 | attempt가 1개 이상 | `test_m2_2_has_attempt` | `report.attempts` 길이 |
| 3 | step이 1개 이상 | `test_m2_3_has_step` | `report.attempts[].steps_count` 합, steps API로 받은 step 수 |
| 4 | 지표(metric)가 1개 이상 | `test_m2_4_has_metric` | `report.metrics` 길이 |
| 5 | 리포트 응답이 스키마를 통과한다 | `test_m2_5_report_matches_schema` | `GET /runs/{id}/report` 200 응답 ↔ `apps/api/openapi.yaml` `Report` |

보조 확인(합격 조건은 아니지만 어디서 막혔는지 보여 준다):

- `test_flow_finished_without_error`: 흐름이 중간에 끊기지 않았다 (HTTP 오류, 시간 초과).
- `test_all_requests_and_responses_match_schema`: 보낸 요청 본문과 받은 응답 전부가 openapi.yaml을 통과하고, step의 `action`·`element_snapshot`이 `worker/schemas.py` 모델을 통과한다.
- `FixtureReplyTests`: 가짜 LLM 답 목록(`tests/fixtures/e2e/signup/fake_replies.json`)을 Playwright로 직접 따라 하면 과업 성공 조건(`url_contains: /done.html`)까지 간다. API 없이 돌아서 CI에서도 실행된다. 수집 JS가 요소 번호 매기는 방식을 바꾸면 여기서 먼저 깨진다.

스키마 검사는 `tests/test_openapi_schema.py`의 `body_schema`와 `Draft202012Validator`를 그대로 쓴다. 그 테스트처럼 `format`(date-time, uri)은 검사하지 않는다.

## 지금 상태 (11/2)

API 서버가 없어서 `STEPMETER_API_URL`을 주지 않으면 `M2FlowTests`는 전부 건너뛴다(CI도 같다). `FixtureReplyTests`만 돈다.
흐름 코드는 목 JSON(`tests/fixtures/mock/api/`)을 돌려주는 임시 서버로만 확인했다. 실제 API·워커로는 아직 돌려 보지 않았다.

## 실행 방법

### 지금 (API 없음)

```sh
python -m unittest tests.e2e.test_m2_flow -v     # FixtureReplyTests만 돌고 M2FlowTests는 skip
```

### API·워커가 생긴 뒤

1. DB·Redis를 띄우고 마이그레이션한다 ([infra/README.md](../../infra/README.md) "Docker").
   ```sh
   docker compose up -d --build --wait db redis
   docker compose run --rm migrate
   ```
2. API 서버와 워커를 띄운다. 워커는 **가짜 LLM 설정**으로 띄운다(아래 "가짜 LLM"). compose에 `api`·`worker` 서비스가 아직 없어 명령은 플랫폼 백엔드가 정하면 여기에 적는다.
3. 초대 코드를 하나 발급한다(관리자 스크립트, 아직 없음).
4. 테스트를 실행한다.
   ```sh
   export STEPMETER_API_URL=http://127.0.0.1:8000     # 예시. API 서버 주소 (경로 앞부분이 있으면 포함)
   export STEPMETER_ACCESS_CODE=<발급한 초대 코드>
   python -m unittest tests.e2e.test_m2_flow -v
   ```
   PowerShell은 `$env:STEPMETER_API_URL="http://127.0.0.1:8000"`처럼 준다.

| 환경 변수 | 필수 | 뜻 |
|---|---|---|
| `STEPMETER_API_URL` | 예 | API 서버 주소. 없으면 `M2FlowTests` 전체를 건너뛴다 |
| `STEPMETER_ACCESS_CODE` | 예 | `X-Access-Code` 헤더 값. API 주소를 줬는데 없으면 skip이 아니라 오류로 멈춘다(합격 기준이 조용히 건너뛰어지지 않게) |
| `STEPMETER_E2E_SITE_URL` | 아니오 | 워커가 `tests/fixtures/e2e/`를 열 수 있는 주소. 없으면 테스트가 `127.0.0.1`의 빈 포트에 직접 띄운다 |
| `STEPMETER_E2E_TIMEOUT_S` | 아니오 | run이 끝나기를 기다리는 최대 시간(초). 기본 600 |
| `STEPMETER_E2E_LOG_DIR` | 아니오 | 실행 기록 JSON 위치. 기본 `screenshots/e2e/`(git 제외). 파일은 `m2_{페이지}.json`이고 초대 코드는 넣지 않는다 |

**워커가 Docker 안에서 돌면** 테스트가 띄운 `127.0.0.1` 페이지에 닿지 않는다. 이때는 페이지를 따로 띄우고 워커가 닿는 주소를 준다.

```sh
python -m http.server 8765 --directory tests/fixtures/e2e
export STEPMETER_E2E_SITE_URL=http://host.docker.internal:8765/   # Linux는 compose에 extra_hosts host-gateway 필요
```

요청하는 값(`test_m2_flow.py` `RUN_REQUEST`): `viewport=desktop`, `repeat_n=3`, `model=claude-haiku-5-5`, `mode=agent`. 새 과업이라 재생할 기준 run이 없으므로 `auto` 대신 `agent`를 쓴다.

## 가짜 LLM으로 돌리기 (에이전트 코어·LLM 담당에게 요청)

크레딧 없이 E2E를 돌리려면 워커가 Claude 대신 `worker/llm/fake.py`의 `FakeAdapter`를 미리 정한 답 목록으로 써야 한다.
지금은 `FakeAdapter(replies)`만 있고, 워커(에이전트 루프)가 어떤 어댑터를 쓸지 고르는 설정은 없다. 아래는 E2E 쪽에서 필요한 것을 적은 제안이고, 이름과 형식은 담당이 정한다.

| 항목 | 제안 |
|---|---|
| 어댑터 고르기 | 워커 환경 변수 `STEPMETER_LLM=fake`. 없으면 지금처럼 Claude. `run.model`은 그대로 둔다. API는 `claude-haiku-5-5`, `claude-sonnet-5-5`만 받으므로(ADR 0002) "fake"는 run 값이 아니라 워커 설정이어야 한다 |
| 답 목록 위치 | 워커 환경 변수 `STEPMETER_FAKE_REPLIES=<파일 경로>`. E2E 첫 파일은 `tests/fixtures/e2e/signup/fake_replies.json` |
| 답 목록 형식 | `worker/schemas.py` 행동 JSON 객체의 배열. 워커는 각 객체를 `json.dumps`해서 `FakeAdapter(replies)`에 넘긴다 |
| attempt마다 처음부터 | `repeat_n=3` 반복(병렬일 수 있음)이 어댑터 하나를 같이 쓰면 답 순서가 섞인다. attempt마다 새 `FakeAdapter`를 만들거나 답 위치를 attempt별로 따로 센다 |
| 요소 번호 | 답의 `target`은 LLM에 보낸 요소 목록 번호다. `fake_replies.json`은 수집 JS `observe()`의 `el_id`(1부터 문서 순서)와 같다고 보고 썼다. 에이전트 코어가 가림 제외·30개 자르기 뒤 번호를 다시 매기면 규칙을 알려 준다(고정 페이지는 요소 2개, 가림 없음이라 지금은 같을 것으로 본다) |
| `explain` 호출 | 문제 설명 생성(W3)이 가짜 모드에서도 불리면 고정 문장 하나를 돌려준다. `Issue.explanation`은 필수 문자열이다 |
| 비용·키 | 가짜 모드에서는 `ANTHROPIC_API_KEY` 없이 시작해야 한다. `llm_call.model`은 `fake`, `cost_usd`는 0으로 남는다(`FakeAdapter` 그대로) |
| 운영 차단 | 스테이징·운영 워커에서는 `STEPMETER_LLM=fake`를 켤 수 없게 한다 |

정해지지 않은 것: 페이지 3개를 한 워커로 돌릴 때 run마다 다른 답 목록을 고르는 방법(예: 파일 대신 `{project.base_url: 답 목록}` 묶음). 벤치마크 페이지를 넣을 때 LLM 담당과 정한다.

## 아직 없는 부품과 담당

| 부품 | 담당 | 지금 | E2E에 필요한 것 |
|---|---|---|---|
| API 서버 | 플랫폼 백엔드 | `apps/api/`에 openapi.yaml, DB 모델, 마이그레이션만 있음 | `POST /projects`, `POST /projects/{id}/tasks`, `POST /tasks/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/report`, `GET /runs/{id}/attempts/{n}/steps` |
| 큐(Redis + RQ)·워커 진입점 | 플랫폼 백엔드 | `worker/queue/` README만 | run을 큐에 넣고 꺼내 status를 `running`→`completed`로 기록 (`docs/worker_api_spec.md`) |
| 초대 코드 발급 | 플랫폼 백엔드 (관리자 스크립트) | 없음 | E2E용 코드 1개 |
| compose의 `api`·`worker` 서비스 | 플랫폼 백엔드, 회귀 비교·인프라 | `db`, `redis`, `web`만 있음 | 한 명령으로 띄우기. Docker 워커가 고정 페이지에 닿는 방법(`host.docker.internal` 또는 `tests/fixtures/e2e/`를 서빙하는 서비스) |
| 에이전트 루프 | 에이전트 코어 | `worker/agent/` README만 | attempt·step·element_snapshot 저장, 성공 조건 판정 |
| 드라이버 | 에이전트 코어 | `worker/driver/` README만 | PlaywrightDriver(desktop), 효과 유형 |
| 가짜 LLM 설정 | LLM·프롬프트 (에이전트 코어가 불러 씀) | `FakeAdapter`만 있음 | 위 "가짜 LLM" |
| run 단위 지표 저장 | 측정 지표·규칙 | `worker/metrics/cursor_distance.py`만 | 조건 4: `metric` 행(`attempt_id = null`) 1개 이상. 지표 이름 목록 미정 |

API가 `base_url`을 검사해 사설 주소(`127.0.0.1`, `host.docker.internal`)를 막는다면 개발·E2E 환경에서는 열어 두어야 한다(플랫폼 백엔드).

## 벤치마크 페이지 3개로 늘리기

`test_m2_flow.py`의 `PAGES`에 `E2EPage`를 더한다. 자리는 주석으로 남겨 두었다.

- `benchmark/apps.json`의 `split: development` 앱만 쓴다. 홀드아웃 앱은 11/30–12/1 최종 평가 전에 돌리지 않는다([ADR 0003](../../docs/adr/0003-holdout-private.md), [ADR 0008](../../docs/adr/0008-schedule-to-1204.md)).
- 앱 주소는 `site_env`에 적은 환경 변수로 받는다. 변수가 없으면 그 페이지만 건너뛴다.
- 페이지마다 가짜 LLM 답 목록이 필요하다. 목록과 페이지 버전이 어긋나지 않게 `FixtureReplyTests` 같은 확인을 같이 둔다.

## 파일

- `test_m2_flow.py`: M2 합격 기준 E2E, 가짜 LLM 답 목록 확인
- `../fixtures/e2e/signup/`: 고정 페이지(`index.html` 이름 입력 → `done.html`), 가짜 LLM 답 목록(`fake_replies.json`)

Compose 내부 fixture 서버와 API/worker 실행 준비는 [infra/m2.md](../../infra/m2.md)를 따른다. 실제 API·코어 구현 전에는 M2FlowTests 합격으로 간주하지 않는다.
