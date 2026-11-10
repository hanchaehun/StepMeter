# worker/agent/

- **담당 역할:** 에이전트 코어
- **하는 일:** 에이전트 루프(Playwright 자체 루프), 행동 스키마(4.3), 종료·실패 판정.
- **참고:** 개발계획서 3.1, 4장

## ADR 0010에 따른 할 일

- LLM에 보내는 요소 목록(최대 30개, `observe()`의 `el_id` 그대로 유지)에 가려진 요소도 넣고 `"(가려짐)"`으로 표시하며, 드라이버가 가려진 대상에 대해 돌려준 스냅샷(`occluded=True`)과 `no_change` 결과를 그대로 step으로 저장한다 (ADR 0010)
- 후처리 순서는 시도별 지표 저장(`finalize_run_metrics` 포함) → `save_run_medians` → `update_progress(finished=True)` → `completed`로 한다. 단, 모든 시도가 `end_reason=error`면 같은 순서로 `save_run_medians`까지 한 뒤 `update_progress(finished=True)`·`completed` 대신 `status=failed`, `finished_at`을 기록한다(하나라도 error가 아니면 성공 0개여도 `completed`) (ADR 0010)
- 단계 스크린샷(JPEG 품질 70, `save_screenshot`으로 저장)은 대상이 있는 행동(`click`·`type`·`select`)이면 드라이버가 대상을 스크롤한 뒤 스냅샷과 같은 시점(행동 직전)에 찍고, 대상이 없는 행동(`scroll`·`back`·`wait`·`done`·`fail`)이면 행동 직전에 찍어 저장한다 (ADR 0010)
- `scan_page`가 `ElementHandle`과 같은 출처 iframe을 지원하기 전까지는 iframe 안 대상을 `path_targets`에서 뺀다 (ADR 0010)

## `worker.agent.run.run(run_id)` 실행 규약 요약

- **시작·어댑터**: `run`을 `WHERE status='queued'` 조건으로 `running`, `started_at=now()`, `prompt_version="action_v1"`으로 바꾸고, 시도(attempt)마다 `make_adapter(run.model)`과 `prompts/action_v1.md`를 쓴다. LLM 호출마다 DB `LlmCall` 행을 추가하고 `run.cost_usd`에 더한다.
- **`select` 옵션**: `observe()` 항목 중 `tag == "select"`인 요소는 활성 `<option>` 텍스트 목록(1번부터)을 함께 읽어 LLM 프롬프트에 보여준다.
- **루프·종료 판정**: 매 단계 `Step.state_hash`는 `sha256(URL 경로 + 보이는 요소 이름·텍스트 정렬 목록)`으로 계산하며, 같은 `(state_hash, action)`이 3회 반복되면 `end_reason="loop"`로 끝내고 `r05.evaluate()` 후보를 만든다. `done(goal_reached)` 시 `task.success_condition`(`url_contains`, `text_present`)을 확인하고, 조건이 `null`이면 `success=True, success_estimated=True`로 기록한다. 드라이버/효과 관찰 예외(`EffectObservationError`, `UnclassifiedNetworkEffect` 등)는 `end_reason="error"`, `end_detail`에 사유를 남긴다.
- **대표 시도·이슈 점수**: 성공한 시도(`success=True`) 중 `step_count`가 중앙값에 가장 가까운 시도(동률이면 `Attempt.index`가 작은 것)를 `run.representative_attempt_id`에 기록한다(성공 시도가 없으면 `None`). W4 이슈 점수 모델 전까지 `save_candidates(..., confidence=1.0)`을 기본값으로 넘긴다.

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 화면에 비밀번호 칸이 보인다는 이유만으로 `blocked`로 끝내지 않는다(`blocked_reason`의 비밀번호 칸 검사를 뺀다). CAPTCHA·봇 확인은 그대로 둔다 (ADR 0011 1번)
- 비밀번호 칸에는 과업 문장에 그대로 적힌 값만 입력하고, 누르기는 허용한다. 과업 문장에 없는 값이면 실행하지 않고 `blocked`·`end_detail=login_wall`로 끝낸다(끝내기 전에 최대 2번 다시 고르게 할 수 있다). 카드 칸과 되돌릴 수 없는 버튼은 지금처럼 `safety_stop`이다 (ADR 0011 1번)
- 프롬프트 버전이 오르면 읽는 파일과 `prompt_version` 값을 같이 바꾼다 (ADR 0011 1번)
- 단계마다 `worker/metrics`가 계산한 예상 소요 시간을 `Step.est_seconds`에 저장하고, 시도 합계를 지표 `est_task_time`으로 저장한다. 모바일은 저장하지 않는다 (ADR 0011 3번)
- 모델이 요소 목록에 없는 번호를 고르면 시도를 error로 끝내지 않고 형식 오류처럼 다시 묻는다 (ADR 0011 6번)
- 시도가 끝나면 `r07.evaluate()`를 불러 후보를 저장한다. W2에 구현만 되고 호출이 없다 (ADR 0011 6번)
- select 단계도 Fitts ID·이동 거리·R07 대상에 넣는다. 지금 `loop.py`의 대상 조건은 `click`·`type`뿐이라 select 단계의 `fitts_id`가 비고 `travel_distance`·`fitts_id_sum`에서 빠진다(`openapi.yaml`의 Step.fitts_id는 click·type·select). 측정 지표·규칙 담당의 "select를 click처럼 세기"와 같이 바꾼다 (ADR 0011 6번)
- R08·R09는 구현한 담당(측정 지표·규칙, LLM·프롬프트)이 `loop.py` 호출까지 PR에 넣는다. 에이전트 코어는 호출 위치와 인자를 리뷰한다 (ADR 0011 6번)
- 재측정(`auto`, 기준 run 있음)은 대표 경로를 먼저 재생하고, 끊기면 에이전트로 처음부터 `repeat_n`회 다시 잰다. 끊긴 지점에서 이어 가지 않는다. 에이전트 시도의 병렬 실행은 재생이 끝난 뒤에 시작한다 (ADR 0011 8번)
