# 사람 실험 세션 진행 절차

참가자 한 명의 세션을 처음부터 끝까지 진행하는 방법이다. **이 문서 하나만 보고 진행할 수 있게 썼다.** 명령은 그대로 복사해 쓰고, 참가자에게 하는 말은 인용 상자(>)의 문장을 그대로 읽는다. 진행자마다 설명이 달라지면 측정값도 흔들린다.

- **담당:** 대시보드 UI (세션 운영)
- **상태:** 안. 파일럿 3명을 마친 뒤 확정한다.
- **배경 문서(읽지 않아도 진행 가능):** [동의서](consent-form.md), [6페이지와 과업 문장](pages.md), [수집 스크립트 설명](README.md)
- 명령은 모두 **Windows PowerShell, 저장소 루트(`StepMeter` 폴더)** 기준이다.

## 한눈에 보기

| 단계 | 할 일 | 걸리는 시간 |
|---|---|---|
| A. 처음 한 번 | 진행자 PC에 실행 환경 설치 | 30분 안팎 |
| B. 세션 날 시작 | 최신 main 받기, 서버 띄우기, 6개 주소 확인 | 10분 |
| C. 참가자마다 | 조건 확인 → 동의서 → 안내 → 페이지 6개 → 코드 안내 → 검사 | 20분 이내 |
| D. 세션 날 끝 | 서버 끄기, 기록 복사, 데이터 전달 | 5분 |

## 준비물

| 항목 | 기준 |
|---|---|
| 진행자 PC | Windows 노트북. 화면의 **논리 해상도 세로 950px 이상**(아래 A-3) |
| 마우스 | 진행자 PC에 연결한다. 모든 참가자가 마우스를 쓴다(`--device mouse`). 트랙패드·터치는 쓰지 않는다 |
| 동의서 | [consent-form.md](consent-form.md)를 인쇄한다. 1절 담당자·연락처를 채운 것. 참가자 수만큼 |
| 메모지 | 참가자에게 코드를 적어 줄 종이, 진행 메모용 종이 |
| 타이머 | 휴대폰 스톱워치. 페이지당 3분을 잰다(스크립트가 시간을 끊어 주지 않는다) |
| 참가자 코드 범위 | C-2 표에서 내 범위를 확인한다 |

## A. 처음 한 번: 진행자 PC 준비

### A-1. 설치

Python 3.12, Node 22, Git이 있어야 한다. 저장소를 받은 뒤 루트에서:

```powershell
git switch main
git pull origin main
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }   # 가상환경이 이미 있으면 새로 만들지 않는다
$PY = if (Test-Path .venv\Scripts\python.exe) { "$PWD\.venv\Scripts\python.exe" } else { "$PWD\.venv\python.exe" }
& $PY --version                                          # Python 3.12.x가 나와야 한다
& $PY -m pip install -r requirements-dev.txt
npm ci
npm run build:collect
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.venv\ms-playwright"
& $PY -m playwright install chromium
```

#### `$PY`를 쓰는 이유

이 문서의 python 명령은 모두 `& $PY …`로 쓴다. **가상환경을 켜지(`Activate.ps1`) 않는다.**

- 필요한 패키지(playwright 등)는 저장소의 `.venv` 안에만 있다. 그냥 `python`을 치면 PC에 깔린 다른 python이 잡혀 `No module named 'playwright'`로 멈춘다.
- `.venv`를 만든 방법에 따라 python 위치가 `.venv\Scripts\python.exe`이거나 `.venv\python.exe`다. 위의 `$PY` 줄이 둘 중 있는 쪽을 고른다. 켜기 스크립트가 없는 PC도 있어서 켜는 방법은 쓰지 않는다.
- `$PY`와 `$env:PLAYWRIGHT_BROWSERS_PATH`는 **터미널 창을 닫으면 사라진다.** 새 창을 열면 B-1 블록부터 다시 실행한다.

### A-2. 결함판 빌드

```powershell
& $PY -m benchmark.serve_variants build
```

앱 3개를 받아 기준선·결함판 6개를 빌드한다. 처음에는 몇 분 걸린다. 패치가 그대로면 다음부터는 건너뛴다.

### A-3. 화면 높이 확인

Chromium 창 안의 페이지(1280×800)와 브라우저 UI(약 100px)가 다 보여야 한다. 창이 잘리면 참가자가 보는 첫 화면이 기록과 달라져 첫 화면 판정(R06)이 틀어진다.

- Windows 설정 → 디스플레이 → 배율이 125% 이상이면 **100%로 낮춘다**(FHD 125%는 세로 864px라 모자란다).
- 세션 시작 때 `[경고] 화면 높이 …px가 뷰포트 …보다 작습니다`가 나오면 배율을 더 낮춘다.
- `--viewport` 옵션으로 화면을 줄이지 않는다. 세션 뒤 검사가 1280×800이 아닌 파일을 오류로 처리한다.

## B. 세션 날 시작 (그날 한 번)

### B-1. 터미널 준비

PowerShell을 열고 저장소 루트에서 아래를 실행한다. **이 터미널 창은 그날 세션이 끝날 때까지 닫지 않는다.** 창을 새로 열었으면 이 블록을 다시 실행한다.

```powershell
git switch main
git pull origin main
$PY = if (Test-Path .venv\Scripts\python.exe) { "$PWD\.venv\Scripts\python.exe" } else { "$PWD\.venv\python.exe" }
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.venv\ms-playwright"
& $PY --version   # Python 3.12.x가 나와야 한다
npm run build:collect
```

`npm run build:collect`는 수집 번들을 최신 코드로 다시 만든다. pull로 수집 코드가 바뀌었을 수 있으니 세션 날마다 한다.

### B-2. 서버 띄우기

```powershell
& $PY -m benchmark.serve_variants build   # 바뀐 패치가 있으면 다시 빌드. 없으면 바로 끝난다
& $PY -m benchmark.serve_variants check   # 결함판 4·5·6번에 결함이 있고 기준선은 깨끗한지 확인
& $PY -m benchmark.serve_variants serve   # 서버를 백그라운드로 띄우고 page_id별 주소 표를 보여 준다
```

- `check`가 실패하면(종료 코드 1, 출력에 실패 항목) **세션을 열지 않고** 세션 운영 담당에게 알린다. 참가자가 결함이 없는 결함판을 하게 되면 그 데이터는 쓸 수 없다.
- `serve`는 바로 돌아온다. 서버는 `stop` 전까지 계속 떠 있다.

### B-3. 주소 6개 확인

평소 쓰는 브라우저로 아래 6개를 한 번씩 열어 페이지가 뜨는지 본다.

| 과업 # | `page_id` | 시작 주소 |
|---|---|---|
| 1 | `sb-admin-2/register/baseline` | http://127.0.0.1:8766/register.html |
| 2 | `material-kit-react/products/baseline` | http://127.0.0.1:8767/products |
| 3 | `material-kit-react/sign-in/baseline` | http://127.0.0.1:8767/sign-in |
| 4 | `sb-admin-2/login/small` | http://127.0.0.1:8791/login.html |
| 5 | `shadcn-admin/tasks/contrast` | http://127.0.0.1:8782/tasks |
| 6 | `shadcn-admin/users/below-fold` | http://127.0.0.1:8785/users |

포트와 주소의 원본은 `benchmark/variants.json`이다. `& $PY -m benchmark.serve_variants urls`로 다시 볼 수 있다.

## C. 참가자 세션

### C-1. 참가 조건 확인 (과업 설명보다 먼저)

> "시작하기 전에 하나만 여쭤볼게요. 관리자 대시보드나 로그인 화면 같은 웹 화면 몇 개를 쓰실 텐데, 혹시 SB Admin, Material Kit, shadcn admin 같은 관리자 템플릿 화면을 전에 써 보신 적 있으세요?"

- "있다"면 그 자리에서 끝내고 데이터를 받지 않는다:
  > "이번 연구는 처음 보시는 분의 기록이 필요해서요. 시간 내 주셔서 감사합니다."
- 과업 설명을 들은 뒤에는 "본 적 있다"고 말하기 어려워지므로 이 질문을 맨 먼저 한다.

### C-2. 동의서와 참가자 코드

1. 동의서를 건네고 읽을 시간을 준다. 3·4절(기록하는 것, 기록하지 않는 것)을 짚어 준다:
   > "입력하신 글자는 저장하지 않고, 키를 누른 시각만 남습니다."
2. 질문을 받고 서명을 받는다. 서명하지 않으면 진행하지 않는다.
3. 참가자 코드를 정한다.
   - 형식은 `P01`, `P02`, … 이다. **진행자끼리 겹치면 안 되므로** 아래 표의 내 범위 안에서 작은 번호부터 순서대로 쓴다. 범위를 다 쓰면 세션 운영 담당에게 더 받는다.

     | 진행자 | 참가자 코드 |
     |---|---|
     | @bomink1215 | `P01` – `P04` |
     | @hanchaehun | `P05` – `P07` |
     | @doithyun | `P08` – `P09` |
     | @leewonjunlee-eng | `P10` – `P11` |
     | @bshyuunn | `P12` – `P13` |
     | @msterk11 | `P14` |

   - 조건 확인에서 돌려보낸 사람이나 동의하지 않은 사람에게는 코드를 주지 않는다. 코드는 동의서에 서명한 참가자에게만 쓴다.
   - 리허설·연습에는 `P00`만 쓴다. 본 데이터와 섞이지 않게 하기 위해서다.
   - 동의서에는 코드를 적는다. 이름과 코드를 잇는 표는 **만들지 않는다**. 이름·연락처를 어디에도 적지 않는다.

### C-3. 공통 안내

> "이제 웹 페이지 6개에서 간단한 일을 하나씩 해 주시면 됩니다. 빨리 하거나 잘할 필요는 없어요. 평소에 하시던 대로 하시면 됩니다. 중간에 막히면 끝내지 못하셔도 괜찮습니다. 입력 칸에는 제가 알려 드리는 가짜 값만 넣어 주세요."

> "평소에 컴퓨터를 하루 몇 시간쯤 쓰세요? 대략이면 됩니다."

터미널에 참가자 코드와 답한 시간을 넣는다. 아래 페이지별 명령은 이 두 값을 그대로 쓴다.

```powershell
$P = "P01"   # 이 참가자의 코드
$H = 6       # 하루 컴퓨터 사용 시간(0~24)
```

### C-4. 페이지 6개

**순서는 아래로 고정한다.** 비슷한 로그인 과업인 3번과 4번 사이에 다른 과업 두 개를 둬서 학습 효과를 줄였다.

| 차례 | ① | ② | ③ | ④ | ⑤ | ⑥ |
|---|---|---|---|---|---|---|
| 과업 # | 1 | 3 | 5 | 2 | 4 | 6 |

#### 페이지마다 같은 진행 방법

1. 그 차례의 명령을 터미널에 붙여 넣고 실행한다. Chromium 창이 뜬다.
2. 페이지가 다 보이면 과업 문장을 **그대로** 읽고 타이머를 시작한다.
3. 참가자가 하는 동안 **돕지 않는다**. 질문을 받으면 과업 문장만 다시 읽어 준다. 그 밖에는 이렇게만 답한다:
   > "편하신 대로 해 주세요."
4. "끝난 것으로 보는 시점"이 화면에 나타나면 터미널에서 **Enter**를 누르고, `과업을 끝냈나요? [y/N]`에 **`y`** → Enter.
5. **3분**이 지나도 끝나지 않으면 이렇게 말하고 Enter → **`N`** → Enter. 참가자가 그만두겠다고 하면 같은 방법으로 처리한다.
   > "여기까지 하셔도 됩니다."
6. 터미널에 `저장: …json  (이벤트 N개, 완료=True/False)`가 나오면 다음 차례로 넘어간다.

#### 지켜야 할 것

- **Chromium 창을 닫지 않는다.** 진행자든 참가자든 창을 닫으면 그 즉시 미완료(`completed=false`)로 저장된다. 끝낼 때는 항상 터미널에서 Enter로 끝낸다.
- **어느 페이지에 결함이 있는지 말하지 않는다.**
- **같은 참가자가 같은 페이지를 두 번 하지 않는다.** 두 번째는 빨라져서 쓸 수 없다. 명령을 잘못 실행했으면 다시 하지 말고 메모해 두었다가 세션 뒤 검사 때 함께 알린다.

---

#### ① 과업 1 — 회원가입

```powershell
& $PY human-study/session.py --participant $P --page-id sb-admin-2/register/baseline --url http://127.0.0.1:8766/register.html --device mouse --hours $H
```

> "이름 Minsu Kim, 이메일 study@example.com, 비밀번호 Study1234, 확인 칸에도 같은 값을 입력하고 Register Account를 눌러 주세요."

- 화면에 보여 줄 값: `Minsu Kim` / `study@example.com` / `Study1234`
- **끝난 시점:** 로그인 화면으로 이동

#### ② 과업 3 — 로그인 후 비밀번호 표시

```powershell
& $PY human-study/session.py --participant $P --page-id material-kit-react/sign-in/baseline --url http://127.0.0.1:8767/sign-in --device mouse --hours $H
```

> "이메일을 study@example.com, 비밀번호를 Study1234로 바꿔 입력하고, 비밀번호가 보이게 해 주세요."

- 칸에 기본값이 들어 있어서 지우고 새로 입력해야 한다. 이 부분은 안내하지 않는다.
- **끝난 시점:** 비밀번호가 보이게 바뀜

#### ③ 과업 5 — Tasks 필터 후 Edit 열기

```powershell
& $PY human-study/session.py --participant $P --page-id shadcn-admin/tasks/contrast --url http://127.0.0.1:8782/tasks --device mouse --hours $H
```

> "Status가 Todo인 작업만 보이게 한 뒤, TASK-8202 작업의 Edit 화면을 열어 주세요."

- **끝난 시점:** `TASK-8202`의 수정 화면이 열림. 다른 작업의 Edit을 열었으면 아직 끝난 것이 아니다.

#### ④ 과업 2 — 제품 정렬·필터

```powershell
& $PY human-study/session.py --participant $P --page-id material-kit-react/products/baseline --url http://127.0.0.1:8767/products --device mouse --hours $H
```

과업 문장 **앞에** 이 안내를 먼저 읽는다:

> "이 페이지는 데모라 정렬이나 필터를 바꿔도 목록은 바뀌지 않습니다."

> "정렬을 Price: Low-High로 바꾸고, 필터에서 Category를 Apparel로 골라 주세요."

- **끝난 시점:** Category에서 Apparel이 선택됨(목록은 바뀌지 않는다)

#### ⑤ 과업 4 — 로그인 후 Remember Me

```powershell
& $PY human-study/session.py --participant $P --page-id sb-admin-2/login/small --url http://127.0.0.1:8791/login.html --device mouse --hours $H
```

> "이메일 study@example.com, 비밀번호 Study1234를 입력하고 Remember Me를 선택해 주세요."

- **끝난 시점:** Remember Me 체크박스가 선택됨

#### ⑥ 과업 6 — 사용자 초대

```powershell
& $PY human-study/session.py --participant $P --page-id shadcn-admin/users/below-fold --url http://127.0.0.1:8785/users --device mouse --hours $H
```

> "Invite User 창을 열고 이메일 study@example.com, Role은 Admin을 입력한 뒤 Invite를 눌러 주세요."

- **끝난 시점:** "You submitted the following values:" 알림이 뜸

---

### C-5. 끝

> "끝났습니다. 참가자 코드는 P01입니다. 나중에 기록을 지우고 싶으시면 이 코드를 알려 주시면 됩니다."

코드를 종이에 적어 드린다(동의서 6절).

### C-6. 바로 검사 (참가자가 간 뒤, 다음 참가자 전에)

```powershell
& $PY human-study/check_sessions.py $P
```

출력 예:

```
  sb-admin-2/register/baseline             완료     42초  클릭 3
  material-kit-react/products/baseline     완료     55초  클릭 6
  ...
  6페이지 합계 5.3분 (동의서·안내 시간 제외)
경고: …
오류: …
정상
```

| 보는 곳 | 기준 | 다를 때 |
|---|---|---|
| 마지막 줄 | `정상` | `오류 N건`이면 **파일을 지우지 말고** 수집 스크립트 담당(리포트 UI)에게 출력 전체를 보낸다 |
| 페이지별 완료/미완료 | 세션 때 `y`/`N`으로 답한 것과 같다 | 다르면 메모해서 함께 알린다 |
| 6페이지 합계 | 동의서·안내를 더해 20분 안 | 파일럿이면 기록해 둔다 |

오류로 나오는 것(종료 코드 1):

- 6페이지 중 빠진 파일이 있다 / 같은 페이지 파일이 2개 이상이다
- 6페이지 목록에 없는 `page_id`가 있다 (`--page-id` 오타)
- 스키마 오류, `*.invalid.json` 파일이 생겼다
- 뷰포트가 1280×800이 아니다
- 이벤트가 하나도 없다 / 시각(`t_ms`)이 거꾸로 간다

경고만 나오는 것(종료 코드 0, 진행은 계속):

- **3분 넘은 페이지:** 제한 시간에 끊었으면 괜찮다.
- **대상이 null인 클릭:** 좌표가 함께 나온다. 본문 글자나 빈 곳을 누른 것이면 괜찮다. **과업 대상**(Register Account, 비밀번호 표시 아이콘, Todo, Edit, Apparel, Remember Me, Invite User, Admin, Invite 등)을 누른 클릭이면 수집 스크립트 담당에게 알린다.

## D. 세션 날 끝

```powershell
& $PY -m benchmark.serve_variants stop
```

1. **빌드 기록 복사:** `benchmark/apps/variants/`의 `*/*.manifest.json`과 `serve-history.jsonl`을 그날 참가자 데이터와 같은 비공개 폴더에 복사한다. 참가자가 어떤 빌드를 봤는지 증명하는 기록이다.
2. **데이터 전달:** `data/human/`의 그날 파일(`human-session-<코드>-…json`)과 1의 기록을 세션 운영 담당에게 비공개로 전달한다. 공개 저장소, 이슈, 메신저 공개 채널에는 올리지 않는다.
3. **커밋하지 않는다.** `data/`는 git 제외 폴더다. 수집 파일을 다른 폴더로 옮겨 커밋하지 않는다.
4. **동의서 보관:** 서명한 동의서는 데이터와 분리해 보관한다. 사진을 찍거나 스캔해 올리지 않는다.
5. API가 생기면 세션 운영 담당이 `upload.py`로 올린다.

## 문제가 생겼을 때

| 증상 | 할 일 |
|---|---|
| `The expression after '&' in a pipeline element produced an object that was not valid`(한국어 Windows는 "'&' 뒤의 식이 … 올바르지 않습니다") | `$PY`가 비어 있다(새 터미널 창). B-1 블록을 다시 실행한다 |
| `No module named 'playwright'` | `& $PY` 대신 `python`으로 실행했다. 명령을 `& $PY …`로 다시 실행한다 |
| `& $PY --version`이 3.12가 아니거나 파일이 없다고 나온다 | `.venv`가 없거나 다른 버전으로 만들어졌다. A-1을 다시 한다 |
| `Executable doesn't exist` (Chromium 없음) | `$env:PLAYWRIGHT_BROWSERS_PATH` 줄을 빠뜨렸다. B-1 블록을 다시 실행한다 |
| `…collect.js 없음: … npm run build:collect 먼저 실행` | `npm run build:collect`를 실행한다 |
| Chromium에 "사이트에 연결할 수 없음" | 서버가 꺼져 있다. 참가자에게 과업을 읽기 **전이면** 터미널에서 Ctrl+C로 멈추고 `& $PY -m benchmark.serve_variants serve` 후 같은 명령을 다시 실행한다. 멈춘 사실을 메모해 둔다 |
| `[경고] 화면 높이 …` | 참가자가 오기 전이면 배율을 100%로 낮추고 다시 실행한다(A-3) |
| `[경고] 스키마 검증 실패` | 파일이 `*.invalid.json`으로 남았다. 지우지 말고 다음 페이지로 넘어가고, 세션 뒤 수집 스크립트 담당에게 알린다 |
| 참가자가 Chromium 창을 닫았다 | 미완료로 저장되었다. 같은 페이지를 다시 하지 않고 다음 차례로 넘어간다 |
| `check`가 실패한다 | 그날 세션을 열지 않는다. 세션 운영 담당에게 출력 전체를 보낸다 |

