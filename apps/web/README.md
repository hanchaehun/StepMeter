# apps/web/

- **담당 역할:** 리포트 UI · 대시보드 UI
- **하는 일:** React 대시보드. 리포트·단계 상세·오버레이는 리포트 UI, 측정 생성·진행·비교·재생 확인 화면과 측정 이력·추이 차트(F11)는 대시보드 UI가 맡는다.
- **참고:** 개발계획서 3장, 13장 / 서비스 기획서 6장

## 실행 (리포트 UI · W1 정적 리포트 화면)

레이아웃 명세는 [`docs/wireframes/f06-report.md`](../../docs/wireframes/f06-report.md). 이 슬라이스는 API 없이 `tests/fixtures/mock/api/*.json`을 읽어 그린다. 목 JSON은 10/30 동결(계획 10/27).

```
cd apps/web
npm install
npm run dev        # http://localhost:5173
npm test           # vitest (watch). CI처럼 한 번만: npx vitest run
npm run typecheck  # tsc
npm run gen:api    # apps/api/openapi.yaml → src/api/types.ts (손으로 고치지 않는다)
```

- 스택: Vite 5, React 18, TypeScript, Tailwind 3.4, shadcn/ui 스타일 Button, Vitest + Testing Library.
- 색 토큰은 `src/index.css`의 `:root`. 값은 F06 명세 "색 토큰" 표와 같다.
- 테스트 기대값은 목 JSON을 사람이 읽고 계산한 값이며 각 테스트에 근거 주석을 둔다 (개발계획서 15.2).
- 상태 변형 보기: `http://localhost:5173/?variant=allFailed` (전부 실패), `?variant=noIssues` (문제 0건), `?variant=mobile` (모바일 측정). 변형 데이터는 `src/fixtures/variants.ts`.

### 실제 API에 붙이기 (리포트 v1, W2)

- `.env.local`에 `VITE_API_URL=/api`를 두면 `/runs/{id}` 주소를 API에서 읽는다(`src/api/client.ts`). 없으면 목 모드. `?mock=1`을 붙이면 API 주소가 있어도 목 모드.
- `/api/*`는 Vite(dev·preview)가 `http://127.0.0.1:8000`으로 넘긴다(`vite.config.ts`의 proxy, 다른 주소는 환경변수 `API_PROXY_TARGET`). 브라우저가 8000을 직접 부르면 `X-Access-Code` 헤더 때문에 CORS preflight가 걸리는데 API에 CORS 설정이 없어서다. 배포 때는 같은 출처(리버스 프록시)로 두거나 API에 CORS를 넣어야 한다. 값은 `.env.local`에 쓴다(Git Bash에서 `VITE_API_URL=/api npm run build`처럼 넘기면 `/api`가 Windows 경로로 바뀐다).
- 확인한 것(11/8): 목 JSON을 내주는 API 스텁(8000, 코드 검사 포함)에 프록시로 붙여 헤드리스 Chrome으로 초대 코드 입력 → 틀린 코드 안내 → 리포트 → 새로고침 → 없는 run(404)까지 확인. 진짜 API(DB·Redis 필요)와는 아직 안 붙여 봤다.
- 호출 순서: `GET /runs/{id}` → completed일 때만 `GET /runs/{id}/report` → 대표 attempt의 `GET /runs/{id}/attempts/{n}/steps`. 초대 코드는 `X-Access-Code` 헤더, 화면에서 한 번 입력하면 브라우저 세션(`sessionStorage`)에만 남는다.
- 상태 화면(`src/components/report/ReportStatus.tsx`): 불러오는 중 / 초대 코드 입력(401) / 없는 측정(404) / 아직 진행 중·리포트 없음(409, run 상태로 구분) / 오류 + 다시 시도.
- 아직 없는 것: `GET /tasks/{id}`가 API에 없어 실제 모드에서는 과업 문장·사이트 주소 대신 "과업 #id"만 보인다(백엔드에 요청). 라우터 라이브러리는 대시보드 UI와 합의 뒤 도입하며, 지금은 `src/pages/ReportRoute.tsx`가 주소를 직접 읽는다.
- API 서버 띄우기: `apps/api/README.md`(uvicorn) 또는 `infra/m2.md`(Compose). 초대 코드 발급은 `python -m apps.api.issue_code "라벨"`.
- 화면은 기획서 6.1대로 "리포트 요약"과 "단계 상세" 둘. 단계 상세는 주소 해시와 동기화된다: `#issue-102`, `#step-1`. 뒤로가기로 요약에 돌아온다.

## ADR 0010에 따른 할 일

- 경로 밖 참고 이슈(`is_reference=True`, `step=null`)도 `element_key=null`일 수 있으므로, 리포트 화면(`StepDetail`, `IssueRow` 등)은 요소 없는 반복 루프 문제 여부를 `element_key === null`이 아니라 `rule_id === "R05"`로 판단한다 (ADR 0010)
- 성공한 시도가 0개면 run 단위 지표가 없으므로(0으로 채우지 않음) 리포트는 "성공한 시도 없음"으로 보여준다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 측정 생성·진행 화면을 11/22(M3)까지 만든다(`docs/wireframes/f01-measure-create.md`). 과업 입력칸 옆에 "입력값은 가짜 값으로 적고 실제 계정 정보는 적지 않는다"는 안내를 둔다 (ADR 0011 1·4번)
- 측정 이력(F11)은 측정 목록이 필수이고 추이 차트는 선택이다 (ADR 0011 4번)
- 재생 확인 화면·대응 관계 저장과 라벨 입력 화면은 이번 일정에서 만들지 않는다. 재생이 끊기면 끊긴 지점을 보여 주는 데까지만 한다 (ADR 0011 4번)
- 예상 소요 시간 옆에 "문헌값 기준 추정 · 시스템 응답 시간 제외"를 표시한다 (ADR 0011 3번)
- `GET /tasks/{id}`가 생기면 리포트 제목에 과업 문장과 사이트 주소를 보인다. 주소는 과업의 `project_id`를 `GET /projects` 결과에서 찾아 읽는다. 1차 외부 테스트(11/18) 전에 붙인다 (ADR 0011 7번)
- 측정 목록 화면은 `GET /projects/{id}/tasks`로 과업을 고른 뒤 `GET /tasks/{id}/runs`를 부른다 (ADR 0011 7번)
- 자기 측정에는 전용 초대 코드를 따로 발급해 쓴다. 초대 코드 입력칸이 비밀번호 칸(`type=password`)이라 에이전트는 과업 문장에 적힌 값만 입력한다. 팀이나 외부 테스트에 쓰는 코드는 과업 문장에 적지 않는다 (ADR 0011 1·6번)

## 측정 생성·진행·목록과 #75 UX 감사 반영 (2026-11-23)

- 측정 진행(`/runs/{id}/progress`, #80)·측정 목록(`/history`, #81) 화면을 넣었다. 헤더의 고정값 "Today 7 / 10 runs left"는 지웠다.
- 측정 생성의 "측정 예상"(시간·비용)과 `lib/estimate.ts`는 지웠다(#83). 반복 5회 안내는 숫자 없이 "3회보다 오래 걸립니다"다.
- #72 임시 회피: 같은 과업·뷰포트의 가장 최근 완료 측정에 대표 경로가 없으면 `mode=agent`로 보내고 429의 "재생만 하기"도 숨긴다(`src/api/measure.ts` `latestUsableBase`). 워커가 #72 제안 2를 고치면 되돌린다.
- UX 감사(`C:/git/stepmeter-ux-audit-2026-11-23/report.md`, 저장소 밖)에서 고른 항목:
  - 실제 API 모드의 `/`는 측정 목록이다. 목 모드의 `/`는 데모 리포트 그대로다(`infra/scripts/check_web.py`). 남은 `href="#"` 링크를 `/history`·`/new`로 연결했다(F-01).
  - 리포트 문제 목록: 같은 (규칙, 요소)는 한 줄 + "×n", 펼치면 원래 행이다. 참고는 기본 목록과 나눠 접고 심각도 대신 "참고"로 표시한다. 표시만 바꾸며 API·채점은 그대로다(F-02).
  - 숫자 표기는 `src/lib/format.ts`(소수 최대 자리, 비용 4자리)를 쓴다(F-03). 썸네일 자리 글자는 회색 바탕 위라 `text-muted`다(F-04, WCAG 1.4.3).
  - 확인 상자(측정 취소·예시 문장 바꾸기)는 Esc로 닫히고 연 버튼으로 포커스를 돌려준다. 취소 확인의 자동 포커스는 "계속 측정"이다(F-05).
  - 리포트 제목·주소 줄은 `overflow-wrap:anywhere`(F-06). 진행 화면의 알림 영역(role=status)은 하나이며 단계가 바뀔 때만 글자가 바뀐다(F-07).
  - 헤더 메뉴에서 갈 곳 없는 Report·Compare 링크를 뺐다. Report는 리포트 화면에서만 현재 위치로 보이고, Compare는 비교 화면(#82)이 생기면 더한다(F-09).
  - 측정 목록 주석에 예상 소요 시간이 "—"인 경우를 적었다(F-10). 2026-11-23부터 재생 재측정도 값을 저장한다. 초대 코드 안내의 "(F17)"을 뺐다(F-11).

## 비교 화면 (F07, #82)

- 주소 `/compare?base=&target=` → `GET /compare`. 범위는 #82 결정(B안 + 끊긴 지점 한 줄)이고, 순서는 개발계획서 7.5다: 문제 변화(새로 생김·해결됨 목록, 유지는 건수) → 재생 비교(+ `diverged_at_step` 한 줄) → 에이전트 비교 → 경로 정렬(추가·삭제 개수만). `null`인 블록은 숨긴다.
- 판정은 API의 `verdict`를 그대로 쓴다. `threshold`는 "판정 기준"으로 쓰고, 재생 비교의 클릭 수만 회 단위(±1회), 나머지는 %다(7.4). `not_comparable`이거나 `threshold`가 `null`이면 "비교 불가", `agent.spread_weak`면 "편차 추정 약함"이다.
- 판정 지표는 클릭 수·커서 이동 거리·예상 소요 시간 3개다. 나머지는 "참고 지표(판정 안 함)"로 접어서 값만 보인다. 문장 변환은 `src/lib/compare.ts`.
- 진입: 측정 목록에서 완료된 측정 두 줄을 고르면 먼저 만든 측정이 기준이 된다. 리포트 머리의 "Compare with #N"은 `/compare?base=N&target=이 측정`이다. 409가 오면 서버 메시지를 그대로 보인다.
- 목 모드: 목 서버의 `/compare`는 아는 측정끼리면 완료·과업·뷰포트를 확인해 409를 내고, 모르는 번호는 `tests/fixtures/mock/api/comparison.json`을 번호만 바꿔 돌려준다(예: `/compare?base=41&target=42`).
- 재생 확인 화면(후보 3개 묻기)·대응 관계 저장은 ADR 0011 4번에 따라 만들지 않았다.
