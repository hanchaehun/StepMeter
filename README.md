# StepMeter

AI 에이전트가 웹사이트를 한 단계씩 써보며 UX를 숫자로 측정하는 도구.

- 기획: [docs/StepMeter_서비스기획서.docx](docs/StepMeter_서비스기획서.docx)
- 설계·일정: [docs/StepMeter_개발계획서.docx](docs/StepMeter_개발계획서.docx)

## 역할별 작업 폴더

| 역할 | 주 작업 폴더 |
|---|---|
| PM · 통합·QA | `tests/e2e`, `docs` |
| 에이전트 코어 | `worker/driver`, `worker/agent`, `worker/replay` |
| LLM·프롬프트 | `worker/llm`, `prompts` |
| 측정 지표·규칙 | `worker/metrics`, `worker/rules`, `worker/a11y`, `ml/timing` |
| 수집·매칭 | `worker/collect`, `worker/matching`, `ml/issue_clf` |
| 플랫폼 백엔드 | `apps/api`, `worker/queue`, `ml/pipeline` |
| 회귀 비교·인프라 | `worker/compare`, `infra`, `benchmark`, `.github/workflows` |
| 리포트 UI | `apps/web` (리포트), `human-study` (수집 스크립트) |
| 대시보드 UI | `apps/web` (대시보드), `human-study` (동의서·세션) |

각 폴더의 `README.md`에 담당 역할과 참고할 문서 절이 적혀 있다.
여러 역할이 함께 쓰는 데이터 형식(`worker/schemas.py`, OpenAPI 스키마)은 개발계획서 13.1의 역할 간 인터페이스를 따른다.
