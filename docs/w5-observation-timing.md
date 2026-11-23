# W5 관찰기·R06 진단·사람 시간 비교

기준 main: `750226a` (2026-11-23). [#77](https://github.com/hanchaehun/StepMeter/issues/77) 후속 작업.
원본 사람 파일·개인별 판단 목록·분석 결과는 비공개 로컬에 보관한다.

## R03 수정

장바구니 버튼이 다른 요소의 class를 바꿔 패널을 표시해도, 기존 관찰기는 그 요소가
행동 대상 또는 aria-controls 대상이 아니면 놓쳤다. class/style/hidden 변경 시
기존 요소와 조상의 표시 상태를 비교하고 실제 뷰포트 안의 표시/숨김 전환을 반영한다.
CSS 전환 지연·열린 shadow root도 관찰 창 안에서 처리한다.
단순 색상·위치 변화, 타이머, 화면 밖 요소와 숨긴 프레임은 반응으로 만들지 않는다.

합성 로컬 대조군에서 Search는 실제 no_change로 유지하고 Cart 표시는 dom_mutation으로 판정한다.
R03 규칙·공유 스키마·3초 관찰 범위는 그대로다. 이 수정만으로 전체 앱의 FP가
얼마나 감소했는지는 주장하지 않는다. 실제 모델 재실행 결과가 필요하다.
에이전트 코어 담당의 변경 검토 대상이다.

## R06 확인한 사실과 한계

공개 #77 첨부 ZIP의 0차 결과를 정답 대상 단위로 정리했다.

| below-fold 앱 | Haiku | Sonnet |
|---|---|---|
| sb-admin-2 | TP | TP |
| material-kit-react | FN | TP |
| react-shopping-cart | FN | TP |
| shadcn-admin | FN | FN |

따라서 구판 0차 자료의 재현율은 각각 1/4, 3/4다. Sonnet의 장바구니 R06 FP 두 건은
위 TP와 별개이며 재현율 분자에 넣지 않는다. 이는 최신 main 재측정 수치가 아니다.
main의 `benchmark/w3.md`에서 #75 후 Haiku는 여전히 1/4이고,
Sonnet은 shadcn-admin 8건만 다시 측정했으므로 새 4개 앱 전체 수치를 만들 수 없다.

R06은 화면의 첫 click/type/select가 로드 시 첫 화면 밖에 있었고
first_view_scroll_px가 null이 아닐 때만 발생한다. 같은 화면에서 먼저 다른 대상을
누르면 나중의 정답 대상에는 발생하지 않을 수 있다. 이는 코드로 확인한 가능한 경로이지,
첨부 CSV만으로 입증한 각 모델의 실제 행동 원인은 아니다.
query 필터 변화는 같은 화면이고 새 문서/경로 변경은 첫 행동 판정을 초기화한다.

공개 main·관련 이슈와 확인한 CI artifacts에는 원본 실행 경로와 비교용 예측 시간이 없었다.
FN 행의 이슈 발생 횟수 0을 대상 미도달로 해석하지 않는다.
실제 차이를 확정하려면 해당 0차/재측정 실행의 단계별 행동·초기 화면 스냅샷·종료 사유가 필요하다.

다음 benchmark 실행부터 `dom/r06.json`에 이슈가 없는 대상 행동의 조건도 남긴다.
`benchmark.review_r06`은 첫 대상 아님/첫 화면 안/로드 시 부재/첫 화면 밖 첫 대상과
실제 R06 발생의 불일치를 구분한다. 진단 정보는 LLM 입력이나 규칙 조건에 사용하지 않는다.

## 시간 비교 준비

기존 문헌 KLM·DB 저장·사람 시간 사전 정의를 재사용한다. `timing.json`은 실제 DB의
시도별 시간과 run 집계를 보존한다. 사람의 종료 행동은 원본 events 인덱스와
완료 확인·대상·진행 메모를 사람이 대조해 별도 목록에 남긴다.
`click` 누락 보완, stable 대기 제외, notes 이상 페이지 제외, 초기 절차 민감도,
유효 성공 3건 미만의 시간 미보고 기준을 바꾸지 않는다.

`ml.timing.compare`는 같은 과업의 검증 가능한 문헌 KLM run 값으로 모델별·절차별
MAPE와 동률 평균 순위 Spearman을 계산한다. 실제 에이전트 예측 원본이 없으면
대기 상태를 반환한다. 합성 예측값을 실제 사람 비교 수치로 발표하지 않는다.
명령 방식의 회고 메모는 출처·미확인 빌드 정보를 표시하고 원본 notes로 가장하지 않는다.
진행자별 수합 자료·완료 판정 목록·표본 수와 민감도 보고서는 비공개로 유지한다.

## 검증 방법

```sh
python -m unittest tests.test_effect_visibility tests.test_r06_diagnostics tests.test_timing_compare -v
python -m benchmark.verify_r03_controls
docker compose --profile test run --build --rm tests
```

에이전트 연결 회귀는 `tests.test_agent_core`에서 이슈 없는 첫/후속 대상의 R06 기록과
실제 저장된 attempt/run KLM 값의 export를 확인한다. 전체 테스트는 PostgreSQL·Redis가
연결된 새 테스트용 Compose 프로젝트에서 실행한다. 유료 모델 재실행·비밀 앱 열람은 하지 않는다.

2026-11-23 검증: Docker 전체 717개 실행에서 실패 0, 환경 조건으로 15개 건너뜀
(별도 API 서버 7, GUI 화면 7, 로컬 앱 빌드 1). 이후 run 집계·진단 메타데이터 등
최종 보완은 관련 테스트와 기존 benchmark pipeline 17개를 최종 이미지에서 재검증해 모두 통과했다.
R03 대조 도구도 Search=no_change, Cart=dom_mutation으로 통과했다. Ruff와 git diff 검사는 통과했다.
