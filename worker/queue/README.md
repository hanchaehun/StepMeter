# worker/queue/

- **담당 역할:** 플랫폼 백엔드
- **하는 일:** 작업 큐 연결, 진행률 갱신, 병렬 반복 실행.
- **참고:** 개발계획서 2.2, 4.6
- **할 일 (W2 큐 구현 때 먼저):** 진행률(progress)의 저장 위치와 계산식을 정하고 세 문서를 맞춘다. 지금은 `docs/worker_api_spec.md` 2절(Redis 작업 정보에 저장, 계산식 있음), `apps/api/db/models.py`·`apps/api/db/db-columns.md`의 `run.progress`(DB 칸, 계산식 미정), `apps/api/openapi.yaml`의 `Run.progress` 설명(계산식 미정)이 서로 다르다 ([ADR 0007](../../docs/adr/0007-w2-start-decisions.md) 담당 결정 대기).
