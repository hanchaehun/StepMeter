# W3 수집·매칭 구현 기록 (이원준)

기준: main `907b371`, ADR 0010·0011, 사용자가 제공한 2026-11-12 Notion W3 정리.
브랜치: `feat/collect-labels-issue-features`. 원본 개인 메모는 수정하지 않는다.

## 구현

| W3 항목 | 결과 |
|---|---|
| observe() label 방식 | input 의미 정보 유지, 보이는 label/indicator를 통한 번호 클릭, stale 연결 검증, disabled 보호. 같은 출처 iframe·열린 Shadow DOM 회귀 포함 |
| 이슈 점수 특징 추출 | 순수 함수 10개 특징, 실행 도구용 JSON 입출력, 종료 시도 중 중복 제거한 발견 비율, 결측·비율 방향·버전 문서화 |
| 가림 판정 보강 | label을 가림으로 오인하지 않음, label 안의 독립 링크는 제외, 막을 통과해 강제 클릭하지 않음, 무 hit도 가림 처리, 프레임 이동 후 좌표 재계산 |

`worker/schemas.py`, OpenAPI, DB 모델·마이그레이션은 변경하지 않는다.
다른 출처 iframe·닫힌 Shadow DOM은 ADR 0011대로 제외한다. 기획서의 전체 일정,
홀드아웃 접근, 선택적 로지스틱 회귀 구현보다 최신 main·ADR을 따른다.

연결된 label을 axe 경로에 포함하는 김도현 담당 작업은 별도다. 이 변경은 의미 대상의
ElementHandle을 계속 반환하므로, axe 경로 확장 담당이 그 input의 labels를 읽어
연결할 수 있다. label 대상으로 바꾼 핸들을 원래 input이라고 속이지 않는다.
실제 로그인 전체 과업은 별도 담당의 비밀번호 정책 변경에 의존한다. 아래 검증은
Remember Me 체크 단계이며 실제 계정 로그인/폼 제출은 하지 않는다.

## 발견한 실패 사례와 보완

| 재현 | 원인/결과 | 조치 |
|---|---|---|
| Bootstrap opacity=0, z-index=-1 input | W2 수집은 누락, label이 hit되면 가림으로 오판 | label 연결·기하와 의미 대상을 분리; 실제 마우스로 indicator를 누름 |
| small 변이의 빈 label + ::before | label의 border bbox가 0이라 단순 visible 판정은 누락 | 생성된 indicator의 크기·표시도 확인 |
| 체크는 바뀌었지만 effect=no_change | 기존 effect 관찰기가 native input의 투명도를 이유로 제외 | label pseudo indicator의 가시성을 기준으로 native checked 변화 감지 |
| 투명 input + 일반 글자 label만 있음 | checked 속성 변화만으로 시각 반응이라고 하면 R03 누락 가능 | 보이는 indicator가 없는 경우 기존 no_change 회귀 유지 |
| observe 후 iframe 위치 변경 | 고정 저장된 iframe offset은 스크린샷·클릭 좌표와 어긋남 | snapshot 때 프레임 체인 위치를 다시 계산 |
| label 중심의 독립 링크/overlay | label 자손이면 무조건 통과시킬 경우 다른 행동 실행 위험 | 독립 상호작용 대상은 proxy에서 제외, 가림 스냅샷/no_change 반환 |

## 실행과 증거

`infra/README.md`대로 Python 3.12.10 가상환경 의존성, Node 22.23.2,
루트·웹 npm ci, 수집 번들, Playwright Chromium 1194를 준비했다.

```sh
python -m unittest tests.test_collect_labels tests.test_issue_features -v
python -m unittest tests.test_agent_core tests.test_collect tests.test_collect_styled_controls tests.test_effect_native_controls -v
python -m unittest discover -s tests -v
ruff check worker tests apps/api infra/scripts benchmark/*.py ml/issue_clf
mypy --explicit-package-bases --follow-imports=silent worker/metrics/cursor_distance.py
npm --prefix apps/web test -- --run
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
python -m benchmark.verify_spa --output benchmark/evidence/w3-spa
```

SB Admin 실앱 재현(공개 development만):

```sh
python -m benchmark.checkout sb-admin-2
python -m benchmark.build_variant sb-admin-2 baseline
python -m benchmark.build_variant sb-admin-2 small
python -m benchmark.verify_collect_labels
```

이미 받은 checkout/build가 있으면 다시 만들지 않는다. smoke 도구는 임시 loopback
서버를 띄우고 종료하며 외부 HTTP 요청을 차단한다. baseline/small 모두
Remember Me 번호 클릭 → checked=true → dom_mutation을 확인했다.
뒤에 막을 추가하면 체크 상태를 바꾸지 않고 R04를 기록하며 R03은 제외한다.
1280×800 화면의 행동 전 JPEG·행동 후 PNG와 snapshot/build provenance는
`benchmark/evidence/w3-collect-labels/`에 있다. small 화면의 체크 상태도 육안 확인했다.

합성 SPA는 쿠키 모달·고정 헤더·가상 스크롤·열린 Shadow DOM·같은 출처 iframe을
포함한다. 정량 보고서는 `benchmark/evidence/w3-spa/report.json`이다.
사람 정답 검토 대기이므로 종료 코드 2/review_pending을 합격으로 바꾸지 않는다.
실제 SPA 3개 전체 인증은 이원준 W3 코드 완료와 구분한다.

테스트 실행 로그는 git 제외 `data/w3/`에 있다. 실제 참가자 자료나 API 키를 만들거나
커밋하지 않았다. Git 커밋·PR 설명은 작성자가 직접 쓴다.

### 최종 확인 (2026-11-12)

- 전체 Python: 403개 실행, 실패 0, skip 55 (`data/w3/full-tests.log`).
  API/PostgreSQL/Redis 환경 의존 검사는 로컬에서 제외되므로 배포 E2E 통과는 아니다.
- 마지막 스크롤 보완 후 label·agent→DB 연결 13개 추가 확인: 전부 통과
  (`data/w3/final-label-tests-v2.log`). 전체 발견 시점 이후 추가한 빈 label/display:none
  조합도 이 검사에 포함된다.
- 특징 추출 9개 검사와 실제 CLI 합성 입력→JSON 출력 통과. CLI 예제는
  `data/w3/feature-example-{input,output}.json`이며 실앱 0차 데이터가 아니다.
- Ruff(ml 포함), 지정된 이동 거리 mypy 통과. 웹 86개 테스트, typecheck, build 통과.
- 합성 SPA: 5개 상태, 오류 0, 누락률 0, 오염률 0, 번호 클릭 9/9.
  사람 검토 대기 `review_pending`/종료 코드 2 유지. 실제 3개 SPA 인증은 미완료.
- 최종 SB Admin baseline/small smoke 2/2 통과
  (`data/w3/sb-admin-smoke-final.log`, `benchmark/evidence/w3-collect-labels/report.json`).

W3 세 항목의 코드와 위 검증은 완료했다. 실제 0차 실행 도구의 run 데이터 연결,
개발 앱에서 확인할 새 실패 사례 반영, 다른 담당자의 axe label 경로 확장과 로그인
정책 변경은 협업 연결점이다. 이를 이미 완료한 것으로 표기하거나 Notion 카드 상태를
대신 변경하지 않았다.

## 이어서 합의할 GitHub 이슈 초안 (게시하지 않음)

**제목:** W3 label 번호 클릭 연결·이슈 특징 추출 입력 연동 확인

**받는 사람:** 배송현(에이전트 코어), 김도현(측정·규칙), 전철우(회귀 비교·인프라)

**내용:**

- label 방식 체크박스·라디오는 observe/resolve_element에서 input 의미 대상을 유지합니다.
  클릭 준비는 scroll_target_into_view, 실행은 드라이버의 click_point 경로를 사용합니다.
  SB Admin baseline/small의 Remember Me 단계와 합성 agent→DB snapshot 저장을 확인했습니다.
  에이전트 통합 시 원래 input의 스크롤/클릭을 직접 부르는 곳이 있으면 이 경로를 써 주세요.
- 김도현 님의 '연결된 label도 axe 경로로 보기'에서 input.labels 확장까지 연결해 주세요.
  이 변경의 snapshot은 native input 스타일과 label 조작 bbox가 함께 올 수 있습니다.
- 특징 추출 API는 ml/issue_clf/features.py, JSON 어댑터 입력은 ml/issue_clf/README.md에 있습니다.
  0차 실행 도구는 같은 run의 종료 agent 시도 전체와 실제 이슈 대상 식별자/스냅샷을
  넘겨 주세요. axe 대상과 행동 대상이 다르면 행동 snapshot을 대신 넘기지 않습니다.
  정답 selector·라벨은 특징 추출 입력에 넣지 않습니다.
- SPA 스트레스 문서상 실제 3개 앱의 사람 검토와 팀원 SPA는 아직 대기입니다.
  새로 확인된 가림 오판이 있으면 고정 revision·재현 상태·독립 기대값·스크린샷을
  전달해 주세요. 다른 출처 iframe·닫힌 shadow root는 이번 범위에서 제외합니다.
