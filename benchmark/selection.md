# W1 벤치마크 선정

원본 소스와 MIT 라이선스를 확인하고 `apps.json`에 정확한 커밋을 고정했다.
선정과 실행 준비를 구분한다. 6개 모두 실행·클리닝 완료 상태는 아니다.

| 앱 | 분할 | 선정 이유 / 실행 상태 |
|---|---|---|
| satnaing/shadcn-admin | 개발 | Tailwind/shadcn, 클라이언트 라우팅·대화상자·분할 로딩. 원본 검토, 런타임 미검증 |
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
W2의 결함 변이·정답·평가 스크립트는 이번에 만들지 않았다.
