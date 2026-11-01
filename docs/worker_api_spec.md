# StepMeter 워커 ↔ API 인터페이스

개발계획서 13.1 "워커 ↔ 플랫폼 백엔드: 큐 작업 페이로드, 진행률 갱신 방식, DB 쓰기 경계"의 내용. 계획서에는 항목 이름만 있어서 플랫폼 백엔드가 정했다.

- 괄호 속 숫자 = 개발계획서 장·절, F00 = 서비스기획서 기능
- 구조는 개발계획서 그림 1을 따른다: 큐는 워커에 작업을 넘기고 진행 상태를 담는다. DB 저장은 워커에서 한다.

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
| 저장 위치 | Redis 큐의 작업 정보 (그림 1 "진행 상태", 2.1 "진행률 저장"). API는 실행 중이면 여기서 읽어 `GET /runs/{id}`로 돌려준다 |
| 내용 | 진행률(0~100) + 최근 step: 회차(`attempt_index`), `idx`, 스크린샷 키, 판단 한 줄(`thought`) (F02 "현재 스크린샷, 에이전트의 최근 판단 한 줄") |
| 갱신 시점 | 워커가 step 하나를 끝낼 때마다 |
| 계산식 | `floor(90 × (끝난 attempt 수 + Σ 진행 중 attempt의 step 수 ÷ 30) ÷ 예정 attempt 수)`. 후처리(지표·규칙·설명)까지 끝나면 100. 이전 값보다 작아지지 않는다 |
| 상태 기록 | `queued`는 API가 run을 만들 때. `running`(작업을 꺼낼 때, `started_at`), `completed`·`failed`(끝날 때, `finished_at`)는 워커 |

- 30 = 실행 1회의 step 상한 (4.5)
- 예정 attempt 수: auto 모드에서 재생 뒤 에이전트를 몇 번 돌리는지에 따라 바뀐다
- 에이전트가 과업에 실패하거나 사이트가 막은 경우는 `completed`, 사유는 `attempt.end_reason` (openapi.yaml RunStatus)

## 3. DB 쓰기 경계 (2.2, 10장)

| 항목 | 정한 것 |
|---|---|
| 쓰는 방식 | 각 역할 모듈이 자기 테이블에 직접 쓴다 (그림 1: 워커에서 직접 "저장"). 스키마와 마이그레이션은 플랫폼 백엔드가 관리한다 (`apps/api/db/models.py`) |
| step·element_snapshot 저장 시점 | 에이전트 코어가 정한다. 진행 화면은 2번 묶음의 Redis 진행 상태가 맡는다 |
| 스크린샷 | 플랫폼 백엔드가 `save_screenshot(bytes) -> key`를 제공한다. 워커가 불러 받은 키를 `step.screenshot_key`에 기록한다. 저장소는 로컬 디스크, 스테이징·운영은 R2 (3장, 13장) |

### 테이블별 쓰는 역할

| 역할 | 테이블 |
|---|---|
| 에이전트 코어 | attempt, step, element_snapshot |
| 측정 지표·규칙 | metric, issue |
| LLM·프롬프트 | llm_call |
| API (플랫폼 백엔드) | project, task, run 생성·취소, comparison, element_alias, issue_label, human_session, human_event |
| 워커 (상태 기록) | run의 status, started_at, finished_at, prompt_version, cost_usd, representative_attempt_id |
| 관리자 스크립트 | access_code |
| ml 스크립트 | model_version |
