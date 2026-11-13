# W1 스테이징 연결

스테이징은 팀원이 인터넷에서 열어보는 테스트 환경이다. 로컬 Docker 실행과 별개다.
2026-11-01 정적 목 리포트를 Vercel의 별도 `stepmeter-staging` 프로젝트에 배포했다.
주소: https://stepmeter-staging-qgqm7euhh-jcwoo1204.vercel.app
API/큐 워커 진입점이 현재 main에 없어 전체 측정 서비스는 배포하지 않는다.

## Vercel: 정적 리포트

팀의 Vercel 계정에서 저장소를 Import하고 별도 테스트 프로젝트로 만든다.
Root Directory는 저장소 루트(`.`), Framework는 Other, Node는 22로 설정한다.
`apps/web`만 루트로 잡으면 루트의 목 JSON과 `vercel.json`을 놓칠 수 있다.
루트 `vercel.json`이 npm 설치·빌드 명령, `apps/web/dist` 출력과 SPA rewrite를 지정한다.
프론트에는 API 키나 DB 암호를 넣을 필요가 없다.
작성자가 직접 커밋·푸시한 브랜치를 연결해 배포하고 발급된 URL을 기록한다.

CLI를 사용하는 경우 Vercel 계정 로그인·프로젝트 연결 후 저장소 루트에서 `vercel`로 preview 배포한다.
이번 작업에서 CLI 설치나 계정 로그인을 대신 진행하지 않았다.

배포 뒤:

```sh
python infra/scripts/check_web.py https://발급받은-스테이징-주소
```

팀 전용 접근 보호가 켜진 배포는 먼저 브라우저에서 접근 가능 여부를 확인한다.
목 리포트 화면을 열고 요약/상세 전환, 새로고침, 모바일 폭을 확인한다.
Vercel 배포 이력에 URL·소스 커밋·확인자를 기록하고, 문제 시 이전 정상 배포를 다시 지정한다.
현재 화면은 목 데이터이며 측정 요청·DB 연동 완료를 의미하지 않는다.

## Railway: 후속 API/워커 연결

팀 계정에서 staging 환경과 전용 PostgreSQL·Redis를 만든다.
로컬 Compose의 공용 암호를 클라우드에 복사하지 않고 서비스가 발급한 연결 정보를 쓴다.
DB/Redis는 내부 네트워크 연결을 사용하고 API·워커 서비스의 환경 변수로만 전달한다.
SQLAlchemy/Alembic용 URL은 `postgresql+psycopg://` 형식이어야 한다.
비밀 변수는 Railway 변수 화면에 저장하고 소스·프론트 빌드 변수에 넣지 않는다.

API/워커 담당자에게 다음을 확정받은 뒤 해당 진입점으로 배포한다:

- API 실행 모듈·포트·상태 확인 경로
- 큐 워커 실행 명령 (큐 이름·페이로드·DB 쓰기 경계는 [docs/worker_api_spec.md](../docs/worker_api_spec.md)에서 정했다)
- 필수 환경 변수와 마이그레이션 실행 시점

Railway에서 같은 정적 화면을 Docker로 시험하려면 Config File Path를
`/infra/railway.web.toml`, 소스 루트를 저장소 루트로 지정한다.
이는 Vercel의 대안 경로이며 API 서버용 설정이 아니다.
Docker 웹은 Railway의 `PORT`를 받아 수신하며 `/healthz`로 준비 상태를 검사한다.
스테이징 DB의 `upgrade head`는 연결을 확정한 뒤 한 번 실행하고, 테스트 DB를 비우는 테스트는 연결하지 않는다.

## 완료 기록

배포 및 외부 브라우저 확인 결과다. API/워커를 포함한 전체 서비스 배포와 구분한다.

| 항목 | 현재 |
|---|---|
| 프론트 URL / 배포 ID | 위 URL / dpl_G7ZTk9qRLxSJyuMmtL6z7mW4xAJf, READY |
| Vercel 프로젝트 / 계정 공간 | stepmeter-staging / jcwoo1204 |
| 배포 소스 커밋 | 0986e9106bb6e0c601427044f7dd0bb194bb2de2 (PR #20, CI 통과) |
| 배포 방식 | 고정 커밋의 화면 소스 62개 파일 직접 업로드, 원격 빌드 |
| Vercel target | production: 새로 만든 테스트 전용 프로젝트의 첫 배포. 기존 프로젝트 변경 없음 |
| Railway staging / DB / Redis | 미연결 |
| API/워커 진입점 | 담당자 확인 필요 |
| 외부 브라우저 확인 | 데스크톱·모바일 200, 요약/상세 이동·상세 새로고침 성공, pageerror 없음 |
| 모바일 화면 제한 | 390px 뷰포트에서 문서 너비 505px; 기존 UI 가로 넘침은 UI 담당자 후속 확인 |
| 롤백 확인 | 첫 배포로 이전 정상 배포 없음. 롤백 실행은 하지 않음 |

GitHub 저장소 연결은 Vercel GitHub integration 권한 부족으로 거절되어,
커밋 객체에서 읽은 프론트 소스와 목 JSON만 직접 업로드했다. `.env`·키·벤치마크 원본/증거는 업로드하지 않았다.
따라서 이후 GitHub push가 자동 배포되지는 않는다. 자동 배포는 저장소 소유자의 Vercel GitHub 연동 후 연결한다.
로컬 문서의 미커밋 변경은 배포 소스에 포함하지 않았다.

프로젝트의 기존 배포 보호를 유지했다. 일반 주소는 Vercel 로그인/권한 확인이 필요할 수 있다.
검증은 인증된 연결에서 만든 임시 공유 링크로 수행했고, 그 링크의 접근 값은 문서에 저장하지 않았다.
팀원에게 실제로 공유할 때는 접근 권한 또는 만료되는 공유 링크를 확인한다.
스크린샷과 검증 JSON은 `screenshots/vercel-staging/`에 있으며 git 제외다.

공식 설정 참고: [Vercel project configuration](https://vercel.com/docs/project-configuration),
[Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[Railway config as code](https://docs.railway.com/config-as-code/reference).

## W3 전체 서비스 배포 준비 (2026-11-13 갱신)

#51의 API·워커 실행 정보를 기준으로 다음 순서로 배포한다.
PR #36 PM 리뷰에서 `/api` 리버스 프록시 사용은 승인됐다.
아래 설정 파일 추가는 클라우드 배포 완료 기록이 아니다.

1. Railway staging 프로젝트에 PostgreSQL·Redis와 API·worker 두 서비스를 만든다.
   신규 서비스는 기존 Config as Code에 opt-in할 수 없어 `railway.toml` 경로를 지정하지 않는다.
   대시보드에서 API·worker의 Builder=DOCKERFILE, Dockerfile path=`/infra/Dockerfile.worker`,
   시작 명령을 각각 `python -m infra.scripts.start_api`, `python -m infra.scripts.start_worker`로 설정한다.
   API pre-deploy는 아래 마이그레이션 명령, healthcheck는 `/openapi.json`·120초,
   두 서비스의 재시도는 3회로 설정한다. worker replica는 1개이며 공개 도메인을 만들지 않는다.
   기존 TOML 예시는 신규 서비스에서 사용할 수 없어 제거했다.
   근거: [Railway Config as Code 안내](https://docs.railway.com/config-as-code/reference).
2. API 변수: `DATABASE_URL`(postgresql+psycopg 형식), `REDIS_URL`, `PORT=8000`,
   `STEPMETER_ENV=staging`,
   `STEPMETER_API_COMMAND=uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`.
   API pre-deploy가 `upgrade head`를 실행한다. API 배포 성공 후 worker를 배포한다.
3. worker 변수: 같은 DB·Redis 주소, `ANTHROPIC_API_KEY`, `STEPMETER_ENV=staging`.
   `STEPMETER_LLM`, `STEPMETER_FAKE_REPLIES`는 설정하지 않는다.
4. R2 저장 코드가 main에 들어온 후 API·worker 양쪽에 PM이 준비한
   `STEPMETER_R2_ENDPOINT`, `STEPMETER_R2_BUCKET`, `STEPMETER_R2_ACCESS_KEY_ID`,
   `STEPMETER_R2_SECRET_ACCESS_KEY`를 비공개 변수로 설정한다. 버킷은 비공개,
   서명 URL 900초. PM은 11/13 추가 지시에서 버킷·토큰 준비 완료와 초대 후 변수 입력을 알렸다.
   백엔드 R2 저장 코드 반영은 별도로 확인한다(#51).
   Railway 서비스 간 로컬 디스크를 공유한다고 가정하지 않는다.
5. 확정된 API HTTPS 주소로 다음 명령을 실행한다. 출력은 검토용이며 원본을 덮어쓰지 않는다.
   `python -m infra.scripts.prepare_staging --api-url https://실제-API-주소 --output data/staging/vercel.json`
   검토 후 생성한 내용을 루트 `vercel.json`에 적용하고 Vercel에서 `VITE_API_URL=/api`를 설정한다.
   rewrite는 SPA fallback보다 앞에 온다. 프론트에는 비밀 변수를 넣지 않는다.
6. API 셸에서 `python -m apps.api.issue_code "외부테스트-A팀"`으로 팀별 코드를 발급한다.
   원문은 한 번만 보이며 로그·이슈에 붙이지 않는다.
7. 실제 브라우저에서 코드 입력 → 운영자가 만든 run → 상태 → 리포트 → 스크린샷을 확인한다.
   API/RQ/Postgres/실제 모델 연결의 성공·실패, 소스 커밋과 배포 URL을 기록한다.
   `/openapi.json` 200만으로 전체 측정 성공으로 세지 않는다.

11/17까지 연결되지 않으면 1차 테스트(11/18–11/21)는 운영자 PC Compose로 진행한다.
1차는 운영자가 측정을 생성하고 팀은 리포트를 본다. 생성·진행 화면은 11/22 기한이다.


## 11/13 Railway 실제 구성 기록

- 프로젝트: `stepmeter-staging`, private, 개인 계정. 환경: `staging`.
- 대시보드: https://railway.com/project/9ddda971-ee27-4ec1-925d-e5cea5040882
- 현재 Trial: 30일 또는 $5 크레딧. Hobby 결제·카드 등록은 하지 않았다.
  사용량 화면에 별도 Usage Limits 설정이 없어 $8 hard limit/알림은 아직 설정하지 못했다.
  Trial 크레딧과 명시적인 $8 사용량 상한을 같은 완료 항목으로 표현하지 않는다.
- PostgreSQL·Redis는 Online. 템플릿 DB 볼륨은 각각 500 MB다.
  API/worker에는 볼륨을 만들지 않았다. Postgres 공개 접속은 추가하지 않고 내부 DNS를 확인했다.
- Postgres 템플릿의 현재 기본 이미지는 `ghcr.io/railwayapp-templates/postgres-ssl:18`이다.
  로컬 검증 기준 PostgreSQL 16과 다르므로 실배포 전 마이그레이션·API DB 검증이 필요하다.
  새 DB에는 아직 테이블이 없고, 버전 교체나 볼륨 삭제는 하지 않았다.
- API·worker를 만들고 위 Dockerfile·시작 명령·API 마이그레이션·healthcheck 설정을 적용했다.
  worker는 1 replica, 두 서비스 모두 소스 미연결로 Offline이며 배포 성공이 아니다.
- API 변수 5개: DATABASE_URL, REDIS_URL, STEPMETER_ENV, PORT, STEPMETER_API_COMMAND.
  worker 변수 3개: DATABASE_URL, REDIS_URL, STEPMETER_ENV.
  DB 암호를 읽거나 복사하지 않고 같은 프로젝트의 Postgres 변수 참조를 사용했다.
  REDIS_URL도 같은 프로젝트의 Redis.REDIS_URL 참조로 연결했다.
- GitHub 소스 연결 창에서 `hanchaehun/StepMeter`를 검색했으나 No repositories found였다.
  계정의 Railway GitHub App 저장소 접근 설정을 연결해야 한다. 앱 권한은 임의로 확대하지 않았다.
- 사용자 요청에 따라 PM에게 프로젝트 Can Edit 권한 초대를 발송했고, Invite pending 상태를 확인했다.
  ANTHROPIC_API_KEY와 R2 변수 입력은 아직 확인되지 않았다.
- API 공개 주소가 아직 없어 Vercel rewrite에 임의 주소를 넣거나 프론트를 배포하지 않았다.
- 비용 계획: 12/4까지 약 1만원, 설정 가능해지면 Compute hard limit/알림 $8을 확인한다.
  worker 1대, DB용 소형 볼륨만 사용한다. 결제 시 영수증 전달은 작성자가 진행하며 아직 영수증은 없다.
  발표 후 올해 안에 서비스 삭제·Hobby 해지가 필요하다. 자동 삭제나 해지를 예약하지 않았다.
- 확인 스크린샷: `screenshots/railway-staging/services-2026-11-13.jpg` (git 제외).

완료한 것은 프로젝트·DB 생성과 API/worker 준비 설정이다. 소스 연결, 인증/R2 변수,
Postgres 18 환경에서의 DB 검증, API/worker 실배포, Vercel 연결, 비용 상한 확인은 남아 있다.
