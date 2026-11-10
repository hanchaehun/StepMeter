# 0010. W3 모듈 통합 전 계약 정리

- **날짜:** 2026-11-09 (PM 결정)
- **근거 기록:** 아래 표와 항목별 반영할 곳

## 배경

main `3238e16` 기준 검토에서 에이전트 루프(`worker/agent/`)가 수집·드라이버·규칙·지표·API·리포트 화면 모듈을 이을 때 부딪히는 계약 불일치를 발견했다. W3 통합 작업을 시작하기 전에 한 번에 정한다.

## 결정

### 1. 가려진 요소(R04)
- LLM에 보내는 요소 목록에 가려진 요소도 넣고 `"(가려짐)"`으로 표시한다. 최대 30개 제한에 포함한다. 개발계획서 4.2의 "LLM 목록에서 뺀다"를 바꾼다(반투명 막 아래 버튼은 사람 눈에도 보이고 사람은 눌러 본다).
- 가려진 대상에 `click`·`type`·`select`를 하면 드라이버는 예외를 던지지 않고, 실제 조작 없이 스냅샷(`occluded=True`)과 효과 `no_change`를 담은 결과를 돌려준다. 에이전트는 이를 step으로 저장한다.
- 규칙 엔진은 같은 step에서 R04가 나오면 R03(무반응)은 내지 않는다(같은 원인 중복 방지).

### 2. R02 측정값
- axe `color-contrast` 노드의 `contrastRatio`를 `measured`, `expectedContrastRatio`를 `threshold`에 넣는다.

### 3. 경로 밖 참고 이슈
- 규칙 엔진은 경로 밖 참고 이슈(`is_reference=True`, `step=None`)에서 `element_key=None`을 유지한다.
- 리포트 화면은 R05 여부를 `element_key`가 아니라 `rule_id === "R05"`로 판단한다.

### 4. 지표 집계 하나로
- `finalize_run_metrics`는 시도(attempt)별 `step_count`만 저장하고 run 단위 값은 쓰지 않는다.
- run 단위 값은 `save_run_medians` 하나가 만든다: 성공한 시도의 중앙값(개발계획서 4.6).
- 성공한 시도가 0개면 run 단위 지표는 없다(0으로 채우지 않는다). 리포트는 "성공한 시도 없음"으로 보인다.
- 에이전트 후처리 순서: 시도별 지표 저장 → `save_run_medians` → `update_progress(finished=True)` → `completed`.

### 5. 스크린샷 시점
- 단계 스크린샷은 드라이버가 대상을 스크롤한 뒤, 스냅샷과 같은 시점(행동 직전)에 찍는다. bbox 오버레이와 어긋나지 않게 한다.

### 6. axe 스캔
- `scan_page`는 수집기가 주는 `ElementHandle`을 받도록 바꾸고, 같은 출처 iframe 대상도 지원한다.
- 바뀌기 전까지 에이전트는 iframe 안 대상을 `path_targets`에서 뺀다.

### 7. 작은 수정
- `benchmark/build_variant.py` 매니페스트 경로는 `as_posix()`로 기록한다.
- 베이스라인(`baseline_axe.py`, `baseline_llm.py`) 재실행 때 `below-fold`는 `entry.html`에서 시작한다([ADR 0009](0009-r06-first-target.md)).

### 8. 모든 시도가 error인 run의 상태 (2026-11-10 추가)
- run의 모든 시도(attempt)가 `end_reason=error`로 끝나면 run은 `failed`로 끝낸다. 측정 결과가 아니라 시스템 실패로 본다.
- 하나라도 `success`·`gave_up`·`loop`·`budget_exceeded`·`blocked`·`safety_stop`이면 `completed`로 끝낸다. 성공 0/3이어도 `completed`이며, "사이트가 어렵다"는 UX 결과로 리포트에 그대로 보인다.
- 두 경우 모두 시도별 지표 저장과 `save_run_medians`를 먼저 실행한다(4번 순서 유지). `failed`일 때는 `update_progress(finished=True)`와 `completed` 대신 기존 실패 처리와 같이 `status=failed`, `finished_at`을 기록한다.
- 취소(`canceled`) 처리는 바꾸지 않는다.
- 모델 응답 형식 오류로 모든 시도가 error인 경우는 서비스 쪽 실패로 보며, openapi RunStatus의 'failed = 서비스 장애, 에이전트 실패는 completed' 설명과 같은 뜻이다(에이전트 실패 = gave_up·loop 등).

| # | 항목 | 반영할 곳 |
|---|---|---|
| 1 | 가려진 요소(R04) 목록 포함·무조작 반환·R03 중복 제외 | `worker/collect/`, `worker/agent/`, `worker/driver/`, `worker/rules/` |
| 2 | R02 `measured`·`threshold` 기록 | `worker/rules/` |
| 3 | 리포트 화면 R05 판별 기준 (`rule_id === "R05"`) | `apps/web/` |
| 4 | 지표 집계 일원화 및 후처리 순서 | `worker/metrics/`, `worker/agent/` |
| 5 | 스크롤 뒤 행동 직전 스크린샷 촬영 | `worker/driver/`, `worker/agent/` |
| 6 | `scan_page` `ElementHandle`·동일 출처 iframe 지원 | `worker/a11y/`, `worker/agent/` |
| 7 | `build_variant.py` `as_posix()`, 베이스라인 `below-fold` `entry.html` | `benchmark/` |
| 8 | 모든 시도가 error면 run `failed`, 하나라도 아니면 `completed` | `worker/agent/` |

## 대안

- R04를 수집 원본(`observe`)만으로 판정한다: 어떤 요소가 과업 대상인지 알 수 없어 오탐이 많아 기각했다.
