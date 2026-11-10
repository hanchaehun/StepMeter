# worker/queue/

- **담당 역할:** 플랫폼 백엔드
- **하는 일:** 작업 큐 연결, 진행률 갱신, 병렬 반복 실행.
- **참고:** 개발계획서 2.2, 4.6

## 사용법 (`runs.py`, 기준 `docs/worker_api_spec.md`)

| 함수 | 부르는 쪽 | 하는 일 |
|---|---|---|
| `enqueue_run(run_id)` | API | `runs` 큐에 `run_id`만 넣는다. 작업 id `run-{run_id}`, 제한 시간 30분. 예외·시간 초과면 `run.status=failed` |
| `cancel_run(session, run_id)` | API | queued·running이면 `canceled`·`finished_at` 기록. queued면 큐에서도 뺀다 |
| `update_progress(session, run_id, finished=False)` | 워커 | step 행을 추가한 트랜잭션에서 부른다. `run.progress`를 다시 계산하고, run이 running이 아니면(취소됨) False |
| `save_screenshot(data) -> key` | 워커 | `data/screenshots/`에 저장. key를 `step.screenshot_key`에 적는다 |

- 제한 시간은 일단 30분으로 정했다 (1회 약 5분 × 3회 병렬 + 여유, 개발계획서 4.6). 넘거나 워커 함수가 예외로 끝나면 RQ 실패 콜백(`_mark_failed`)이 running인 run을 `failed`·`finished_at`으로 바꾼다. 실제 소요 시간을 보고 조정한다.
- `session`을 받는 함수는 commit하지 않는다. 부르는 쪽이 commit한다.
- 환경 변수: `REDIS_URL`(기본 `redis://localhost:6379/0`), `DATABASE_URL`
- RQ 워커는 fork를 써서 Windows에서 바로 돌릴 수 없다. Docker나 WSL에서 실행한다.
- 테스트: `TEST_DATABASE_URL`, `TEST_REDIS_URL`을 주고 `python -m unittest tests.test_queue -v` (둘 다 비운다)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 재측정(`auto`)에서 재생이 끊기면 에이전트가 처음부터 `repeat_n`회 다시 잰다. 진행률의 예정 시도 수는 재생 시도 수에 `repeat_n`을 더한 값이다 (ADR 0011 8번)
- 병렬 반복은 에이전트 시도에만 쓰고, 재생이 끝난 뒤에 시작한다 (ADR 0011 8번)
