# human-study/app/ — 사람 실험 진행 프로그램

[세션 진행 절차](../session-procedure.md)를 창 하나로 진행한다(`procedure_version` `self_guided_v1`). 진행자는 조건 확인·동의서까지
하고 노트북을 건네며, 참가자가 화면 안내대로 과업 6개를 직접 한다. 노트북을 돌려받으면 진행자가 페이지별 완료를 확정하고
진행 이상을 메모한다(`notes-<코드>.json`).

- **Windows:** `StepMeter-human-<버전>.zip`을 풀고 `StepMeter-human.exe` 더블클릭. 설치·저장소·명령이 필요 없다(사이트·수집 번들·Chromium이 exe 폴더 안에 있다).
- **Mac:** 저장소를 받은 뒤 Finder에서 `human-study/app/run_mac.command` 더블클릭. 처음 한 번은 설치·사이트 빌드로 10~15분 걸린다.
- **Windows 개발자(exe 빌드 전 확인):** `human-study\app\run_source.ps1`

두 방식의 진행 화면·메모·저장 형식은 같다. 어느 방식인지와 OS는 notes의 `run_mode`(`exe-windows`, `source-mac` 등)에 남는다.

## 화면 순서

| 누가 보는 화면 | 화면 | 쓰는 것 |
|---|---|---|
| 진행자 | 진행자(이 PC에 기억)·참가자 코드(범위의 다음 빈 번호 제안, 범위 밖이면 확인)·연습 모드(P00) | `session_plan.json`의 범위 표 |
| 진행자 | 시작 전 점검: 사이트 6개 주소 200, 사이트 빌드가 check를 통과한 빌드인지, 수집 번들, 화면 높이(`screen.availHeight` ≥ 950), 화면 너비(`screen.availWidth` ≥ 1280 + 패널 420 = 1700), 저장 폴더, 외장 마우스. 하나라도 실패하면 [시작]이 막힌다 | `benchmark/serve_variants.py`, Chromium |
| 진행자 | C-1 조건 확인 → C-2 동의서 → "노트북을 참가자에게 건네주세요" [건넸어요] | 절차서 문장 그대로 |
| 참가자 | 시작 안내 + 하루 컴퓨터 사용 시간(0~24) → 과업마다 과업 문장(④는 데모 안내 먼저, ①은 입력할 값)과 [시작] | `views.py` |
| 참가자 | [시작] → Chromium 창(왼쪽 위로 옮김) + 오른쪽 패널(과업 문장, [다 했어요] [그만할게요]). 남은 시간은 보이지 않는다 | `session.run_session_async`(interact 콜백), `save_session_or_dump` |
| 참가자 | 3분이면 소리와 "여기까지 하셔도 됩니다." / 창을 닫으면 "브라우저 창이 닫혔습니다…" → [다음] | |
| 참가자→진행자 | "수고하셨습니다. 노트북을 진행자에게 돌려주세요." [돌려줬어요] | |
| 진행자 | 확인표: 6페이지마다 참가자 답·끝난 시점을 보고 완료 확정(기본값 = 참가자 답, 3분·창 닫힘은 미완료 고정) + 진행 이상 체크·한 줄 메모 | `session.save_session`(바뀐 페이지만 다시 저장) |
| 진행자 | 마지막 안내(코드) → `check_sessions` 결과 → `check-<코드>.txt`, `upload-<코드>.zip`, 폴더 열기 | `check_sessions.main` |

- 페이지가 끝나면 참가자 답으로 먼저 저장한다([다 했어요] = `completed=true`). 진행자가 확인표에서 바꾸면 그 페이지 파일의
  `completed`만 고쳐 같은 파일 이름으로 다시 저장한다(다른 칸은 그대로). 원래 값과 바꾼 사실은 notes에 남는다.
- 같은 코드로 이미 한 페이지는 다시 하지 않는다. 프로그램이 중간에 꺼지면 다시 열어 같은 코드로 이어 한다. 진행 중에 꺼진
  페이지(`.partial`만 남음)는 다시 하지 않고 확인표에 "기술 문제"로 미리 체크된다.
- 데이터: `문서\StepMeter-human\` (연습은 `문서\StepMeter-human-practice\`). exe 폴더에는 쓰지 않는다. 진행자 선택·로그는 `%APPDATA%\StepMeter-human\`(Mac `~/Library/Application Support/StepMeter-human/`).
- 이름·연락처를 받는 칸은 없다. 진행자는 GitHub 아이디, 참가자는 코드만 쓴다. 메모 칸 옆에 "이름·연락처는 적지 않기"를 표시한다.
- **[이미 끝난 세션 메모 입력]**: 프로그램 전에(진행자가 읽어 주는 방식으로) 진행한 세션의 폴더와 코드를 고르면, 세션 파일은
  읽기만 하고 페이지별 메모만 받아 `notes-<코드>.json`을 만든다(`app_version` 등은 `before-app`, `procedure_version`은 `read_aloud`).

## notes-<코드>.json

```json
{"session": {"participant_code": "P05", "facilitator": "hanchaehun", "app_version": "20261114-7325d3a",
             "repo_commit": "…40자…", "site_manifest_hashes": {"sb-admin-2/baseline": "…", "…": "…"},
             "os": "Windows-11-…", "screen_avail_height": 1032, "started_at": "2026-11-14T05:00:00Z",
             "run_mode": "exe-windows", "procedure_version": "self_guided_v1"},
 "pages": [{"order": 1, "page_id": "sb-admin-2/register/baseline", "participant_reported": "done",
            "completed": true, "completed_confirmed": false, "confirmation_changed": true,
            "auto_stopped_3min": false, "issue": true, "issue_codes": [3], "note": "…"}, "…"]}
```

- `participant_reported`: `done`([다 했어요]) · `gave_up`([그만할게요]) · `timeout`(3분) · `closed`(창을 닫음) · `crashed`(브라우저 오류) · `null`(저장되지 않은 페이지, 이미 끝난 세션)
- `completed`: 처음 저장한 값(참가자 답 기준). `completed_confirmed`: 진행자가 확정한 값(세션 json의 `completed`). `confirmation_changed`: 바꿨으면 true
- `issue_codes`(`self_guided_v1`): 1 참가자가 진행자에게 도움을 요청해 답해 줌, 2 참가자가 과업을 잘못 이해함, 3 버튼을 늦게/일찍 누름, 4 기술 문제, 5 기타(한 줄 메모 필수)
- `issue_codes`(`read_aloud`, 이미 끝난 세션): 1 과업 문장을 다르게 읽음, 2 참가자를 도와줌, 3 창을 늦게/잘못 띄움, 4 완료 버튼을 늦게/일찍 누름, 5 기술 문제, 6 기타
- 분석에서 `issue=true`인 페이지만 주 분석에서 빼고, `procedure_version`별로 결과를 함께 보고한다([ml/timing/README.md](../../ml/timing/README.md)).

## exe 빌드 (Windows, 한 번)

사전 준비: infra/README.md "W1 실행 환경", `python -m benchmark.serve_variants build`.

```powershell
human-study\app\build_exe.ps1
```

`npm run build:collect` → `serve_variants check`(실패하면 멈춤, 사이트를 다시 빌드하지 않음) → 내장 폴더 준비(저장소와 같은 상대 경로로
기존 모듈·사이트 빌드 5개·manifest·check 결과를 복사하고 해시 확인) → PyInstaller onedir(`requirements-build.txt`) → Chromium 포함.
결과는 `dist\StepMeter-human-<날짜-커밋7>\StepMeter-human.exe`와 같은 이름의 zip이다. `dist/`, `build/`, `*.zip`은 커밋하지 않는다.
zip 안의 `처음 실행할 때 읽기.txt`에 Windows 보호 창("추가 정보 → 실행") 안내가 있다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `controller.py` | 진행 로직(화면 없음). 테스트는 이것과 `views.py`만 쓴다 |
| `views.py` | 참가자 화면 내용(문구·버튼). 진행자용 말·결함·끝난 시점·남은 시간을 넣지 않는다 |
| `gui.py` | tkinter 화면. 진행자가 읽는 문장·참가자 과업 문장 26pt, 진행 중 패널 20pt |
| `resources.py` | exe·소스 방식에 따라 경로를 고르고 기존 모듈을 파일 경로로 불러온다 |
| `sites.py` | 내장 사이트 서버(serve_variants 재사용)와 점검 |
| `notes.py` | 진행 이상 메모 형식 |
| `runtime.py` | 실제 실행용 연결 |
| `autodrive.py` | 개발자 확인용 `--auto`(연습 모드에서 버튼 자동 누름) |
| `build_exe.py`, `build_exe.ps1` | exe 빌드 |
| `run_mac.command`, `run_source.ps1` | 소스 방식 실행 |

## 테스트

```sh
.venv/Scripts/python.exe -m unittest tests.test_human_app -v
```

GUI 없이 controller로, 합성 페이지(`tests/fixtures/human-study/page.html`)·임시 폴더·헤드리스 Chromium을 쓴다.
기대값은 `session-procedure.md`(문장·순서·범위, C-4 3분 규칙), `pages.md`, `benchmark/variants.json`에서 테스트가 직접 읽는다.
실제 사이트 서버 테스트는 `benchmark/apps/variants/` 빌드가 있을 때만 돈다(git 제외 폴더).

개발자 확인(진짜 창·Chromium, 연습 모드 P00): `python human-study/app --auto` 또는 `StepMeter-human.exe --auto`.
자동 진행은 ②에서 [그만할게요], ③은 3분 자동 종료, 나머지는 [다 했어요]를 누르고, 확인표에서 ④를 미완료로 바꾼다.
데이터 폴더를 바꾸려면 `STEPMETER_HUMAN_HOME` 환경 변수를 준다.
