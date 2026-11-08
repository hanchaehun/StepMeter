# W2 M2 인프라 작업·검증 기록

2026-11-06 KST, 브랜치 `w2-m2-infra`, 기준 main `2bb2eb5`.
작업 시작 시 git pull --ff-only origin main으로 원격을 갱신했다. 이전 squash-merge된
w2-infra 이력은 보존하고 최신 origin/main에서 새 브랜치를 만들었다.

## 변경

- Compose m2 프로필에 API·worker·내부 fixture 서버 추가. DB 마이그레이션·Redis·fixture 준비 후 워커 실행.
- API 실행 명령은 STEPMETER_API_COMMAND로 전달. 백엔드의 실행 계약을 임의로 가정하지 않음.
- worker는 기존 큐 JOB_FUNC를 검사한 뒤 RQ runs 큐를 시작. 구현 부재 시 작업을 소비하지 않음.
- API·worker 공유 screenshots 볼륨과 비특권 사용자 쓰기 권한 준비.
- CI Python job에 Redis 서비스·TEST_REDIS_URL 추가.
- Compose tests에 별도 test-redis 연결. 개발 Redis와 테스트 Redis 분리.
- Docker CI에 워커 컨테이너의 브라우저·DB·Redis·fixture·스크린샷 검사 추가.
- Docker build context에서 홀드아웃·원시 증거 제외.
- infra/m2.md에 실행법·외부 의존성·전달할 이슈 초안, benchmark/w2-readiness.md에 앱별 잔여 상태 정리.

## 검증

| 검증 | 결과 |
|---|---|
| 기본 및 m2/test Compose 구성 | 정상 파싱 |
| GitHub Actions Redis 설정 | YAML 파싱·서비스·테스트 주소 확인 |
| Docker 이미지 빌드 | 성공 |
| 전체 Docker unittest | 147개 중 140 성공, 7 skip(API 미구현 M2 E2E만) |
| Redis enqueue 테스트 | skip 없이 성공 |
| worker 컨테이너 네트워크 | PostgreSQL SELECT 1, Redis PING 성공 |
| 브라우저와 fixture | 내부 서비스명으로 signup 접근, 요소 수집, 신청 후 done.html 도달 |
| 가짜 LLM 설정 | API 키 없이 답 목록 로드 성공 |
| 스크린샷 | 비특권 worker 저장 및 API 컨테이너에서 동일 파일 읽기 성공 |
| 시작 스크립트 | API 명령 미설정·코어 함수 부재 시 exit 1과 구체적 오류. API 명령 인자 전달 성공 |
| lint / diff | ruff·git diff --check 성공 |

검사기는 페이지 완료 URL의 쿼리 문자열도 허용하도록 수정 후 재검증했다.
실제 에이전트 루프 대신 브라우저로 fixture 조작·네트워크를 확인한 것이다.
API→큐→워커→metric→리포트 M2 합격이나 취소 후 코어 정리 완료를 의미하지 않는다.
호스팅된 GitHub CI는 미실행이며, 커밋·푸시·배포는 수행하지 않았다.

개발 DB·Redis와 격리한 `stepmeter-w2-check` 프로젝트(호스트 포트 15433/16379)에서 검증했다.
검증용 컨테이너만 down으로 종료했고, 기존 프로젝트와 볼륨은 삭제하지 않았다.
실행 로그와 완료 화면: `screenshots/m2-infra/` (git 제외).

## 남은 팀 의존 작업

- 원격 19개 브랜치 조사 결과 API 서버·에이전트 루프·드라이버 Python 구현 없음. 열린 PR 없음, 관련 이슈 #26. (11/8 PR #32로 API 서버 들어옴)
- 백엔드 실행 모듈·의존성·초대 코드 발급 명령, 에이전트 run(run_id)가 제공되면 실제 M2 E2E와 취소를 검증한다.
- 앱별 기준선·6종 결함 제작 분담과 PM 교차 검토가 필요하다. 공개 앱 준비 완료를 부풀리지 않는다.
- 보조 conversion fixture는 앱 개수에 포함하지 않으며 홀드아웃 설정·정답을 공개하거나 평가하지 않았다.
