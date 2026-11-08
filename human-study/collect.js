// 사람 데이터 수집 스크립트 (개발계획서 9.1 "수집", 동의서 3·4절).
//
// 브라우저 안에서 참가자의 마우스 이동·누름·뗌·클릭·스크롤·키 입력의 시각과 좌표, 대상 요소 지문을
// window.__hsPush(event)로 내보낸다. 이벤트는 openapi.yaml HumanEvent 다섯 칸뿐이다:
//   { t_ms, type: move|down|up|click|scroll|key|stable, x, y, target_key }
// 입력한 글자는 절대 기록하지 않는다. 키는 시각과 대상 요소만 남긴다(키 누름 횟수 = key 이벤트 수).
//
// 전제 (세션 러너가 init script로 먼저 넣는다):
//   - window.__hsStart: 세션 시작 epoch ms. t_ms = Date.now() − __hsStart
//   - window.__hsOrigin: 연구용 페이지의 출처. 다른 출처(외부 링크·검색)에서는 설치하지 않는다 (동의서 4절)
//   - window.__hsPush(ev): 이벤트를 받는 함수 (Playwright expose_function). 페이지 이동 뒤에도 유지된다
//   - globalThis.__stepmeter: 이원준 님 수집 번들(worker/collect/dist/collect.js). 요소 지문은 observe()의
//     tag·role·name·label_text·landmark를 그대로 써서 dom-accessibility-api 계산과 어긋나지 않게 한다 (3.1)
(() => {
  // 최상위 문서에서만, 연구용 페이지 출처에서만 설치한다 (프레임 좌표·stable이 섞이지 않게)
  if (window.top !== window) return;
  const origin = window.__hsOrigin;
  if (origin) {
    const same = location.origin === origin || (origin === "file://" && location.protocol === "file:");
    if (!same) return;
  }
  if (window.__hsInstalled) return;
  window.__hsInstalled = true;

  const MOVE_INTERVAL_MS = 16;   // 약 60Hz
  const STABLE_MS = 300;         // load 후 DOM 변경이 300ms 없으면 "화면 안정" (9.1)

  const now = () => Math.max(0, Math.round(Date.now() - (window.__hsStart ?? Date.now())));
  // t는 핸들러 첫 줄에서 잡은 시각. 지문 계산(observe) 시간이 t_ms에 더해지지 않게 한다
  const push = (type, x, y, target_key, t = now()) => {
    try {
      window.__hsPush({ t_ms: t, type, x, y, target_key });
    } catch (_) {
      /* 러너가 없으면(개발 중) 조용히 버린다 */
    }
  };

  // ---- 요소 지문: element_key 형식 `tag|role|name|label_text|landmark` (null → "") ----
  const keyOf = (it) => [it.tag, it.role ?? "", it.name ?? "", it.label_text ?? "", it.landmark ?? ""].join("|");

  function observed() {
    const S = globalThis.__stepmeter;
    if (!S) return [];
    try {
      return S.observe();
    } catch (_) {
      return [];
    }
  }

  // (x, y) 뷰포트 좌표를 덮는 상호작용 요소 중 가장 작은 것. 가려지지 않은 요소를 우선한다. 없으면 null (본문 글 등).
  function fingerprintAt(x, y) {
    let best = null;
    for (const it of observed()) {
      const b = it.bbox;
      if (x < b.x || x > b.x + b.width || y < b.y || y > b.y + b.height) continue;
      const rank = (it.occluded ? 1 : 0) * 1e9 + b.width * b.height;
      if (!best || rank < best.rank) best = { it, rank };
    }
    return best ? keyOf(best.it) : null;
  }

  // 포커스된 요소의 지문. observe() 항목 중 같은 자리(±1px)의 것만. 못 찾으면 null (엉뚱한 요소로 대체하지 않는다)
  function fingerprintOf(el) {
    if (!el || el === document.body || el === document.documentElement) return null;
    const r = el.getBoundingClientRect();
    const same = (a, b) => Math.abs(a - b) <= 1;
    for (const it of observed()) {
      const b = it.bbox;
      if (same(b.x, r.x) && same(b.y, r.y) && same(b.width, r.width) && same(b.height, r.height)) return keyOf(it);
    }
    return null;
  }

  // ---- 포인터 ----
  let lastMoveAt = -Infinity;
  let lastPointer = null;

  document.addEventListener(
    "pointermove",
    (e) => {
      const t = now();
      lastPointer = { x: e.clientX, y: e.clientY };
      const p = performance.now();
      if (p - lastMoveAt < MOVE_INTERVAL_MS) return;
      lastMoveAt = p;
      push("move", e.clientX, e.clientY, null, t);
    },
    { capture: true, passive: true },
  );

  const pointerType = { pointerdown: "down", pointerup: "up", click: "click" };
  for (const name of Object.keys(pointerType)) {
    document.addEventListener(
      name,
      (e) => {
        const t = now();
        // detail=0 click은 키보드(Enter·Space)나 label이 만든 합성 클릭이다. 포인터 조작이 아니므로 기록하지 않는다
        if (name === "click" && e.detail === 0) return;
        lastPointer = { x: e.clientX, y: e.clientY };
        push(pointerType[name], e.clientX, e.clientY, fingerprintAt(e.clientX, e.clientY), t);
      },
      { capture: true, passive: true },
    );
  }

  // ---- 스크롤: 좌표는 마지막 포인터 위치 (휠·트랙패드 스크롤은 좌표가 없다) ----
  window.addEventListener(
    "scroll",
    () => push("scroll", lastPointer ? lastPointer.x : null, lastPointer ? lastPointer.y : null, null),
    { capture: true, passive: true },
  );

  // ---- 키 입력: 시각과 대상만. e.key는 읽지 않는다. 자동 반복(repeat)은 세지 않는다 ----
  document.addEventListener(
    "keydown",
    (e) => {
      const t = now();
      if (e.repeat) return;
      push("key", null, null, fingerprintOf(document.activeElement), t);
    },
    { capture: true, passive: true },
  );

  // ---- 화면 안정: load 뒤, 그리고 DOM 변경이 STABLE_MS 동안 없으면 stable ----
  let stableTimer = null;
  const armStable = () => {
    if (stableTimer) clearTimeout(stableTimer);
    stableTimer = setTimeout(() => {
      stableTimer = null;
      push("stable", null, null, null);
    }, STABLE_MS);
  };
  const startObserving = () => {
    new MutationObserver(armStable).observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
    armStable();
  };
  if (document.readyState === "complete") {
    startObserving();
  } else {
    window.addEventListener("load", startObserving, { once: true });
  }
  // bfcache로 돌아오면 load가 없으므로 다시 안정 판정
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) armStable();
  });
})();
