# worker/collect/

- **담당 역할:** 수집·매칭
- **하는 일:** 페이지 주입 JS. 요소 목록 수집(역할·접근 가능한 이름은 esbuild로 번들한 dom-accessibility-api로 계산), 측정 훅 스냅샷, Shadow DOM·iframe·가림 처리.
- **참고:** 개발계획서 3.1, 4.2, 5.1

## 사용법

```bash
npm ci && npm run build:collect   # src/collect.js + dom-accessibility-api → dist/collect.js (git 제외)
pip install -r requirements-dev.txt && python -m playwright install chromium
python -m unittest tests.test_collect
```

```python
from worker.collect.collector import record_first_view, observe, snapshot

await record_first_view(page)       # 페이지 로드 직후 1회 (이동할 때마다 다시)
items = await observe(page)         # [{el_id, tag, role, name, landmark, label_text, bbox, occluded}]
snap = await snapshot(page, el_id)  # ElementSnapshot (click·type 직전)
```

- `observe()`는 뷰포트 안의 보이는 요소를 **가려진 요소까지** 돌려준다. LLM에 보낼 목록(가려진 요소 포함·`"(가려짐)"` 표시, 최대 30개, [ADR 0010](../../docs/adr/0010-w3-integration-decisions.md))은 에이전트 코어가 이 결과를 잘라 만들고, 반환 형식은 에이전트 코어와 정한다.
- 아직 안 하는 것: 다른 출처 iframe, 닫힌 shadow root (W2 SPA 스트레스 테스트 뒤 보완).
- `__stepmeter.describe(el)`: 임의 요소의 지문 필드(`tag`·`role`·`name`·`label_text`·`landmark`)를 `observe()`와 같은 계산으로 돌려준다. 사람 데이터 수집(`human-study/collect.js`)이 참가자가 누른 좌표의 실제 요소에 쓴다. `observe()` 결과와 에이전트 쪽 동작은 바꾸지 않는다 (#43).

## 번호 대상 해석

`resolve_element(page, el_id)`는 마지막 `observe()`의 **원래 요소**를 Playwright ElementHandle로 반환한다. 호출자가 `dispose()`해야 한다. 프레임 내부 요소는 실제 owner frame으로 handle을 옮겨 클릭 좌표를 맞춘다. DOM 연결이 끊기거나 이름·역할·주요 식별 속성·select 옵션 순서가 바뀌면 stale 오류를 내며 다른 번호로 조용히 대체하지 않는다. 스크롤·가상 목록 재활용·라우트 변경 후에는 새 `observe()`를 사용한다. 동일한 속성을 가진 레코드 교체까지 완전히 검출하는 것은 아니다.

SPA 정량 검증과 합성 회귀: [benchmark/spa/README.md](../../benchmark/spa/README.md). 실제 3개 SPA 합격과 합성 테스트 통과는 구분한다.

### Styled native controls

A transparent native checkbox/radio may still be the actual visible widget's hit
target. The collector includes it only when it has a visible associated label,
visible ancestors, pointer events, and a visible sibling SVG/image/canvas indicator
fully inside its input rectangle. It preserves the native input's role, name,
geometry and opacity. A Material Kit drawer regression and numbered Driver
integration tests cover this pattern.

W3: 보이는 연결 label로 조작하는 체크박스·라디오도 지원한다
([ADR 0010](../../docs/adr/0010-w3-integration-decisions.md) 9번).
`observe()`·`resolve_element()`의 의미 대상은 원래 input이다. 가림은 실제 label
표면에서 검사하고, 드라이버는 `click_point()`가 검증한 최상위 좌표로 실제 마우스를
누른다(force 클릭/JS checked 변경 없음). 비활성 컨트롤은 조작하지 않는다.
label 연결·정체성이 바뀌면 기존 번호는 stale이다. label 안의 독립 링크/버튼은
체크박스 조작으로 대신 누르지 않는다. 투명 막도 pointer-events가 있으면 가림이다.

input 사각형 중심이 label 또는 절대 배치된 `::before` 안이면 native bbox를
유지한다(Bootstrap의 16×20px input 포함). input이 display:none/화면 밖 등으로
표면을 나타내지 못하면 보이는 label의 bbox를 쓴다. 빈 label은 절대 배치된
`::before` 사각형을 사용한다. 역할·이름·style·bg_chain은 input 기준이다.
복잡한 transform을 건 pseudo-element의 정밀 기하는 지원하지 않는다.
체크 상태 효과는 보이는 native/MUI/label pseudo indicator가 있을 때 관찰한다.
표시가 전혀 없는 투명 input의 checked 속성만 바뀐 경우는 시각 반응으로 세지 않는다.

검증: `tests.test_collect_labels`, `tests.test_collect_styled_controls`,
`tests.test_effect_native_controls`, `tests.test_agent_core`.
실제 SB Admin 기준선·small 변이 재현:
`python -m benchmark.verify_collect_labels` (빌드는 `benchmark.build_variant`로 준비).
가림 보강·특징 추출·검증과 협업 전달 사항은
[W3 기록](../../docs/w3-collection-features.md)을 참고한다.

## ADR 0010에 따른 할 일

- LLM에 보내는 요소 목록에 가려진 요소(`occluded=True`)도 빼지 않고 넣으며 `"(가려짐)"`으로 표시한다 (ADR 0010)
- 가려진 요소도 최대 30개 제한 안에 포함한다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 다른 출처 iframe과 닫힌 shadow root 보완은 이번 일정에서 하지 않고 한계로 둔다. 개발 앱 0차 실행에서 수집 누락 때문에 실패한 케이스가 나오면 그때 다룬다 (ADR 0011 4번)
