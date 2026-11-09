# worker/rules/

- **담당 역할:** 측정 지표·규칙
- **하는 일:** 규칙 엔진 R01~R11. R03 무반응 클릭은 효과 유형 no_change와 노이즈 제외 규칙(5.1)으로 판정한다. 테스트 없이 머지 불가, 테스트 기대값은 사람이 계산하거나 명세에서 가져온다.
- **참고:** 개발계획서 5.1, 6장, 15.2

## W2

R01~R07·R10을 규칙별 파일에 구현했다. 결과는 내부 `Candidate`이며 공유
Step/ElementSnapshot/API 스키마를 추가하거나 변경하지 않는다.

| 규칙 | 판정 |
|---|---|
| R01 | axe target-size 확정 결과 우선. 미판정이면 24px·중심 간 24px 간격 예외 적용. 인라인 링크 제외, 24~44px 권장 안내 |
| R02 | axe `color-contrast` violations. 직접 대비비 추정 없음 |
| R03 | click + 코어가 노이즈 제외 후 기록한 `no_change` |
| R04 | snapshot.occluded |
| R05 | attempt.end_reason == loop. 단순 반복 클릭은 해당하지 않음 |
| R06 | 클릭 대상이 로드 때 화면 밖. first_view_scroll_px가 null인 나중 생성 요소는 제외 |
| R07 | 측정 가능한 대상 중 ID 상위 ceil(N/10), min(width,height)<32, ID>0 |
| R10 | axe button-name/link-name/label 등 명시된 이름·레이블 규칙 |

R07의 표본 수 반올림·동률 처리는 계획서에 정의되지 않아 상위 ceil(N/10)개와
경계 동률 전체 포함으로 명시했다. 실제 임계값 튜닝이나 홀드아웃 접근은 하지 않는다.
R06은 가로로만 화면 밖인 경우도 포함한다(scroll px가 0일 수 있음).

`engine.evaluate_step()`은 R01/R03/R04/R06에 step_id와 요소 지문을 붙인다.
`r05.evaluate()`는 실행 종료 때 한 번, `r07.evaluate()`는 실행 전체 ID 계산 후
호출한다. R07 반환 목록은 입력 순서와 같으며 caller가 해당 step_id·지문을 붙인다.
`engine.evaluate_axe()`는 경로 밖 결과를 `is_reference=True`로 유지한다.
화면 밖이면서 경로 밖인 대비 문제는 제외한다. 원본 incomplete는 후보로 승격하지 않는다.

`save_candidates(session, run_id, candidates, confidence=...)`는 기존 issue 모델에
저장한다. step의 run 소속을 검증하고 같은 후보 재저장 시 기존 행/라벨을 보존한다.
스코어는 별도 담당 영역이므로 임의 기본값 없이 caller가 제공한다. commit하지 않으며
기존 이슈를 지우거나 run 상태를 바꾸지 않는다. 설명은 판정 근거 템플릿이고 LLM 설명이 아니다.

## 코어 담당자에게 전달할 연결 사항

- 이슈 제목 제안: `W2 측정·규칙 호출부와 실행 중 관측값 연결`
- 받는 사람: 에이전트 코어·수집 담당
- 내용: 행동 전 snapshot/실제 Locator와 임시 키로 axe 검사, 행동 후 DB step ID에 연결 및 노이즈 제외
  effect_type 제공, 초기·각 행동 후 scrollY/URL 및 안정된 대상 identity 수집,
  실행 종료 후 R05/R07·metric/issue 저장 호출이 필요하다. 현재 main의 코어 실행부는
  아직 구현되지 않았다. 취소 확인·최종 commit·run 완료 처리는 코어가 맡는다.

검증: `python -m unittest tests.test_rules_w2 tests.test_a11y_scan tests.test_measurement_persistence`.
R08/R09/R11, 휴리스틱 가중치 학습, LLM 설명, KLM은 이번 변경 범위에 포함하지 않는다.
