# 0004. 테스트 계정은 이번 일정(12/4까지)에서는 구현하지 않는다

- **날짜:** 2026-10-30 (OpenAPI 동결, PR #11)
- **근거 기록:** [apps/api/openapi.yaml](../../apps/api/openapi.yaml) `TaskCreate`, [apps/api/db/db-columns.md](../../apps/api/db/db-columns.md) `credentials_ref`, [docs/wireframes/f01-measure-create.md](../wireframes/f01-measure-create.md)

## 배경

서비스 기획서 5장 F01은 테스트 계정(선택)을 입력받는다.
개발계획서 10장은 계정 정보를 암호화 저장소에 따로 두고 task에는 참조값(`credentials_ref`)만 저장하도록 했다.

## 결정

테스트 계정은 이번 일정(12/4까지)에서는 구현하지 않는다(2026-11-05 변경, [ADR 0008](0008-schedule-to-1204.md)). 처음 결정은 M3(11월 22일) 이후로 미루는 것이었다.
`TaskCreate`와 `task` 테이블에 `credentials_ref`가 없고, F01 입력칸은 비활성이며, 로그인이 필요한 화면은 측정하지 않는다.
보관 위치와 기간은 구현할 때 정한다.
로그인·가입 폼에 과업 문장의 가짜 값을 입력하는 과업은 측정한다(2026-11-10 추가, [ADR 0011](0011-w3-plan-gaps.md) 1번). 계정이 있어야 들어가는 화면은 여전히 측정하지 않는다.

## 대안

- 지금 받는다: 암호화 저장소가 정해지지 않아 보관할 곳이 없다.
