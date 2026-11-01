# W1 스테이징 연결

스테이징은 팀원이 인터넷에서 열어보는 테스트 환경이다. 로컬 Docker 실행과 별개다.
이번 산출물은 배포 설정과 로컬 검증까지이며, 외부 URL 발급은 아직 하지 않았다.
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
- 큐 워커 실행 명령·큐 이름·페이로드·DB 쓰기 경계
- 필수 환경 변수와 마이그레이션 실행 시점

Railway에서 같은 정적 화면을 Docker로 시험하려면 Config File Path를
`/infra/railway.web.toml`, 소스 루트를 저장소 루트로 지정한다.
이는 Vercel의 대안 경로이며 API 서버용 설정이 아니다.
Docker 웹은 Railway의 `PORT`를 받아 수신하며 `/healthz`로 준비 상태를 검사한다.
스테이징 DB의 `upgrade head`는 연결을 확정한 뒤 한 번 실행하고, 테스트 DB를 비우는 테스트는 연결하지 않는다.

## 완료 기록

외부 배포 후 아래 빈 항목을 채워야 스테이징 완료다.

| 항목 | 현재 |
|---|---|
| 프론트 URL / 배포 ID | 미발급 |
| 배포 소스 커밋 | 미커밋 |
| Railway staging / DB / Redis | 미연결 |
| API/워커 진입점 | 담당자 확인 필요 |
| 외부 브라우저 확인·롤백 확인 | 배포 후 수행 |

공식 설정 참고: [Vercel project configuration](https://vercel.com/docs/project-configuration),
[Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[Railway config as code](https://docs.railway.com/config-as-code/reference).
