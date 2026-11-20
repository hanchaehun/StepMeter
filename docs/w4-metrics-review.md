# W4 #77 규칙 점검

기준 main 52a7f13, 공개 이슈 #77의 stepmeter-fp-breakdown-2026-11-18.zip.
SHA256: 66155e2e4c1bd36fd565b8a70e8d20486e21e2e8ea54ecaa46cc692dc995c669.
원본 첨부: https://github.com/hanchaehun/StepMeter/issues/77
이 문서는 실제 사람 자료를 사용하지 않는다.

## 데스크톱 R01 참고 분리의 영향

아래는 보관된 rules_only 행에서 low 권장 후보를 참고로 재분류한 수치다.
새 모델 실행/재측정이 아니며 기존 score.json을 변경하지 않는다.

| 모델 | 규칙 | 전 TP/FP/FN | 후 TP/FP/FN |
|---|---|---|---|
| Haiku | R01 | 3/41/1 | 3/1/1 |
| Haiku | R02 | 3/0/1 | 3/0/1 |
| Haiku | R03 | 2/18/1 | 2/18/1 |
| Haiku | R04 | 4/5/0 | 4/5/0 |
| Haiku | R06 | 1/0/3 | 1/0/3 |
| Haiku | R10 | 3/0/1 | 3/0/1 |
| Sonnet | R01 | 3/52/1 | 3/1/1 |
| Sonnet | R02 | 3/0/1 | 3/0/1 |
| Sonnet | R03 | 2/25/2 | 2/25/2 |
| Sonnet | R04 | 4/4/0 | 4/4/0 |
| Sonnet | R06 | 3/2/1 | 3/2/1 |
| Sonnet | R10 | 4/0/0 | 4/0/0 |

합계 Haiku 16/64/7→16/24/7 (precision .200→.400),
Sonnet 19/83/5→19/32/5 (.186→.373). FN과 recall은 그대로다.

재현: `python -m benchmark.review_rule_fps <첨부.zip> --output data/w4/fp-review.json`.
출력은 전후 규칙별 건수와 high FP·성공 시도 포함 R03 사례 전체를 보존한다.

## 남은 R01 high 16px 1건

두 모델 모두 react-shopping-cart/small의 `.product-action button:nth-of-type(2)`다.
고정 소스 Product.jsx와 저장소 small.patch를 대조하면 이 요소는 원본 ADD TO CART가
아니라 변이에서 추가한 `aria-label="Product help"` 버튼이다. 첫 버튼과 모두 16×16,
margin=0으로 바로 붙어 있어 최소 크기 및 작은 타겟 간격 기준을 실제로 위반한다.
정답 JSON은 첫 번째 버튼만 지목하므로 두 번째의 올바른 검출도 채점상 FP다.
라벨을 늘리거나 판정을 숨기지 않고 규칙을 유지한다. 원본 앱 자체의 위반이라고 하지 않는다.

## 성공 시도에도 나온 R03

공개 CSV에서 성공 시도를 포함하는 FP:
- Haiku 4건: baseline-remove·unnamed의 검색 버튼 및 cart-icon, 각 2건.
- Sonnet 11건: 검색 버튼 baseline·below-fold·contrast·small·unnamed (5건),
  cart-icon baseline·baseline-remove·below-fold·contrast·small·unnamed (6건).

고정 upstream: sivadass/react-shopping-cart@0e867f1caf6abd7114aab6ae704a2824064e84e0,
`src/components/Header.jsx`, `CartPreview.jsx`, 저장소 baselines/react-shopping-cart.patch를 대조했다.

1. 검색: 입력 onChange가 검색을 실행한다. 기준선 패치가 form을
   `onSubmit={e=>e.preventDefault()}`로 바꿨고 submit 버튼에는 별도 handler가 없다.
   따라서 이미 입력된 검색 버튼을 다시 눌러도 변화가 없는 것이 소스 동작이다.
   timeout을 늘릴 근거가 없다. 버튼 무반응을 검출한 R03과 '주입한 정답만' 평가하는 FP를 구분한다.
2. cart-icon: preventDefault 후 상태를 toggle하고 별도 `.cart-preview`의 active class를 바꾼다.
   현재 관찰기는 class/style 변경을 행동 대상 또는 aria-controls 대상에서만 유효하게 보므로,
   별도 preview의 보임/숨김을 놓칠 수 있다. 소스 구조를 재현하는 로컬 도구로 확인한다.
   제안: 코어/효과 관찰 담당이 class/style/hidden 변경 시 실제 viewport의 보임 전후 변화만
   감지하도록 보완하고, 무관한 hover·광고·타이머 변화는 제외하는 테스트를 함께 추가한다.
   모든 class 변화를 유효 반응으로 세거나 관찰 시간을 늘리는 수정은 하지 않는다.

재현: `python -m benchmark.verify_r03_controls` (로컬 HTML·네트워크 차단).
출력은 검색 no_change와 cart의 실제 보임 전후 및 visibility_missed를 구분한다.
Docker 재현 결과: search.effect=no_change, cart는 before_visible=false→after_visible=true인데
cart.effect=no_change, visibility_missed=true였다. 이는 실제 표시 전환 관찰 누락을 확인한 것이다.
이 도구는 원본 React 앱 전체 경로를 재실행하지 않는다. 실제 기록의 각 프레임은
원본 실행 evidence가 별도 제공돼야 대조할 수 있다. 이번에는 CSV·고정 소스·합성 동작으로
원인을 분류하고 관찰기 수정은 제안으로 남긴다.

## 다음 확인

실패 시도에만 나온 R03은 #75 수집/관찰 수정 후 재측정한다.
R06 Haiku 1/4, Sonnet 3/4 차이는 화면 첫 행동의 경로에 의존하므로 원본 경로 대조가 필요하다.
새 모델 호출과 R06 심층 분석, 이슈 점수 튜닝은 수행하지 않았다.

## 검증 기록

- 별도 Compose 프로젝트 stepmeter-w4-20261119의 새 PostgreSQL(tmpfs)·Redis·Chromium에서
  전체 663개 실행: 648개 통과, 실패 0, 15 skip(API E2E 7, 앱 빌드 1, 디스플레이 GUI 7).
- Docker 집중 검사 46개 통과. ADR 예시 11.93초의 단계·시도·run 저장, 모바일 제외,
  자동 준비 스크롤 1.1초, 성공 중앙값·재호출·실패/replay 제외·롤백을 확인했다.
- Ruff 및 새 계산/분석 모듈과 드라이버의 지정 mypy 통과.
- 초기 Docker 엔진 500 오류는 Desktop 재시작으로 복구했다.
  첫 전체 검사는 집중 ORM 검사의 미버전 테이블이 남은 DB를 재사용해 DuplicateTable 3건이 났다.
  새 격리 프로젝트에서 재실행해 API·마이그레이션을 포함한 전체 검사가 통과했다.
- 로그: git 제외 data/w4/docker-tests.log, docker-focused.log, r03-controls.log, fp-review.json.
- 실제 참가자 자료·유료 LLM은 사용하지 않았다. 사람 시간/MAPE/상관의 실제 수치는 아직 없다.
