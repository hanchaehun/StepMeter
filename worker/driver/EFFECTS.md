# Effect observer (task 5.1)

`EffectObserver(page)` starts network history immediately. Keep it alive throughout
an attempt, and call `await observer.aclose()` after its last action. Use one per
page and serialize actions. No HTTP payloads, headers or query values are retained
in network history; its request keys contain origin/path and expire after 3 seconds.

`await observer.click(locator)` prepares actionability/scrolling **before** baseline,
then captures the exact handle. For other actions, prepare them first and call
`await observer.observe(async_action, target=element_handle, prepare=async_check)`.
Order: install observer scripts → `prepare()` (target recheck, option check, safety
guard; not timed) → start window → `action()`. Errors from `prepare` (SafetyStop,
EffectObservationError) propagate unchanged. The window starts immediately before
invoking the action, is at most 3000 ms (shorter configurable for tests), and does
not finish early after DOM evidence. Input calls (click, fill, press, select_option,
go_back) receive a Playwright `timeout` of `action_timeout_ms` (5/6 of the window,
2500 ms by default), so a timed-out input is cancelled in the browser instead of
landing late (type + Enter share one such deadline; Enter gets the rest, at least 100 ms); the window's `asyncio.wait_for` remains a slightly longer safety net.
클릭의 조작 가능 확인과 누를 지점 계산은 준비 단계에서 하고, 관찰 창 안에서는 입력 전달만 한다.
Action timeout, cancellation, detached contexts and page closure are errors, not
`no_change`. The agent re-observes after a Playwright `TimeoutError` from `perform`
(ADR 0011 11). Always call `result.as_step_effect()` before persisting the two
frozen Step fields.

Priority: URL > modal count > meaningful DOM/focus/scroll > no_change. Modal
selectors are deduplicated per node. Open shadow roots are observed. Currently
attached frames receive observers, including initially hidden frames. Visibility
is evaluated at mutation time through same-origin ancestor frames: each child
rectangle is clipped to local/top viewports and overflow-clipping ancestors.
Axis-aligned scaling and frame movement are supported; removed nodes combine
cached pre-removal visibility with current frame geometry.

Detached/reloaded contexts and newly attached frames fail closed unless a
higher-priority main-frame URL change was observed. A new frame may show a modal
before an observer could attach, so returning `dom_mutation` would claim incomplete
classification. Caller must retry a fresh observation or report that error.
예외: 관찰 창 안에 새 문서로 이동한 하위 iframe(예약 사이트의 달력 iframe)은 오류로 치지 않는다. 그 iframe 요소가 화면 안에 보이면 화면 변화(dom_mutation)로 보고, 안 보이면 프레임 판정으로는 변화가 아니며 기존 네트워크 규칙(ADR 0011, 아래)이 그대로 적용된다.
iframe 요소를 찾을 수 없으면(떨어져 나감) 그대로 오류이고, 주 프레임이 같은 주소로 새로고침되는 경우도 그대로 오류다.
Cross-origin frame ancestry and rotated/skewed/3D frame transforms are explicitly
incomplete, not silently treated as visible or no_change. Arbitrary clip-path,
rounded-corner clipping and pixel-level occlusion are not modeled by this observer.


DOM exclusions: invisible/offscreen nodes, ancestors with role timer/marquee,
aria-live off, or exact class tokens carousel/swiper/slider/slick/banner/ad. An
action inside such a container exempts that container only. Numeric/colon/space
text-only differences are ignored. Removed-node evidence uses cached pre-removal
visibility refreshed on mutations and every 25 ms. Changes to target/aria-controls
state attributes (including class), and actual input/change state changes count (value, native selectedIndex, checkbox/radio checked); arbitrary class animation does not.

Class/style/hidden changes on unrelated targets are eligible only within 100 ms
after a captured pointerdown/click/keydown/input event during the action window.
Only the changed element and its descendants (including open shadow roots) are
tracked for visible appearance/disappearance, even without aria-controls. A later
attribute mutation outside that interval revokes eligibility for its subtree.
CSS transitions from an eligible mutation can still finish inside the observation
window; merely starting observation does not authorize mutations. This temporal
heuristic cannot distinguish unrelated mutations coinciding within those 100 ms.
Geometry-only movement and color changes on unrelated elements do not. Existing
noise, offscreen and hidden-frame exclusions still apply. This fixes #77's cart
panel omission without declaring an inert search button responsive.

Replay compatibility: baseline paths recorded before this PR may contain
no_change for cart-panel steps now classified as dom_mutation. Replaying such a
path can stop with effect_changed. Record a fresh baseline under the new observer
before comparing versions; do not suppress that mismatch or rewrite old evidence.

이 커밋(ADR 0011 11번) 전에 기록된 기준 경로는 첫 화면(안정화 대기)·화면 해시(요소 60개)·반응 판정(준비를 관찰 창 밖으로)이 달라 재생이 끊길 수 있다. 버전을 비교하기 전에 기준을 다시 잰다.

알려진 한계: 글자나 목록이 저절로 바뀌는 화면(공지 문구, 시계, 실시간 목록)에서는 반응 없는 클릭이 dom_mutation으로 기록돼 R03을 놓칠 수 있다.
대기 구간에 바뀐 요소를 제외하는 방식은 보류했다. 이유: (1) 재생은 단계 사이 대기가 짧아 에이전트와 판정이 달라진다 (2) 바뀌는 대상이 부모 컨테이너로 기록돼 그 안의 진짜 반응까지 무시된다 (3) 늦게 도착한 응답이나 첫 화면 그리기를 타이머로 오인한다.

Policy decisions, deliberately explicit:
- All query keys are significant by default; caller may supply reviewed
  `ignored_query_keys`. Query ordering alone is not a change. Hash navigation is
  opt-in (`hash_routes=True`) for a verified hash-router application.
- Analytics domain exclusion takes precedence over write methods. Only successful
  (2xx/3xx) fetch/xhr/document responses for requests started inside the window
  count. Failed/cancelled requests and beacon/ping do not count. Repeated same-origin,
  same-path GET in the preceding 3 seconds is polling; query changes do not reset it.
- A successful network response with no visible effect maps to `dom_mutation`
  with `changed=true` when `as_step_effect()` is called (ADR 0011). This avoids
  a false R03 without changing the frozen schema. Callers must use this method
  for persistence and rule evaluation.

Tests: `python -m unittest discover -s tests -p 'test_effect*.py' -v`.
Browser test uses normal Playwright Chromium, optionally a locally installed
browser through `STEPMETER_CHROMIUM_EXECUTABLE`. Fixtures are specification-based
synthetic regression cases, not completion of SPA benchmark task 3.1.

## Numbered-action integration

`PlaywrightDriver(page).perform(validated_action)` consumes the last collector
observation, resolves its original node, rechecks identity after actionability
preparation, captures an `ElementSnapshot` and returns an `ActionResult` with the
effect. It supports click, full-value type, single native select, 80% viewport
scroll, back and one-second wait; done/fail belong to agent orchestration.
Reobserve after state changes. Dispose the driver once the attempt ends.
The current collector does not present native option labels to an LLM; a caller
using select must provide the current ordered option list. No LLM run, DB Step
persistence or queue entrypoint is supplied by this component.

Styled native checkbox/radio visibility uses the same narrow predicate as the
collector: self opacity 0, pointer events enabled, visible ancestors and associated
label, and a visible sibling SVG/image/canvas fully inside the input rectangle.
Only self transparency is exempted; no indicator, hidden ancestor, or invisible
label remains excluded. Native checked state changes count even when focus was
already on the control; repeated toggles do not rely on CSS class changes.
