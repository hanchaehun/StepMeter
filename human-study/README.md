# human-study/

- **담당 역할:** 리포트 UI(수집 스크립트) · 대시보드 UI(동의서·세션 운영)
- **하는 일:** 사람 데이터 수집 스크립트, 동의서, 과업 목록. 외부 참가자 실험은 IRB 심의 없이 `consent-form.md`의 동의서를 받아 진행한다 (참가자 12~15명, 벤치마크 페이지 6개, [ADR 0001](../docs/adr/0001-no-irb.md)).
- **참고:** 개발계획서 9.1
- **문서:** [동의서](consent-form.md) · [모집 공고](recruitment.md) · [6페이지와 과업 문장](pages.md) · [세션 진행 절차](session-procedure.md) · 세션 직후 검사 `check_sessions.py`

## 수집 스크립트 (리포트 UI)

참가자의 마우스 이동·누름·뗌·클릭·스크롤·키 입력의 **시각과 좌표, 대상 요소 지문**만 기록해
`apps/api/openapi.yaml`의 `HumanSessionCreate` 형식 JSON으로 저장한다 (개발계획서 9.1 "수집", 동의서 3·4절).

| 파일 | 하는 일 |
|---|---|
| `collect.js` | 브라우저 안에서 이벤트를 기록해 `window.__hsPush(event)`로 내보낸다. 요소 지문은 이원준 님 수집 번들(`worker/collect/dist/collect.js`)의 `observe()` 값을 그대로 써서 `tag\|role\|name\|label_text\|landmark` 형식(`element_key`와 같음)으로 만든다 |
| `session.py` | 진행자 명령. Playwright로 화면 있는 Chromium을 띄우고, 페이지마다 수집 스크립트를 넣고, 끝나면 JSON을 저장한다 |
| `schema.py` | 저장 전·업로드 전에 openapi 스키마로 검사한다 |
| `upload.py` | 저장된 JSON을 `POST /human-sessions`로 올린다. 이번 일정에서는 엔드포인트를 만들지 않아 쓰지 않는다 (ADR 0011 4번) |

### 기록하는 것 / 기록하지 않는 것

| 이벤트 `type` | 언제 | `x, y` | `target_key` |
|---|---|---|---|
| `stable` | 페이지 load 뒤, 그리고 DOM 변경(요소 추가·속성 변경 포함)이 300ms 동안 없을 때마다 | null | null |
| `move` | 포인터 이동. 16ms 간격으로 묶음(약 60Hz) | 뷰포트 좌표 | null |
| `down` / `up` / `click` | 포인터로 누름 / 뗌 / 클릭. 키보드(Enter·Space)나 label이 만든 합성 click은 기록하지 않는다 | 뷰포트 좌표 | 그 자리의 상호작용 요소 지문(가려지지 않은 것 우선). 본문 글이면 null |
| `scroll` | 스크롤 | 마지막 포인터 위치 | null |
| `key` | 키를 누를 때마다 1건 (Shift·Backspace 포함, 자동 반복은 제외) | null | 포커스된 요소 지문. 못 찾으면 null |

- **입력한 글자는 기록하지 않는다.** 키는 시각과 대상만 남긴다. `key` 이벤트 수는 키 누름 횟수다(글자 수와 비슷하지만 Shift·Backspace도 센다).
- **연구용 페이지 밖은 기록하지 않는다**(동의서 4절). 시작 주소와 출처가 다른 페이지(외부 링크, 검색)와 iframe 안에서는 스크립트가 설치되지 않는다.
- Python 쪽은 이벤트의 다섯 칸만 받아 적고, 받을 때마다 `.partial-*.jsonl`에 덧붙인다. 크래시나 Ctrl+C가 나도 그때까지의 기록이 남는다.
- 이름·연락처는 받지 않는다. 참가자 코드(`--participant`)만 쓴다. 코드와 사람을 잇는 표는 만들지 않는다(동의서 운영 메모).
- `t_ms`는 세션 시작(명령을 친 시각)부터 경과 ms. 첫 이벤트는 `stable`이라 생각 시간(M) 표본 계산이 선다(9.1).

### 진행자 절차

사전 준비(한 번): 저장소 루트에서 `infra/README.md` "W1 실행 환경"대로 Python 3.12 가상환경과 `npm ci`, `npm run build:collect`, `python -m playwright install chromium`.

1. 벤치마크 앱 서버를 띄운다 (`pages.md`, `session-procedure.md` 참고. 결함판도 패치를 적용해 띄운 로컬 서버 주소를 그대로 `--url`로 넘기며 `--mutation` 옵션은 쓰지 않는다).
2. 참가자에게 동의서(`consent-form.md`)를 설명하고 서명을 받는다. 참가자 코드를 정한다.
3. 세션을 시작한다 (`page_id`는 `<앱 id>/<페이지>/<변이>` 형식).
   ```sh
   python human-study/session.py --participant P01 --page-id sb-admin-2/register/baseline \
       --url http://127.0.0.1:8766/register.html --device mouse --hours 6
   python human-study/session.py --participant P01 --page-id sb-admin-2/login/small \
       --url http://127.0.0.1:8791/login.html --device mouse --hours 6
   ```
   Chromium 창이 뜨면 참가자에게 과업 문장(`pages.md`)을 읽어 준다.
4. 참가자가 끝내면 터미널에서 **Enter**, "과업을 끝냈나요? [y/N]"에 답한다. 참가자가 창을 닫으면 그 즉시 `completed=false`로 저장된다.
5. 파일은 `data/human/human-session-{참가자}-{page_id}-{시각}.json`에 생긴다. 스키마 검증에 실패하면 버리지 않고 `*.invalid.json`으로 남기고 오류를 보여준다. `data/`는 git 제외다. **커밋하지 않는다.**
6. 파일은 서버에 올리지 않는다(ADR 0011 4번). 진행자가 팀 Notion에서 팀원만 볼 수 있는 페이지에 올려 측정 지표 담당에게 넘긴다. 저장소·이슈·채팅방에는 올리지 않는다.

### 참가자 PC 요구사항

진행자 노트북에서 Chromium을 띄우므로 참가자 PC는 필요 없다. 마우스 또는 트랙패드(`--device`에 적는다). 터치는 쓰지 않는다.
화면은 뷰포트 1280×800에 브라우저 UI 약 100px이 더 들어가야 하므로 **논리 해상도 높이 약 950px 이상**이어야 한다(Windows 125% 배율 FHD는 864라 모자란다). 모자라면 시작할 때 경고가 나오고, 그대로 진행하면 참가자가 보는 첫 화면이 기록된 뷰포트와 달라진다(R06 첫 화면 판정에 영향). 배율을 100%로 낮추거나 `--viewport 1280x720`처럼 줄인다.

### 알려진 한계

- 다른 출처 iframe 안의 이벤트는 받지 못한다(수집 번들과 같은 범위).
- `page_id`는 `<앱 id>/<페이지>/<변이>` 형식을 쓴다(6개 목록은 `pages.md` 참고).
- `stable`은 속성 변경(class·data-state 등)에도 반응하므로, 마우스를 올리기만 해도 hover 스타일 때문에 `stable`이 생길 수 있다. 생각 시간(M) 표본을 "직전 stable → 다음 동작"으로 뽑으면 짧아질 수 있다. 수집은 바꾸지 않고, 분석에서 "마지막 click·key 뒤 첫 stable"만 기준점으로 쓴다(ADR 0011 3번).
- 클릭 대상은 누른 좌표의 실제 요소(`elementFromPoint`)에서 위로 올라가며 가장 가까운 대상 요소를 찾고, 번들의 `describe(el)`로 지문을 만든다. label을 누르면 연결된 입력칸(숨긴 체크박스·라디오)이 대상이고, body 끝에 포털로 붙는 팝업·콤보박스 항목(`role=option` 등)도 잡힌다(#43, 2026-11-10). 본문 글처럼 대상 요소가 아니면 null이다.
- 콤보박스 항목(예: shadcn-admin Role 목록)은 누르는 순간 목록이 닫혀 `click` 없이 `down`·`up`만 남을 수 있다. 분석에서는 `click`이 없으면 `up`을 클릭으로 본다.

### 테스트

```sh
.venv/Scripts/python.exe -m unittest tests.test_human_collect tests.test_human_session -v
```

기대값은 `tests/fixtures/human-study/page.html`의 고정 좌표와 `tests/fixtures/mock/api/human_session_request.json`에서 사람이 계산했다.

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 세션 파일은 서버에 올리지 않고, 팀 Notion에서 팀원만 볼 수 있는 페이지로 넘긴다. 저장소에는 올리지 않는다 (ADR 0011 4번)
- 보관 기한(2026-12-31)이 지나거나 참가자가 철회하면 진행자 PC의 파일과 함께 Notion 페이지의 파일도 지운다. Notion 휴지통에서도 지운다 (ADR 0011 4번, 동의서 5·6절)
- 수집 스크립트의 `stable` 기록 방식은 바꾸지 않는다. 마우스를 올려 생긴 `stable`은 분석에서 거른다 (ADR 0011 3번)
