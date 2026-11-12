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
`data/`는 git 제외다. 실행 도구의 실제 run→이 입력 어댑터는 회귀 비교·인프라와
협의할 연결점이다. W3의 실행 도구가 main에 아직 없으므로 실제 0차 데이터가
생겼다고 주장하지 않는다.

검증: `python -m unittest tests.test_issue_features -v`.
통합 작업과 실패 사례는 [W3 기록](../../docs/w3-collection-features.md)에 있다.

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 기본 목록은 `is_reference=false`인 이슈다. 점수가 임계값 미만인 후보는 `is_reference=true`로 저장한다. 임계값은 11/27 동결 때 고정하고 홀드아웃 평가에서 바꾸지 않는다 (ADR 0011 2번)
- 특징 추출과 가중치 튜닝에는 개발 앱 0차 실행과 같은 실행 도구(`benchmark/`)의 결과를 쓴다 (ADR 0011 2번)
- 실사이트 약 20건은 라벨 입력 화면 없이 스프레드시트로 2명이 판정한다. 결과 CSV와 일치도(κ) 계산 스크립트를 `ml/` 아래에 둔다 (ADR 0011 4번)
