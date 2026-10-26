# apps/api/

- **담당 역할:** 플랫폼 백엔드 (비교 API는 회귀 비교·인프라)
- **하는 일:** FastAPI 서버. 초대 코드 인증(X-Access-Code), 프로젝트별 일일 측정 상한(F17), 측정 요청 접수(mode: auto | agent | replay_only), 결과 조회, 스크린샷 서명 URL, 비교 API.
- **OpenAPI 스키마:** `openapi.yaml`에 10월 27일 동결 합의본을 둔다. FastAPI 구현이 생기면 FastAPI가 만드는 OpenAPI 문서를 이 합의본과 맞춘다.
- **참고:** 개발계획서 2.1, 11장, 13.1
