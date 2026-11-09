# 배송현: 에이전트 벤치마크 구현 및 개발 앱 실행 기록

기준: `hanchaehun/StepMeter` main `1f1d6ffa77970cbb014e567f87897a10aab0e5e2`.
구현에는 API 키가 포함되지 않는다. 공개 개발 앱 기준선은 fake 모델의 격리된
API 통합 실행과 실제 Claude Sonnet 모델의 직접 에이전트 실행으로 확인했다.

## 계획과 구현 결과

1. 최신 main/ADR 0010/worker agent README를 기준으로 기존 API·큐·LLM·측정 모듈을 재사용한다.
2. `worker.agent.run.run(run_id)` 진입점을 구현한다. queued 상태의 요청만 원자적으로 시작하고,
   DB에서 과업/주소/모델/뷰포트를 읽는다. 각 attempt는 독립 브라우저 컨텍스트와 새 어댑터를 쓴다.
3. 요소 관찰 → 최대 30개 후보/번호 스크린샷 → 모델 행동 파싱 → 안전검사 → 드라이버 실행 →
   Step/ElementSnapshot/스크린샷/진행률 저장을 연결한다. 가려진 요소와 원래 el_id를 보존한다.
4. 호출별 LlmCall/비용, 종료 원인, URL+텍스트 성공 조건(둘 다 있으면 AND), 조건 없는 추정 성공,
   3회 반복 루프, 30단계/300초 제한, 로그인/CAPTCHA 차단, 취소를 처리한다.
5. 원문 상태의 각종 측정/규칙을 저장한다. 성공 attempt의 중앙값과 대표 attempt를 계산한 다음에만
   progress=100/completed로 만든다. 실패를 성공/0 중앙값으로 위장하지 않는다.
6. ADR 0010 드라이버·axe·후처리 계약을 보완한다. select는 활성 옵션만 1-based로 노출하고
   실제 native index로 실행하며, 관찰 이후 옵션이 바뀌면 중단한다.
7. FakeAdapter와 합성 HTML로 브라우저/ORM 회귀 테스트를 수행한다. 별도로 공개 개발 앱
   `react-shopping-cart`의 기준 과업을 fake 모델과 격리된 API·큐·DB에서 실행했다.

`worker/schemas.py`, `apps/api/openapi.yaml`, DB 모델/마이그레이션은 변경하지 않았다.

## 검증 환경 준비

기존 `infra/m2.md`, `compose.yaml`의 환경을 그대로 사용한다. Python 의존성은 기존 requirements,
JS 의존성은 루트 package-lock을 따른다. 개발 키는 사용자가 로컬에서 별도 설정하며 패키지에 없다.

```sh
npm ci
npm run build:collect
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
# 합성 HTML만 사용, 실제 모델/외부 사이트를 호출하지 않는 검사:
python -m unittest tests.test_agent_core tests.test_agent_review tests.test_driver_adr tests.test_adr_postprocess -v
```

`tests.test_agent_core`/`test_agent_review`는 임시 SQLite와 테스트 전용 progress shim을 사용한다.
프로덕션 경로는 기존 PostgreSQL update_progress를 그대로 사용한다. SQLite 통과가 PostgreSQL
행 잠금/동시 취소/RQ/HTTP 리포트의 합격을 의미하지 않는다.

## API 연결 실제 모델 실행 전 마지막 게이트

1. 팀 개발 환경 PostgreSQL/Redis/마이그레이션과 API·worker 시작을 확인한다.
2. 운영 데이터가 아닌 테스트 환경에서 기존 엄격 M2 명령으로 API→큐→worker→리포트를 재검증한다.
   `infra/scripts/run_m2_e2e.py`는 합성 signup fixture 기반이며 실제 모델 키가 필요 없다.
3. 그다음 `benchmark/w2.md`의 development 앱 하나를 선택하고 실제 URL·과업·성공 조건을 확인한다.
   holdout 데이터는 열거나 실행하지 않는다. `mode=agent`로 요청한다.
4. API·큐·PostgreSQL과 실제 모델을 함께 연결하는 실행은 아직 별도로 검증해야 한다.

아래 명령은 합성 fixture와 fake 모델을 쓰는 격리된 Compose 프로젝트에서만 실행한다.

```sh
docker compose -p stepmeter-agent-test --profile m2 up -d --build --wait api worker
docker compose -p stepmeter-agent-test --profile m2 run --rm api python -m infra.scripts.run_m2_e2e
```

## 중요한 범위/제한

- `agent` 모드 및 기준 run이 없는 `auto`만 실행한다. 명시적 agent 모드의 base_run_id는 무시한다.
  `replay_only`, 기준 run이 있는 auto는 replay 구현으로 잘못 가장하지 않고 run 실패로 처리한다.
- attempt는 독립 컨텍스트로 순차 실행한다. 최대 3개 병렬 스케줄링은 이번 패치에 포함하지 않았다.
- 격리된 합성 fixture·fake 모델로 API/RQ/PostgreSQL 리포트 E2E를 확인했다. 공개 개발 앱
  `react-shopping-cart` 기준선의 상품 검색·수량 2개 장바구니 추가도 fake 모델로 3회 성공했다.
  실제 Claude Sonnet의 자율 실행은 직접 worker 경로와 임시 SQLite에서 1회 성공했다.
  실제 모델과 API/RQ/PostgreSQL을 동시에 연결한 실행은 미검증이다.
- 로그인/봇 차단 및 위험한 버튼의 감지는 보수적인 휴리스틱이다. 모든 부작용을 차단하는 샌드박스가 아니다.
  모호한 submit, 사이트 특화 우회 표현 등의 위험은 남는다. 권한 있는 개발 fixture/벤치마크에서만 실행한다.
- 같은 URL의 문서 재로딩이 효과 관찰 context를 없애면 기존 observer는 error로 끝낸다.
  이를 정상 변화로 추측하거나 가짜 Step 효과로 저장하지 않는다.
- axe는 main document/open shadow path만 지원한다. iframe 대상 axe 검사는 제외하며 통과로 주장하지 않는다.
- 모델이 응답을 돌려준 호출은 파싱 실패나 중간 취소 시에도 기록한다. SDK가 응답 없이 실패하거나
  timeout된 호출의 청구/토큰은 알 수 없어 LlmCall로 추정 기록하지 않는다.
- 실제 Fitts 측정 불가(None)가 있으면 합계 키를 생략한다. 성공 경로들의 지표 키가 다르면 기존
  save_run_medians 계약에 따라 집계를 실패시켜 불완전한 중앙값을 보고하지 않는다.
- 브라우저 캡처/입력 내용은 테스트 대상 페이지의 민감정보를 포함할 수 있으므로 실제 계정/개인정보를 넣지 않는다.

## 적용 후 검증 기록 (2026-11-09)

- ZIP 기준 main `1f1d6ffa77970cbb014e567f87897a10aab0e5e2`에 패치 충돌 없이 적용했다.
- Python 3.12 집중 테스트 36개 통과. 전체 회귀 361개 실행, 실패 0개, 로컬 환경 의존 skip 55개.
- 격리된 Docker test-db/test-redis에서 전체 회귀 361개 실행, 실패 0개, skip 7개.
- 격리된 `stepmeter-agent-test` Compose 프로젝트에서 fake 모델·합성 signup 화면으로 엄격 M2 E2E 8개 통과. 기존 개발 DB나 큐를 사용하지 않았다.
- Ruff, 지정된 mypy 검사, 웹 테스트 86개, 웹 타입 검사와 빌드 통과.
- 공개 개발 앱 `react-shopping-cart` 고정 revision `0e867f1caf6abd7114aab6ae704a2824064e84e0`의
  기준선에서 fake 모델로 상품 과업을 3회 실행해 모두 `success`로 끝냈다. 각 6 Step,
  run `completed`·progress 100, run 지표 10개, 이슈 9개, API 응답 스키마 오류 0개였다.
  실행 요약과 장바구니 수량 2개 화면은 git 제외
  `benchmark/evidence/react-shopping-cart/agent-fake/`에 있다.
- 첫 fake 모델 직접 시험은 React 재렌더링 뒤 이전 요소 번호를 다시 클릭해 `stale el_id`
  오류로 끝났다. 고정 응답 목록에 `wait`와 새 관찰을 넣은 뒤 위 3회 실행을 검증했다.
- 실제 모델 시도에서 필수 `target`이 빠진 행동과 React 재렌더링으로 만료된 요소 번호가
  발견됐다. 파싱 실패는 최대 3회 재요청하고, 만료 번호는 행동을 실행하지 않은 채 새 화면을
  관찰하도록 수정했다. 두 경우 모두 회귀 테스트를 추가했다.
- 실제 Claude Sonnet 5.5 직접 실행은 임시 SQLite progress shim과 로컬 공개 개발 앱에서
  1회 시도 5 Step, LlmCall 6회로 `success`/progress 100을 기록했다. 마지막 화면에
  Broccoli `2 Nos.`와 합계 ₹240이 보이며, 성공 조건 `text_present: 2 Nos.`를 통과했다.
  비용 기록은 USD 0.0495756이다. 요약과 화면은 git 제외
  `benchmark/evidence/react-shopping-cart/agent-real/`에 보관한다.
