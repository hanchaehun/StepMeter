# 0005. 초대 코드별로 프로젝트를 분리한다

- **날짜:** 2026-10-30 (PR #12)
- **근거 기록:** [apps/api/openapi.yaml](../../apps/api/openapi.yaml) 첫 설명, [apps/api/db/models.py](../../apps/api/db/models.py) `Project.owner_id`, [tests/test_db_migration.py](../../tests/test_db_migration.py)

## 배경

F17 최소 접근 제어는 로그인 없이 `X-Access-Code` 헤더의 초대 코드로 사용자를 제한한다.
`project.owner_id`가 무엇을 가리킬지 정해지지 않았었다.

## 결정

초대 코드 1개가 프로젝트 여러 개를 가진다. `project.owner_id`는 요청한 코드의 `access_code.id`다.
다른 코드의 project와 그 아래 task·run·issue는 보이지 않는다(404).

## 대안

- 코드와 관계없이 모든 프로젝트를 공유한다: 다른 초대 코드를 받은 사용자끼리 서로의 프로젝트가 보인다.
