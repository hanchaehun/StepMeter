# W1 작업·검증 기록 (2026-11-01 KST)

작업 브랜치 `chore/w1-infra`, 기준 main `da554da`. `git pull origin main`은 Already up to date.
커밋·푸시·PR 작성은 하지 않았다. 공용 `worker/schemas.py`와 `apps/api/openapi.yaml`도 변경하지 않았다.

## 구현한 것

- Python 3.12 버전 파일·로컬 가상환경·고정 개발 의존성, Node 22 버전 파일
- 누락된 axe-core 4.10.3을 공용 npm 의존성으로 고정
- PR/main/수동 GitHub Actions: Python·DB·브라우저, 프론트, Docker 3개 job
- Chromium 테스트 이미지와 비특권 nginx 정적 리포트 이미지
- Compose: 개발 PostgreSQL/Redis/웹, 개발 DB 마이그레이션, 별도 테스트 DB/테스트 프로필
- Vercel 정적 리포트 설정, Railway Docker 웹 대안 설정·실제 연결 절차
- 벤치마크 6개 출처/라이선스/커밋/과업 기록, 개발 4·홀드아웃 2 분리
- 두 개발 앱의 지정 페이지 클리닝 패치와 고정 커밋 체크아웃 도구
- 브라우저/axe 증거 생성 도구, 실행 문서

## 실행 결과

| 검증 | 결과 |
|---|---|
| 호스트 Python 3.12 전체 unittest | 62개 실행, 성공, DB 1개 skip (DB 없는 환경) |
| Docker Python 3.12 전체 unittest | 62개 모두 성공, skip 없음; 테스트 DB 마이그레이션 포함 |
| 프론트 Vitest | 8개 파일, 58개 테스트 성공 |
| 프론트 TypeScript / Vite | 성공 (호스트 Node 24 및 Docker Node 22 빌드) |
| ruff / 이동거리 모듈 mypy | 성공; 전체 strict 타입 검사는 아님 |
| Compose 설정 / 웹·테스트 이미지 빌드 | 성공 |
| 개발 PostgreSQL / Redis | healthy, 마이그레이션 head 성공, Redis PONG |
| Docker nginx /healthz | 200, ok |
| 정적 리포트 브라우저 | 요약→상세→요약 성공, pageerror 없음, 스크린샷 확인 |
| MUI 기준선 타입 검사·프로덕션 빌드 | 성공 (큰 번들 경고 있음) |
| 고정 커밋 체크아웃·패치 적용 | 두 개발 앱 모두 성공, benchmark/apps 아래 git 제외 상태로 준비 |
| 기준선 상호작용 | Bootstrap 폼 입력·키보드 체크박스·로그인/회원가입 이동, MUI 비밀번호 표시 전환·필터 열기/Escape 닫기 성공 |
| GitHub Actions 호스팅 실행 | 아직 실행하지 않음: 작성자의 커밋·푸시 필요 |

호스트 테스트 로그: `/private/tmp/stepmeter-w1-python-tests.txt`.
컨테이너 테스트 로그: `/private/tmp/stepmeter-w1-docker-tests.txt`.
화면 증거: `screenshots/w1-report.png`, `benchmark/evidence/` (git 제외).
원시 데이터에는 원본 앱의 데모 연락처가 있어 public 커밋 대상에서 제외했다.
작업 종료 시 Docker web/db/redis는 실행 중이다. 검증 전용 test-db와 임시 벤치마크 서버 2개는 중지했다.

## 벤치마크 지정 페이지

axe 4.10.3, Chromium 141, desktop 1280×800. 아래 숫자는 노드 수가 아니라 violation rule 수다.

| 앱/페이지 | 원본 | 패치 후 | 패치 후 incomplete |
|---|---:|---:|---:|
| SB Admin 2 / login.html | 4 | 0 | 0 |
| SB Admin 2 / register.html | 3 | 0 | 0 |
| Material Kit / sign-in | 3 | 0 | 1 |
| Material Kit / products | 5 | 0 | 1 |

MUI의 남은 incomplete는 배경/의사 요소 등에 따른 color-contrast 자동 판정 불가다.
네 페이지의 초기 화면 검증이며 열린 필터·모든 모바일 상태·모든 원본 페이지 검증은 아니다.
스크린샷을 검토했으나 수동 WCAG 전체 점검/PM 최종 승인은 미완료다.
따라서 두 앱은 클리닝 패치 준비 완료이며 최종 정상 기준선 승인은 보류다.
벤치마크 앱 1개를 LLM 에이전트로 완주한 기록은 아니며 그 팀 완료 기준도 충족했다고 주장하지 않는다.

## W1에서 남은 것

1. 팀 배포 계정에 연결해 외부 스테이징 URL 발급·접속 확인. 현재 로컬 URL은 외부 스테이징이 아니다.
2. API/큐 워커 진입점과 환경 변수 계약 확인. main에는 실행 서버/큐 루프가 아직 없다.
3. 앱별 담당자 확정·정상 기준선 교차 검토. 커머스 후보는 외부 데이터 로컬화와 구형 빌드 도구 교체가 필요하다.
4. 작성자가 변경을 읽고 직접 커밋·푸시한 뒤 GitHub Actions 원격 실행 확인.

기존 프론트 설치에서 npm audit는 9건(중간 5, 높음 2, 치명적 2)을 보고했다.
이번에는 다른 담당자의 Vite/Vitest 등 버전을 임의로 올리지 않았다. 정적 파일 배포를 기준으로 준비했으며
후속 의존성 업데이트 검토가 필요하다. MUI 원본 의존성 audit 보고도 남아 있어 최종 기준선 동결 전 함께 확인한다.

## 사용자에게 제안하는 GitHub 이슈 초안

제목: W1 스테이징용 API·큐 워커 실행 계약 확정

받는 사람: 플랫폼 백엔드·에이전트 코어 담당

내용: API 모듈/실행 명령/포트/health 경로, 큐 워커 명령/큐 이름/페이로드,
필수 환경 변수와 DB 쓰기 경계·마이그레이션 실행 시점을 공유해 주세요.
현재 main에는 진입점이 없으므로 확정 후 Docker·Railway 서비스를 연결하려고 합니다.

제목: W1 벤치마크 6개 역할 분담·기준선 교차 검토

받는 사람: PM·리포트 UI·대시보드 UI·LLM/프롬프트·플랫폼 백엔드 담당

내용: benchmark/apps.json의 개발 4/홀드아웃 2와 과업을 검토하고 앱별 담당자를 정해 주세요.
SB Admin 2와 Material Kit의 지정 페이지 패치·axe 결과를 준비했습니다. MUI의 대비 incomplete와
동적 상태를 수동 확인하고 기준선 승인 여부를 정해 주세요. 홀드아웃 설정·정답은 제한된 장소에서 관리해야 합니다.

제목: 기존 프론트 개발 의존성 audit 결과 확인

받는 사람: 리포트 UI·대시보드 UI 담당

내용: 기존 잠금 파일의 npm ci에서 audit 9건을 확인했습니다. 기존 테스트·타입 검사·빌드는 통과하며
이번 인프라 작업에서는 버전을 바꾸지 않았습니다. npm audit 상세와 개발 서버/배포 영향 범위를 확인하고 업데이트 범위를 합의해 주세요.

이슈는 초안만 작성했으며 GitHub에 등록하거나 다른 사람에게 메시지를 보내지 않았다.
