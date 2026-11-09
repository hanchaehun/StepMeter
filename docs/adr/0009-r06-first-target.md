# 0009. R06은 화면마다 첫 행동 대상만 본다

- **날짜:** 2026-11-09 (PM 결정)
- **근거 기록:** [worker/rules/r06.py](../../worker/rules/r06.py), [worker/rules/engine.py](../../worker/rules/engine.py), [tests/test_rules_w2.py](../../tests/test_rules_w2.py), [benchmark/labels/](../../benchmark/labels/)

## 배경

- 개발계획서 5.7은 "과업의 첫 행동 대상이 로드 직후 뷰포트 밖이면 경고", 6장 표는 R06을 "첫 행동 대상이 로드 시 뷰포트 밖"으로 정했다. W2 첫 구현(#28)도 `is_first_target`인 대상만 봤다.
- 11/9(aa6e291)에 "click 행동이면 순서와 관계없이"로 바꿨다. 이때 type 행동은 빠졌다.
- R06 정답 5개는 모두 각 과업의 첫 행동 대상이다.

  | 정답 | 대상 | 과업의 첫 행동 |
  |---|---|---|
  | conversion below-fold | `#signup` | 가입 시작 화면(`entry.html`)의 첫 click |
  | shadcn-admin below-fold | Invite User 버튼 | 초대 제출 과업의 첫 click |
  | sb-admin-2 below-fold | `#exampleFirstName` | 회원가입 과업의 첫 입력(type) |
  | material-kit-react below-fold | `input[name="email"]` | 로그인 과업의 첫 입력(type) |
  | react-shopping-cart below-fold | `input[type="search"]` | 상품 검색 과업의 첫 입력(type) |

## 결정

R06은 페이지 또는 SPA 화면이 로드된 뒤, 그 화면에서 처음 행동하는 대상(click·type·select)이 로드 시 첫 화면 밖에 있을 때 나온다.

- 화면이 바뀔 때마다(내비게이션·SPA 라우트 변경) 첫 행동 대상을 다시 센다. scroll·back·wait는 대상 행동이 아니라 세지 않는다.
- 화면 구분(PM 승인): 출처+경로로 구분하고, 쿼리만 바뀌면 같은 화면이며, 해시는 해시 라우터 앱에서만 화면으로 센다.
- `engine.evaluate_step()`의 `is_first_target`은 필수 인자다. 호출자는 `r06.FirstTargetTracker`에 행동 직전 URL과 행동 종류를 순서대로 넣어 값을 얻고, 같은 주소를 다시 불러온 페이지 로드는 `new_screen()`으로 알린다. 화면이 바뀌면 수집기의 첫 화면 기록(`record_first_view`)도 다시 해야 "로드 시 첫 화면"이 그 화면 기준이 된다.
- conversion below-fold는 가입 시작 화면(`entry.html`)에서 시작한다. 가입 폼(`index.html`)에서는 `#signup`이 쿠키 닫기·이메일·비밀번호 다음 네 번째 행동이라 첫 행동 대상이 아니기 때문이다. 정답은 그대로 두고 `verify_conversion.py`의 below-fold 시작 페이지만 바꿨다.
- 로드 때 없던 요소(`first_view_scroll_px`가 null)는 지금처럼 판정하지 않는다.

## 한계

- 쿠키 배너·안내 대화상자처럼 과업과 관계없는 행동이 화면의 첫 행동이면, 그 뒤의 과업 버튼이 첫 화면 밖에 있어도 R06으로 잡지 못한다. conversion below-fold를 가입 시작 화면에서 시작하게 한 것도 이 때문이다.
- 대화상자를 열고 닫는 것과 쿼리만 바뀌는 필터는 화면 변경으로 세지 않는다.

## 후속 확인

에이전트 루프가 생긴 뒤 실제 run에서 R06 후보의 오탐·누락을 데이터로 다시 확인한다. 첫 대상 기준이 너무 좁은지, 쿠키 배너 같은 과업 밖 첫 행동을 건너뛰어야 하는지를 그때 정한다.

## 대안

- 11/9 기준 유지(click이면 순서와 관계없이): 가입 폼에서 시작하는 conversion `#signup`도 잡지만, 입력칸을 처음 type하는 과업(개발 앱 정답 3개)은 click이 없으면 잡지 못한다. 과업 중간에 스크롤해서 누르는 아래쪽 버튼도 모두 R06이 될 수 있다.
- 과업과 관계없는 첫 행동(쿠키 배너 등)을 빼고 센다: 무엇이 과업 밖 행동인지 정할 기준이 아직 없다.
