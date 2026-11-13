# worker/rules/

- **담당 역할:** 측정 지표·규칙
- **하는 일:** 규칙 엔진 R01~R11. R03 무반응 클릭은 효과 유형 no_change와 노이즈 제외 규칙(5.1)으로 판정한다. 테스트 없이 머지 불가, 테스트 기대값은 사람이 계산하거나 명세에서 가져온다.
- **참고:** 개발계획서 5.1, 6장, 15.2

## W2

R01~R07·R10을 규칙별 파일에 구현했다. 결과는 내부 `Candidate`이며 공유
Step/ElementSnapshot/API 스키마를 추가하거나 변경하지 않는다.

| 규칙 | 판정 |
|---|---|
| R01 | axe target-size 확정 결과 우선. 미판정이면 작은 타겟 중심의 반지름 12px 원과 모든 이웃 bbox의 겹침, 작은 이웃의 반지름 12px 원과의 겹침을 함께 검사. 인라인 링크 제외, 24~44px 권장 안내 |
| R02 | axe `color-contrast` violations. 직접 대비비 추정 없음 |
| R03 | click + 코어가 노이즈 제외 후 기록한 `no_change` |
| R04 | snapshot.occluded |
| R05 | attempt.end_reason == loop. 단순 반복 클릭은 해당하지 않음 |
| R06 | 화면(페이지 로드·SPA 라우트 변경)이 로드된 뒤 처음 행동하는 대상(click·type·select)이 로드 시 첫 화면 밖. 화면이 바뀔 때마다 다시 센다([ADR 0009](../../docs/adr/0009-r06-first-target.md)). first_view_scroll_px가 null인 나중 생성 요소는 제외 |
| R07 | 측정 가능한 대상 중 ID 상위 ceil(N/10), min(width,height)<32, ID>0 |
| R10 | axe button-name/link-name/label 등 명시된 이름·레이블 규칙 |

R07의 표본 수 반올림·동률 처리는 계획서에 정의되지 않아 상위 ceil(N/10)개와
경계 동률 전체 포함으로 명시했다. 실제 임계값 튜닝이나 홀드아웃 접근은 하지 않는다.
R06은 가로로만 화면 밖인 경우도 포함한다(scroll px가 0일 수 있음).

`engine.evaluate_step()`은 R01/R03/R04/R06에 step_id와 요소 지문을 붙인다.
`is_first_target`은 필수다. `r06.FirstTargetTracker`에 행동 직전 URL과 행동 종류를 순서대로 넣어 얻는다.
화면은 출처+경로로 구분하고 쿼리만 바뀌면 같은 화면이다. 해시는 `hash_routes=True`일 때만 센다.
같은 주소를 다시 불러온 페이지 로드는 `new_screen()`으로 알린다.
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
- 내용: 행동 전 snapshot과 수집기의 ElementHandle(`scan_page` 반영 전까지는 동일 출처 iframe 제외, [ADR 0010](../../docs/adr/0010-w3-integration-decisions.md)) 및 임시 키로 axe 검사, 행동 후 DB step ID에 연결 및 노이즈 제외
  effect_type 제공, 초기·각 행동 후 scrollY/URL 및 안정된 대상 identity 수집,
  화면이 바뀔 때마다 첫 화면 다시 기록(record_first_view)과 FirstTargetTracker로 첫 행동 대상 판정,
  실행 종료 후 R05/R07·metric/issue 저장 호출이 필요하다. 현재 main의 코어 실행부는
  아직 구현되지 않았다. 취소 확인·최종 commit·run 완료 처리는 코어가 맡는다.

검증: `python -m unittest tests.test_rules_w2 tests.test_a11y_scan tests.test_measurement_persistence`.
R08/R09/R11, 휴리스틱 가중치 학습, LLM 설명, KLM은 이번 변경 범위에 포함하지 않는다.

## ADR 0010에 따른 할 일

- 같은 step에서 R04(가림)가 나오면 같은 원인 중복을 막기 위해 R03(무반응)은 내지 않는다 (ADR 0010)
- R02는 axe `color-contrast` 노드의 `contrastRatio`를 `measured`에, `expectedContrastRatio`를 `threshold`에 넣는다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 화면 변화 없이 서버 응답만 있는 행동은 드라이버가 `dom_mutation`으로 준다. R03을 내지 않는다 (ADR 0011 5번)
- R07은 시도 종료 때 에이전트 코어가 부른다. 연결되면 step_id와 지문이 붙는지 확인한다 (ADR 0011 6번)
- 벤치마크 채점은 R01·R02·R03·R04·R06·R10만 한다. 다른 규칙이 기본 목록에 낸 이슈는 건수만 따로 보고한다 (ADR 0011 2번)
- R08은 구현하는 PR에 `worker/agent/loop.py` 호출까지 넣는다(R07처럼 구현만 되고 호출이 빠지지 않게). R09도 같다(LLM·프롬프트 담당). 에이전트 코어가 리뷰한다 (ADR 0011 6번)
- axe 규칙(R02·R10) 이슈에서 axe가 짚은 요소의 selector는 지금 `explanation` 끝("대상: …")에만 남고, `element_key`는 행동 대상의 지문이다. 채점 도구가 이 selector를 읽는 방법을 회귀 비교·인프라, LLM·프롬프트 담당과 정한다. 설명 생성이 `explanation`을 바꾼 뒤 같은 후보를 다시 저장하면 `save_candidates`가 새 행을 만든다는 점도 같이 본다 (ADR 0011 6번)

R01 간격 예외는 [WCAG 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)을 따른다.
중심→이웃 bbox 최단거리 <12px 또는 작은 이웃과 중심거리 <24px이면 실패한다.
접하기만 하는 12/24px 경계는 통과한다. bbox는 실제 클릭 영역의 직사각형 근사다.
기존 계획서의 중심 원끼리만 비교하는 설명을 보완한다. scan은 axe 4.10.3에서
기본 비활성인 target-size를 명시적으로 활성화하며 다른 기본 규칙도 유지한다.
