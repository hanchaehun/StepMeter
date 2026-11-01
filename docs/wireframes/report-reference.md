# 참고 리포트 분석 — Lighthouse · PageSpeed Insights · axe DevTools

개발계획서 15.4가 와이어프레임 전에 하라고 한 분석이다. 세 리포트의 정보 위계, 이슈 정렬, 심각도 표현을 정리하고, F06 리포트 화면에 가져온 것과 버린 것을 적는다. 결과는 [`f06-report.md`](f06-report.md)와 [`f06-report.html`](f06-report.html)에 반영했다.

- **담당:** 리포트 UI
- **근거:** 개발계획서 15.4 "참고 리포트 분석 (W1, 와이어프레임 전)", 서비스 기획서 6.2 "리포트 작성 원칙"
- **조사 방법:** 공식 문서와 Lighthouse 리포트 렌더러 소스(`report/renderer/*.js`, `core/config/default-config.js`), Deque 문서. 화면을 직접 캡처한 것이 아니라 실제 UI 문구가 조금 다를 수 있다. 출처는 맨 아래.

---

## 1. Lighthouse

**한 페이지**를 한 번 로드한 결과다. 사이트를 돌아다니지 않는다.

### 구조 (위에서 아래로)

1. 카테고리 점수 게이지 4개: Performance, Accessibility, Best Practices, SEO (최근 Agentic Browsing 추가).
2. 카테고리별 헤더: 게이지 + 한 줄 설명.
3. Performance는 Metrics 묶음(FCP, LCP, TBT, CLS, Speed Index)이 먼저. "Expand view"로 지표 설명 펼침.
4. 로딩 과정 스크린샷 필름스트립.
5. "Show audits relevant to: All / FCP / LCP / TBT / CLS" 필터. 고른 지표에 영향 주는 항목만 남긴다.
6. 실패 항목을 그룹으로. Performance는 Insights / Diagnostics (Lighthouse 13부터 옛 Opportunities가 Insights로 통합). Accessibility는 Contrast, Names and labels, Navigation, ARIA, Tables and lists, Internationalization and localization, Audio and video, Best practices.
7. 접힌 묶음 3개: "Additional items to manually check (N)", "Passed audits (N)", "Not applicable (N)". 기본은 접혀 있고 건수만 보인다. 경고 붙은 통과 항목은 "Passed audits but with warnings"로 따로.
8. 실행 환경 블록(Device, Network throttling, CPU throttling, Screen emulation, Axe version)과 "Values are estimated and may vary" 면책.

### 점수와 색

| 점수 | 색 | 라벨 |
|---|---|---|
| 0–49 | 빨강 | Poor |
| 50–89 | 주황 | Needs Improvement |
| 90–100 | 초록 | Good |

- Performance 점수는 지표 5개의 가중 평균(TBT 30%, LCP 25%, CLS 25%, FCP 10%, SI 10%). 개별 개선 항목은 점수에 영향을 주지 않는다고 명시한다.
- Accessibility 점수는 axe 규칙별 가중치(10 / 7 / 3 / 1 / 0)의 가중 평균. 부분 점수 없음. 버튼 이름 누락 10, 대비 부족 7, 타겟 크기 7.
- 점수에 반영 안 되는 항목에는 "Unscored" 표시와 툴팁 "This audit does not contribute to the overall category score".

### 정렬 (렌더러 소스 기준)

- Performance 실패 항목: 점수 낮은 순 → 선택한 지표 필터의 절감량 큰 순 → 전체 지표 영향도 큰 순 → 안내 등급 순.
- 다른 카테고리: 그룹 안에서 가중치 높은 순.
- 통과 항목은 정렬하지 않고 접는다.

### 항목 한 줄

- 왼쪽 상태 아이콘(통과 초록 원, 중간 주황 사각, 실패 빨강 삼각, 정보성 회색, 오류).
- 제목(통과/실패에 따라 문구가 바뀜) + 오른쪽 끝 displayValue("Est savings of 1,230 ms", "3 elements found").
- 설명 안 "Learn more" 링크. 관련 지표가 있으면 "Relevant to LCP" 칩.
- 펼치면 표. 열 제목 "Element", "Failing Elements", "Est Savings", "URL", "Source".
- **요소 표시:** 전체 페이지 스크린샷에서 해당 요소 영역을 잘라낸 썸네일(최대 147×100) + 요소 라벨 + HTML 스니펫 + CSS 선택자(툴팁). 스니펫은 "Expand snippet / Collapse snippet".

## 2. PageSpeed Insights

Lighthouse 위에 **실사용자 데이터 층**을 얹은 구조. 역시 URL 하나다. "Origin" 전환은 도메인 전체의 28일 통계이지 페이지를 훑은 결과가 아니다.

### 구조 (위에서 아래로)

1. Mobile / Desktop 탭.
2. **"Discover what your real users are experiencing"** — 실사용자(CrUX, 28일).
   - 맨 위 "Core Web Vitals Assessment: Passed / Failed". LCP, INP, CLS 셋의 75번째 백분위가 전부 Good이어야 Passed.
   - 지표 카드: 핵심 3개(LCP, INP, CLS) 먼저, 그다음 FCP, TTFB.
   - 지표마다 75번째 백분위 값이 색으로 크게, 아래 초록·주황·빨강 3분할 막대에 구간 비율(%).
   - "This URL / Origin" 전환. URL 데이터가 부족하면 "This URL" 비활성, 도메인 데이터로 대체. 그것도 없으면 "No Data".
   - "Expand view"로 분포 상세. 섹션 끝에 수집 기간·기기·네트워크·표본·Chrome 버전 꼬리말.
3. **"Diagnose performance issues"** — Lighthouse 실험실 데이터.
   - 카테고리 게이지 4개(옛날엔 페이지 맨 위였는데 이 섹션 안으로 내려옴).
   - 지표 목록 + 상태 아이콘, 로딩 스크린샷 썸네일, 그 아래 Lighthouse와 같은 Insights / Diagnostics / Passed audits.
   - 끝에 테스트 위치·스로틀링 꼬리말.

### 실사용자 지표 임계값

| 지표 | Good | Needs Improvement | Poor |
|---|---|---|---|
| LCP | ≤2.5s | 2.5–4s | >4s |
| INP | ≤200ms | 200–500ms | >500ms |
| CLS | ≤0.1 | 0.1–0.25 | >0.25 |
| FCP | ≤1.8s | 1.8–3s | >3s |
| TTFB | ≤0.8s | 0.8–1.8s | >1.8s |

### 설계 포인트

- "실제 사람 데이터"와 "기계가 돌린 실험실 데이터"를 **섹션 자체를 나눠** 구분하고 각 섹션에 출처 꼬리말. 두 숫자가 다를 수 있음을 구조로 보여준다.
- 합격/불합격 한 줄 → 근거 지표 → 개선 항목. **결론 → 근거 → 할 일** 순서.
- 모든 숫자 옆에 임계값 기준 색과 분포가 같이 붙는다.

## 3. axe DevTools (Chrome DevTools 패널)

**지금 열려 있는 DOM 상태 하나**를 검사한다. 모달·아코디언은 열린 상태와 닫힌 상태를 각각 스캔하라고 문서에 적혀 있다. 사이트 크롤링은 유료 제품(axe Monitor)이다.

### 구조

1. 시작: "Full Page Scan" / "Partial Page Scan"(선택 요소만).
2. 결과 상단: 스캔한 URL + "Re-run".
3. 요약: "Total Issues" 숫자, 클릭하면 필터로 동작하는 분류 칩.
   - 영향도 4단계: Critical, Serious, Moderate, Minor. 각각 건수.
   - "Needs Review": axe-core가 확신하지 못한 후보(이미지·그라데이션 위 대비 등). 사용자가 위반/기각으로 표시하면 세션에 기억.
   - "Best Practice": WCAG 기준에 직접 묶이지 않는 권장 사항. 설정에서 켜야 보임.
   - "AUTOMATIC ISSUES" / "GUIDED ISSUES" 구분.
4. 이슈 목록: **규칙 단위로 묶고 규칙마다 건수.** 규칙을 펼치면 규칙 설명.
5. 이슈 상세: Issue description, Element location(CSS 선택자), Element source(HTML), "Highlight"(페이지에서 테두리, 누르면 "Stop Highlight"), "Inspect Element", "Share Issue", 영향도 배지 + WCAG 태그, 해결 단계, "More info"(Deque University).
6. 같은 규칙의 요소가 여러 개면 상세 안 페이저로 하나씩(1 of N).
7. Export: CSV / JSON / JUnit XML. JSON 필드: ruleId, impact, description, help, helpUrl, tags, selector, source, summary, needsReview.

### 영향도 정의 (axe-core 공식)

| 영향도 | 정의 | 대응 |
|---|---|---|
| Critical | 핵심 기능·콘텐츠에 확실히 접근 못 함 | 가능한 한 빨리, 1주 안 |
| Serious | 부분적 또는 완전한 장벽 | 우선 수정 |
| Moderate | 어려움은 있지만 막지는 않음 | 현재 릴리스에서 |
| Minor | 성가신 수준 | 근처 작업 중이면 수정 |

### 설계 포인트

- 점수가 없다. 총 건수와 영향도 분포만 보여주고 영향도가 곧 우선순위.
- 문제를 "규칙 → 요소" 2단으로 묶어 같은 문제 30개를 30줄로 늘어놓지 않는다.
- 요소 위치는 스크린샷이 아니라 **살아있는 페이지에 하이라이트** + 선택자 + 소스.
- 확실하지 않은 판정을 "Needs Review"로 분리해 기본 목록의 신뢰도를 지킨다.

---

## 4. 세 리포트의 공통점

| 공통 패턴 | Lighthouse | PSI | axe |
|---|---|---|---|
| 결론 → 근거 → 할 일 | 게이지 → 지표 → 항목 | Passed/Failed → 지표 → 항목 | 총 건수 → 영향도 → 목록 |
| 통과·해당 없음은 접는다 | Passed audits (N) 접힘 | 같음 | (통과는 아예 안 보여줌) |
| 같은 문제는 묶는다 | 감사 항목 안 표로 | 같음 | 규칙 → 요소, 건수 + 페이저 |
| 숫자에 기준을 붙인다 | 3단계 색 + 임계값 | 3단계 색 + 분포 % | 영향도 4단계 |
| 불확실한 판정 분리 | Unscored, manual check | — | Needs Review |
| 요소 가리키기 | 잘라낸 썸네일 + 스니펫 + 선택자 | 같음 | 라이브 하이라이트 + 선택자 + 소스 |

## 5. StepMeter와의 차이

세 도구는 전부 **한 페이지**를 잰다. StepMeter는 **과업 경로**를 잰다. 에이전트가 최대 30단계를 가며 여러 페이지와 화면 상태를 지나고 단계마다 스냅샷과 axe 결과가 쌓인다. 그래서 우리 리포트에는 세 도구에 없는 축이 하나 있다. **단계(step) 축**이다. 문제 11종 중 R05 하나를 빼면 전부 특정 단계의 특정 요소에 붙어 있으므로, 문제 목록과 단계 축이 서로를 가리켜야 한다.

어느 페이지를 보는지는 리포트 UI가 정하지 않는다. 범위는 F01에서 사용자가 입력하고, 실제 경로는 에이전트 코어가 정하며, 페이지 전체 axe 결과 중 과업 경로 위 요소만 기본 목록에 넣는 건 측정 지표·규칙 담당의 규칙(개발계획서 5.5)이다. 리포트 UI는 그 결과를 단계 축 위에 배치하고 참고를 분리해 보여준다.

## 6. F06에 가져온 것 / 버린 것

### 가져온 것

| 무엇 | 어디서 | F06에서 어떻게 |
|---|---|---|
| 맨 위 한 줄 판정 | PSI Core Web Vitals Assessment | Verdict "3회 중 2회 성공 · 예상 7.9초" |
| 결론 → 근거 → 할 일 순서 | PSI, Lighthouse | Verdict → Path metrics → Issues |
| 규칙 → 요소 묶음과 건수, 페이저 | axe | 같은 규칙은 묶고 건수. 팝업에 이전/다음 |
| 잘라낸 요소 썸네일 | Lighthouse 요소 셀 | Issues 행의 72×48 썸네일. 라이브 하이라이트는 불가(저장된 스크린샷)라 Lighthouse 방식 |
| 심각도를 기호 + 글자로 | Lighthouse 아이콘, axe 배지 | ▲ High ■ Medium ● Low |
| 숫자 옆 기준 | PSI 임계값, Lighthouse displayValue | "2.9 : 1 · 기준 4.5 : 1", "30px · 권장 44px" |
| 불확실한 판정 분리 | axe Needs Review, Lighthouse Unscored | is_reference → Reference 목록 |
| 통과 항목에 건수 | Lighthouse Passed audits | Passed rules 8 + 규칙별 통과 근거 한 줄 |
| 실행 환경 꼬리말 | Lighthouse runtime settings | More metrics의 모델·프롬프트·비용·시각 |
| 지표 설명 펼침보다 숫자 우선 | Lighthouse Metrics | Path metrics 4개 숫자 + 짧은 꼬리표 |

### 버린 것

| 무엇 | 왜 |
|---|---|
| 0–100 종합 점수 게이지 | 우리 데이터에 종합 점수가 없다. "숫자는 코드가 만든다" 원칙상 점수를 합성하지 않는다. 게이지를 그리면 없는 점수를 만든 것처럼 보인다 |
| 통과·참고 항목 접기 | 보민님 F01과 같은 이유로 "숫자가 말없이 사라지면 고장으로 본다". 참고와 통과는 접지 않고 옅게, 스크롤 아래에 둔다 |
| 라이브 하이라이트 / Inspect | 측정 대상 페이지가 우리 화면 안에 없다. 저장된 스크린샷 위 오버레이로 대체 |
| 지표 필터 칩 ("Show audits relevant to") | 문제가 보통 몇 건이라 필터가 필요 없다. 대신 단계 축으로 거른다 |
| 3분할 분포 막대 | 실사용자 분포가 없다. 반복 3회의 편차(±N%)를 글자로만 |
| Needs Review의 사용자 판정 저장 | 라벨링은 PM·수집·매칭의 이슈 라벨 흐름(`/issues/{id}/label`)이 따로 있다. 리포트 화면에서는 하지 않는다 |
| Export 버튼 | 학기 범위 밖. 공유는 팝업 해시 URL로 대신 |

---

## 출처

- Lighthouse: [overview](https://developer.chrome.com/docs/lighthouse/overview), [performance scoring](https://developer.chrome.com/docs/lighthouse/performance/performance-scoring), [accessibility scoring](https://developer.chrome.com/docs/lighthouse/accessibility/scoring), [understanding results](https://github.com/GoogleChrome/lighthouse/blob/main/docs/understanding-results.md), [moving to Insights](https://developer.chrome.com/blog/moving-lighthouse-to-insights), [v13 release](https://github.com/GoogleChrome/lighthouse/releases/tag/v13.0.0), 렌더러 소스 `report/renderer/report-utils.js`, `performance-category-renderer.js`, `category-renderer.js`, `details-renderer.js`, `core/config/default-config.js`, `core/lib/i18n/i18n.js`
- PageSpeed Insights: [About PSI](https://developers.google.com/speed/docs/insights/v5/about), [What's new in PSI](https://web.dev/whats-new-pagespeed-insights), [CrUX on PSI](https://developer.chrome.com/docs/crux/guides/pagespeed-insights)
- axe DevTools: [extension docs](https://docs.deque.com/devtools-for-web/4/en/devtools-extension/), [Scanning](https://docs.deque.com/devtools-for-web/4/en/devtools-scanning), [Exporting](https://docs.deque.com/devtools-for-web/4/en/devtools-export), [axe-core issue impact](https://github.com/dequelabs/axe-core/blob/develop/doc/issue_impact.md), [axe extension 3.0](https://www.deque.com/blog/upgrade-accessibility-testing-axe-extension-3-0/), [freee 가이드](https://a11y-guidelines.freee.co.jp/en/explanations/axe.html)
