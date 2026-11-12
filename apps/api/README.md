# apps/api/

- **담당 역할:** 플랫폼 백엔드 (비교 API는 회귀 비교·인프라)
- **하는 일:** FastAPI 서버. 초대 코드 인증(X-Access-Code), 프로젝트별 일일 측정 상한(F17), 측정 요청 접수(mode: auto | agent | replay_only), 결과 조회, 스크린샷 서명 URL, 비교 API.
- **OpenAPI 스키마:** `openapi.yaml`에 합의본을 둔다. 10/30 동결(계획 10/27). FastAPI 구현이 생기면 FastAPI가 만드는 OpenAPI 문서를 이 합의본과 맞춘다.
- **참고:** 개발계획서 2.1, 11장, 13.1

## DB (PostgreSQL 16, SQLAlchemy 2 + Alembic)

- 테이블 정의: `db/models.py` (개발계획서 10장). 마이그레이션: `migrations/versions/`
- 설치: `pip install -r apps/api/requirements.txt`
- 로컬 DB (Docker). 5432를 이미 쓰는 PostgreSQL이 있으면 5433처럼 다른 포트를 쓴다.
  ```
  docker run -d --name stepmeter-pg -e POSTGRES_USER=stepmeter -e POSTGRES_PASSWORD=stepmeter -e POSTGRES_DB=stepmeter -p 5433:5432 postgres:16
  ```
- 레포 루트에서 실행. DB 주소는 환경 변수 `DATABASE_URL`로 준다.
  ```
  export DATABASE_URL=postgresql+psycopg://stepmeter:stepmeter@localhost:5433/stepmeter
  python -m alembic -c apps/api/alembic.ini upgrade head            # 테이블 만들기
  python -m alembic -c apps/api/alembic.ini revision --autogenerate -m "<변경 내용>"  # models.py를 바꾼 뒤 새 마이그레이션 만들기
  python -m alembic -c apps/api/alembic.ini downgrade -1            # 직전 마이그레이션 되돌리기
  ```
- 자동 생성한 마이그레이션 파일은 커밋 전에 직접 읽어 확인한다.
- 테스트: `TEST_DATABASE_URL`에 테스트 전용 DB 주소를 주고 `python -m unittest tests.test_db_migration` (DB를 비웠다가 다시 만든다)

## API 서버 (FastAPI)

- 코드: `main.py`. 요청·응답은 `openapi.yaml`을 따르고, `/docs`는 이 합의본을 그대로 보여준다.
- 환경 변수: `DATABASE_URL`, `REDIS_URL` (기본 `redis://localhost:6379/0`)
- 실행 (레포 루트, 마이그레이션 후)
  ```
  uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
  ```
  Compose(`m2` 프로필)에서는 `STEPMETER_API_COMMAND`에 위 명령을 준다 (infra/m2.md).
- 초대 코드 발급 (F17). 원문은 한 번만 출력되고 DB에는 sha256 지문만 저장된다. 받은 코드는 따로 보관한다.
  ```
  python -m apps.api.issue_code "라벨"
  ```
  요청마다 `X-Access-Code: <코드>` 헤더가 필요하다. 없거나 틀리면 401.
- 스크린샷 (이슈 #51): `STEPMETER_R2_ENDPOINT`와 `STEPMETER_R2_BUCKET`이 **둘 다** 있으면 Cloudflare R2, 없으면 로컬 디스크
  - 디스크: 워커가 `data/screenshots/{key}`에 저장하고 API가 `/screenshots/{key}`로 내준다 (로컬 개발, 로컬 Compose)
  - R2: 워커가 R2 버킷에 올리고, API는 900초짜리 서명 URL을 `screenshot_url`로 준다 (스테이징, 운영)
  - API와 워커 둘 다 아래 변수를 같은 값으로 받는다. 둘만 있고 키가 없으면 스크린샷 저장·조회 때 `KeyError`

  | 변수 | 값 |
  |---|---|
  | `STEPMETER_R2_ENDPOINT` | `https://<계정ID>.r2.cloudflarestorage.com` |
  | `STEPMETER_R2_BUCKET` | 버킷 이름 (스테이징 `stepmeter-screenshots-staging`) |
  | `STEPMETER_R2_ACCESS_KEY_ID` | 그 버킷만 읽고 쓰는 R2 API 토큰의 Access Key ID |
  | `STEPMETER_R2_SECRET_ACCESS_KEY` | 같은 토큰의 Secret Access Key. 저장소·이슈에 쓰지 않는다 |
- 아직 없는 것: 일일 측정 상한(429, W4), `GET /tasks/{id}/runs`, `/compare`, `/issues/{id}/label`, `/human-sessions`, `/tasks/{id}/aliases`
- 테스트: `TEST_DATABASE_URL`을 주고 `python -m unittest tests.test_api` (DB를 비운다. Redis는 가짜로 바꿔 쓴다)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- W4에 `GET /tasks/{id}/runs`(측정 목록)를 만든다 (ADR 0011 6번)
- `/tasks/{id}/aliases`, `/issues/{id}/label`, `/human-sessions`는 이번 일정에서 구현하지 않는다. 이 경로들은 `openapi.yaml`에 그대로 둔다 (ADR 0011 4번)
- 스테이징에서 워커가 저장한 스크린샷을 API가 내줄 수 있게 공용 저장(R2 또는 공유 볼륨)을 11/17까지 연결한다 (ADR 0011 6번)
- `GET /tasks/{id}`와 `GET /projects/{id}/tasks`를 `openapi.yaml`에 더하고 구현한다. 응답은 `Task` 형식 그대로이고, 다른 초대 코드의 과업이면 404다. `GET /tasks/{id}`는 11/17 스테이징 배포 전에, 과업 목록은 W4 측정 목록과 같이 낸다. `openapi.yaml` 변경은 CODEOWNERS 승인 PR로 하고 목 JSON도 같이 맞춘다 (ADR 0011 7번)
- 위 PR에서 RunMode 설명의 `auto` 문구("끊기면 그 지점부터 에이전트")를 "끊기면 에이전트로 처음부터 repeat_n회"로 고친다. 값과 형식은 바꾸지 않는다 (ADR 0011 8번)
- 스테이징에서 웹과 API의 출처가 다르면 CORS 설정이 필요하다. `/api` 프록시로 같은 출처에 둘지 CORS를 넣을지는 회귀 비교·인프라 담당과 정한다 (ADR 0011 6번)
