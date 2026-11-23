# worker/replay/

- **담당 역할:** 에이전트 코어
- **하는 일:** 경로 고정 재생과 에이전트 전환. 사후 검증에서 효과 유형(5.1)과 URL 경로를 기록과 비교한다.
- **참고:** 개발계획서 7.2

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 재측정(`auto`)은 기준 run의 대표 경로를 먼저 재생한다. 끝까지 재생되면 에이전트를 돌리지 않는다 (ADR 0011 8번)
- 재생이 끊기면 그 시도를 끊긴 지점과 함께 남기고(`replay_status=partial`), 에이전트가 처음부터 `repeat_n`회 다시 잰다. 끊긴 지점에서 이어 가지 않는다. 개발계획서 7.2의 "그 지점부터 이어받는다"와 다르다 (ADR 0011 8번)
- run 단위 지표에서 재생 값과 에이전트 값을 섞지 않는다 (ADR 0011 8번)

## 실행 흐름

`worker.agent.run.run(run_id)`가 기준 run의 대표 attempt를 읽고 `worker/replay/runner.py`로
경로를 재생한다. 기준 run은 같은 과업·뷰포트에서 완료됐고 대표 경로가 있어야 한다.
재생은 LLM을 부르지 않는다. 기록된 대상 스냅샷과 현재 `observe()` 결과를
`worker.matching.match`로 비교하고, 유일하게 맞는 요소 번호로 행동을 실행한다.
이름이 같은 후보가 하나여도 기준 단계와 관찰된 이름 목록이 달라졌다면 대상이
바뀌었을 수 있으므로 조작 전에 멈춘다. 이름이 바뀐 후보는 기존 매칭 조건에 더해
후보의 이름만 이전 이름으로 되돌렸을 때 기준 단계의 상태 해시와 일치해야 한다.
확인할 수 없으면 `target_identity_unverified`와 기준 단계 번호를 기록한다.
드라이버의 민감 입력·위험 버튼 검사를 그대로 사용한다.

재생 attempt는 시작할 때 `kind=replay`로 만들고, 실제 실행한 각 Step을 저장하는
트랜잭션에서 `update_progress`를 부른다. 효과 유형이나 다음 단계의 URL 경로가
기록과 다르면 실행한 단계까지 저장하고 `replay_status=partial`,
`diverged_at_step`에 기준 단계 번호를 남긴다. 대상이 없거나 애매하면 실행 전
partial로 끝난다. `replay_only`는 여기서 멈추고, `auto`는 새 페이지에서 에이전트
시도를 `repeat_n`회 시작한다. 완주한 재생은 성공 조건을 다시 확인한 뒤 full로
기록한다. 취소된 run을 완료 상태로 덮어쓰지 않는다.

재생 지표는 replay attempt에 따로 저장하고, full이면 replay 종류의 run 중앙값을
만든다. partial 뒤 에이전트를 돌린 경우 run 중앙값은 성공한 agent 시도만 사용한다.
대상 규칙과 axe 검사도 재생한 단계에서 다시 평가한다. 종료 시 R07을 계산해
해당 대상의 step ID와 요소 키를 붙여 저장한다.
재생한 각 단계에는 에이전트 루프와 같은 KLM 문헌값(`worker.metrics.klm.estimate_step`)을 `est_seconds`로 저장하고,
데스크톱이면 재생한 단계의 합을 시도 지표 `est_task_time`으로 저장한다(partial이면 재생한 단계까지).
그 화면의 첫 행동에 M을 더하는 기준은 `first.new_screen()`을 부르는 자리와 같다. 모바일은 계산하지 않는다
(ADR 0011 3·10번). 그래서 재생 비교의 `est_task_time`이 판정된다.

현재 저장 형식에는 `<select>`의 이전 옵션 문구가 없으므로 옵션 번호가 그대로인지만
확인할 수 있다. 마지막 행동 뒤의 URL은 기준 경로에 다음 Step이 없으면 효과 유형과
성공 조건으로만 검증한다. 사후 대응 관계 저장 UI는 ADR 0011 범위에서 제외됐다.

검증: `python -m unittest tests.test_replay -v` (합성 브라우저), 전체 테스트는
`python -m unittest discover -s tests -q`.

병렬 에이전트 시도 변경은 PR #58에서 진행 중이다. 이 브랜치는 현재 `main`의 순차
시도 코드를 바탕으로 하므로 PR #58을 합칠 때 `worker/agent/run.py`의 시도 실행
부분을 함께 조정해야 한다. `worker/queue/runs.py`의 재생 포함 분모 변경은 양쪽에 있다.
