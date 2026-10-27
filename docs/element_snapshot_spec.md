# StepMeter ElementSnapshot 형식 (검토안)

`click`·`type` 직전에 대상 요소 하나에 대해 측정 훅이 저장하는 값이다. 개발계획서 5.1(측정 훅), 5.7(가시성), 5.4(타겟 크기 예외), 7.2(매칭 지문), 11장(`element_snapshot` 테이블)을 합쳐 정했다. 측정 지표·규칙, DB 저장, 요소 매칭이 이 형식을 입력으로 쓴다. 데이터 모델은 [`worker/schemas.py`](../worker/schemas.py)에 있다.

모든 모델은 `extra="forbid"`, `strict=True`다. 문자열 숫자(`"100"`), `1`을 `true`로 보는 변환, `NaN`·`Infinity`, 정의되지 않은 필드는 거절한다. 좌표와 크기는 **최상위 뷰포트 기준 CSS px**다. iframe 안 요소도 최상위 좌표로 바꿔서 준다.

예시는 [`tests/fixtures/mock/element_snapshot.json`](../tests/fixtures/mock/element_snapshot.json)이다 (쿠키 배너에 가린 구매 버튼).

## 필드

| 필드 | 형식 | 수집 방법 |
|---|---|---|
| `el_id` | 양의 정수 | 관찰에서 LLM에게 보여준 번호 (행동의 `target`) |
| `tag` | 소문자 문자열 | `tagName` |
| `role` | 문자열 \| `null` | dom-accessibility-api `getRole` (암묵 역할 포함). 역할이 없으면 `null` |
| `name` | 문자열 (≤1000자) | dom-accessibility-api `computeAccessibleName`, 공백 정리. 이름이 없으면 `""` |
| `landmark` | `banner` `navigation` `main` `complementary` `contentinfo` `search` `form` `region` \| `null` | 가장 가까운 랜드마크 조상. `form`·`region`은 이름이 있을 때만 |
| `label_text` | 문자열 (≤200자) \| `null` | **이름이 없을 때만** 조상 3단계 안에서 처음 보이는 글자. 이름 없는 요소 매칭 지문용(7.2) |
| `inline_in_text` | bool | 링크 역할 + `display: inline*` + 같은 부모에 글자 노드가 있음. 타겟 크기 예외(5.4) |
| `context` | `document` `open_shadow` `same_origin_iframe` | 요소가 있는 곳 |
| `viewport` | `{width, height}` | |
| `scroll` | `{x, y}` | `window.scrollX`, `scrollY` |
| `bbox` | `{x, y, width, height}` | `getBoundingClientRect()` + iframe 오프셋 |
| `style` | 아래 표 | `getComputedStyle()` |
| `bg_chain` | `BackgroundLayer[]` (1개 이상) | 대상 자신부터 `html`까지. iframe 안이면 iframe 요소를 거쳐 바깥 문서 `html`까지 |
| `occluded` | bool | 중심점의 `elementFromPoint`가 대상 또는 그 자손이 아님 |
| `occluder` | `{tag, role, name, bbox}` \| `null` | 대신 잡힌 맨 위 요소. `occluded=false`면 반드시 `null` |
| `in_first_view` | bool | 로드 직후 기록한 첫 화면 목록에 있었는지 |
| `first_view_scroll_px` | 0 이상 실수 \| `null` | 아래 참고 |
| `nearby_targets` | `{role, name, bbox}[]` | 아래 참고 |

`style`: `color`, `background_color`, `background_image`는 브라우저 문자열 그대로(`"rgb(119, 119, 119)"`, `"rgba(0, 0, 0, 0)"`, `"none"`). `font_size`는 px 숫자, `font_weight`는 1~1000 정수, `opacity`는 0~1.

`BackgroundLayer`: `tag`, `background_color`, `background_image`, `opacity`.

### 판정 세부

- **가림**: 중심점은 bbox 중심이다. bbox가 뷰포트에 일부만 걸치면 보이는 부분의 중심을 쓴다. Shadow DOM과 같은 출처 iframe 안까지 내려가 맨 위 요소를 찾는다. 대상의 **조상**이 잡히면(예: 대상에 `pointer-events:none`) 가림으로 본다.
- **첫 화면**: 페이지 로드 직후 1회, 상호작용 요소마다 중심점이 `[0, width) × [0, height)` 안이면 첫 화면이다. 기록 시점의 스크롤을 빼서 스크롤 0 기준으로 계산한다.
  - `first_view_scroll_px` = `max(0, 문서 기준 중심 y − 뷰포트 높이)`. 첫 화면 요소는 `0`이다. 가로로만 벗어난 요소는 `in_first_view=false`, `0`이다.
  - 로드 때 없던 요소(나중에 뜬 메뉴 등)는 `in_first_view=false`, `first_view_scroll_px=null`이다.
- **주변 타겟**: 마지막 관찰의 다른 요소 중, 대상 bbox 중심에서 그 요소 bbox의 가장 가까운 점까지 거리가 48px 이하인 요소다. 대상의 조상·자손은 뺀다. 5.4 간격 예외(지름 24px 원 겹침)는 이 목록으로 측정 지표 쪽에서 판정한다.

## 이번 범위에서 정하지 않은 것

- 값을 실제로 수집하는 주입 JS와 Driver 연결: W1 요소 수집 JS 작업에서 이 형식에 맞춰 구현한다.
- 관찰 시점의 요소 목록(번호·LLM 목록) 형식: 에이전트 코어와 따로 정한다.
- `Step` 데이터 형식: 에이전트 코어가 정한다.
