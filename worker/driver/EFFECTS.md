# Effect observer (task 5.1)

`EffectObserver(page)` starts network history immediately. Keep it alive throughout
an attempt, and call `await observer.aclose()` after its last action. Use one per
page and serialize actions. No HTTP payloads, headers or query values are retained
in network history; its request keys contain origin/path and expire after 3 seconds.

`await observer.click(locator)` prepares actionability/scrolling **before** baseline,
then captures the exact handle. For other actions, prepare them first and call
`await observer.observe(async_action, target=element_handle)`. The window starts
immediately before invoking the action, is at most 3000 ms (shorter configurable
for tests), and does not finish early after DOM evidence. Action timeout,
cancellation, detached contexts and page closure are errors, not `no_change`.
Always call `result.as_step_effect()` before persisting the two frozen Step fields.

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
Cross-origin frame ancestry and rotated/skewed/3D frame transforms are explicitly
incomplete, not silently treated as visible or no_change. Arbitrary clip-path,
rounded-corner clipping and pixel-level occlusion are not modeled by this observer.


DOM exclusions: invisible/offscreen nodes, ancestors with role timer/marquee,
aria-live off, or exact class tokens carousel/swiper/slider/slick/banner/ad. An
action inside such a container exempts that container only. Numeric/colon/space
text-only differences are ignored. Removed-node evidence uses cached pre-removal
visibility refreshed on mutations and every 25 ms. Changes to target/aria-controls
state attributes (including class), and actual input/change state changes count (value, native selectedIndex, checkbox/radio checked); arbitrary class animation does not.

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
