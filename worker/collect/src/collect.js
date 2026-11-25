// 페이지 주입 수집기 (개발계획서 4.2, 5.1, docs/element_snapshot_spec.md).
// esbuild로 dom-accessibility-api와 함께 번들해 window.__stepmeter 로 노출한다.
import { computeAccessibleName, getRole } from "dom-accessibility-api";

// #75: ARIA 위젯 역할(옵션 목록·메뉴 선택 항목·스위치·콤보박스 등)은 tabindex가 없거나 -1이어도 조작 대상이다.
// cmdk CommandItem·Radix SelectItem(role=option)이 빠지면 필터·선택 과업을 끝낼 수 없다.
const INTERACTIVE =
  "a, button, input, select, textarea, [role=button], [role=link], [role=tab], [role=checkbox], [role=menuitem], " +
  "[role=option], [role=menuitemcheckbox], [role=menuitemradio], [role=radio], [role=switch], [role=combobox], " +
  "[role=treeitem], [role=slider], [role=spinbutton], [role=searchbox], [role=textbox], [onclick]";
const LANDMARKS = new Set([
  "banner", "navigation", "main", "complementary", "contentinfo", "search", "form", "region",
]);
const NAMED_ONLY = new Set(["form", "region"]);
// #75: 열린 겹침 층(모달·팝오버·옵션 목록·메뉴). 에이전트가 60개를 고를 때 이 안의 요소를 먼저 둔다.
const OVERLAY = 'dialog[open], [role=dialog], [role=alertdialog], [aria-modal="true"], [role=listbox], [role=menu]';
const TEXT_INPUT_TYPES = new Set(["text", "email", "search", "password", "tel", "url", "number"]);
const TEXT_INPUT_ROLES = new Set(["textbox", "searchbox", "combobox"]);
const NEARBY_PX = 48;

// 마지막 observe() 결과와 로드 직후 첫 화면 기록. 페이지 이동 시 window와 함께 사라진다.
let observed = [];
let firstView = new WeakMap();

const isInteractive = (el) =>
  el.matches(INTERACTIVE) || (el.hasAttribute("tabindex") && el.tabIndex >= 0);

const clean = (text, max) => text.replace(/\s+/g, " ").trim().slice(0, max);
const nameOf = (el) => clean(computeAccessibleName(el, { hidden: !!labelProxy(el) }), 1000);
const roleOf = (el) => getRole(el) || null;

// Capture semantic identity, not just isConnected: virtual lists can reuse a DOM
// node for another row between observe and action. Never renumber on resolve.
const identityOf = (el) => JSON.stringify([
  el.tagName, roleOf(el), nameOf(el), el.getAttribute("id"),
  el.getAttribute("href"), el.getAttribute("name"), el.getAttribute("type"),
  el.getAttribute("data-id"), el.getAttribute("data-key"), el.getAttribute("data-testid"),
  el.tagName === "SELECT" ? [...el.options].map(o => [o.value, o.label, o.disabled]) : null,
]);

// Shadow DOM과 같은 출처 iframe 경계를 넘는 부모. 최상위 html이면 null.
function up(el) {
  if (el.parentElement) return el.parentElement;
  const parent = el.parentNode;
  if (parent && parent.host) return parent.host;
  return el.ownerDocument.defaultView?.frameElement ?? null;
}

function isSelfOrAncestor(ancestor, node) {
  for (let el = node; el; el = up(el)) if (el === ancestor) return true;
  return false;
}

// iframe 안 문서 좌표를 최상위 뷰포트 좌표로 바꾸는 오프셋 (테두리·패딩 포함).
function frameOffset(iframe, ox, oy) {
  const r = iframe.getBoundingClientRect();
  const cs = getComputedStyle(iframe);
  return [
    ox + r.x + iframe.clientLeft + parseFloat(cs.paddingLeft),
    oy + r.y + iframe.clientTop + parseFloat(cs.paddingTop),
  ];
}

// Cross-origin frames and closed shadow roots remain out of scope (ADR 0011).
function* walk(root, context, ox, oy) {
  for (const el of root.querySelectorAll("*")) {
    if (isInteractive(el)) yield { el, context, ox, oy };
    if (el.shadowRoot) yield* walk(el.shadowRoot, "open_shadow", ox, oy);
    if (el.tagName === "IFRAME") {
      let doc = null;
      try {
        doc = el.contentDocument;
      } catch {}
      if (doc) yield* walk(doc, "same_origin_iframe", ...frameOffset(el, ox, oy));
    }
  }
}

function bboxOf({ el, ox, oy, proxy }) {
  // Frame positions can change after observe() when the driver scrolls.
  ox = oy = 0;
  for (let frame = el.ownerDocument.defaultView?.frameElement; frame;
       frame = frame.ownerDocument.defaultView?.frameElement) {
    [ox, oy] = frameOffset(frame, ox, oy);
  }
  let r = el.getBoundingClientRect();
  if (proxy) {
    const lr = proxy.getBoundingClientRect();
    // Bootstrap's native 16px rectangle sits over label::before. Preserve it
    // for target-size measurements. Fully hidden/offscreen inputs instead use
    // their visible label's action rectangle.
    const center = [r.x + r.width / 2, r.y + r.height / 2];
    const before = getComputedStyle(proxy, "::before");
    const pseudo = before.position === "absolute" && before.content !== "none" && before.content !== "normal"
      ? { x: lr.x + parseFloat(before.left), y: lr.y + parseFloat(before.top),
          width: parseFloat(before.width), height: parseFloat(before.height) } : null;
    const inside = b => b && center[0] >= b.x && center[1] >= b.y &&
      center[0] < b.x + b.width && center[1] < b.y + b.height;
    if (r.width <= 1 || r.height <= 1 || (!inside(lr) && !inside(pseudo))) {
      r = lr.width > 0 && lr.height > 0 ? lr : pseudo || lr;
    }
  }
  return { x: r.x + ox, y: r.y + oy, width: r.width, height: r.height };
}

function visibleLabel(label) {
  if (!label.isConnected || !label.checkVisibility({ opacityProperty: true, visibilityProperty: true }) ||
      getComputedStyle(label).pointerEvents === "none") return false;
  const r = label.getBoundingClientRect();
  // An empty Bootstrap label can have width 0 but a visible ::before widget.
  const before = getComputedStyle(label, "::before");
  return (r.height > 0 && r.width > 0) ||
    (before.content !== "none" && before.content !== "normal" && before.display !== "none" &&
     before.visibility === "visible" && Number(before.opacity) > 0 &&
     parseFloat(before.width) > 0 && parseFloat(before.height) > 0);
}

function labelProxy(el) {
  if (!el.matches('input[type="checkbox"],input[type="radio"]') ||
      (el.checkVisibility({ opacityProperty: true, visibilityProperty: true }) &&
       getComputedStyle(el).pointerEvents !== "none") || hasVisibleNativeIndicator(el)) return null;
  return [...(el.labels || [])].find(visibleLabel) || null;
}

// Styled native checkbox/radio: the transparent input remains the real target,
// while a visible sibling paints its indicator. Do not widen this to arbitrary
// transparent controls or replace native target geometry/semantics with a label.
function hasVisibleNativeIndicator(el) {
  if (!el.matches('input[type="checkbox"],input[type="radio"]') ||
      getComputedStyle(el).opacity !== "0" || getComputedStyle(el).pointerEvents === "none" ||
      !el.checkVisibility({ visibilityProperty: true }) ||
      !el.parentElement?.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
  const visibleLabels = [...(el.labels || [])].filter(label =>
    label.checkVisibility({ opacityProperty: true, visibilityProperty: true }) &&
    label.getBoundingClientRect().width > 0 && label.getBoundingClientRect().height > 0);
  if (!visibleLabels.length) return false;
  const box = el.getBoundingClientRect();
  return [...el.parentElement.children].some(indicator => {
    if (!indicator.matches("svg,img,canvas") ||
        !indicator.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const r = indicator.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left >= box.left && r.top >= box.top &&
      r.right <= box.right && r.bottom <= box.bottom;
  });
}

// 요소 자신이 보조 기술에서 숨겨졌고 1px 이하로 잘린 경우만 뺀다 (Radix Select의 native select).
// 조상의 aria-hidden(모달 배경)이나 sr-only 입력칸은 빼지 않는다.
function isAriaHiddenAndClipped(el) {
  if (el.getAttribute("aria-hidden") !== "true") return false;
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return r.width <= 1 && r.height <= 1 &&
    (cs.overflow === "hidden" || cs.clip === "rect(0px, 0px, 0px, 0px)" || cs.clipPath === "inset(50%)");
}

const isVisible = (el, box) =>
  box.width > 0 &&
  box.height > 0 &&
  !isAriaHiddenAndClipped(el) &&
  (el.checkVisibility({ opacityProperty: true, visibilityProperty: true }) ||
   hasVisibleNativeIndicator(el));

const inViewport = (b) =>
  b.x < innerWidth && b.y < innerHeight && b.x + b.width > 0 && b.y + b.height > 0;

function landmarkOf(el) {
  for (let a = up(el); a; a = up(a)) {
    const role = getRole(a);
    if (LANDMARKS.has(role) && (!NAMED_ONLY.has(role) || nameOf(a))) return role;
  }
  return null;
}

// 가장 가까운 겹침 층 조상이 있는지 (Shadow DOM·같은 출처 iframe 경계를 넘어 올라간다).
function inOverlay(el) {
  for (let a = up(el); a; a = up(a)) if (a.matches(OVERLAY)) return true;
  return false;
}

// 텍스트 입력칸: input text·email·search·password·tel·url·number, textarea, 역할 textbox·searchbox·combobox.
// el.type은 type이 없거나 모르는 값이면 "text"다.
function isTextInput(el, role) {
  return (el.tagName === "INPUT" && TEXT_INPUT_TYPES.has(el.type)) ||
    el.tagName === "TEXTAREA" || TEXT_INPUT_ROLES.has(role);
}

const CHECKABLE_ROLES = new Set(["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"]);

// action_v4: 해당하는 상태만 true/false로 넣는다. 값(value 문자열)은 넣지 않는다.
// identityOf·지문·snapshot()에는 쓰지 않는다 (입력해도 같은 요소로 남아야 한다).
function stateOf(el, role) {
  const state = {};
  if ((el.tagName === "INPUT" && TEXT_INPUT_TYPES.has(el.type)) || el.tagName === "TEXTAREA") {
    state.filled = el.value !== "";
  } else if (el.isContentEditable) {
    state.filled = (el.textContent || "").trim() !== "";
  }
  if (el.matches('input[type="checkbox"],input[type="radio"]')) state.checked = el.checked;
  else if (CHECKABLE_ROLES.has(role)) state.checked = el.getAttribute("aria-checked") === "true";
  // cmdk puts aria-selected on the cursor item, not the checked one: leave selected out for [cmdk-item].
  if (el.hasAttribute("aria-selected") && !el.hasAttribute("cmdk-item")) {
    state.selected = el.getAttribute("aria-selected") === "true";
  }
  if (el.hasAttribute("aria-expanded")) state.expanded = el.getAttribute("aria-expanded") === "true";
  const native = el.matches("button,input,select,textarea");
  if (native || el.hasAttribute("aria-disabled")) {
    state.disabled = (native && el.matches(":disabled")) || el.getAttribute("aria-disabled") === "true";
  }
  return state;
}

function labelText(el) {
  let a = el;
  for (let i = 0; i < 3 && (a = up(a)); i++) {
    const text = clean(a.innerText || "", 200);
    if (text) return text;
  }
  return null;
}

function isInlineInText(el, role) {
  if (role !== "link" || !getComputedStyle(el).display.startsWith("inline")) return false;
  return [...(el.parentNode?.childNodes ?? [])].some(
    (n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim()
  );
}

// Shadow DOM·같은 출처 iframe 안까지 내려가 (x, y)의 맨 위 요소를 찾는다.
function deepHit(x, y) {
  let root = document;
  let ox = 0;
  let oy = 0;
  for (;;) {
    let el = root.elementFromPoint(x - ox, y - oy);
    if (!el) return null;
    while (el.shadowRoot) {
      const inner = el.shadowRoot.elementFromPoint(x - ox, y - oy);
      if (!inner || inner === el) break;
      el = inner;
    }
    let doc = null;
    if (el.tagName === "IFRAME") {
      try {
        doc = el.contentDocument;
      } catch {}
    }
    if (!doc) return { el, ox, oy };
    [ox, oy] = frameOffset(el, ox, oy);
    root = doc;
  }
}

// bbox가 뷰포트에 일부만 걸치면 보이는 부분의 중심.
function visibleCenter(b) {
  const x0 = Math.max(0, b.x);
  const y0 = Math.max(0, b.y);
  const x1 = Math.min(innerWidth, b.x + b.width);
  const y1 = Math.min(innerHeight, b.y + b.height);
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}

function styleOf(el) {
  const cs = getComputedStyle(el);
  return {
    color: cs.color,
    background_color: cs.backgroundColor,
    background_image: cs.backgroundImage,
    font_size: parseFloat(cs.fontSize),
    font_weight: parseInt(cs.fontWeight, 10),
    opacity: parseFloat(cs.opacity),
  };
}

function bgChain(el) {
  const chain = [];
  for (let a = el; a; a = up(a)) {
    const s = styleOf(a);
    chain.push({
      tag: a.tagName.toLowerCase(),
      background_color: s.background_color,
      background_image: s.background_image,
      opacity: s.opacity,
    });
  }
  return chain;
}

function nearestDistance([cx, cy], b) {
  const dx = Math.max(b.x - cx, 0, cx - (b.x + b.width));
  const dy = Math.max(b.y - cy, 0, cy - (b.y + b.height));
  return Math.hypot(dx, dy);
}

// 페이지 로드 직후 1회. 상호작용 요소마다 스크롤 0 기준 중심점이 첫 화면 안인지 기록한다.
function recordFirstView() {
  firstView = new WeakMap();
  for (const entry of walk(document, "document", 0, 0)) {
    entry.proxy = labelProxy(entry.el);
    const b = bboxOf(entry);
    if (!entry.proxy && !isVisible(entry.el, b)) continue;
    const cx = b.x + b.width / 2 + scrollX;
    const cy = b.y + b.height / 2 + scrollY;
    const inView = cx >= 0 && cx < innerWidth && cy >= 0 && cy < innerHeight;
    firstView.set(entry.el, { inView, scrollPx: inView ? 0 : Math.max(0, cy - innerHeight) });
  }
}

// 뷰포트 안의 보이는 상호작용 요소 전체(가려진 요소 포함). el_id는 1부터 문서 순서.
function observe() {
  observed = [];
  for (const entry of walk(document, "document", 0, 0)) {
    entry.proxy = labelProxy(entry.el);
    const b = bboxOf(entry);
    if (b.width > 0 && b.height > 0 && (entry.proxy || isVisible(entry.el, b)) && inViewport(b)) {
      entry.identity = identityOf(entry.el);
      entry.proxyIdentity = entry.proxy && identityOf(entry.proxy);
      observed.push(entry);
    }
  }
  return observed.map((entry, i) => {
    const b = bboxOf(entry);
    const name = nameOf(entry.el);
    const role = roleOf(entry.el);
    return {
      el_id: i + 1,
      tag: entry.el.tagName.toLowerCase(),
      role,
      name,
      landmark: landmarkOf(entry.el),
      label_text: name ? null : labelText(entry.el), // 이름 없는 요소 매칭 지문 (7.2)
      bbox: b,
      occluded: isOccluded(entry, b),
      // 입력됨·선택됨·펼쳐짐·비활성 표시용 (action_v4). state_hash·매칭 지문에는 들어가지 않는다.
      state: stateOf(entry.el, role),
      // 정렬 전용 (#75). 에이전트가 60개를 고를 때만 쓰고 LLM에 보내는 항목에서는 뺀다.
      sort: { overlay: inOverlay(entry.el), text_input: isTextInput(entry.el, role) },
    };
  });
}

function hitAt(entry, b) {
  const hit = deepHit(...actionPoint(entry, b));
  if (!hit) return undefined;
  if (isSelfOrAncestor(entry.el, hit.el)) return null;
  // Only a label's own activation surface is interchangeable with its control.
  // An embedded link/button is an independent action, never a proxy click.
  if (entry.proxy && isSelfOrAncestor(entry.proxy, hit.el) &&
      !hit.el.closest('a[href],button,input,select,textarea,[role=button],[role=link]')) return null;
  return hit;
}

const isOccluded = (entry, b) => hitAt(entry, b) !== null;

// A disconnected/concave SVG shape's bounding-box centre can be empty water.
// Pick geometry BEFORE hit-testing: never hunt for a hole in a real overlay.
// On by default; `__stepmeterSvgGeometry = false` restores pure centre policy.
// Other elements (including labels) retain their existing centre policy.
function svgShapes(el) {
  if (typeof el.isPointInFill === "function") return [el];
  if (el.namespaceURI !== "http://www.w3.org/2000/svg" || el.localName !== "g") return [];
  return [...el.querySelectorAll("path,rect,circle,ellipse,polygon,polyline")].filter(shape => {
    for (let parent = shape; parent !== el; parent = parent.parentElement) {
      if (isInteractive(parent)) return false;
    }
    return true;
  });
}

function actionPoint(entry, b) {
  const center = visibleCenter(b);
  const el = entry.el;
  if (globalThis.__stepmeterSvgGeometry === false || entry.proxy) return center;
  const shapes = svgShapes(el).filter(shape => {
    const cs = getComputedStyle(shape);
    if (cs.fill === "none" || Number(cs.fillOpacity) === 0 || Number(cs.opacity) === 0 ||
        cs.visibility !== "visible" || cs.display === "none") return false;
    return true;
  });
  if (!shapes.length) return center;
  const localBox = el.getBoundingClientRect();
  const ox = b.x - localBox.x, oy = b.y - localBox.y;
  // The full paint stack includes a shape underneath an overlay. Selecting
  // geometry from that stack cannot hunt for an uncovered edge. Let Chromium
  // project CSS 3D transforms: SVG getScreenCTM() only exposes a 2D matrix.
  const root = el.getRootNode();
  const painted = ([x, y]) => root.elementsFromPoint(x - ox, y - oy)
    .some(hit => shapes.includes(hit));
  if (painted(center)) return center;
  const points = [];
  const left = Math.max(0, b.x), top = Math.max(0, b.y);
  const width = Math.min(innerWidth, b.x + b.width) - left;
  const height = Math.min(innerHeight, b.y + b.height) - top;
  for (let y = 1; y < 32; y++) for (let x = 1; x < 32; x++) {
    points.push([left + width * x / 32, top + height * y / 32]);
  }
  points.sort((a, c) => Math.hypot(a[0]-center[0], a[1]-center[1]) -
                         Math.hypot(c[0]-center[0], c[1]-center[1]));
  return points.find(painted) || center;
}

// 측정 훅: 마지막 observe()의 el_id 요소 값 (ElementSnapshot).
function snapshot(elId) {
  resolveElement(elId);
  const entry = observed[elId - 1];
  if (!entry || !entry.el.isConnected) throw new Error(`stale el_id ${elId}`);
  const { el, context } = entry;
  const bbox = bboxOf(entry);
  const role = roleOf(el);
  const name = nameOf(el);
  const hit = hitAt(entry, bbox);
  const first = firstView.get(el);
  const center = [bbox.x + bbox.width / 2, bbox.y + bbox.height / 2];

  const nearby = [];
  for (const other of observed) {
    if (other === entry || !other.el.isConnected) continue;
    if (isSelfOrAncestor(el, other.el) || isSelfOrAncestor(other.el, el)) continue;
    const ob = bboxOf(other);
    if (nearestDistance(center, ob) <= NEARBY_PX) {
      nearby.push({ role: roleOf(other.el), name: nameOf(other.el), bbox: ob });
    }
  }

  return {
    el_id: elId,
    tag: el.tagName.toLowerCase(),
    role,
    name,
    landmark: landmarkOf(el),
    label_text: name ? null : labelText(el),
    inline_in_text: isInlineInText(el, role),
    context,
    viewport: { width: innerWidth, height: innerHeight },
    scroll: { x: scrollX, y: scrollY },
    bbox,
    style: styleOf(el),
    bg_chain: bgChain(el),
    occluded: hit !== null,
    occluder: hit ? {
      tag: hit.el.tagName.toLowerCase(),
      role: roleOf(hit.el),
      name: nameOf(hit.el),
      bbox: bboxOf(hit),
    } : null,
    in_first_view: first ? first.inView : false,
    first_view_scroll_px: first ? first.scrollPx : null,
    nearby_targets: nearby,
  };
}

function resolveElement(elId) {
  if (!Number.isInteger(elId) || elId < 1) throw new Error("invalid el_id");
  const entry = observed[elId - 1];
  if (!entry || !entry.el.isConnected || identityOf(entry.el) !== entry.identity ||
      (entry.proxy && (labelProxy(entry.el) !== entry.proxy ||
       identityOf(entry.proxy) !== entry.proxyIdentity || entry.proxy.control !== entry.el))) {
    throw new Error(`stale el_id ${elId}: observe again`);
  }
  return entry.el;
}

function clickPoint(elId) {
  resolveElement(elId);
  const entry = observed[elId - 1];
  if (!entry.proxy && (globalThis.__stepmeterSvgGeometry === false ||
      !svgShapes(entry.el).length)) return null;
  const box = bboxOf(entry);
  if (!inViewport(box) || isOccluded(entry, box)) throw new Error("action target is occluded");
  const [x, y] = actionPoint(entry, box);
  return { x, y };
}

function scrollTarget(elId) {
  const el = resolveElement(elId);
  const r = el.getBoundingClientRect();
  return r.width > 1 && r.height > 1 ? el : observed[elId - 1].proxy || el;
}

// 임의 요소의 지문 필드 (observe() 항목과 같은 계산). 사람 데이터 수집(human-study/collect.js)이
// 참가자가 누른 좌표의 실제 요소(라벨이 가리키는 입력칸, 포털 목록 항목 등)에 쓴다. observe() 결과는 바꾸지 않는다.
function describe(el) {
  const name = nameOf(el);
  return {
    tag: el.tagName.toLowerCase(),
    role: roleOf(el),
    name,
    landmark: landmarkOf(el),
    label_text: name ? null : labelText(el),
  };
}

globalThis.__stepmeter = { recordFirstView, observe, snapshot, resolveElement, clickPoint, scrollTarget, describe };
