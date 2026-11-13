# benchmark/

- **담당 역할:** 회귀 비교·인프라 (결함 주입 총괄·평가). 개발 앱별 결함 주입과 정답은 리포트 UI, 대시보드 UI, LLM·프롬프트, 플랫폼 백엔드가 나눠 맡고 PM이 교차 검토한다. 홀드아웃 앱의 결함 주입·정답·최종 평가는 회귀 비교·인프라 담당 혼자 맡는다([ADR 0007](../docs/adr/0007-w2-start-decisions.md)).
- **하는 일:** `checkout.py`로 `apps/`에 받는 오픈소스 앱(개발 4 + 홀드아웃 2, git 제외), `mutations/{app}/{variant}.yaml` 결함 주입 설정, `labels/{page}.json` 정답, `eval.py` 평가 스크립트. 정답에는 렌더링 결과로 발현을 확인한 결함만 넣는다. CI에서 매주 월요일에 개발 앱만 평가하고, 홀드아웃 앱은 11/30–12/1 최종 평가 때 한 번만 돌린다([ADR 0008](../docs/adr/0008-schedule-to-1204.md)).
- **주의:** 측정 지표·규칙과 수집·매칭 담당은 홀드아웃 앱 2개의 설정과 정답을 최종 평가 전까지 보지 않는다. 홀드아웃 앱의 이름·설정·정답은 이 저장소에 적지 않고 `holdout/`(git 제외)에서 회귀 비교·인프라 담당만 관리한다([ADR 0003](../docs/adr/0003-holdout-private.md)).
- **참고:** 개발계획서 8장

W1 선정·고정 커밋·재현 방법과 클리닝 범위: [selection.md](selection.md), [apps.json](apps.json).

W2 도구·전환 과업·검증과 남은 작업: [w2.md](w2.md).

W2 앱별 잔여 상태·담당 요청: [w2-readiness.md](w2-readiness.md).

W3 수집 label 회귀: `python -m benchmark.verify_collect_labels`.
`benchmark.build_variant`로 준비한 SB Admin `baseline`·`small`에서 Remember Me
번호 클릭·checked 효과·overlay R04를 loopback 환경으로 확인하고 증거를
`benchmark/evidence/w3-collect-labels/`에 남긴다. 전체 에이전트 벤치마크나
사람 실험 6페이지 검증을 대신하지 않는다. [수집·특징 추출 기록](../docs/w3-collection-features.md).

## ADR 0010에 따른 할 일

- `build_variant.py`가 `stepmeter-build.json` 매니페스트에 기록하는 패치 경로는 `as_posix()`로 통일한다 (ADR 0010)
- 베이스라인(`baseline_axe.py`, `baseline_llm.py`)을 다시 실행할 때 `below-fold` 케이스는 `entry.html`에서 시작한다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 개발 앱을 에이전트로 돌려 `eval.py` 예측을 만드는 실행 도구를 W3 안에 만든다. 케이스마다 시작 주소, 과업 문장(입력값 포함), 성공 조건을 이 폴더의 한 파일에 둔다. 사람 실험 6페이지의 과업 문장은 `human-study/pages.md`와 같아야 한다 (ADR 0011 1·2번)
- 예측은 run의 기본 목록 이슈(`is_reference=false`)를 (케이스, 규칙, 요소)당 1건으로 만든다. 일치, 오탐, 채점하는 규칙 6개, "규칙만"과 "점수 적용" 두 가지 채점은 ADR 0011 2번을 따른다. 정답 정보는 워커의 판정과 점수 계산에 넘기지 않는다 (ADR 0011 2번)
- 일치를 확인하는 방법은 개발 앱에서 정해 이 폴더 문서에 적고, 홀드아웃 평가가 끝날 때까지 바꾸지 않는다 (ADR 0011 2번)
- 0차 실행: W3 안에 개발 앱 4개의 정상 과업 8개와 변이 24개를 `claude-haiku-5-5`로 한 번 돌려 완주율과 "규칙만" 점수를 낸다. 돌지 못한 케이스는 이유와 함께 적는다 (ADR 0011 2번)
- axe 단독·LLM 스크린샷 베이스라인도 같은 단위와 같은 일치 기준으로 채점한다 (ADR 0011 2번)
- 실행 도구는 비밀번호 칸 화면이 아닌 케이스(shadcn-admin, react-shopping-cart)로 먼저 만든다. sb-admin-2와 material-kit-react는 선행 수정(비밀번호 칸 규칙, label 방식 체크박스, axe 주입, 연결된 label 경로)이 들어오는 대로 돌린다 (ADR 0011 6번)
- axe 규칙 이슈의 일치 판정에는 axe가 짚은 요소가 필요하다. 지금 그 selector는 `Issue.explanation` 끝에만 있고 `element_key`는 행동 대상의 지문이다. 읽는 방법을 측정 지표·규칙, LLM·프롬프트 담당과 정해 일치 확인 방법 문서에 같이 적는다 (ADR 0011 6번)

W3 과업 고정·직접 워커 실행·요소 일치 규약·특징 추출 연결과 회귀/문구 변경 버전:
[w3.md](w3.md). 현재 구현·실행 의존성은 [W3 현황](../docs/w3-infra-status.md)에 있다.
