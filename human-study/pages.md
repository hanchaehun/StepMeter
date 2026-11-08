# 사람 실험 6페이지

사람 실험(개발계획서 9.1)에서 쓸 벤치마크 페이지 6개(정상 3, 결함 3)와 과업이다. 에이전트도 같은 페이지를 수행해 비교한다.

- **담당:** 대시보드 UI
- **상태:** 확정 (2026-11-08, PM 승인). 남은 일은 아래 "남은 것" 참고.
- **결함 페이지 안내 금지:** 참가자에게 어느 페이지에 결함이 있는지 알려 주지 않는다.

## 선정 기준

1. **과업:** `benchmark/apps.json`에 있는 과업을 그대로 쓴다. 에이전트와 사람이 같은 과업을 해야 비교할 수 있다.
2. **앱:** 개발 앱만 쓴다. `react-shopping-cart`는 의존성 교체와 데이터 로컬화가 끝나지 않아 뺐다. 남은 3개 앱의 과업이 정확히 6개다.
3. **중복 금지:** 6개 모두 다른 페이지다. 같은 사람이 같은 페이지의 정상판과 결함판을 모두 하면 두 번째 시간이 짧아진다.
4. **정상 페이지:** 기준선 패치(`benchmark/baselines/`)가 있는 페이지에서만 고른다.
5. **결함 유형:** 작은 타겟, 낮은 대비, 첫 화면 밖 핵심 버튼만 쓴다. 과업을 끝낼 수 있어 시간 표본이 남고, 스크롤 표본도 얻을 수 있다. 무반응 버튼과 가려진 요소는 과업이 끊길 수 있어 뺐다.

## 페이지와 과업

| # | 구분 | `page_id` | `apps.json` 과업 | 결함 유형 |
|---|---|---|---|---|
| 1 | 정상 | `sb-admin-2/register/baseline` | 회원가입 폼 입력 후 로그인 화면으로 이동 | 없음 |
| 2 | 정상 | `material-kit-react/products/baseline` | 제품 목록에서 정렬·필터 변경 | 없음 |
| 3 | 정상 | `material-kit-react/sign-in/baseline` | 로그인 폼 입력 후 비밀번호 표시 전환 | 없음 |
| 4 | 결함 | `sb-admin-2/login/small` | 로그인 폼 입력 후 Remember Me 선택 | 작은 타겟 (R01) |
| 5 | 결함 | `shadcn-admin/tasks/contrast` | Tasks 필터 후 작업 편집 열기 | 낮은 대비 (R02) |
| 6 | 결함 | `shadcn-admin/users/below-fold` | Users에서 사용자 초대 제출 | 첫 화면 밖 핵심 버튼 (R06) |

### `page_id` 형식

`<앱 id>/<페이지>/<변이>`로 쓴다(PM 결정, 2026-11-08). 변이 이름은 `benchmark/mutations/`의 파일 이름과 같고, 정상 페이지는 `baseline`이다.
`apps/api/openapi.yaml`의 `HumanSession.page_id` 설명은 아직 `"앱/변이"`라 담당자에게 수정을 요청했다. 타입은 문자열이라 수집과 업로드에는 영향이 없다.

### 결함을 넣는 방법

`mutate.py`(페이지 로드 직후 DOM 수정)를 쓰지 않고, 앱 소스에 직접 넣은 패치 파일을 쓴다. 기준선 패치(`benchmark/baselines/{앱}.patch`)를 적용한 뒤 변이 패치(`benchmark/mutations/{앱}/{변이}.patch`)를 적용해 로컬 서버를 띄운다. 참가자는 진행자 PC 브라우저에서 이 서버를 연다. 패치를 적용해 띄우는 틀은 PM이 준비한다.

| # | 패치 | 상태 |
|---|---|---|
| 4 | `benchmark/mutations/sb-admin-2/small.patch` | 대시보드 UI가 만드는 중 |
| 5 | `benchmark/mutations/shadcn-admin/contrast.patch` | #35로 main에 있음. 행 메뉴의 Edit 글자에 흐린 글자 클래스(대비 1.47:1) |
| 6 | `benchmark/mutations/shadcn-admin/below-fold.patch` | #35로 main에 있음. 설명 문단의 `min-h-svh` 때문에 Invite User가 첫 화면 밖(top 892px) |

`shadcn-admin`의 기존 문제는 `benchmark/baselines/shadcn-admin.patch`가 정리했다(`benchmark/selection.md` "shadcn-admin 클리닝"). 5·6번은 이 패치를 그대로 쓰기로 PM과 확인했다.

## 참가자에게 주는 과업 문장

입력값은 아래 가짜 값을 쓴다. 실제 이메일이나 비밀번호를 넣지 않게 하기 위해서다.

| # | 과업 문장 | 끝난 것으로 보는 시점 |
|---|---|---|
| 1 | 이름 `Minsu Kim`, 이메일 `study@example.com`, 비밀번호 `Study1234`(확인 칸에도 같은 값)를 입력하고 **Register Account**를 눌러 주세요. | 로그인 화면으로 이동 |
| 2 | 정렬을 **Price: Low-High**로 바꾸고, 필터에서 Category를 **Apparel**로 골라 주세요. | Category 선택 (목록은 바뀌지 않음) |
| 3 | 이메일을 `study@example.com`, 비밀번호를 `Study1234`로 바꿔 입력하고, 비밀번호가 보이게 해 주세요. | 비밀번호 표시로 전환 |
| 4 | 이메일 `study@example.com`, 비밀번호 `Study1234`를 입력하고 **Remember Me**를 선택해 주세요. | 체크박스 선택 |
| 5 | Status가 **Todo**인 작업만 보이게 한 뒤, **TASK-8202** 작업의 **Edit** 화면을 열어 주세요. | `TASK-8202`의 수정 화면 열림 |
| 6 | **Invite User** 창을 열고 이메일 `study@example.com`, Role **Admin**을 입력한 뒤 **Invite**를 눌러 주세요. | "You submitted the following values:" 알림 표시 |

6번 과업은 처음에 "창을 열었다가 Cancel로 닫기"였으나, #35에서 `apps.json` 과업이 "사용자 초대 제출"로 바뀌어 맞췄다. 취소는 화면에 끝난 표시가 남지 않아 에이전트의 성공 조건을 정할 수 없기 때문이다. 기준선 패치에서 알림이 사라지지 않게 해 두었다.

2번 과업을 시작하기 전에 진행자가 "이 페이지는 데모라 정렬이나 필터를 바꿔도 목록은 바뀌지 않습니다"라고 안내한다. 목록이 안 바뀌어 참가자가 헤매는 시간이 측정값에 섞이지 않게 하기 위해서다. 결함 여부는 알려 주지 않는다.

## 실행해서 확인한 것 (2026-11-06)

`benchmark/apps.json`의 고정 커밋으로 로컬 개발 서버를 띄우고 브라우저에서 과업 문장대로 직접 수행했다.

- `shadcn-admin` (`e16c87f`, 기준선 패치 없음): `npx pnpm@10.18.3 install --frozen-lockfile` 후 `pnpm dev`, 포트 8768
- `material-kit-react` (`69e780a`, 기준선 패치 적용 상태): `npm ci` 후 `npm run dev`, 포트 8767

| # | 결과 | 메모 |
|---|---|---|
| 2 | 끝까지 됨 | 정렬 메뉴의 Price: Low-High, 필터 창의 Category Apparel 확인. 정렬과 필터를 바꿔도 제품 목록은 바뀌지 않는다 |
| 5 | 끝까지 됨 | 로그인 없이 `/tasks` 진입. 작업 상세 화면이 따로 없어 `apps.json`의 "작업 상세 열기"를 행 메뉴의 Edit 화면으로 해석했다 |
| 6 | 끝까지 됨 | 로그인 없이 `/users` 진입. Invite User 창이 열리고 Cancel로 닫힌다 |
| 3 | 끝까지 됨 | 이메일과 비밀번호 칸에 기본값이 들어 있어 지우고 새로 입력해야 한다. 비밀번호 표시 전환 확인 |

- **2번 목록:** 정렬과 필터를 바꿔도 목록이 바뀌지 않아, 과업 전에 안내하기로 했다(위 "참가자에게 주는 과업 문장" 참고).
- **5번 작업 ID:** 작업 목록은 `src/features/tasks/data/tasks.ts`가 고정 시드(`faker.seed(12345)`)로 만든 100개다. Todo는 16개이고, 기본 정렬에서 필터 후 맨 위는 `TASK-8202`다. 처음 문장의 "첫 번째 작업"은 참가자가 정렬을 바꾸거나 다른 필터를 같이 걸면 달라지고, 제목이 라틴어 더미 문장이라 진행자가 맞는 작업을 열었는지 확인하기 어렵다. 그래서 과업 문장에 ID를 넣었다.

## 확정 전 확인할 것

- [x] `shadcn-admin`을 실행해 5·6번 과업이 끝까지 되는지 확인한다.
- [x] `material-kit-react`의 열린 필터 상태를 포함해 2번 과업을 확인한다.
- [x] 3번 과업을 실행해 확인한다.
- [x] 5번 과업 문장에 작업 ID(`TASK-8202`)를 넣을지 정한다. → 넣는다.
- [x] 2번 과업에서 목록이 바뀌지 않는다는 것을 세션 전에 안내할지 정한다. → 안내한다.
- [x] `shadcn-admin` 기준선을 확인한다. → `benchmark/baselines/shadcn-admin.patch`(#35)로 정리됨.
- [x] 결함 주입 담당과 4·5·6번의 페이지와 결함 유형을 맞춘다. → 지금 안대로 확정, 4·5·6번 모두 대시보드 UI 담당.
- [x] `page_id`에 쓸 변이 이름을 맞춘다. → `<앱 id>/<페이지>/<변이>`.
- [x] 6번 과업을 `apps.json`에 맞춰 "초대 제출"로 바꾼다.

## 남은 것

- [ ] 4번 `benchmark/mutations/sb-admin-2/small.patch`를 만들고 렌더링으로 발현을 확인한다.
- [ ] 6번 과업을 바뀐 문장대로 다시 실행해 끝까지 되는지 확인한다.
- [ ] 파일럿에서 전체 시간이 20분 안에 끝나는지와, 로그인 과업 3·4번이 비슷해 학습 효과가 생기는지 확인한다.
