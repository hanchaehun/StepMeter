# infra/

- **담당 역할:** 회귀 비교·인프라
- **하는 일:** docker-compose, Railway 설정, 스테이징·운영 배포.
- **참고:** 개발계획서 3장

## W1 실행 환경

Python 3.12, Node 22 (`.python-version`, `.nvmrc`), Docker Compose v2를 사용한다.
macOS에서 기본 `python3`이 3.9라면 설치된 `python3.12`를 명시한다.
이번 작업에서는 `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`를 사용했다.

저장소 루트에서:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
npm --prefix apps/web ci
npm run build:collect
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/ms-playwright"
python -m playwright install chromium
python -m unittest discover -s tests -v
ruff check worker tests apps/api infra/scripts benchmark/*.py
mypy --explicit-package-bases --follow-imports=silent worker/metrics/cursor_distance.py
npm --prefix apps/web test -- --run
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

로컬 unittest는 `TEST_DATABASE_URL`이 없으면 DB 테스트 1개를 건너뛴다.
DB까지 포함하는 검증은 아래 Docker 테스트를 사용한다. LLM 테스트는 가짜 client를 쓰므로 키가 필요 없다.
`requirements-dev.in`은 직접 의존성, `requirements-dev.txt`는 검증한 전이 의존성까지 고정한 파일이다.
의존성 갱신은 가상환경에서 `.in` 설치 → `pip freeze > requirements-dev.txt` → CI 전체 검증 순서로 한다.
axe-core는 수집/접근성 테스트용으로 루트 npm 의존성에 4.10.3을 고정했다.

## Docker

```sh
docker compose up -d --build --wait web db redis
docker compose run --rm migrate
docker compose --profile test build tests
docker compose --profile test run --rm tests
docker compose exec -T redis redis-cli ping
curl --fail http://127.0.0.1:8080/healthz
```

- 정적 리포트: http://127.0.0.1:8080 (목 JSON, 실제 측정 API 연결 전)
- 개발 DB: `127.0.0.1:5433`, 사용자/암호/DB 모두 `stepmeter` (로컬 전용)
- Redis: `127.0.0.1:6379`
- 호스트 포트가 겹치면 `WEB_PORT`, `POSTGRES_PORT`, `REDIS_PORT`를 바꾼다.
- `migrate`는 개발 DB에 `upgrade head`만 실행한다.
- `tests`는 포트를 공개하지 않는 별도 `test-db`를 사용한다. 테스트가 테이블을 비워도 개발 DB는 보존된다.
- 테스트 DB는 tmpfs, 개발 DB는 `pgdata` 볼륨이다. 종료는 `docker compose --profile test down`.
  `down -v`는 개발 데이터도 지우므로 일상 종료에 사용하지 않는다.
- `Dockerfile.worker`는 Chromium/테스트 실행 이미지다. 아직 없는 RQ 워커나 API 서버를 흉내 내지 않는다.
- Chromium은 일반 사용자로 실행하며, 이 이미지는 신뢰하는 로컬 테스트 페이지에 사용한다.

브라우저 확인과 스크린샷:

```sh
python infra/scripts/check_web.py http://127.0.0.1:8080
```

`screenshots/w1-report.png`는 git 제외다. 정적 리포트의 요약/상세 전환과 JavaScript 오류를 검사한다.

## CI

`.github/workflows/ci.yml`: PR, main push, 수동 실행. 유료 LLM 호출·배포·홀드아웃 평가는 실행하지 않는다.

| Job | 확인 |
|---|---|
| python | 수집 번들, Chromium, ruff, 이동거리 모듈 mypy, 전체 unittest, PostgreSQL 마이그레이션 |
| web | Vitest, TypeScript, Vite 빌드, 정적 리포트 artifact |
| docker | Compose 형식, 두 이미지 빌드, 컨테이너 전체 테스트, 웹 상태·HTML 응답 |

기존 코드를 일괄 재작성하지 않도록 ruff는 실행 오류 중심으로 시작한다.
mypy는 현재 통과하는 이동거리 모듈에 적용하며, 스키마는 기존 `ACTION_ADAPTER` 타입 표기 미비로
검사 대상에 직접 넣지 않는다. 공용 스키마는 변경하지 않았다. 전체 Python strict 검사나 프론트 ESLint 완료를 뜻하지 않는다.
GitHub 원격 실행은 작성자가 변경을 커밋·푸시한 뒤 확인한다.
매주 개발 앱을 평가하는 작업은 `eval.py`가 생기는 후속 단계에서 연결한다.

스테이징 절차는 [staging.md](staging.md), 이번 검증 결과는 [w1-status.md](w1-status.md)를 참고한다.
