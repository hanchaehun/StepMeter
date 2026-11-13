# W3 회귀 비교·인프라 구현 현황

2026-11-12, 최신 main `2b02624`에서 분기한 `codex/w3-completion` 작업이다.
W2 작업 브랜치는 보존했다. 변경은 비교 기능·평가 도구·인프라 준비 순서로 나눠 커밋한다.
PR 작성·팀 메시지 게시·애플리케이션 실배포는 수행하지 않았다.
공용 `worker/schemas.py`, `apps/api/openapi.yaml`, DB 모델·마이그레이션은 변경하지 않았다.

## 구현한 작업

| W3 작업 | 구현·검증 결과 |
|---|---|
| 재측정 비교 v1 | `worker/compare/engine.py`, `service.py`, 기존 `GET /compare` 연결. 지표 중앙값·편차, 이슈 신규/해결/유지, 경로 정렬, 소유권 검사·캐시 |
| 회귀 쌍·문구 변경 | 4개 개발 앱의 10개 대상에 확인 조작 추가판 10개와 문구판 10개. 고정 기준선 산출물을 복사하고 SHA256 출처 기록. 실제 Chromium 20/20 검증 |
| 0차 실행 준비 | `benchmark/tasks.json`: 정상 8과업+변이 24개. 모든 고정 빌드·패치 해시 준비 |
| 평가 실행·채점 | 실제 PostgreSQL 직접 워커 실행기, 라벨 없는 DOM 증거 캡처, 스크립트/네트워크 없는 오프라인 요소 일치, 규칙만/점수 적용 채점·미실행 사유 |
| 특징 추출 연결 | 실제 run→측정 자료→기존 `ml.issue_clf.export` 입력. 종료 agent 시도 전체를 분모로 제공하고 실제 이슈 대상이 다르면 잘못된 snapshot을 전달하지 않음 |
| 11/17 배포 준비 | Railway API/worker 대시보드 설정표, 실제 API origin으로 Vercel `/api` rewrite를 생성하는 도구, R2·마이그레이션·실제 브라우저 점검 절차 |

사용법과 요소 일치 규약은 [benchmark/w3.md](../benchmark/w3.md),
비교의 판정 범위는 [worker/compare/README.md](../worker/compare/README.md),
스테이징 절차는 [infra/staging.md](../infra/staging.md)에 있다.

## 검증

- Docker 전체 Python 418개: 실패 0, 7 skip(별도 서버가 필요한 M2 E2E).
  `data/w3/docker-tests-final.log`. 이미지의 Python 3.12·Node 22 수집 번들·Chromium,
  격리 PostgreSQL/Redis 환경이다.
- 이후 추가한 전체 파이프라인·출처 구분·DOM 선택자 보존을 포함한 W3 집중 검사 12개 통과.
  합성 화면·fake 모델로 3회 worker→DB→DOM 증거→측정 자료→특징 추출→오프라인 채점 연결을 확인했다.
  SQLite progress shim이므로 PostgreSQL 잠금 검증과 구분한다.
- 비교 API의 실제 PostgreSQL 계약·인증·다른 코드 404·다른 과업/뷰포트 409·캐시 검사는
  Docker 전체 검사에 포함됐다. 기대값은 100→141의 변화 41, 기준 편차 .2와 임계값 .4로 손계산했다.
- 회귀판·문구판 20/20: `benchmark/evidence/w3/version-check-pointer/report.json`과 PNG.
  이는 자료 발현·조작 확인이며 재생 완주율/회귀 검출 최종 성능을 의미하지 않는다.
- 웹 Vitest 86개, typecheck·build, Ruff, 지정 mypy, `git diff --check` 통과.
- 로컬 첫 전체 검사는 Chromium 경로 미지정으로 실패했다. 저장소의
  `PLAYWRIGHT_BROWSERS_PATH=.venv/ms-playwright`와 최신 수집 번들로 집중 검사를 다시 통과했다.

## 아직 실행하지 못한 것

실제 Haiku 0차 실행은 `ANTHROPIC_API_KEY`가 실행 환경에 없어 진행하지 않았다.
`benchmark/evidence/w3/preflight-final/summary.json`에 32개 빌드 준비와 인증 조건 미충족을 기록했다.
이 결과에 임의 점수·완주율을 넣지 않았다. 사용자가 인증값의 위치를 모른다고 답했으므로
LLM 담당자의 실행 환경 연결이 필요하다. 키를 채팅에 보내도록 요구하지 않는다.

main의 비밀번호 칸 차단, axe 주입·label 경로 연결은 ADR 0011에 따라 담당자가 수정할 작업이다.
R01 누락 수정 PR #53은 확인 시 미병합이다. 이들이 해결되기 전에도 비밀번호 화면이 없는
shadcn-admin·react-shopping-cart부터 실행할 수 있다. 실제 Claude+API/RQ/Postgres를 함께
연결한 검증은 직접 워커 평가와 별도다.

11/17 스테이징 실배포는 Railway 서비스 주소·계정 연결과 #51의 R2 저장 코드·비공개 키가
필요하다. R2 계정·버킷·키는 PM, R2 저장 구현은 백엔드가 각각 11/14 준비 예정이라고 밝혔다.
현재 준비 파일을 실제 배포 완료로 표기하지 않는다. W4 pooled 편차와 재생기·재생 완주율 검증,
베이스라인 실행, 사람 실험 진행을 본인 완료 작업으로 대체하지 않았다.

## 전달할 GitHub 이슈 초안

### 실제 0차 평가 실행 환경 연결

- 제목: `[W3 0차 평가] 32개 개발 케이스 준비 완료 — Claude 인증 환경 연결 요청`
- 받는 사람: LLM·프롬프트(@msterk11), PM(@hanchaehun)
- 내용: 고정 과업 32개와 빌드, 직접 워커 실행·채점·특징 추출 연결을 준비했습니다.
  본인 환경에는 ANTHROPIC_API_KEY가 없고 사용자는 설정 위치를 모릅니다.
  기존 실제 호출에 사용한 비공개 실행 환경을 연결하거나 담당 환경에서 실행할 수 있도록
  인증 설정 위치만 안내 부탁드립니다. 키 원문은 이슈·저장소·채팅에 적지 말아 주세요.
  Haiku로 케이스마다 API 최소 반복 3회를 사용합니다. shadcn-admin/커머스부터 실행 가능합니다.

### 선행 수정과 실제 axe 대상 식별

- 제목: `[W3 평가 연결] 비밀번호 정책·axe 주입·label 경로와 대상 selector 보존 확인`
- 받는 사람: 에이전트 코어(@bshyuunn), 측정·규칙(@doithyun), LLM·프롬프트(@msterk11)
- 내용: ADR 0011의 비밀번호 정책과 axe 주입/label 경로 수정 반영 시점을 확인 부탁드립니다.
  평가기는 실제 행동 직전 DOM과 axe selector를 별도 sidecar에 보존합니다.
  서비스의 R02/R10 selector도 설명 생성 후 없어지지 않는 전달 규약이 필요합니다.
  비교기는 selector가 없으면 행동 지문으로 대체해 같은 이슈라고 주장하지 않습니다.
  #53 병합 후 small 변이도 실제 경로로 확인하겠습니다.

### 스테이징 #51 답변 초안

- 제목: `#51 후속: /api 프록시와 11/17 배포 준비`
- 받는 사람: 플랫폼 백엔드(@ojunhorange), PM(@hanchaehun)
- 내용: PR #36 승인대로 Vercel /api 프록시를 사용합니다. Railway API/worker 설정과
  API origin 기반 rewrite 생성기, 마이그레이션·환경 변수·브라우저 검증 절차를 준비했습니다.
  11/14 R2 저장 코드와 키 준비 후 API/worker 양쪽 설정을 연결하고 11/17까지 확인하겠습니다.
  API origin·서비스 접근 정보는 비공개로 연결 부탁드립니다. 지연 시 합의된 로컬 Compose로
  1차 리포트 테스트를 진행합니다.

추가 검증: 별도 `stepmeter-w3-m2` Compose 프로젝트의 API→RQ→worker→PostgreSQL→리포트
엄격 M2 E2E 8개가 통과했다(`data/w3/m2-e2e.log`). fake 모델과 합성 signup 화면이며
실제 모델 0차 평가 결과는 아니다. 격리 프로젝트의 컨테이너는 검증 후 종료하고 볼륨은 삭제하지 않는다.


## 11/13 PM 추가 지시 반영

Railway 개인 Trial에서 private `stepmeter-staging` 프로젝트와 `staging` 환경을 생성했다.
PostgreSQL/Redis Online, 각 DB 볼륨 500MB다. API/worker 준비 설정과 내부 DB/Redis 변수 참조를
적용했지만 GitHub 소스 미연결로 Offline이다. worker replica는 1개다.
사용자 요청에 따라 PM에게 프로젝트 Can Edit 권한 초대를 발송했고 수락 대기 상태를 확인했다.
Claude/R2 키 입력은 아직 확인되지 않았다.
Hobby 결제·$8 상한 설정·배포 완료로 기록하지 않는다.

기존 TOML 준비안은 신규 Railway 서비스에서 지원되지 않는 것을 실제 설정 화면과 공식 문서에서
확인해 제거하고, 대시보드 설정으로 바꿨다. 최신 상태와 남은 단계는
[스테이징 실제 구성 기록](../infra/staging.md#1113-railway-실제-구성-기록)에 있다.
