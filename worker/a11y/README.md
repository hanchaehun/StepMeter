# worker/a11y/

- **담당 역할:** 측정 지표·규칙
- **하는 일:** axe-core 실행과 결과 변환 (과업 경로·단계 정보만 붙인다).
- **참고:** 개발계획서 5.4, 5.5, 6장(R02, R10)

## W1 POC: 로컬 axe-core 직접 주입

작업 기준 main의 a11y 폴더에는 실행 코드가 없고 저장소에는 패키지 관리 파일도 없다. 기존 워커의 비동기
인터페이스에 맞춰 Python Playwright의 async `Page`를 받는다.

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
  -> page.add_script_tag(path=로컬 axe.min.js)
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
python -m pip install "pydantic>=2,<3" pytest playwright
python -m playwright install chromium
npm install --no-save --package-lock=false --ignore-scripts axe-core@4.10.3
python -m pytest tests/test_cursor_distance.py tests/test_a11y_axe.py -q
python -m pytest -q
```

별도로 준비한 파일은 `AXE_CORE_PATH` 환경 변수에 절대 경로를 지정한다.
`node_modules/`는 기존 `.gitignore` 대상이며 배포 파일을 소스에 복사하지 않는다.
테스트는 로컬 HTML을 `page.set_content()`로 로드하고 네트워크 요청을 차단한다.
이름 없는 버튼에서 `button-name` rule id를 확인하고, 이름을 붙이면 해당 id가
사라지는지 확인한다. 전체 violation 개수는 고정하지 않는다. 설치 누락은
skip 처리하지 않으며 파일·주입·실행 실패의 예외 전파도 검사한다.

## W1 비범위

R01~R11 매핑, DB persistence, issue severity 판정, path filtering,
path/step 결합, LLM 연동은 구현하지 않는다.

참고: [Python wrapper](https://pypi.org/project/axe-playwright-python/),
[axe API](https://www.deque.com/axe/core-documentation/api-documentation/),
[Playwright 주입 API](https://playwright.dev/python/docs/api/class-page#page-add-script-tag),
[Promise 결과 반환](https://playwright.dev/python/docs/evaluating).
