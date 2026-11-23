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

- **시작·어댑터**: `run`을 `WHERE status='queued'` 조건으로 `running`, `started_at=now()`, `prompt_version="action_v3"`으로 바꾸고, 시도(attempt)마다 `make_adapter(run.model)`과 `prompts/action_v3.md`를 쓴다(버전은 `worker/agent/persistence.py`의 `PROMPT_VERSION` 하나). LLM 호출마다 DB `LlmCall` 행을 추가하고 `run.cost_usd`에 더한다.
- **`select` 옵션**: `observe()` 항목 중 `tag == "select"`인 요소는 활성 `<option>` 텍스트 목록(1번부터)을 함께 읽어 LLM 프롬프트에 보여준다.
- **루프·종료 판정**: 매 단계 `Step.state_hash`는 `sha256(URL 경로 + 보이는 요소 이름·텍스트 정렬 목록)`으로 계산하며, 같은 `(state_hash, action)`이 3회 반복되면 `end_reason="loop"`로 끝내고 `r05.evaluate()` 후보를 만든다. `done(goal_reached)` 시 `task.success_condition`(`url_contains`, `text_present`)을 확인하고, 조건이 `null`이면 `success=True, success_estimated=True`로 기록한다. `done(safety_stop)`, `fail`(모델의 포기), 위험 조작 차단(`SafetyStop`), 비밀번호 칸 차단(`LoginWall`)으로 끝날 때도 성공 조건이 있으면 먼저 현재 페이지로 확인해, 이미 충족됐으면 `end_reason="success"`, `success=True, success_estimated=False`로 끝낸다. 충족되지 않았거나 확인 자체가 실패하면 원래대로 `safety_stop`·`gave_up`·`blocked`(`login_wall`)이고, 조건이 `null`이면 추정 성공으로 바꾸지 않는다. 드라이버/효과 관찰 예외(`EffectObservationError` 등)는 `end_reason="error"`, `end_detail`에 사유를 남긴다.
- **병렬 실행**: 에이전트 attempt는 재생이 끝난 뒤 최대 `STEPMETER_MAX_PARALLEL_ATTEMPTS`개(1~3, 기본 3) 동시에 돈다. 호출 한도(`LLMRateLimitError`)로 끝난 attempt가 나오면 실행 중인 attempt가 모두 끝난 뒤 남은 attempt를 하나씩 돌린다 (계획서 4.6).
- **대표 시도·이슈 점수**: 성공한 시도(`success=True`) 중 `step_count`가 중앙값에 가장 가까운 시도(동률이면 `Attempt.index`가 작은 것)를 `run.representative_attempt_id`에 기록한다(성공 시도가 없으면 `None`). 후보 저장 시 `confidence=1.0`을 잠정값으로 넘긴다. `STEPMETER_ISSUE_SCORE_CONFIG`가 있으면 모든 agent 시도 후 `save_run_medians` 다음, run 완료 전에 점수를 확정한다. 설정이 없으면 기존 값이다. 재생 이슈·run 단위 참고 후보는 유지한다. 설정 형식·기록·제약은 [이슈 점수 README](../../ml/issue_clf/README.md)를 따른다.

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 비밀번호 칸이 보이기만 하면 진행한다. 비밀번호 칸 클릭은 허용하고, 입력은 과업 문장에 그대로 있는 비어 있지 않은 값만 허용한다. 그렇지 않으면 `blocked`·`end_detail=login_wall`로 끝낸다. CAPTCHA·봇 확인은 차단하고 카드 칸과 되돌릴 수 없는 버튼은 `safety_stop`이다 (ADR 0011 1번).
- 행동 프롬프트는 `action_v3`이며 읽는 파일, Run과 LlmCall의 `prompt_version`이 일치한다(#75에서 v2 → v3).
- W4 연결 완료: 단계마다 `Step.est_seconds`, 시도 합계 `est_task_time`을 저장한다. 모바일은 저장하지 않는다(아래 W4 절, ADR 0011 3번).
- 모델이 요소 목록에 없는 번호를 고르면 형식 오류처럼 최대 2번 다시 묻는다. 끝내 번호가 없으면 `ActionInputError:invalid_target`로 기록한다 (ADR 0011 6번).
- 시도가 끝나면 `r07.evaluate()`를 불러 대상 step ID와 요소 키를 붙여 후보를 저장한다 (ADR 0011 6번).
- select 단계도 Fitts ID·이동 거리·R07 대상에 넣는다. 지금 `loop.py`의 대상 조건은 `click`·`type`뿐이라 select 단계의 `fitts_id`가 비고 `travel_distance`·`fitts_id_sum`에서 빠진다(`openapi.yaml`의 Step.fitts_id는 click·type·select). 측정 지표·규칙 담당의 "select를 click처럼 세기"와 같이 바꾼다 (ADR 0011 6번)
- R08·R09는 구현한 담당(측정 지표·규칙, LLM·프롬프트)이 `loop.py` 호출까지 PR에 넣는다. 에이전트 코어는 호출 위치와 인자를 리뷰한다 (ADR 0011 6번)
- 재측정(`auto`, 기준 run 있음)은 대표 경로를 먼저 재생하고, 끊기면 에이전트로 처음부터 `repeat_n`회 다시 잰다. 끊긴 지점에서 이어 가지 않는다. 에이전트 시도의 병렬 실행은 재생이 끝난 뒤에 시작한다 (ADR 0011 8번)

## W4 KLM 연결

loop는 행동 완료 후 KLM 문헌값을 계산해 save_step의 est_seconds로 전달한다.
시도 합계는 est_task_time이며 run 중앙값은 기존 save_run_medians가 만든다.
중단·취소 때 미실행 행동은 합계에 넣지 않는다. 모바일은 시간 지표를 저장하지 않는다.
자동 준비 스크롤은 ActionResult.auto_scrolled와 axe 준비 전후 비교로 전달한다.
#75에서 type에 submit(입력 후 Enter)이 추가됐다. KLM은 submit=true면 K를 1회 더한다(`estimate_step`, 확인함).

## #75 관찰 누락 보완 (2026-11-23)

- **30개 선택** (`observation.describe`): 요소가 30개 이하면 `observe()` 문서 순서 그대로 보낸다. 넘으면
  ① 열린 겹침 층 안의 요소(가장 가까운 조상이 `dialog[open]`, `[role=dialog]`, `[role=alertdialog]`,
  `[aria-modal="true"]`, `[role=listbox]`, `[role=menu]`) → ② 가려지지 않은 요소 → ③ 텍스트 입력칸(input
  text·email·search·password·tel·url·number, textarea, 역할 textbox·searchbox·combobox) → ④ 기존 기준(main 안,
  화면 중심 거리, 큰 순, el_id) 순으로 고른다. 겹침 층·텍스트 입력 여부는 `observe()` 행의 정렬 전용 필드
  `sort`로 받고 LLM에 보내는 항목에서는 뺀다. 30개 안의 가려진 요소는 계속 `"(가려짐)"`이다 (ADR 0010).
- **submit**: `type`의 `submit=true`면 드라이버가 같은 효과 관찰 안에서 `fill` 뒤 같은 요소에 Enter를 한 번 누른다.
  비밀번호 칸 규칙(`guard_target`)은 지금처럼 먼저 돈다. 재생은 기록된 `submit`을 그대로 재현하고,
  `submit`이 없는 예전 기록은 `False`로 재생한다.
- **Enter 제출 안전 검사**: `guard_target(..., submit=True)`는 click과 같은 되돌릴 수 없는 버튼 판정
  (`is_irreversible_label`)을 Enter가 일으킬 동작의 후보에 적용하고, 걸리면 `SafetyStop('Irreversible submit')`이다.
  후보는 폼이 있으면 기본 제출 버튼(없으면 폼의 aria-label·name·title), 폼이 없으면 조상 3단계 안의
  button·[role=button]·input[type=submit]이다. 드라이버는 행동 전과 실행 직전 재검사 두 곳에서 `submit`을 넘긴다
  (ADR 0011 10번).
- 모델이 고른 행동에 쓰지 않는 필드를 보내면(예: click에 submit=true) 다시 물을 때 그 필드 이름을 알려 준다
  (`action_feedback.unexpected_fields`). 값은 쓰지 않는다. 최종 실패 코드 형식(`invalid_fields:필드`)은 그대로다.
- 시간 초과(시도 예산 초과가 아닌 `TimeoutError`)로 끝난 시도는 `end_detail`에 그때 돌던 단계를 붙인다:
  `TimeoutError@observe|screenshot|llm|prepare|axe|evidence|perform|save|settle`. 메시지는 저장하지 않는다
  (진단 배경: `benchmark/w3.md` "#75 수정 후 재측정" 알려진 한계 1번).
