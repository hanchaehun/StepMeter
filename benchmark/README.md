# benchmark/

- **담당 역할:** 회귀 비교·인프라 (결함 주입 총괄·평가). 개발 앱별 결함 주입과 정답은 리포트 UI, 대시보드 UI, LLM·프롬프트, 플랫폼 백엔드가 나눠 맡고 PM이 교차 검토한다. 홀드아웃 앱의 결함 주입·정답·최종 평가는 회귀 비교·인프라 담당 혼자 맡는다([ADR 0007](../docs/adr/0007-w2-start-decisions.md)).
- **하는 일:** `checkout.py`로 `apps/`에 받는 오픈소스 앱(개발 4 + 홀드아웃 2, git 제외), `mutations/{app}/{variant}.yaml` 결함 주입 설정, `labels/{page}.json` 정답, `eval.py` 평가 스크립트. 정답에는 렌더링 결과로 발현을 확인한 결함만 넣는다. CI에서 매주 월요일에 개발 앱만 평가하고, 홀드아웃 앱은 11/30–12/1 최종 평가 때 한 번만 돌린다([ADR 0008](../docs/adr/0008-schedule-to-1204.md)).
- **주의:** 측정 지표·규칙과 수집·매칭 담당은 홀드아웃 앱 2개의 설정과 정답을 최종 평가 전까지 보지 않는다. 홀드아웃 앱의 이름·설정·정답은 이 저장소에 적지 않고 `holdout/`(git 제외)에서 회귀 비교·인프라 담당만 관리한다([ADR 0003](../docs/adr/0003-holdout-private.md)).
- **참고:** 개발계획서 8장

W1 선정·고정 커밋·재현 방법과 클리닝 범위: [selection.md](selection.md), [apps.json](apps.json).

W2 도구·전환 과업·검증과 남은 작업: [w2.md](w2.md).

W2 앱별 잔여 상태·담당 요청: [w2-readiness.md](w2-readiness.md).

## ADR 0010에 따른 할 일

- `build_variant.py`가 `stepmeter-build.json` 매니페스트에 기록하는 패치 경로는 `as_posix()`로 통일한다 (ADR 0010)
- 베이스라인(`baseline_axe.py`, `baseline_llm.py`)을 다시 실행할 때 `below-fold` 케이스는 `entry.html`에서 시작한다 (ADR 0010)
