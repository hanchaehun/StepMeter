# worker/metrics/

- **담당 역할:** 측정 지표·규칙
- **하는 일:** 지표 계산 (순수 함수). 테스트 없이 머지 불가, 테스트 기대값은 사람이 계산하거나 명세(WCAG, 문헌값)에서 가져온다.
- **참고:** 개발계획서 5장, 15.2

## W2 호출 계약

공유 `worker/schemas.py`와 DB 스키마는 그대로 사용한다. 아래 계산 함수는
브라우저·DB·LLM에 의존하지 않는다.

| 파일 | 입력과 결과 |
|---|---|
| `cursor_distance.py` | click/type 직전 snapshot 순서 → 뷰포트 중앙부터 bbox 중심까지 거리 합(px) |
| `fitts.py` | 같은 snapshot 순서 → 단계별 방향성 Fitts ID(bit). 면적 0이면 `None`, 이동 0이면 0 |
| `interactions.py` | 행동명 → click/type/back/step 수, 행동·효과 → 무반응 클릭 수 |
| `interactions.py` | 행동·안정된 대상 키 → 연속 반복의 추가 클릭 수(A,A,A는 2) |
| `interactions.py` | 초기·종료를 포함한 scrollY/URL 목록 → 수직 스크롤 거리/URL 경로 전환 수 |
| `persistence.py` | `Session`과 계산값 → 기존 metric 행 저장, 성공한 동일 kind 실행의 중앙값 저장 |

`done`은 단계 수에 포함하지 않는다. `type`은 문자 수가 아니라 행동 횟수다.
스크롤 거리에는 모든 스크롤의 전후 관측값이 필요하다. click/type snapshot만으로
중간 스크롤이나 마지막 스크롤을 추정하지 않는다. URL query/hash 변화만으로는
페이지 전환을 세지 않는다. 반복 클릭 키에 화면마다 재사용되는 `el_id`를 단독으로
쓰지 않는다. 현재 DB Step에는 모든 행동 전후 scrollY·DOM identity가 없으므로
코어가 실행 중 해당 목록을 제공해야 한다.

`save_attempt_metrics(session, attempt_id, values)`의 키·단위는 `UNITS`에 있다.
기존 리포트와 같이 이동 거리는 `travel_distance`, Fitts 합은 `fitts_id_sum`이다.
Fitts가 `None`인 경로를 완전한 합으로 보고하지 않는다(해당 합계 키 생략).
`save_run_medians(session, run_id, kind="agent")`는 완료·성공한 실행만 사용하며
재생과 에이전트를 섞지 않는다. 재생을 선택하면 `replay_status="full"`도 요구한다.
성공 실행들의 키가 다르거나 측정이 누락되면 예외를 내며, 성공 실행이 없으면
집계 행을 만들지 않고 기존 W2 집계만 제거한다. 표본 편차·KLM·보정값은 W3 이후다.
DB 함수는 commit하지 않는다. 후처리 후 caller가 취소 상태를 확인하고 commit한다.

## 검증

### M2 run 후처리

`finalize_run_metrics(session, run_id, kind="agent")`를 모든 attempt 종료 후 호출한다.
기존 DB Step.action을 idx 순서로 읽고 done 이전 행동 수를 계산해 종료된 시도(attempt)별
`step_count`를 저장하며, run 단위(`attempt_id=NULL`) 값은 쓰지 않는다([ADR 0010](../../docs/adr/0010-w3-integration-decisions.md)).
run 단위 중앙값은 `save_run_medians(session, run_id, kind="agent")` 하나가 성공한 시도로만 계산한다.
성공한 시도가 0개면 run 단위 지표는 만들지 않는다(0으로 채우지 않음).
kind를 지정해 agent/replay를 섞지 않는다. 종료된 실행에 행동이 없으면 실제 0이다.
attempt 자체가 없거나 진행 중이면 오류이며, 취소·종료된 run에는 쓰지 않는다.
동일 호출은 기존 행을 갱신한다. commit 및 run 상태 변경은 코어가 담당한다.

```python
from worker.metrics.persistence import save_run_medians
from worker.metrics.postprocess import finalize_run_metrics

# 코어가 소유한 transaction 안에서: 시도별 지표 저장 → save_run_medians → update_progress(finished=True) → completed
finalize_run_metrics(session, run_id)
save_run_medians(session, run_id)
```

코어 담당 전달 제목: `M2 조건 4: 시도별 지표 저장 후 save_run_medians 호출 연결`
내용: 종료 후 시도별 지표(`finalize_run_metrics` 포함) 저장 → `save_run_medians` → `update_progress(finished=True)` → `completed` 순서로 동일 트랜잭션에서 완료 처리해 주세요(ADR 0010).
API 담당은 run_id에 해당하는 attempt_id=NULL metric을 report.metrics에 반환해야 합니다.
실행부/API 연결 전에는 DB 수준 검증이며 HTTP E2E 통과를 의미하지 않습니다.

```sh
python -m unittest tests.test_cursor_distance tests.test_metrics_w2 tests.test_measurement_persistence
```

저장 테스트는 기본적으로 임시 SQLite를 사용한다. `TEST_DATABASE_URL`을
테스트 전용 PostgreSQL로 지정하면 같은 ORM 테스트를 PostgreSQL에서 실행한다.
SQLite 결과는 PostgreSQL 잠금·동시성 검증을 대신하지 않는다.

## ADR 0010에 따른 할 일

- `finalize_run_metrics`는 시도(attempt)별 `step_count`만 저장하고 run 단위(`attempt_id=NULL`) 값은 쓰지 않는다 (ADR 0010)
- run 단위 지표는 `save_run_medians` 하나가 성공한 시도의 중앙값으로만 만들고, 성공한 시도가 0개면 run 단위 지표를 만들지 않는다(0으로 채우지 않음) (ADR 0010)
- 에이전트 후처리 순서는 시도별 지표 저장 → `save_run_medians` → `update_progress(finished=True)` → `completed`로 맞춘다 (ADR 0010)
