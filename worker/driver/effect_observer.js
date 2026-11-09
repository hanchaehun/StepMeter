({key, target, duration}) => {
  let until = 0;
  const result = {dom: false, modal: false, incomplete: false};
  const noiseTokens = new Set(['carousel','swiper','slider','slick','banner','ad']);
  const roots = new Set();
  const observers = [];
  const known = new Map();
  const cleanups = [];
  const parent = el => el.parentElement || el.getRootNode()?.host || null;
  const contains = (ancestor, node) => {for (let e=node;e;e=parent(e)) if(e===ancestor)return true; return false;};
  // Keep this narrow predicate aligned with collect.js; native target stays unchanged.
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

  const intersect = (a,b) => ({left:Math.max(a.left,b.left),top:Math.max(a.top,b.top),right:Math.min(a.right,b.right),bottom:Math.min(a.bottom,b.bottom)});
  const nonempty = r => r.right>r.left&&r.bottom>r.top;
  const visible = (el, cached=null) => {
    if (!cached && !el?.isConnected) return false;
    const initial=cached || el.getBoundingClientRect();
    let rect={left:initial.left,top:initial.top,right:initial.right,bottom:initial.bottom}, win=el.ownerDocument.defaultView;
    if(!nonempty(rect))return false;
    let node=cached?null:el;
    while(win) {
      // Read geometry at the mutation, not merely when observation was installed.
      for(let e=node;e;e=parent(e)) {
        const style=win.getComputedStyle(e);
        if(style.display==='none'||style.visibility==='hidden'||(Number(style.opacity)===0&&!(e===el&&hasVisibleNativeIndicator(el))))return false;
        if(e!==node) {
          const box=e.getBoundingClientRect();
          if(['hidden','clip','scroll','auto'].includes(style.overflowX))rect={...rect,left:Math.max(rect.left,box.left),right:Math.min(rect.right,box.right)};
          if(['hidden','clip','scroll','auto'].includes(style.overflowY))rect={...rect,top:Math.max(rect.top,box.top),bottom:Math.min(rect.bottom,box.bottom)};
        }
      }
      rect=intersect(rect,{left:0,top:0,right:win.innerWidth,bottom:win.innerHeight});
      if(!nonempty(rect))return false;
      if(win===win.top)return true;
      let frame;
      try {frame=win.frameElement;}catch {result.incomplete=true;return false;}
      if(!frame){result.incomplete=true;return false;}
      const box=frame.getBoundingClientRect();
      // Axis-aligned CSS scaling is supported. Rotated/skewed frame chains are
      // deliberately unclassified rather than claiming inaccurate visibility.
      for(let e=frame;e;e=parent(e)) {
        const transform=frame.ownerDocument.defaultView.getComputedStyle(e).transform;
        if(transform!=='none') {
          const m=new DOMMatrixReadOnly(transform);
          if(!m.is2D||m.b!==0||m.c!==0||m.a<=0||m.d<=0){result.incomplete=true;return false;}
        }
      }
      const sx=box.width/frame.offsetWidth, sy=box.height/frame.offsetHeight;
      if(!Number.isFinite(sx)||!Number.isFinite(sy))return false;
      rect={left:box.left+(frame.clientLeft+rect.left)*sx,right:box.left+(frame.clientLeft+rect.right)*sx,top:box.top+(frame.clientTop+rect.top)*sy,bottom:box.top+(frame.clientTop+rect.bottom)*sy};
      node=frame;win=frame.ownerDocument.defaultView;
    }
    return false;
  };
  const noisy = el => {
    for(let e=el;e;e=parent(e)) {
      const excluded=['marquee','timer'].includes(e.getAttribute('role')) || e.getAttribute('aria-live')==='off' || [...e.classList].some(c=>noiseTokens.has(c));
      if(excluded && !(target && contains(e,target)))return true;
    }
    return false;
  };
  const meaningful = el => visible(el)&&!noisy(el);
  const active = () => performance.now()<=until;
  const isModal = el => el.matches('dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"]') && visible(el);
  const all = () => [...roots].flatMap(root=>[...root.querySelectorAll('*')]);
  let modalCount=0;
  const remember = () => {for(const el of all())known.set(el,{meaningful:meaningful(el),rect:el.getBoundingClientRect()});};
  const modals = () => {const count=all().filter(isModal).length;if(count!==modalCount&&active())result.modal=true;modalCount=count;};
  const removedMeaningful = el => {const old=known.get(el);return old?.meaningful&&visible(el,old.rect);};
  const normalized = text => (text||'').replace(/[\d\s:]/g,'');
  const controlState = () => target?.matches('input[type="checkbox"],input[type="radio"]') ? target.checked : target?.tagName === 'SELECT' ? target.selectedIndex : target && 'value' in target ? target.value : undefined;
  let controlValue = controlState();
  const controlled = el => el===target || (target?.getAttribute('aria-controls')||'').split(/\s+/).includes(el.id) && !!el.id;
  const visit = root => {
    if(roots.has(root))return;roots.add(root);
    const ob = new MutationObserver(records=>{
      if(!active())return;
      for(const m of records) {
        const el=m.target.nodeType===1?m.target:m.target.parentElement;
        if(m.type==='characterData' && meaningful(el) && normalized(m.oldValue)!==normalized(m.target.data))result.dom=true;
        if(m.type==='attributes' && controlled(el) && meaningful(el) && m.oldValue!==el.getAttribute(m.attributeName))result.dom=true;
        if(m.type==='childList') {
          // Compare replaced text too: ticking clocks often use textContent.
          const removed=[...m.removedNodes], added=[...m.addedNodes];
          const textOnly=[...removed,...added].every(n=>n.nodeType===3);
          if(textOnly) {
            if(meaningful(el)&&normalized(removed.map(n=>n.textContent).join(''))!==normalized(added.map(n=>n.textContent).join('')))result.dom=true;
          } else {
            for(const n of removed)if(n.nodeType===1 && (removedMeaningful(n) || [...n.querySelectorAll('*')].some(removedMeaningful)))result.dom=true;
            for(const n of added)if(n.nodeType===1 && (meaningful(n)||[...n.querySelectorAll('*')].some(meaningful)))result.dom=true;
          }
        }
      }
      discover();modals();remember();
    });
    ob.observe(root,{subtree:true,childList:true,characterData:true,characterDataOldValue:true,attributes:true,attributeOldValue:true,attributeFilter:['aria-expanded','aria-selected','aria-checked','disabled','class','open','role','aria-modal','style','hidden']});observers.push(ob);
    const focus=e=>{if(active()&&e.target.matches?.('input,textarea,select,[contenteditable="true"]')&&meaningful(e.target))result.dom=true;};
    root.addEventListener('focusin',focus,true);cleanups.push(()=>root.removeEventListener('focusin',focus,true));
    const input=e=>{if(e.target===target&&active()&&meaningful(target)&&controlState()!==controlValue){result.dom=true;controlValue=controlState();}};
    for(const type of ['input','change']){root.addEventListener(type,input,true);cleanups.push(()=>root.removeEventListener(type,input,true));}
  };
  const discover = () => {visit(document);let size;do{size=roots.size;for(const el of all())if(el.shadowRoot)visit(el.shadowRoot);}while(size!==roots.size);};
  discover();remember();modalCount=all().filter(isModal).length;
  const scroll=e=>{const el=e.target===document?document.documentElement:e.target;if(active()&&(e.target===document?visible(document.documentElement):meaningful(el)))result.dom=true;};
  document.addEventListener('scroll',scroll,true);cleanups.push(()=>document.removeEventListener('scroll',scroll,true));
  // Capture geometry before removals, including layout changes without mutations.
  const timer=setInterval(()=>{if(active()){discover();modals();remember();}},25);
  globalThis[key]={start:()=>{result.dom=false;result.modal=false;known.clear();remember();modalCount=all().filter(isModal).length;until=performance.now()+duration;},stop:()=>{clearInterval(timer);observers.forEach(o=>o.disconnect());cleanups.forEach(f=>f());delete globalThis[key];return result;}};
}
