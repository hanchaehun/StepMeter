# F06 리포트 화면 레이아웃 명세 (검토안)

리포트 화면의 영역 구조, 각 영역이 쓰는 데이터, 팝업 동작, 상태 전환을 정한다. 시각 목업은 같은 폴더의 [`f06-report.html`](f06-report.html)이며 브라우저로 열어 본다. 이 문서가 값과 규칙의 기준이고, 목업은 그 배치를 보여주는 참고물이다. 참고 리포트 분석은 [`report-reference.md`](report-reference.md).

- **범위:** 리포트 화면 하나(기획서 6.1의 "리포트 요약"과 "단계 상세"를 합친 것). 측정 생성(F01), 진행(F02), 비교(F07), 측정 이력(F11)은 대시보드 UI 담당의 별도 문서.
- **근거:** 서비스 기획서 **5장 F03·F04·F05·F06·F09·F10 행**, **6.1 화면 목록 "리포트 요약"·"단계 상세" 행**, **6.2 리포트 작성 원칙**, **7장 측정 지표 표** / 개발계획서 **6장(규칙 R01–R11, 6.1 설명 생성, 6.2 이슈 점수)**, **11장·13.1(API, 동결 스키마)**, **15.4(자체 UX)**.
- **데이터 기준:** `apps/api/openapi.yaml`의 `Report`·`Step` 스키마와 `tests/fixtures/mock/api/report.json`·`steps.json`(10/27 동결). 이 문서는 스키마를 바꾸지 않는다.
- **아직 정해지지 않은 것:** 모바일 엄지 도달 구역의 데이터 출처(F08)와 단계 상세 화면 통합 여부. 아래 "리뷰어에게 묻는 것". 스크린샷 URL 만료, R05 구간 표시, 탭·팝업 공용화는 구현하면서 해당 역할과 맞춘다("플랫폼 백엔드에 요청할 것", "결정이 필요한 사항").

---

# 리뷰어에게 묻는 것

| # | 누구에게 | 묻는 것 | 왜 급한지 |
|---|---|---|---|
| **1** | **측정 지표·규칙 · 플랫폼 백엔드** | 모바일 "엄지 도달 구역"(F08)은 **어떤 데이터로 오는가** | **가장 급함.** 동결 스키마에 필드가 없다. 화면에서 bbox로 계산할지, 규칙 결과로 올지에 따라 모바일 리포트가 달라진다 |
| 2 | PM | 기획서 6.1의 "단계 상세" 별도 화면을 **Steps 탭 + 팝업으로 합쳐도 되는가** | 반대면 팝업을 별도 화면으로 떼어낸다. 구조가 바뀌니 구현 전에 답이 필요하다 |

---

## 영역 구조

데스크톱 1280×800 기준. 탭 3개(Overview / Issues / Steps)와 팝업 하나.

```
┌─ 앱 헤더 (56) ─────────────────────────────────────────────────────────┐
│ StepMeter   New run · History · Report · Compare        Today 7/10 runs │
├─ 제목 영역 ────────────────────────────────────────────────────────────┤
│ REPORT · RUN #42                                                       │
│ 장바구니에 상품을 담고 결제까지 간다                                      │
│ shop.example · Desktop · 10-29 14:06 · 3 attempts · 6m 37s  Compare #41 │
│ [Overview] [Issues 3] [Steps 3]                                         │
├─ Overview 첫 화면 (창 높이에 맞춤) ────────────────────────────────────┤
│ VERDICT                              PATH METRICS                       │
│ 3회 중 2회 성공                       7.9s   2clicks   812px   5.4bit   │
│ 예상 7.9초 · 문제 2건 · 참고 1 · 통과 8                                   │
│ ───────────────────────────────────┬───────────────────────────────── │
│ Issues            전체 보기 →        │ Attempts            단계 보기 →   │
│ [썸네일] ▲High  구매 버튼 가려짐  S1 │ Attempt 2 대표  ●──●──●  3 steps  │
│ [썸네일] ■Med   대비 2.9:1       S0 │ Attempt 1 재생  ●──◆     끊김     │
│ [썸네일] ●Low   (참고) 30px       — │ Attempt 3       ●──●──●──● 4 steps│
│                                    │ 가장 어려운 Step 1 · 오래 걸린 Step 0│
│                     ↓ 통과한 규칙과 나머지 측정값                         │
├─ Overview 스크롤 아래 ─────────────────────────────────────────────────┤
│ Passed rules 8   ✓ 무반응 클릭  ✓ 반복 루프  ✓ … (4열, 근거 한 줄씩)      │
│ More metrics     지표 원값·편차·편차 품질 | 성공·단계 수·비용·시각·상위 단계 │
└────────────────────────────────────────────────────────────────────────┘
```

- **Issues 탭:** 문제 전체 목록(큰 썸네일 128×84, 설명 첫 문장, Details 버튼) → Reference → Passed rules.
- **Steps 탭:** 대표 attempt의 단계 카드 3열(스크린샷 + 오버레이, 행동, 판단 이유, 효과·난이도·예상 시간).
- **팝업:** Issues 행 · Attempts 점 · Steps 카드를 누르면. 왼쪽 단계 띠 + 스크린샷(비율 유지, 스크롤 없음), 오른쪽 What / How to fix / Agent. 위에 이전/다음 문제와 닫기.

좁은 화면(1024 미만)은 Issues와 Attempts를 한 열로 쌓고, Path metrics는 2×2. 팝업은 스크린샷 위, 글 아래로 세로 배치.

## 데이터 출처

Report API(`GET /runs/{id}/report`) 한 번과 steps API(`GET /runs/{id}/attempts/{n}/steps`, 대표 attempt) 한 번으로 그린다. 과업 문장은 `GET /tasks/{id}`(Run의 `task_id`)로 따로 받는다.

| 영역 | 필드 | 표기 규칙 |
|---|---|---|
| 제목 | task.task, task.url, run.viewport, run.created_at, attempts.length, run.started_at→finished_at | 모바일이면 "Mobile 390×844" |
| Compare 링크 | run.base_run_id | null이면 링크 없음. 있으면 `/compare?base=41&target=42` |
| 재생 전용 표시 | run.mode | `replay_only`면 메타 줄에 "재생 전용 · LLM 비용 없음" |
| Verdict 큰 글자 | attempts[].success 개수 / run.repeat_n | 하나라도 success_estimated면 "(추정)" |
| Verdict 보조 | metrics.est_task_time, issues(is_reference=false).length, issues(is_reference=true).length, 통과 규칙 수 | 모바일이면 예상 시간 대신 "예상 시간은 데스크톱에서만" |
| Path metrics | metrics[] key=click_count, travel_distance, fitts_id_sum, est_task_time | 값 + 단위. Overview 타일 값은 px는 정수 반올림(Math.round, 812.5→813), 나머지는 소수 1자리. More metrics는 원값. 꼬리표: spread → "편차 ±N%", model_version_id null → "보정 전", 있음 → "사람 실험 보정" |
| Issues 행 | issue.rule_id, severity, element_key(이름 부분), measured, threshold, step, score_reason, is_reference | 제목은 규칙별 템플릿(아래). 썸네일은 step의 스크린샷을 element_snapshot.bbox 중심으로 잘라냄 |
| Attempts | attempts[].index, kind, replay_status, diverged_at_step, end_reason, end_detail, success, steps_count; run.representative_attempt_index | 대표에 "대표". replay면 "재생". partial이면 ◆ + "Step N에서 끊김" + end_detail |
| 가장 어려운·오래 걸린 단계 | top_fitts_steps[0], slowest_steps[0] | More metrics에는 최대 3개 전부 |
| Passed rules | R01~R11 − issues에 나온 rule_id | 모바일 아니면 R11 "모바일만 해당" |
| More metrics | metrics[] 원값·spread·spread_quality; attempts 요약; run.cost_usd, model, prompt_version, started_at, finished_at | spread_quality: ok 없음 / weak "추정 약함" / pooled "이력 기준" |
| Steps 카드·팝업 | step.idx, action(action, thought, expectation, confusion), url, screenshot_url, effect_type, fitts_id, est_seconds, element_snapshot(bbox, occluded, occluder.bbox, nearby_targets) | 아래 "오버레이" |

### 문제 제목 템플릿 (규칙별)

`explanation`은 LLM이 쓴 두 문장이라 길이가 들쭉날쭉하다. 목록 제목은 규칙별 템플릿에 측정값을 끼워 만들고, explanation은 Issues 탭 한 줄과 팝업에만 쓴다.

| 규칙 | 제목 | 측정값 표기 |
|---|---|---|
| R01 작은 타겟 | `{요소} 높이 {measured}px` | `{measured}px · 권장 {threshold}px (최소 24px)` |
| R02 대비 부족 | `{요소} 글자 대비 {measured} : 1` | `{measured} : 1 · 기준 {threshold} : 1 (WCAG AA)` |
| R03 무반응 클릭 | `{요소}를 눌렀는데 반응 없음` | — |
| R04 가려진 요소 | `{요소}가 {가린 요소}에 가려짐` | — |
| R05 반복 루프 | `같은 화면에서 같은 행동을 반복함` | — (요소 없음) |
| R06 첫 화면 밖 | `{요소}가 첫 화면 밖 ({measured}px 아래)` | `스크롤 {measured}px 필요` |
| R07 먼 이동+작은 타겟 | `{요소}까지 멀고 작음 (ID {measured}bit)` | `{measured}bit · 크기 {w}×{h}px` |
| R08 되돌아감 | `뒤로 가기 {measured}회` | — |
| R09 기대 불일치 | `{요소} 뒤 결과가 기대와 다름` | — |
| R10 이름 없는 요소 | `{요소}에 이름 없음` | — |
| R11 키보드 가림 | `{요소}가 가상 키보드에 가릴 수 있음` | — |

요소 이름은 `element_key`의 세 번째 칸(name)에 role 접미(`button`→"버튼", `link`→"링크")를 붙인다("구매 버튼"). name이 비면 role 이름만, 둘 다 비면 "요소". 템플릿의 조사(이/가, 을/를)는 앞 글자 받침에 따라 자동으로 고른다.

### 오버레이 (스크린샷 위)

| 무엇 | 데이터 | 그리기 |
|---|---|---|
| 누른 요소 | element_snapshot.bbox | 빨간 실선 3px + 흰 테두리 3px, 위에 이름 라벨 |
| 클릭 지점 | bbox 중심 | 지름 28px 빨간 원 |
| 가린 요소 | element_snapshot.occluder.bbox (occluded=true) | 빨간 빗금 + 점선, "가린 요소: {tag} ({name 또는 이름 없음})" |
| 근처 요소 | element_snapshot.nearby_targets[].bbox | 회색 점선 + 아래에 "근처: {name}" |
| 문제 요소 (경로 밖) | issue.element_key로 같은 단계 스냅샷에서 찾은 bbox | 누른 요소와 같은 스타일. 못 찾으면 오버레이 없이 글로만 |

스크린샷은 viewport 비율(1280:800 또는 390:844)을 유지해 영역 안에 맞춘다. 오버레이 좌표는 bbox를 같은 비율로 축소. 스크린샷이 아직 안 왔으면 같은 비율의 회색 상자 + "불러오는 중".

## 상태 전환

| 상태 | 조건 | 화면 |
|---|---|---|
| 불러오는 중 | report 응답 전 | 제목 영역만, 아래는 회색 자리표시 |
| 완료 · 일부 성공 | status=completed, representative_attempt_index 있음 | 목업 프레임 1~5 |
| 완료 · 전부 성공 · 문제 0 | issues(is_reference=false) 비어 있음 | 프레임 7. "문제 없음"을 문장으로 |
| 완료 · 전부 실패 | representative_attempt_index=null | 프레임 6. 지표·Steps 없음, 종료 사유별 문장, "다시 측정" 버튼 |
| 모바일 측정 | run.viewport=mobile | 프레임 8. 예상 시간 숨기고 이유 문장, 세로 스크린샷 |
| 재생 전용 | run.mode=replay_only | 메타 줄에 "재생 전용", More metrics 비용 "$0 (LLM 호출 없음)", 프롬프트 "—" |
| 아직 안 끝남 | status ≠ completed | 리포트 대신 측정 진행 화면(F02)으로 보냄. API가 `409 NotFinished`를 주면 같은 처리 |
| 권한 없음 | 401 | F01과 같은 초대 코드 화면 |
| 없는 측정 | 404 | "측정 #N이 없습니다" + History 링크 |
| 팝업 열림 | 행·점·카드 클릭, 또는 주소 `#issue-{id}` / `#step-{idx}` | 프레임 5. Esc·바깥 클릭·뒤로가기로 닫힘 |

### 종료 사유 문장 (attempts.end_reason)

| end_reason | 문장 |
|---|---|
| success | 성공 |
| gave_up | 포기 · "{end_detail}" |
| loop | 반복 루프 · "{end_detail}" |
| budget_exceeded | 30단계 초과 |
| blocked | 차단됨 · "{end_detail}" |
| error | 오류 · "{end_detail}" |
| safety_stop | 위험 행동 직전 멈춤 · "{end_detail}" |

### 극단값

| 경우 | 처리 |
|---|---|
| 문제 20건 이상 | Overview Issues는 6건까지 + "문제 N건 전체 보기 →". Issues 탭은 전부, 같은 규칙은 묶고 건수 |
| 참고 4건 이상 | Overview에는 3건 + "참고 N건 →" |
| 30단계 | Steps 탭 10행 스크롤, 팝업 단계 띠 가로 스크롤 + 현재 단계로 자동 스크롤 |
| 반복 5회 | Attempts 5행. 첫 화면 영역이 창보다 길어지면 그냥 스크롤 |
| 스크린샷 URL 만료 | 회색 상자 + "다시 불러오기" 버튼. 호출 범위는 백엔드와 협의 |

## 팝업 동작

- `<dialog>` 요소. 열리면 닫기 버튼에 포커스, 포커스 가둠, 뒤 화면 `inert`.
- 이전/다음은 `issues[]` 순서(참고 포함)로. 첫 번째에서 이전, 마지막에서 다음은 비활성.
- 단계 띠에서 단계를 누르면 그 단계로. 그 단계에 문제가 있으면 What·How to fix도 그 문제로 바뀐다. 없으면 "이 단계에서 찾은 문제가 없습니다".
- 주소 해시를 `#issue-102` 또는 `#step-1`로 바꾼다(리디렉션 없음). 닫힌 상태에서 열 때만 `history.pushState`로 항목을 하나 추가하고, 팝업 안에서 문제·단계를 옮길 때는 `replaceState`로 같은 항목을 고친다. 그래서 뒤로가기는 팝업을 닫고(페이지를 떠나지 않음), ✕·Esc로 닫으면 추가한 항목을 되돌린다. 새로고침·공유하면 같은 팝업이 열린 채로 뜬다. `#step-N`으로 열면 그 단계의 첫 문제가 함께 선택되고, 없는 `#issue-999`는 팝업을 열지 않는다.
- 요소는 있는데 단계가 없는 문제(경로 밖, `step=null`이고 `element_key` 있음)는 스크린샷 자리에 "경로 밖 요소라 단계 화면이 없습니다" 문장. 행 썸네일은 "경로 밖". 요소도 없는 문제(R05)만 Attempts 띠를 쓴다.
- 요소 없는 문제(R05)는 스크린샷 자리에 Attempts 띠를 크게. 반복 구간 정보가 응답에 없으므로 attempt 전체를 가리킨다. 구간이 필요해지면 에이전트 코어와 협의.

## 기획서에 없고 이 문서에서 정한 것

| 항목 | 출처 |
|---|---|
| "리포트 요약"과 "단계 상세"를 탭 3개 + 팝업 하나로 합침 | 기획서는 두 화면. 문제 10종이 단계·요소에 붙어 있어 같은 스크린샷을 두 화면에 그리는 것보다 한 팝업에서 문제와 단계를 함께 넘기는 게 이동이 적다. PM 확인(묻는 것 2번) |
| 종합 점수 게이지 없음 | 기획서 7장에 종합 점수가 없다. Lighthouse식 게이지는 없는 점수를 만든 것처럼 보여 뺐다 |
| 섹션 이름 영어 (Verdict, Path metrics, Issues, Attempts, Passed rules, More metrics, Steps) | 기획서는 한국어. 라벨은 짧은 영어, 본문·값·문장은 한국어. 대시보드 UI와 통일 |
| 이슈 점수(confidence) 숫자를 숨기고 score_reason 한 줄만 | 기획서 6.2 "점수에 가장 크게 기여한 항목을 이슈마다 한 줄로". 숫자 자체는 사용자에게 의미가 없다 |
| 참고·통과 규칙을 접지 않고 스크롤 아래에 옅게 | F01 명세의 "숫자가 말없이 사라지면 고장으로 본다"와 같은 원칙. 접으면 통과 사실을 못 본다 |
| 첫 화면 영역을 창 높이에 맞춤 | 기획서 근거 없음. 첫 화면에 Verdict·지표·Issues·Attempts가 잘리지 않고 들어오게 하려는 설계 |
| 문제 제목 템플릿 | 기획서 6.1은 LLM 설명 두 문장만 정의. 목록 제목은 길이를 맞추려고 규칙별 템플릿 |
| 전부 실패 상태의 "다시 측정" 버튼 | 기획서 11장 리스크 대응 "실패 원인 분류 후 리포트에 표시"에서 끌어옴 |

위 항목에 반대가 있으면 이 문서를 고친다. 기획서에 근거가 있는 항목을 바꾸려면 기획서를 먼저 고친다.

## 보여주지 않기로 한 데이터

| 필드 | 이유 |
|---|---|
| issue.confidence | 위 표 |
| element_snapshot.style (색·배경·글자 크기·굵기), bg_chain | R02 measured(대비비)로 이미 요약됨. 디버깅용 |
| element_snapshot.landmark, context, label_text, inline_in_text | 매칭·규칙 내부용 |
| element_snapshot.in_first_view, first_view_scroll_px | R06 결과로 요약됨 |
| element_snapshot.viewport, scroll | 오버레이 좌표 계산에만 씀 |
| run.status, progress | 완료된 리포트에서는 항상 completed/100 |
| attempt.kind=agent인 경우의 replay_status, diverged_at_step | 항상 null |

## 플랫폼 백엔드에 요청할 것

`openapi.yaml`은 CODEOWNERS 보호라 이 문서에서 고치지 않는다. 담당자(한채훈·오준호)에게 요청한다.

| 필요한 것 | 왜 |
|---|---|
| 스크린샷 URL 만료 시 단계 단위 재발급 | 팝업에서 단계를 넘기다 만료될 때 attempt 전체를 다시 받지 않으려면 필요 |
| 실패한 attempt의 steps도 조회 가능한지 | 전부 실패 상태에서 "Attempt 1 단계 보기"를 열 수 있으면 실패 원인을 보여줄 수 있다 |
| Report에 task(과업 문장, URL) 포함 또는 `/tasks/{id}` 조회 | 지금은 호출 2번. 리포트 하나에 세 번 호출하면 로딩 상태가 셋이 된다 |

확정 전까지는 목 JSON으로 개발한다. 타입은 `openapi-typescript`로 생성하고 손으로 만들지 않는다.

## 자체 UX 기준 적용

| 기준 | 적용 |
|---|---|
| 텍스트 대비 4.5:1 이상 | 본문 `#0a0a0a` 19.80:1, 보조 `#525252` 7.81:1, 라벨·꼬리말 `#737373` 4.74:1, 오류 `#b91c1c` 6.47:1, 통과 `#166534` 7.06:1 |
| 그래픽 요소 3:1 이상 | 탭 밑줄·단계 버튼·아이콘 버튼 경계 `#737373` 또는 `#171717`. hairline `#e5e5e5`·`#d4d4d4`는 장식 전용 |
| 타겟 24×24 이상 (권장 44×44) | 탭, Details, 아이콘 버튼, 단계 버튼 44px. Issues 행 높이 70px 이상. Attempts 점 36px 버튼 + 간격 14px (WCAG 2.5.8 간격 예외 충족). 자기 측정에서 걸리면 44px로 키운다 |
| 이름 없는 요소 0건 | ◀ ▶ ✕ 와 점 버튼에 aria-label. 오버레이는 aria-hidden, 같은 정보를 오른쪽 글로 |
| 색만으로 의미 전달 금지 | 심각도 ▲■● + 영어 글자, 문제 단계 빨간 점 + "⚠ 문제 1" + 범례, 재생 끊김 ◆ + 문장 |
| 숫자 옆 기준 | "2.9 : 1 · 기준 4.5 : 1 (WCAG AA)", "30px · 권장 44px (최소 24px)", "7.9초 (문헌값 기준)", "편차 ±12% · 추정 약함" |

### 색 토큰 (F01 명세 값을 그대로 채택 — F01 질문 5번의 답)

| 토큰 | 값 | 쓰는 곳 |
|---|---|---|
| `--fg` | `#0a0a0a` | 본문 |
| `--muted-fg` | `#525252` | 보조 설명 |
| `--faint-fg` | `#737373` | 라벨·꼬리말 (F06에서 추가, 대비 4.74:1) |
| `--control-border` | `#737373` | 조작 요소 경계 |
| `--border` | `#d4d4d4` | 영역 구분 장식선 |
| `--hair` | `#e5e5e5` | 행 구분 hairline (F06에서 추가, 장식 전용) |
| `--primary` / `--primary-fg` | `#171717` / `#fafafa` | 주 버튼, 선택된 탭·단계 |
| `--surface` | `#f5f5f5` | 배경 면 |
| `--danger` | `#b91c1c` | 오류 글자, High 기호 |
| `--ok` | `#166534` | 통과 ✓ (F06에서 추가) |
| `--mark` | `#dc2626` | 스크린샷 위 표시선 전용. 글자에 쓰지 않는다 (F06에서 추가) |

Tailwind `theme.extend.colors`와 shadcn/ui CSS 변수(`--foreground`, `--muted-foreground`, `--border`, `--input`, `--primary`)에 같은 값을 매핑한다. 토큰 파일은 `apps/web` 스캐폴드 PR에서 올린다. 과업 예시 칩(F01 질문 4번)은 shadcn/ui Button(outline, 44px)을 공용으로 쓴다.

## 결정한 사항

리포트 UI 범위 안에서 끝나는 항목이라 먼저 정했다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 첫 화면 구성 | Verdict + Path metrics 4개 + Issues·Attempts 2열, 창 높이에 맞춤 | "한 페이지에 보이는 정보 = 중요한 지표, 나머지는 스크롤" |
| 문제 → 단계 연결 | 문제 행에 단계 번호, 단계 점에 빨간 테두리, 팝업에서 양방향 | 문제 10종이 단계·요소에 붙어 있다 |
| 팝업 vs 별도 화면 | 팝업 (스크롤 없이 한 화면, 왼쪽 스크린샷·오른쪽 글) | 스크린샷을 원본에 가까운 크기로 보려면 화면 너비가 필요. 해시 URL로 공유 가능 |
| 접기 | 쓰지 않음 | 위 표 |
| 썸네일 | 72×48 (Overview) / 128×84 (Issues 탭), bbox 중심 잘라냄 | Lighthouse 요소 셀 방식 |

## 결정이 필요한 사항

1. **모바일 엄지 도달 구역의 데이터** — 묻는 것 1번. 측정 지표·규칙 + 플랫폼 백엔드.
2. **단계 상세 화면 통합** — 묻는 것 2번. PM.
3. **공용 컴포넌트 범위(탭·팝업)와 라벨 언어** — 구현 시 대시보드 UI와 맞춘다. 비교 화면에서 같은 팝업을 쓰는 것이 목표.
