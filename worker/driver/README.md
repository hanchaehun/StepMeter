# worker/driver/

- **담당 역할:** 에이전트 코어
- **하는 일:** Driver 인터페이스와 PlaywrightDriver (desktop | mobile). 모바일 뷰포트는 선택 항목이다([ADR 0008](../../docs/adr/0008-schedule-to-1204.md)). 행동 직후 효과 유형 감지(url_change, modal_change, dom_mutation, no_change).
- **참고:** 개발계획서 4.1, 5.1

## 효과 관찰 (5.1)

`effects.EffectObserver`가 행동 전에 관찰을 준비하고 최대 3초 동안 효과를
수집한다. 통합 방법, 네트워크-only 미분류 처리, 노이즈 정책과 검증 범위는
[EFFECTS.md](EFFECTS.md)를 참고한다. Step 저장 전 `as_step_effect()`를 호출해야 한다.

## ADR 0010에 따른 할 일

- 가려진 대상에 `click`·`type`·`select`를 하면 예외(`click(trial=True)` 타임아웃이나 `EffectObservationError`)를 던지지 않고, 실제 조작 없이 스냅샷(`occluded=True`)과 효과 `no_change`를 담은 결과를 돌려준다 (ADR 0010)
- 단계 스크린샷은 대상을 `scroll_into_view_if_needed()`로 스크롤한 뒤 `snapshot()`과 같은 시점(행동 직전)에 찍어 `ActionResult`로 함께 돌려주거나 콜백으로 넘겨 bbox 오버레이와 어긋나지 않게 한다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 행동 뒤 화면 변화는 없고 유효한 서버 응답만 확인되면 `effect_type=dom_mutation`, `changed=true`로 저장한다 (ADR 0011 5번).
- `guard_target`이 비밀번호 칸 규칙을 따르도록 과업 문장과 입력값을 받는다 (ADR 0011 1번)
