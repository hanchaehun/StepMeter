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
geometry and opacity. General transparent inputs, hidden ancestors and controls
without that indicator pattern remain excluded. This does not implement arbitrary
visually-hidden input/label-proxy patterns. A Material Kit drawer regression and
numbered Driver integration tests cover the supported pattern.

W3 할 일(수집기·에이전트 담당): `observe()`가 보이는 label로 조작하는 체크박스·라디오(Bootstrap custom-checkbox 등)도 지원한다. 지금은 지원하지 않아 에이전트가 sb-admin-2 로그인 과업(Remember Me 선택)을 끝낼 수 없다 ([ADR 0010](../../docs/adr/0010-w3-integration-decisions.md) 9번).

## ADR 0010에 따른 할 일

- LLM에 보내는 요소 목록에 가려진 요소(`occluded=True`)도 빼지 않고 넣으며 `"(가려짐)"`으로 표시한다 (ADR 0010)
- 가려진 요소도 최대 30개 제한 안에 포함한다 (ADR 0010)

## ADR 0011에 따른 할 일

결정 내용은 [ADR 0011](../../docs/adr/0011-w3-plan-gaps.md)에 있다.

- 다른 출처 iframe과 닫힌 shadow root 보완은 이번 일정에서 하지 않고 한계로 둔다. 개발 앱 0차 실행에서 수집 누락 때문에 실패한 케이스가 나오면 그때 다룬다 (ADR 0011 4번)
