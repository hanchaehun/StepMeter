# worker/driver/

- **담당 역할:** 에이전트 코어
- **하는 일:** Driver 인터페이스와 PlaywrightDriver (desktop | mobile). 모바일 뷰포트는 선택 항목이다([ADR 0008](../../docs/adr/0008-schedule-to-1204.md)). 행동 직후 효과 유형 감지(url_change, modal_change, dom_mutation, no_change).
- **참고:** 개발계획서 4.1, 5.1

## 효과 관찰 (5.1)

`effects.EffectObserver`가 행동 전에 관찰을 준비하고 최대 3초 동안 효과를
수집한다. 통합 방법, 네트워크-only 미분류 처리, 노이즈 정책과 검증 범위는
[EFFECTS.md](EFFECTS.md)를 참고한다. Step 저장 전 `as_step_effect()`를 호출해야 한다.
