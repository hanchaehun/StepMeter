# StepMeter 작업 지침 (AI 코딩 에이전트용)

## 무엇이 기준인가
- 기획서(docs/*.docx)는 출발점일 뿐이다. 실제로 합의된 내용은 main 브랜치에 있다.
  우선순위: main의 코드·스키마 > docs/*.md 명세 > 기획서.
- 작업 시작 전에 최신 main을 받고(git pull origin main), 아래를 먼저 읽는다.
  - worker/schemas.py (행동·스냅샷·단계 데이터 형식)
  - apps/api/openapi.yaml (API 형식)
  - docs/*_spec.md (동결된 인터페이스 명세)
  - 작업할 폴더의 README.md
- 기획서와 main이 다르면 main을 따르고, 다르다는 사실을 사용자에게 알린다.

## 하지 말 것
- worker/schemas.py, apps/api/openapi.yaml을 편의상 고치지 않는다.
  바꿔야 하면 멈추고 사용자에게 알린다(CODEOWNERS 승인 필요).
- 커밋 메시지와 PR 설명을 쓰지 않는다. 작성자가 직접 쓴다.
- 테스트 기대값을 구현 코드를 보고 만들지 않는다. 사람이 계산하거나 명세(WCAG 등)에서 가져온다.
- API 키, .env, 학번·연락처, 참가자 데이터를 커밋하지 않는다(저장소 public).

## 할 것
- worker/metrics, rules, replay, matching은 테스트를 같이 만든다.
- 에이전트 관련 작업은 실행 로그나 스크린샷을 남긴다.
