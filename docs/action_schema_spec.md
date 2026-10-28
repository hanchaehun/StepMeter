# StepMeter Action Schema (검토안)

기획서의 7개 행동(`click`, `type`, `scroll`, `back`, `wait`, `done`, `fail`)에 **`select`를 추가했다.** 기획서는 드롭다운 요소를 수집하지만 선택 행동은 정의하지 않았다. [Playwright의 `locator.select_option()`](https://playwright.dev/python/docs/input#select-options)은 HTML `<select>`의 옵션을 선택할 수 있다. 이번 스키마는 **단일 선택**만 다루고, 모델은 화면에 보여준 옵션 번호를 반환한다.

## 필드와 행동

모든 행동에는 `action`, `thought`, `expectation`이 필요하다. `thought`와 `expectation`은 공백만이 아닌 1~500자다. `confusion`은 선택 사항이며 값이 있으면 같은 길이의 문자열이어야 한다. 생략하면 `null`이다.

| 행동 | 추가 필드 | 의미 |
|---|---|---|
| `click` | `target` | 관찰한 요소를 왼쪽 버튼으로 한 번 클릭 |
| `type` | `target`, `text` | 입력값 전체 교체. 빈 문자열은 지우기이며 Enter를 누르지 않음 |
| `select` | `target`, `option` | 관찰한 native `<select>`의 옵션 하나 선택 |
| `scroll` | `direction`: `up` / `down` | 최상위 화면을 뷰포트 높이의 80%만큼 이동 |
| `back` | 없음 | 현재 탭의 방문 기록에서 한 단계 뒤로 이동 |
| `wait` | 없음 | 1초 대기 후 다시 관찰 |
| `done` | `reason`: `goal_reached` / `safety_stop` | 목표 달성 주장 또는 위험 행동 전 중단 |
| `fail` | 없음 | 에이전트가 진행을 포기 |

`target`은 현재 관찰의 요소 번호, `option`은 그 `target` 드롭다운에 표시된 옵션 번호다. 둘 다 양의 정수다. `text`는 0~4096자이고 공백을 포함해 그대로 유지한다. 스크롤 80%와 대기 1초는 이번 MVP의 기본값이다.

## JSON 예시

각 줄은 별도의 유효한 응답이다.

```jsonl
{"action":"click","target":1,"thought":"메뉴를 연다","expectation":"메뉴가 열린다"}
{"action":"type","target":2,"text":"","thought":"입력을 지운다","expectation":"입력칸이 빈다"}
{"action":"select","target":3,"option":1,"thought":"지역을 고른다","expectation":"지역이 선택된다"}
{"action":"scroll","direction":"down","thought":"아래를 본다","expectation":"다음 영역이 보인다"}
{"action":"back","thought":"이전 화면으로 간다","expectation":"이전 페이지가 보인다"}
{"action":"wait","thought":"로딩을 기다린다","expectation":"목록이 나타난다"}
{"action":"done","reason":"goal_reached","thought":"완료 화면을 봤다","expectation":"성공 조건을 확인한다"}
{"action":"fail","thought":"더 진행할 수 없다","expectation":"실패 이유가 기록된다"}
```

문자열 번호(`"target":"1"`), 0 이하의 번호, 필수 필드 누락, 다른 행동의 필드, 중복 키, `NaN`, 배열 응답은 거절하고 실행하지 않는다. 관찰에서 사라진 번호는 실행 전에 별도로 확인한다.

## 거절 사유

파서는 `ActionInputError`를 던지고 `code`로 사유를 구분한다. 메시지에는 받은 값을 넣지 않는다.

| `code` | 언제 |
|---|---|
| `invalid_json` | JSON 구문 오류, 객체를 연달아 보냄, `NaN`·`Infinity` 포함 |
| `invalid_shape` | 최상위가 객체가 아님 (배열 응답 등) |
| `duplicate_key` | 같은 키가 두 번 (`{"action":"wait","action":"click"}`) |
| `invalid_action` | `action`이 없거나 위 8개가 아님 |
| `invalid_fields` | 필수 필드 누락, 다른 행동의 필드, 문자열 번호(`"target":"1"`), 0 이하의 번호, 길이 초과, 공백뿐인 설명 |

`done(goal_reached)`는 성공 판정이 아니라 모델의 주장이다. 실제 성공 조건을 확인해야 한다. `done(safety_stop)`은 중단이고, `fail`은 에이전트의 포기다. 브라우저 오류와 구분한다.

데이터 모델은 [`worker/schemas.py`](../worker/schemas.py)에 있다. 실제 클릭·입력 실행은 이 작업에 포함하지 않는다.
