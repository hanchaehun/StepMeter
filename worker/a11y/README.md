# worker/a11y/

- **담당 역할:** 측정 지표·규칙
- **하는 일:** axe-core 실행과 결과 변환 (과업 경로·단계 정보만 붙인다).
- **참고:** 개발계획서 5.4, 5.5, 6장(R02, R10)

## W1 POC: 로컬 axe-core 직접 주입

W1에서 Python Playwright의 async `Page`를 받는 직접 주입 POC를 추가했다.
현재 main은 루트 package.json/package-lock.json에서 axe-core 4.10.3을 관리한다.

| 방식 | 장점 | 이번 범위에서의 비용 |
|---|---|---|
| Python wrapper (`axe-playwright-python`) | 주입·실행과 결과 포맷팅을 제공 | 별도 Python 패키지와 wrapper API에 의존 |
| 로컬 `axe.min.js` 직접 주입 **(선택)** | Playwright API로 실행하고 원본 violations를 그대로 사용 | 호출자가 axe-core 파일과 버전을 준비해야 함 |

MVP의 첫 검증은 주입과 결과 반환이면 충분하므로 직접 주입한다.
wrapper, pytest 플러그인, 별도 Node 실행 서비스는 추가하지 않는다.
Playwright와 axe-core 자체는 실행에 필요하며, 아래 설치는 최초 환경 준비용이다.
검사 중에는 CDN에서 스크립트를 내려받지 않는다.

```text
호출자가 로드한 Page
  -> page.evaluate(로컬 axe.min.js의 UTF-8 소스)
  -> page.evaluate("() => axe.run()") (Promise 완료 대기)
  -> results["violations"]: list[dict]
```

```python
from worker.a11y.axe import run_axe

# async Playwright Page를 로드한 뒤 호출한다.
violations = await run_axe(page, "node_modules/axe-core/axe.min.js")
rule_ids = {violation["id"] for violation in violations}
```

파일 누락, 주입 실패, `axe.run()` 실패는 예외로 전파한다. 실패를 `[]`로
바꾸지 않는다. 반환값은 axe 원본 violations이며 `incomplete` 등 다른 결과는
반환하지 않으므로 빈 목록이 접근성 전체 통과를 의미하지 않는다.
현재 주입 대상은 최상위 프레임이다. iframe별 주입·검사 보장은 후속 범위다.

## 로컬 테스트

저장소 루트에서 활성화한 Python 가상환경과 Node/npm으로 준비한다.
axe-core는 재현을 위해 `4.10.3`으로 고정한다.

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
npm ci   # 루트 package.json이 axe-core 4.10.3을 고정한다
python -m unittest tests.test_cursor_distance tests.test_a11y_axe
python -m unittest discover -s tests
```

별도로 준비한 파일은 `AXE_CORE_PATH` 환경 변수에 절대 경로를 지정한다.
`node_modules/`는 기존 `.gitignore` 대상이며 배포 파일을 소스에 복사하지 않는다.
테스트는 로컬 HTML을 `page.set_content()`로 로드하고 네트워크 요청을 차단한다.
이름 없는 버튼에서 `button-name` rule id를 확인하고, 이름을 붙이면 해당 id가
사라지는지 확인한다. 전체 violation 개수는 고정하지 않는다. 설치 누락은
skip 처리하지 않으며 파일·주입·실행 실패의 예외 전파도 검사한다.

## W2: 경로·단계 연결

W1 `run_axe()`는 호환성을 유지한다. W2 `scan_page()`는 violations뿐 아니라
incomplete/passes도 보존하고 각 node에 `path_keys`, `is_reference`, `in_viewport`를 붙인다.
path key는 caller가 정한 0 이상 임시 키(예: 행동 순번)다. 행동 후 step 저장이 끝나면
`evaluate_axe()`에 임시 키 → 실제 DB step ID 매핑을 전달한다.

```python
from worker.a11y.scan import scan_page
from worker.rules.engine import evaluate_axe, axe_target_size_result

# 행동 전: 0은 이번 행동을 식별하는 임시 키다 (ADR 0010에서 ElementHandle 및 동일 출처 iframe 지원으로 확장).
results = await scan_page(page, "node_modules/axe-core/axe.min.js", {0: target_locator})
size_result = axe_target_size_result(results, 0)  # True/False/None
# 행동 후 코어가 step을 저장한 다음 (DB step ID 12 예시):
candidates = evaluate_axe(results, {0: 12}, {12: snapshot})
```

같은 이름이나 선택자 문자열로 추측하지 않고 실제 DOM identity로 연결한다.
대상 내부 텍스트의 대비 문제도 해당 경로에 묶는다. 경로 밖 문제는 참고로 남기며,
이동 후 과거 대상을 한꺼번에 검사하지 않는다. 요소 누락·중복·분리와 검사 오류는
예외로 전파한다. 현재 코드는 `iframes=False`로 main document와 open shadow root만 검사하고
iframe 대상을 거절하나, [ADR 0010](../../docs/adr/0010-w3-integration-decisions.md)에 따라 `ElementHandle`과 같은 출처 iframe 대상을 지원하도록 바꾼다.

R01 최소 크기 판정은 axe 확정 결과를 우선 사용하고, 간격·인라인 예외·44px 안내는
`worker/rules/r01.py`에서 snapshot과 결합한다. R02/R10은 violations만 매핑한다.
`incomplete`는 실패도 통과도 아니며 원본에 남긴다. 이미지/그라디언트의 픽셀 대비
추정은 아직 구현하지 않았다. 휴리스틱 점수·LLM 설명·iframe별 검사는 후속 범위다.
DB 저장과 severity는 `worker/rules/`가 맡고 axe 실행 계층에서는 판단하지 않는다.

로컬 W2 테스트: `python -m unittest tests.test_a11y_scan`.
이름 없는 경로 안/밖 버튼, #777/흰 배경 대비, shadow DOM, 모호한 대상 및 오류를 확인한다.

참고: [Python wrapper](https://pypi.org/project/axe-playwright-python/),
[axe API](https://www.deque.com/axe/core-documentation/api-documentation/),
[Playwright 주입 API](https://playwright.dev/python/docs/api/class-page#page-add-script-tag),
[Promise 결과 반환](https://playwright.dev/python/docs/evaluating).

## ADR 0010에 따른 할 일

- `scan_page`는 `Locator` 대신 수집기가 주는 `ElementHandle`을 받도록 바꾸고, 같은 출처 iframe 안 대상도 지원한다 (ADR 0010)
- 바뀌기 전까지 에이전트는 iframe 안 대상을 `path_targets`에서 뺀다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- axe를 `page.add_script_tag` 대신 `page.evaluate`로 주입한다. `script-src` CSP가 있는 페이지에서 `add_script_tag`가 거절돼 시도가 error로 끝난다. `page.evaluate`로 넣으면 같은 CSP에서 `axe.run`까지 된다(2026-11-10 확인) (ADR 0011 6번)

## W3

POC와 scan 모두 로컬 UTF-8 스크립트를 `page.evaluate`로 실행한다.
script-src CSP로 script 태그 주입이 막힌 페이지도 검사하며 파일·주입·검사 오류는 전파한다.
행동 대상의 `input.labels`(외부 for 및 감싸는 label, 복수 label)를 같은 경로로 묶는다.
label 내부 텍스트의 color-contrast도 해당 경로다. 내부의 독립 링크/버튼 이름 문제는
행동 대상과 동일한 요소가 아니면 참고로 남긴다. iframe 검사 범위는 기존과 같다.
