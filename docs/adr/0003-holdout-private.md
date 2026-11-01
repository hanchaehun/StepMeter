# 0003. 홀드아웃 앱은 public 저장소에 적지 않는다

- **날짜:** 2026-11-01 (PM 결정)
- **근거 기록:** [benchmark/selection.md](../../benchmark/selection.md), [benchmark/checkout.py](../../benchmark/checkout.py), `.gitignore`

## 배경

개발계획서 8장은 규칙 작성자(측정 지표·규칙, 수집·매칭)가 최종 평가 전까지 홀드아웃 앱 2개의 설정과 정답을 보지 않게 했다.
저장소가 public이라 홀드아웃 정보를 저장소에 두면 보지 않는 것이 약속에만 의존한다.

## 결정

홀드아웃 앱의 이름·설정·정답은 public 저장소 어디에도 적지 않는다.
`benchmark/holdout/`(git 제외)과 접근을 제한한 장소에 두고 회귀 비교·인프라 담당만 관리한다.
`benchmark/checkout.py`는 `benchmark/holdout/apps.json`이 있으면 그 안의 홀드아웃 항목을 읽고, `--include-holdout`을 줘야 받는다.

## 대안

- 저장소의 `benchmark/apps.json`에 두고 규칙 작성자에게 보지 않도록 안내한다 (W1 방식).
