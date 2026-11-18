# ml/issue_clf/

- **담당 역할:** 수집·매칭 (라벨 판정: 팀원 2명, 엇갈리면 PM)
- **하는 일:** 휴리스틱 이슈 점수 가중치 튜닝(기본 엔진으로 고정). 로지스틱 회귀는 비교 실험(ablation)으로만 보고하고 서비스에는 쓰지 않는다. ablation은 선택 항목이다([ADR 0008](../../docs/adr/0008-schedule-to-1204.md)).
- **참고:** 개발계획서 6.2, 9.2

## W3 특징 추출

`features.extract_features(observations, attempt_ids=...)`는 측정 증거만 받아
관찰 한 건마다 `Features`를 돌려주는 순수 함수다. DB·LLM·정답 파일을 읽지 않는다.
W3에서는 가중치/임계값을 정하거나 서비스 confidence=1.0을 교체하지 않는다.

| 특징 | 계산/결측 |
|---|---|
| severity | high=1, medium=0.6, low=0.3 (개발계획서 6.2) |
| measured_ratio | measured/threshold. 측정 없음 또는 threshold=0이면 null |
| violation_extent | R01/R02: clip(1−ratio,0,1), R06/R07: clip(ratio−1,0,1). 방향 미정/비율 결측은 null |
| estimated | 호출자가 근거를 확인한 bool. 원본에 판정 방법이 없으면 null(설명 문자열로 추측하지 않음) |
| role | 실제 이슈 대상 snapshot.role, 없으면 null. 인코딩은 W4 학습 fold에서만 |
| area | 실제 대상의 width×height(CSS px²), snapshot 없으면 null |
| on_path | candidate.step_id가 있음. is_reference만 보고 경로 밖으로 간주하지 않음 |
| path_position | done/fail을 제외한 단계에서 index/(count−1). 단계 하나면 0, 경로 밖/미제공은 null |
| detection_ratio | 같은 (규칙, canonical target_key)가 경로에서 발견된 서로 다른 agent 시도 수 / 종료한 agent 시도 수 |
| confusion | 해당 경로 단계에 공백 아닌 confusion이 있음 |

attempt_ids에는 동일 run의 **종료한 agent 시도 전체**를 실패·무검출까지 넣는다.
같은 시도의 중복 단계는 분자에 한 번만 들어간다. replay·진행 중 시도는 섞지 않는다.
오류가 난 시도도 분모에 있으므로 검출 빈도가 낮아질 수 있다. exporter는 그 종료 사유도
`failed_attempts`로 함께 남긴다. 이 비율은 성공 시도 완주율과 다른 값이다.

`Observation.target_key`는 실행 도구가 확인한 **화면+실제 이슈 대상**의 식별자다.
axe의 대상은 행동 대상과 다를 수 있으므로 행동 지문으로 대신 채우지 않는다.
snapshot도 실제 대상만 준다. 모르면 null로 둔다. 기준 초과 정도의 방향, 경로 위치,
시도 분모 정책은 특징 버전 `issue-features-v1`에 포함되며 변경 시 버전을 올린다.
R06의 기준 0처럼 비율을 정의할 수 없는 경우 임의로 1점을 넣지 않는다.

### 실행 도구용 입력·출력

`python -m ml.issue_clf.export --input data/w3/measurement.json --output data/w3/features.json`

입력 v1은 한 run이다. 아래는 **설명용 합성 자료**이며 실제 0차 실행 결과가 아니다.
snapshot은 선택적인 동결 ElementSnapshot 객체이며 여기서는 생략했다.

```json
{
  "version": 1, "app_id": "sb-admin-2", "case_id": "small", "run_id": 1,
  "attempts": [
    {"id": 1, "kind": "agent", "end_reason": "success"},
    {"id": 2, "kind": "agent", "end_reason": "gave_up"}
  ],
  "observations": [{
    "attempt_id": 1, "target_key": "/login.html|input#customCheck",
    "candidate": {"rule_id": "R01", "severity": "high", "measured": 16,
                  "threshold": 24, "step_id": 10, "is_reference": false},
    "step_index": 0, "step_count": 1, "confusion": null, "estimated": null
  }]
}
```

출력은 feature_version·app_id·case_id·run_id·관찰별 특징·실패 시도 사유다.
입력 텍스트·과업 문장·thought·설명·정답·score를 출력하지 않는다. app_id를 유지해
W4에서 앱 단위 4-fold를 만들 수 있다. v1 내보내기는 공개 개발 앱 4개만 허용하고
정답/라벨 같은 미등록 필드를 거절한다. 기존 출력 파일은 덮어쓰지 않는다.
`data/`는 git 제외다. 실제 run→이 입력 어댑터는 현재
`benchmark/run_development.py:export_measurements()`에 구현되어 있다(#56).
실행 도구의 존재와 정식 0차 데이터 확보는 구분한다.

검증: `python -m unittest tests.test_issue_features -v`.
통합 작업과 실패 사례는 [W3 기록](../../docs/w3-collection-features.md)에 있다.

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 기본 목록은 `is_reference=false`인 이슈다. 점수가 임계값 미만인 후보는 `is_reference=true`로 저장한다. 임계값은 11/27 동결 때 고정하고 홀드아웃 평가에서 바꾸지 않는다 (ADR 0011 2번)
- 특징 추출과 가중치 튜닝에는 개발 앱 0차 실행과 같은 실행 도구(`benchmark/`)의 결과를 쓴다 (ADR 0011 2번)
- 실사이트 약 20건은 라벨 입력 화면 없이 스프레드시트로 2명이 판정한다. 결과 CSV와 일치도(κ) 계산 스크립트를 `ml/` 아래에 둔다 (ADR 0011 4번)

## W4 점수 적용과 비교 준비

`scoring.ScoreConfig`로 가중치 6개(합 1)와 임계값을 명시한다. 기본 설정·학습된
가중치는 제공하지 않는다. `score_features()`는 아래 합을 [0,1]로 자른다.

```text
w_severity × severity + w_violation_extent × violation_extent
+ w_detection_ratio × detection_ratio + w_on_path × on_path
+ w_confusion × confusion − w_estimated × estimated
```

크기·추정 여부 결측은 해당 항 0이며 결측 자체는 특징·감사 로그에서 null로 유지한다.
`estimated=true`만 감점한다. 임계값과 같으면 기본 목록, 미만이면 참고다.
기존 참고 후보는 점수가 높아도 기본 목록으로 올리지 않는다.

운영자는 검증한 설정 JSON 파일을 `STEPMETER_ISSUE_SCORE_CONFIG`로 지정한다.
형식은 `ScoreConfig.as_dict()` 결과다(`scoring_version="issue-score-v1"`,
`weights`는 `scoring.TERMS`의 여섯 이름을 키로 갖는 객체, `threshold`는 [0,1]).
없으면 기존 confidence=1.0 경로를 유지한다. 테스트의 숫자는 손으로 계산한
검증용 숫자이며 튜닝 결과가 아니다. 최종 설정은 11/27에 동결한다.

`runtime.py`는 행동 전 실제 DOM 대상의 구조 경로와 화면·의미 지문을 잡고,
axe는 설명에 보존된 실제 selector를 쓴다. axe 대상 snapshot은 보수적으로 null로
두며 행동 대상을 대신 넣지 않는다. 형제 순서가 달라지는 재정렬 화면은 구조 경로가
달라져 같은 요소의 반복 검출을 적게 셀 수 있다. 위치로 다른 요소를 합치지 않는다.
agent 시도가 모두 종료된 뒤 run 완료 트랜잭션에서 `confidence`, `is_reference`,
`score_reason`을 갱신한다. 실패·무검출도 분모에 포함하고 replay는 제외한다.
진행 중 값은 잠정 confidence=1.0이며 score_reason이 아직 없다.
재생 이슈와 step 없는 run 단위 참고 규칙은 기존 값을 유지한다.
취소·미완료·대상 근거 누락은 최종 점수 저장을 중단한다. commit은 호출자가 한다.

표준 logging의 `ml.issue_clf.runtime` INFO 기록에 run ID, 특징 버전, 설정·해시,
후보별 특징·최종 점수·목록 구분을 남긴다. 운영에서 이 logger의 INFO를 수집해야
전체 설정을 추적할 수 있다. DB score_reason에는 설정 해시·점수 이유·종료 분모가 남는다.
LLM·정답·폼 입력값은 점수 특징에 넣지 않는다. 새 의존성·API·DB 스키마 변경은 없다.

실측 비교는 같은 0차 실행 자료로 다음 순서로 한다. 첫 채점 때
`--calibration-output`을 지정한다(기존 score.json을 덮어쓰지 않음).

```sh
python -m benchmark.score_development data/run --calibration-output data/calibration.json
python -m ml.issue_clf.calibrate --input data/calibration.json --configs data/candidates.json --output data/comparison.json
```

`candidates.json`은 ScoreConfig 객체들의 JSON 배열이다. 비교기는 승인된 개발 앱
자료만 받고, 동일 (케이스, 규칙, 요소)의 중복을 제거해 규칙만/설정별 점수 적용의
정밀도·재현율·F1·규칙별 TP/FP/FN·정밀도 차이·+0.05 여부를 기록한다.
미실행·실패 케이스는 제외 사유로 유지한다. 재현율 감소도 함께 검토해 사람이
설정을 선택한다. 이 도구가 설정을 자동 배포하거나 개발 자료 선택을 독립 평가로
표현하지 않는다. 다른 규칙 건수·미해결 대상은 기존 score.json에 남는다.

실사이트 판정 CSV의 머리글은 `issue_id,label_a,label_b`, 라벨은
`real`, `false`, `unsure` 또는 빈칸이다. `unsure`는 세 번째 범주다.

```sh
python -m ml.issue_clf.agreement --input data/judgments.csv --output data/agreement.json
```

두 판정이 모두 있는 행만 κ를 계산하고 누락·엇갈린 이슈 ID를 따로 보고한다.
표본 없음·한 범주만 있는 퇴화 분모는 κ=null이다. CSV·실제 판정 자료는 커밋하지 않는다.

실제 튜닝·평가 대기 사항과 검증 기록: [W4 기록](../../docs/w4-issue-scoring.md).
