# apps/api/

- **담당 역할:** 플랫폼 백엔드 (비교 API는 회귀 비교·인프라)
- **하는 일:** FastAPI 서버. 초대 코드 인증(X-Access-Code), 프로젝트별 일일 측정 상한(F17), 측정 요청 접수(mode: auto | agent | replay_only), 결과 조회, 스크린샷 서명 URL, 비교 API.
- **OpenAPI 스키마:** `openapi.yaml`에 합의본을 둔다. 10/30 동결(계획 10/27). FastAPI 구현이 생기면 FastAPI가 만드는 OpenAPI 문서를 이 합의본과 맞춘다.
- **참고:** 개발계획서 2.1, 11장, 13.1
- **할 일 (W2 큐 구현 때 먼저):** 진행률(progress)의 저장 위치와 계산식을 정하고 세 문서를 맞춘다. 지금은 `docs/worker_api_spec.md` 2절(Redis 작업 정보에 저장, 계산식 있음), `db/models.py`·`db/db-columns.md`의 `run.progress`(DB 칸, 계산식 미정), `openapi.yaml`의 `Run.progress` 설명(계산식 미정)이 서로 다르다 ([ADR 0007](../../docs/adr/0007-w2-start-decisions.md) 담당 결정 대기).

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
