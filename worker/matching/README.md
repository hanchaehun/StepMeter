# worker/matching/

- **담당 역할:** 수집·매칭
- **하는 일:** 요소 매칭 모듈. 재생(7.2)과 문제 매칭(7.3)이 함께 쓴다.
- **참고:** 개발계획서 7.2 매칭 규칙

## 사용법

```python
from worker.matching.match import match, fingerprint

m = match(recorded, items, aliases)  # recorded: ElementSnapshot 또는 지문 dict, items: observe() 결과
m.status   # "matched" | "none" | "ambiguous"
m.element  # matched일 때 현재 화면의 요소 (observe() 한 줄)
m.step     # 찾은 순위: 0 별칭, 1 정확, 2 유사도, 3 포함, "unnamed" 지문
```

- `aliases`: 사용자가 확인한 `(이전 지문, 새 지문)` 쌍 목록 (element_alias). 지문 형식은 openapi.yaml `ElementFingerprint`.
- 모든 순위에 역할 일치와 유일성이 걸린다. 후보가 둘 이상이면 `ambiguous`, 재생기는 `none`과 같이 경로 변경으로 처리한다.
- 위치·구조는 쓰지 않는다. 이름 없는 요소는 지문(태그·역할·label_text·랜드마크)이 같을 때만 매칭한다.
- 아직 안 하는 것: 4순위 의미 유사도(선택 항목), 사후 검증(효과 유형·URL 비교, 재생기 쪽).
- 테스트: `python -m unittest tests.test_matching` (브라우저 없이 고정 픽스처)
