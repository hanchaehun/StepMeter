# worker/agent/

- **담당 역할:** 에이전트 코어
- **하는 일:** 에이전트 루프(Playwright 자체 루프), 행동 스키마(4.3), 종료·실패 판정.
- **참고:** 개발계획서 3.1, 4장

## ADR 0010에 따른 할 일

- LLM에 보내는 요소 목록(최대 30개, `observe()`의 `el_id` 그대로 유지)에 가려진 요소도 넣고 `"(가려짐)"`으로 표시하며, 드라이버가 가려진 대상에 대해 돌려준 스냅샷(`occluded=True`)과 `no_change` 결과를 그대로 step으로 저장한다 (ADR 0010)
- 후처리 순서는 시도별 지표 저장(`finalize_run_metrics` 포함) → `save_run_medians` → `update_progress(finished=True)` → `completed`로 한다 (ADR 0010)
- 단계 스크린샷(JPEG 품질 70, `save_screenshot`으로 저장)은 대상이 있는 행동(`click`·`type`·`select`)이면 드라이버가 대상을 스크롤한 뒤 스냅샷과 같은 시점(행동 직전)에 찍고, 대상이 없는 행동(`scroll`·`back`·`wait`·`done`·`fail`)이면 행동 직전에 찍어 저장한다 (ADR 0010)
- `scan_page`가 `ElementHandle`과 같은 출처 iframe을 지원하기 전까지는 iframe 안 대상을 `path_targets`에서 뺀다 (ADR 0010)

## `worker.agent.run.run(run_id)` 실행 규약 요약

- **시작·어댑터**: `run`을 `WHERE status='queued'` 조건으로 `running`, `started_at=now()`, `prompt_version="action_v1"`으로 바꾸고, 시도(attempt)마다 `make_adapter(run.model)`과 `prompts/action_v1.md`를 쓴다. LLM 호출마다 DB `LlmCall` 행을 추가하고 `run.cost_usd`에 더한다.
- **`select` 옵션**: `observe()` 항목 중 `tag == "select"`인 요소는 활성 `<option>` 텍스트 목록(1번부터)을 함께 읽어 LLM 프롬프트에 보여준다.
- **루프·종료 판정**: 매 단계 `Step.state_hash`는 `sha256(URL 경로 + 보이는 요소 이름·텍스트 정렬 목록)`으로 계산하며, 같은 `(state_hash, action)`이 3회 반복되면 `end_reason="loop"`로 끝내고 `r05.evaluate()` 후보를 만든다. `done(goal_reached)` 시 `task.success_condition`(`url_contains`, `text_present`)을 확인하고, 조건이 `null`이면 `success=True, success_estimated=True`로 기록한다. 드라이버/효과 관찰 예외(`EffectObservationError`, `UnclassifiedNetworkEffect` 등)는 `end_reason="error"`, `end_detail`에 사유를 남긴다.
- **대표 시도·이슈 점수**: 성공한 시도(`success=True`) 중 `step_count`가 중앙값에 가장 가까운 시도(동률이면 `Attempt.index`가 작은 것)를 `run.representative_attempt_id`에 기록한다(성공 시도가 없으면 `None`). W4 이슈 점수 모델 전까지 `save_candidates(..., confidence=1.0)`을 기본값으로 넘긴다.
