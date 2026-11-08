# W1 벤치마크 선정

원본 소스와 MIT 라이선스를 확인하고 `apps.json`에 정확한 커밋을 고정했다.
선정과 실행 준비를 구분한다. 6개 모두 실행·클리닝 완료 상태는 아니다.

| 앱 | 분할 | 선정 이유 / 실행 상태 |
|---|---|---|
| satnaing/shadcn-admin | 개발 | Tailwind/shadcn, 클라이언트 라우팅·대화상자·분할 로딩. 배포용 빌드 실행, Tasks·Users 과업 경로 클리닝 검증 (W2, 아래 "shadcn-admin 클리닝") |
| minimal-ui-kit/material-kit-react | 개발 | MUI, React Router lazy, 필터 Drawer. 실행·빌드, 로그인/제품 화면 클리닝 검증 |
| StartBootstrap/startbootstrap-sb-admin-2 | 개발 | Bootstrap/jQuery 정적 UI. 로그인/회원가입 화면 실행·클리닝 검증 |
| sivadass/react-shopping-cart | 개발 | 모바일 대응 커머스·SCSS·검색/장바구니. 원본 검토; CRA4/node-sass5 교체와 외부 상품 JSON·이미지 로컬화 필요 |

홀드아웃 2개는 이 public 저장소에 적지 않는다. 목록·설정·정답은 회귀 비교·인프라 담당이 `benchmark/holdout/`(git 제외)과 접근을 제한한 장소에서 관리한다.

원본 링크·커밋·라이선스 위치·각 앱 과업 2개·시작 명령은 [apps.json](apps.json)에 있다.
최소 3개 SPA의 구조를 소스에서 확인했으나 실제 SPA 스트레스 테스트는 W2 작업이다.
모바일 커머스 후보는 별도 백엔드 없이 동작하도록 데이터 로컬화가 필요하므로 아직 준비 완료로 세지 않는다.
후속 준비에서 비용이 지나치게 커지면 앱을 교체하고 고정 커밋/선정 근거를 함께 갱신한다.
라이선스 파일이 없는 jeffersonRibeiro/react-shopping-cart와 표준 라이선스가 없는 Anon은 제외했다.

## 재현

```sh
python benchmark/checkout.py sb-admin-2 material-kit-react
python -m http.server 8766 --bind 127.0.0.1 --directory benchmark/apps/sb-admin-2
# 별도 터미널
npm --prefix benchmark/apps/material-kit-react ci
npm --prefix benchmark/apps/material-kit-react run dev -- --host 127.0.0.1 --port 8767
```

checkout은 고정 커밋을 받고 `baselines/*.patch`가 있으면 적용한다.
이미 존재하는 디렉터리는 덮어쓰지 않는다. 원본 소스는 git 제외하고 패치와 출처를 관리한다.
기본 호출은 개발 4개만 받는다. 홀드아웃은 평가 담당자가 `benchmark/holdout/apps.json`을 두고 `--include-holdout`을 명시해야 한다.
홀드아웃 변이·정답은 이 public 저장소에 올리지 않고 접근을 제한한 별도 장소에서 관리한다.
이번에는 홀드아웃 변이·정답을 만들거나 평가하지 않았다.

## 기존 결함 클리닝

SB Admin 2의 로그인·회원가입: 명시적 폼 라벨, 잘못된 설명 참조 제거, main 랜드마크,
일반 텍스트 4.5:1 기준에 미달한 글자/버튼 대비 수정. Google Fonts 원격 의존도 제거했다.
실제 계정 생성·인증은 없는 데모이므로 과업은 폼 조작·페이지 이동까지만 사용한다.

Material Kit의 로그인·제품 목록: 비밀번호/소셜/검색 버튼 이름, H1·가격 표시의 헤딩 구조,
사이드바·출처 링크의 랜드마크, 내비게이션·가격 텍스트 대비를 수정했다.
필터 내부·모든 페이지·모든 동적 상태까지 깨끗함을 보증하는 패치는 아니다.

`audit.py`는 axe 4.10.3의 전체 결과와 1280×800 스크린샷을 `evidence/`에 보존한다.
각 앱 `before`는 고정 원본, `after`는 해당 패치 적용 결과다.
원본 데모 연락처 등이 포함될 수 있어 원시 JSON·스크린샷은 git 제외한다. 수치 요약은 `infra/w1-status.md`에 남긴다.

```sh
python benchmark/audit.py sb-admin-2 http://127.0.0.1:8766 after
python benchmark/audit.py material-kit-react http://127.0.0.1:8767 after
```

수정 후 검사한 네 페이지의 axe violations는 0이다. MUI 두 페이지에는
`color-contrast` incomplete가 남아 별도 수동 점검이 필요하다.
자동 검사 0건을 WCAG 전체 준수나 최종 정상 기준선 승인으로 해석하지 않는다.
정상 기준선 최종 확정은 PM 교차 검토와 앱 담당자의 과업/동적 상태 확인 후 진행한다.

## shadcn-admin 클리닝 (W2, 플랫폼 백엔드)

개발 모드의 TanStack Router 도구 배지가 요소 목록과 axe 결과에 섞이므로 배포용 빌드로 띄운다.

```sh
python benchmark/checkout.py shadcn-admin
cd benchmark/apps/shadcn-admin
npx pnpm@9.15.9 install --frozen-lockfile
npx pnpm@9.15.9 run build
npx pnpm@9.15.9 exec vite preview --host 127.0.0.1 --port 8772
```

과업 경로의 열린 상태까지 검사했다: Tasks 목록 → Status 필터 열림 → 행 `⋯` 메뉴 열림 → Edit("Update Task") 패널,
Users 목록 → Invite User 대화상자 → 역할 선택 → 제출 후 알림.
클리닝 전 axe violations: `button-name`(Rows per page 선택), `color-contrast`(Suspended 배지 4.02:1),
`aria-dialog-name`(필터 팝업), `empty-table-header`, `page-has-heading-one`, `region`, `skip-link`.
`baselines/shadcn-admin.patch`가 이름·대비·h1·사이드바 navigation·본문 id를 고치고,
검색 대화상자의 숨김 제목이 대화상자 밖에 있던 원본 오류를 안으로 옮긴다.

클리닝 후 8개 상태 중 7개는 violations 0이다. 행 `⋯` 메뉴를 연 상태에만 `region`(best-practice) 1건이 남는다.
Radix가 메뉴를 표의 overflow 상자에 잘리지 않게 body 끝에 포털로 붙이는 구조 때문이며,
메뉴는 `role="menu"`로 접근 가능하다. StepMeter 규칙(R02 `color-contrast`, R10 이름 계열)에 연결되지 않는 axe 규칙이라 채점에 영향이 없다.
`incomplete`의 `aria-valid-attr-value`(닫힌 팝업을 가리키는 aria-controls)와 `color-contrast`(검색창 `⌘K` 기호)는 결함이 아니라고 판단했다.

과업 2는 "초대 대화상자 열고 취소"에서 "초대 제출"로 바꾼다. 취소는 화면에 끝난 표시가 남지 않아 성공 조건을 정할 수 없다.
제출 결과는 알림("You submitted the following values:")으로만 보이는데 기본 5초 뒤 사라져,
에이전트가 완료를 알리기 전에 없어질 수 있다. 패치에서 알림이 사라지지 않게(`duration={Infinity}`) 바꿨다. UX 결함 6종과 관계없는 설정이다.

| 과업 | 경로 | 성공 조건 |
|---|---|---|
| Tasks 필터 후 작업 편집 열기 | /tasks → Status 필터 선택 → 첫 행 `⋯` → Edit | `text_present: "Update Task"` |
| Users에서 사용자 초대 제출 | /users → Invite User → 이메일·역할 입력 → Invite | `text_present: "You submitted the following values:"` |

### shadcn-admin 결함 변이 (소스 패치)

`mutate.py`의 yaml 방식은 페이지 로드 직후 DOM을 한 번 고친다. React 앱에서는 필터를 바꾸면 표 행이 다시 그려져
고친 요소가 사라지고, 대화상자 안 요소는 로드 때 아직 없다(배포용 빌드에서 확인). 그래서 변이마다 소스 패치
`mutations/shadcn-admin/{변이}.patch`를 기준선 패치 위에 적용해 따로 빌드한다. 정답 형식(`labels/`)과 `eval.py`는 같다.

| 변이 | 규칙 | 대상 (과업) | 실수 패턴 | 확인 값 (기준선 → 변이) |
|---|---|---|---|---|
| small | R01 | Invite User (과업 2) | 아이콘 크기 클래스를 아이콘 버튼에 붙임 | 36px → 16px, 옆 버튼과 중심 거리 20px |
| contrast | R02 | 행 메뉴 Edit (과업 1) | 비활성용 흐린 글자 클래스를 활성 항목에 붙임 | axe 통과 → 대비 1.47:1 |
| inert | R03 | 초대 대화상자 Invite (과업 2) | 제출 버튼 `type='button'` | 알림 1 → 3초 동안 알림 0, 대화상자 그대로 |
| overlay | R04 | Status 필터 (과업 1) | 로딩용 반투명 막 제거 누락 | 중심점 최상단 = 버튼 → 막, 클릭해도 안 열림 |
| below-fold | R06 | Invite User (과업 2 첫 클릭) | 설명 문단에 `min-h-svh` | top 116px → 892px (128px 스크롤 필요) |
| unnamed | R10 | 첫 행 `⋯` (과업 1) | 숨김 이름 글자 삭제 | axe 통과 → `button-name` 위반 |

검증은 StepMeter 규칙 코드 없이 DOM 측정값과 axe로 한다. 기준선(8772)과 변이별 빌드(8781~8786)를 띄운 뒤
`python -m benchmark.verify_shadcn_admin`을 실행한다. 결과는 `evidence/shadcn-admin/`(git 제외)에 남는다.
변이별 전체 axe를 기준선과 비교해 의도한 위반 외에 늘어난 것이 없음을 확인했다.
단, unnamed는 행 메뉴 컴포넌트를 공유해 10개 행의 `⋯`가 모두 이름을 잃는다. 정답에는 과업이 누르는 첫 행만 넣었다.
R04 변이에서는 막을 누르면 아무 변화가 없으므로 R03도 함께 검출될 수 있다. conversion과 같게 정답에는 R04만 넣었다.
