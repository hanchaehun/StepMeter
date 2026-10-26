# StepMeter

AI 에이전트가 웹사이트를 한 단계씩 써보며 UX를 숫자로 측정하는 도구.

- 기획: [docs/StepMeter_서비스기획서.docx](docs/StepMeter_서비스기획서.docx)
- 설계·일정: [docs/StepMeter_개발계획서.docx](docs/StepMeter_개발계획서.docx)

역할 배정과 협업 규칙은 팀 노션에서 관리한다. 폴더 구성은 개발계획서 12장을 따르고, 각 폴더의 `README.md`에 담당 역할과 참고할 문서 절이 적혀 있다.

## 공용 인터페이스

여러 역할이 함께 쓰는 데이터 형식은 개발계획서 13.1을 따르며 10월 27일에 동결한다.

| 위치 | 내용 |
|---|---|
| `worker/schemas.py` | ElementSnapshot, Step 등 워커 데이터 형식 (Pydantic 모델) |
| `apps/api/openapi.yaml` | API 스키마 합의본. 프론트 타입은 openapi-typescript로 생성 |
| `tests/fixtures/mock/` | 위 두 스키마에 맞춘 목 JSON. 10월 28일부터 각 파트가 병렬 개발에 쓴다 |
