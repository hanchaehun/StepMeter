# worker/collect/

- **담당 역할:** 수집·매칭
- **하는 일:** 페이지 주입 JS. 요소 목록 수집(역할·접근 가능한 이름은 esbuild로 번들한 dom-accessibility-api로 계산), 측정 훅 스냅샷, Shadow DOM·iframe·가림 처리.
- **참고:** 개발계획서 3.1, 4.2, 5.1

## 사용법

```bash
npm install && npm run build:collect   # src/collect.js + dom-accessibility-api → dist/collect.js (git 제외)
pip install pydantic playwright && playwright install chromium
python -m unittest tests.test_collect
```

```python
from worker.collect.collector import record_first_view, observe, snapshot

await record_first_view(page)       # 페이지 로드 직후 1회 (이동할 때마다 다시)
items = await observe(page)         # [{el_id, role, name, landmark, bbox, occluded}]
snap = await snapshot(page, el_id)  # ElementSnapshot (click·type 직전)
```

- `observe()`는 뷰포트 안의 보이는 요소를 **가려진 요소까지** 돌려준다. LLM에 보낼 목록(가림 제외, 60개 제한)과 반환 형식은 에이전트 코어와 정한다.
- 아직 안 하는 것: 다른 출처 iframe, 닫힌 shadow root (W2 SPA 스트레스 테스트 뒤 보완).
