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
