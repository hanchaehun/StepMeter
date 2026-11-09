# SPA 스트레스 테스트 (3.1)

## 구현된 것과 아직 검증하지 않은 것

- `python -m benchmark.spa_eval`: 독립적으로 작성한 **상태별 전체 정답**과 실제 collector를 비교하는 실행기.
- `python -m benchmark.verify_spa`: 로컬 합성 SPA를 임시 서버에서 실행하고 서버까지 종료하는 재현 명령.
- `synthetic.json`: HTML fixture로부터 독립적으로 작성한 5개 상태(쿠키/닫은 후/모달/가상 목록/해시 라우트). 사람이 검토한 정답이라고 주장하지 않으며 `pending`을 유지한다.
- `real-apps.json`: 고정 리비전의 개발 SPA 후보 2개와 아직 정해지지 않은 팀원 SPA의 준비 상태. **실행 가능한 정답 목록이 아니며 3개 앱 완료 증거도 아니다.** 정적 sb-admin-2와 합성 fixture는 SPA 앱 개수에 넣지 않는다. 홀드아웃은 조회하지 않는다.

`shadcn-admin.template.json`와 `material-kit-react.template.json`은 고정 리비전의 미완성 실행 manifest다. 누락 정답으로 성공하지 않도록 validation에서 의도적으로 거절한다. Material Kit의 실제 실행 경로는 확인 전이라 임의 경로를 넣지 않았다.

실제 3개 SPA 합격은 아직 미완료다. 각 앱을 실행하여 모든 대상이 포함된 정답을 사람이 검토하고, 고정 리비전·준비 상태·과업을 기록한 뒤 각각 실행해야 한다. 세 앱을 합쳐 쿠키 모달, 고정 헤더, 가상 스크롤, 열린 Shadow DOM, iframe 범위를 확인한다. 범위가 없는 앱에 있다고 표시하지 않는다. 팀원 SPA의 저장소/버전/안전한 과업이 필요하다.

## 실행

`infra/README.md`의 Python 3.12, Node 22, npm·Python 의존성, Chromium 설치를 사용한다.

```sh
npm run build:collect
python -m unittest tests.test_spa_eval tests.test_spa_browser -v
python -m benchmark.verify_spa --output evidence/spa/synthetic
# 실제 앱은 별도 loopback 서버로 실행하고, 검토한 manifest를 넘긴다.
python -m benchmark.spa_eval --manifest benchmark/spa/my-reviewed-app.json \
  --base-url http://127.0.0.1:4173 --output evidence/spa/my-reviewed-app
```

`--chromium-executable`은 명시적인 실행 파일이 필요할 때만 사용한다. 기본값은 설치한 Playwright Chromium이다. 실행기는 HTTP(S) loopback 앱만 허용하고 외부 HTTP 요청을 차단하며 차단 호스트를 기록한다. 소스가 외부 API/CDN을 요구하면 로컬 테스트 데이터/리소스를 준비한다. 실제 가입·초대·결제·운영 데이터로 실행하지 않는다. 테스트 데이터와 공개 개발 앱만 사용한다.

종료 코드: `0`은 검토 승인된 해당 manifest의 검사 통과, `2`는 실패·미실행 또는 사람 검토 대기다. 합성 fixture의 정상 측정도 검토 대기라 `2`다. 브라우저 시작 실패는 `not_run` 보고서에 남긴다. 3개 SPA 전체 완료는 단일 manifest나 이 종료 코드로 주장하지 않는다.

## 정답과 상태 설정

`synthetic.json`이 형식 예시다. 실제 정답은 collector 출력에서 복사하지 않는다.

- `app`: 식별자, 고정 revision, `benchmark`/`teammate`/`synthetic` 구분.
- `ground_truth_review`: `pending` 또는 `approved`. 승인 시 실제 검토자와 날짜가 필수다. 도구가 자동 승인하지 않는다.
- `viewport`: 정확한 CSS 픽셀 크기.
- `scenarios`: 서로 독립된 상태. `id`, loopback 기준 `path`, `exhaustive: true`, 필요하면 `ready` 셀렉터와 `setup` 동작을 명시한다.
- `setup`: `click`, `fill`, `press`, `scroll`(컨테이너), `window_scroll`, `wait_visible`. 셀렉터는 실제 렌더링을 확인하고 적는다. setup의 셀렉터 클릭은 상태 준비용으로, 번호 클릭 성공률에 포함하지 않는다.
- `truth`: 고유 `key`, 정확히 하나인 CSS `selector`, 선택적인 같은 출처 `frame` 셀렉터, 사람이 정한 `name`/`role`/`occluded`, `include`(기본 true). Playwright CSS는 열린 shadow를 통과한다. 숨김/화면 밖 음성 대조군은 `include: false`다.
- 정답의 위치는 Playwright의 독립적인 locator.bounding_box에서 측정한다. 이름·역할은 collector에서 가져오지 않는다. 숨겨진 노드는 bbox가 null일 수 있다.
- `clicks`: 실제 클릭해도 안전한 정답 key. 매 클릭마다 새 browser context로 cookies/localStorage/페이지를 초기화하고 준비 과정을 재실행한다.
- `between_observe_and_click`: stale 번호 회귀용 setup. 정상이면 재관찰해야 하는 상태 변화를 의도적으로 끼워 넣을 때만 사용한다.
- `coverage`: 실제 해당 상태에 존재하는 범위만 기록한다. 태그의 정확성 자체는 사람이 스크린샷으로 검토해야 한다.

## 지표와 판정

- 원본 collector는 가려진 요소도 반환한다. 가린 요소를 오염으로 세지 않는다.
- 위치의 2px 허용오차로 일대일 대조한다. 이름/역할은 검증 대상이므로 매칭 조건으로 써서 오류를 숨기지 않는다. 중복/겹침은 임의 선택하지 않고 `ambiguous`로 남긴다. 이런 상태는 실패한다.
- 누락률 = 매칭하지 못한 포함 정답 수 / 포함 정답 수. 목표 ≤10%.
- 오염률 = 매칭하지 못한 수집 결과 수 / 전체 수집 결과 수. 목표 ≤5%.
- 분모가 0이면 null(N/A)이며 완벽한 점수로 표시하지 않는다. 상태별 및 앱 전체 micro 값을 둘 다 저장한다. 한 상태 실패를 전체 평균으로 가리지 않는다.
- 이름·역할·가림 불일치, 오염/누락 원소, 원본 IDs, 비가림 IDs, 최대30개 투영과 제외 수를 분리한다. 최대30개는 ADR0007을 따른다. 이는 진단용 투영이지 프로덕션 LLM 선택 실행 증거가 아니다.
- 번호 클릭은 관찰 ID → snapshot → `resolve_element` 원래 DOM handle → 실제 Playwright 클릭이다. 정답 locator로 클릭을 대체하지 않는다. 정답 노드의 이벤트 수신으로 결과를 독립 검증한다. 잘못된 타겟, stale, 가림, 클릭 오류, 검증할 수 없는 navigation을 따로 남긴다.
- 같은 DOM 노드를 재활용하여 이름·역할·주요 식별 속성 또는 select 옵션 순서가 바뀌면 resolver가 거절한다. 같은 속성을 가진 의미적으로 다른 레코드는 일반 DOM만으로 완전히 식별할 수 없으므로 작업 직전 재관찰이 필요하다.
- 수집 시간은 실행한 상태당 1회(주입/최초 화면 기록 후) 측정한 표본의 median/p95다. 임의 합격시간 기준은 만들지 않았다. 지연 분포가 필요하면 반복 실행한다.
- axe `button-name`/`link-name`을 별도 실행하고 collector 이름 유무와 같은 노드에 매칭한 rule 결과를 비교한다. ARIA-only 위젯은 native rule 범위와 다르며, iframe/shadow의 복합 axe selector는 자동 동일시하지 않고 검토 필요로 남긴다. axe 무위반은 이름/역할 일치 증거가 아니다.

## 증거·실패 처리

출력 디렉터리에 `report.json`, 상태별 PNG가 남는다. 브라우저 버전, 앱 revision, 뷰포트, UTC 확인시각, 원시 관찰, 정답 위치, 이름/역할 불일치, axe 결과, 클릭 결과, 차단 외부 호스트를 포함한다. `evidence/`는 기존 git 제외 경로다. 개인 정보가 있는 앱으로 증거를 만들지 않는다.

공용 `worker/schemas.py`와 OpenAPI는 변경하지 않았다. 이 테스트는 API→큐→LLM→DB→리포트의 전체 M2 E2E가 아니다. 실제 앱에서 실패하면 재현 상태/스크린샷/기대값/실제값을 수집·매칭 담당에게 전달할 자료로 남긴다. 도구가 팀에 연락하거나 이슈를 게시하지 않는다.
