# StepMeter 워커 ↔ API 인터페이스

개발계획서 13.1 "워커 ↔ 플랫폼 백엔드: 큐 작업 페이로드, 진행률 갱신 방식, DB 쓰기 경계"의 내용. 계획서에는 항목 이름만 있어서 플랫폼 백엔드가 정했다.

- 괄호 속 숫자 = 개발계획서 장·절, F00 = 서비스기획서 기능
- 큐는 워커에 `run_id`만 넘긴다. 진행률을 포함한 모든 데이터 쓰기·읽기는 DB로 한다.
  개발계획서 2.1·그림 1("작업 큐: 진행률 저장")과 다르고, 10장(`run.progress`)을 따른다.

## 1. 큐 작업 페이로드 (2.2, 3장 Redis + RQ)

| 항목 | 정한 것 |
|---|---|
| 큐에 넣는 값 | `run_id`만. 큐 이름 `runs`, 작업 id `run-{run_id}` |
| 측정 설정 | 워커가 `run_id`로 DB를 직접 조회한다 (그림 1: 큐는 작업 전달만) |
| 설정 필드 | base_url(project), task·success_condition(task), viewport·mode·repeat_n·model(run), 재생 경로 |
| 재생 경로 | 기준 run(`run.base_run_id`)의 대표 경로 attempt(`representative_attempt_id`)의 step 목록. 행동 + 요소 지문 (7.2) |
| 실행 중 취소 | API가 RQ 중지 명령을 보내고, 워커가 멈춘 뒤 `run.status=canceled`, `finished_at` 기록. 대기 중(`queued`)이면 API가 큐에서 지우고 바로 `canceled` |
| 제한 시간 | 30분 (1회 약 5분, 3회 병렬, 4.6). 넘으면 `run.status=failed` |

## 2. 진행률 갱신 방식 (2.1, 2.2, F02: 대시보드 2초 폴링)

| 항목 | 정한 것 |
|---|---|
| 저장 위치 | DB `run.progress`. API는 `GET /runs/{id}`에서 이 값을 읽어 돌려준다 |
| 갱신 방법 | 워커가 step 행을 추가한 트랜잭션 안에서 플랫폼 백엔드가 제공하는 `update_progress(session, run_id)`를 부른다. 이 함수가 그 run의 step 행을 모아 진행률을 다시 계산하고 한 문장으로 저장한다 (병렬 실행이 동시에 불러도 값이 틀어지지 않게) |
| 계산식 | `floor(90 × (끝난 attempt 수 + Σ 진행 중 attempt의 step 행 수 ÷ 30) ÷ 예정 attempt 수)`. 후처리(지표·규칙·설명)까지 끝나면 100. 이전 값보다 작아지지 않는다 |
| 최근 step | 가장 최근에 저장된 step 행 (openapi.yaml `RunProgress.latest_step`, F02 "현재 스크린샷, 에이전트의 최근 판단 한 줄") |
| 상태 기록 | `queued`는 API가 run을 만들 때. `running`(작업을 꺼낼 때, `started_at`), `completed`·`failed`(끝날 때, `finished_at`)는 워커 |

- 30 = 실행 1회의 step 상한 (4.5)
- 예정 attempt 수: auto 모드에서 재생 뒤 에이전트를 몇 번 돌리는지에 따라 바뀐다
- 에이전트가 과업에 실패하거나 사이트가 막은 경우는 `completed`, 사유는 `attempt.end_reason` (openapi.yaml RunStatus)

## 3. DB 쓰기 경계 (2.2, 10장)

| 항목 | 정한 것 |
|---|---|
| 쓰는 방식 | 각 역할 모듈이 자기 테이블에 직접 쓴다 (그림 1: 워커에서 직접 "저장"). 스키마와 마이그레이션은 플랫폼 백엔드가 관리한다 (`apps/api/db/models.py`) |
| step·element_snapshot 저장 시점 | 행동 하나가 끝날 때마다 바로 저장한다 (2번 묶음 진행률·최근 step의 재료) |
| 스크린샷 | 플랫폼 백엔드가 `save_screenshot(bytes) -> key`를 제공한다. 워커가 불러 받은 키를 `step.screenshot_key`에 기록한다. 저장소는 로컬 디스크, 스테이징·운영은 R2 (3장, 13장) |

### 테이블별 쓰는 역할

| 역할 | 테이블 |
|---|---|
| 에이전트 코어 | attempt, step, element_snapshot |
| 측정 지표·규칙 | metric, issue |
| LLM·프롬프트 | llm_call |
| API (플랫폼 백엔드) | project, task, run 생성·취소, comparison, element_alias, issue_label, human_session, human_event |
| 워커 (상태 기록) | run의 status, started_at, finished_at, prompt_version, cost_usd, representative_attempt_id, progress(`update_progress`로) |
| 관리자 스크립트 | access_code |
| ml 스크립트 | model_version |
