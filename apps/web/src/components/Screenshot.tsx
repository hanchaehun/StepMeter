import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/cn';

export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Overlay {
  kind: 'bbox' | 'occluder' | 'nearby' | 'click';
  bbox: BBox;
  label?: string;
}

interface Props {
  src: string | null;
  viewport: { width: number; height: number };
  overlays: Overlay[];
  /** width: 너비에 맞춤(높이는 비율로). contain: 부모 상자 안에 비율 유지로 맞춤(부모를 ResizeObserver로 잰다). */
  fit?: 'width' | 'contain';
  className?: string;
  /** 이미지가 깨졌을 때 "다시 불러오기"에서 부른다(서명 URL 재발급용). 없어도 같은 주소로 다시 시도한다 */
  onRetry?: () => void;
  /** false면 깨져도 버튼을 두지 않는다. 문제 행 썸네일처럼 버튼 안에 들어갈 때 (버튼 안 버튼 방지) */
  retryable?: boolean;
}

const pct = (v: number, base: number) => `${(v / base) * 100}%`;

/**
 * 누른 요소 이름표를 어디에 붙일지. 기본은 박스 위·왼쪽 맞춤.
 * - 박스가 스크린샷 맨 위(높이의 8% 안)에 있으면 위에 붙이면 프레임 밖으로 잘리므로 박스 아래에 붙인다.
 * - 박스 중심이 오른쪽 절반에 있으면 오른쪽 맞춤으로 붙여 오른쪽 끝에서 잘리지 않게 한다.
 */
export function labelPlacement(bbox: BBox, viewport: { width: number; height: number }): { below: boolean; alignRight: boolean } {
  return {
    below: bbox.y < viewport.height * 0.08,
    alignRight: bbox.x + bbox.width / 2 > viewport.width / 2,
  };
}

// 이름표 글자는 프레임 너비에 맞춰 줄인다(작은 모바일 스크린샷을 가리지 않게). cqw는 shot-frame 기준
const labelText = 'text-[length:clamp(9px,3cqw,12px)]';

/** 컨테이너(cw×ch) 안에 뷰포트 비율(vw:vh)을 유지하며 들어가는 가장 큰 크기. */
export function fitContain(cw: number, ch: number, vw: number, vh: number): { width: number; height: number } {
  const byHeight = ch * (vw / vh);
  if (byHeight <= cw) return { width: byHeight, height: ch };
  return { width: cw, height: cw * (vh / vw) };
}

/**
 * 단계 스크린샷 + 오버레이. 오버레이는 bbox를 뷰포트 대비 백분율로 배치해 어떤 크기로 그려도 맞는다
 * (명세 "오버레이" 표). src가 없거나 깨지면 같은 비율의 회색 자리표시.
 */
export function Screenshot({ src, viewport, overlays, fit = 'width', className, onRetry, retryable = true }: Props) {
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0); // 같은 주소로 다시 시도할 때 img를 새로 만든다
  useEffect(() => {
    // 다른 단계로 넘어가면 다시 시도한다
    setBroken(false);
    setLoaded(false);
  }, [src]);
  const showImage = src !== null && !broken;
  const retry = () => {
    setBroken(false);
    setLoaded(false);
    setAttempt((a) => a + 1);
    onRetry?.();
  };
  const ratio = viewport.height / viewport.width;

  const containerRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ width: number; height: number } | null>(null);
  useEffect(() => {
    if (fit !== 'contain' || !containerRef.current || typeof ResizeObserver === 'undefined') return;
    const el = containerRef.current;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      if (r.width > 0 && r.height > 0) setBox(fitContain(r.width, r.height, viewport.width, viewport.height));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit, viewport.width, viewport.height]);

  const inner = (
    <>
      {showImage ? (
        <>
          {/* 화면용 자리표시라 보조 기술에서는 숨긴다(문제 행 버튼의 접근 이름에 섞이지 않게) */}
          {!loaded && <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-sm text-muted">불러오는 중</div>}
          <img
            key={attempt}
            src={src}
            alt=""
            className="absolute inset-0 h-full w-full object-contain"
            onLoad={() => setLoaded(true)}
            onError={() => setBroken(true)}
          />
        </>
      ) : src !== null && retryable ? (
        // 서명 URL은 900초 뒤 만료된다(이슈 #51). 명세 "극단값": 회색 상자 + "다시 불러오기"
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 text-sm text-muted">
          <span>스크린샷을 불러오지 못했습니다</span>
          <button
            type="button"
            onClick={retry}
            className="inline-flex min-h-[44px] items-center rounded-md border border-control bg-bg px-4 font-semibold text-fg hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            다시 불러오기
          </button>
        </div>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted">스크린샷 없음</div>
      )}
      <div data-testid="overlays" aria-hidden="true" className="absolute inset-0">
        {overlays.map((o, i) => (
          <OverlayBox key={i} overlay={o} viewport={viewport} />
        ))}
      </div>
    </>
  );

  if (fit === 'contain') {
    // 컨테이너를 재서 px로 준다. CSS만으로는 aspect-ratio + max-width + max-height를 동시에 만족시킬 수 없어 0×0이 된다.
    const style = box ? { width: `${box.width}px`, height: `${box.height}px` } : { width: '100%', paddingBottom: `${ratio * 100}%` };
    return (
      <div ref={containerRef} className="flex h-full w-full items-center justify-center">
        <div data-testid="shot-frame" className={cn('relative overflow-hidden rounded bg-[#f3f4f6] [container-type:inline-size]', className)} style={style}>
          {inner}
        </div>
      </div>
    );
  }

  return (
    <div data-testid="shot-frame" className={cn('relative overflow-hidden rounded bg-[#f3f4f6] [container-type:inline-size]', className)} style={{ paddingBottom: `${ratio * 100}%` }}>
      {inner}
    </div>
  );
}

function OverlayBox({ overlay: o, viewport }: { overlay: Overlay; viewport: { width: number; height: number } }) {
  const { x, y, width, height } = o.bbox;
  if (o.kind === 'click') {
    return (
      <div
        data-testid="ov-click"
        className="absolute h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-mark"
        style={{ left: pct(x + width / 2, viewport.width), top: pct(y + height / 2, viewport.height) }}
      />
    );
  }
  const style = {
    left: pct(x, viewport.width),
    top: pct(y, viewport.height),
    width: pct(width, viewport.width),
    height: pct(height, viewport.height),
  };
  if (o.kind === 'bbox') {
    const place = labelPlacement(o.bbox, viewport);
    return (
      <div data-testid="ov-bbox" className="absolute border-[3px] border-mark shadow-[0_0_0_3px_#fff]" style={style}>
        {o.label && (
          <span
            data-testid="ov-bbox-label"
            data-place={`${place.below ? 'below' : 'above'}-${place.alignRight ? 'right' : 'left'}`}
            className={cn(
              'absolute whitespace-nowrap bg-mark px-1.5 py-0.5 font-semibold text-white',
              labelText,
              place.below ? 'top-full rounded-b' : 'bottom-full rounded-t',
              place.alignRight ? '-right-[3px]' : '-left-[3px]',
            )}
          >
            {o.label}
          </span>
        )}
      </div>
    );
  }
  if (o.kind === 'occluder') {
    return (
      <div
        data-testid="ov-occluder"
        className="absolute border-2 border-dashed border-mark bg-[repeating-linear-gradient(45deg,rgba(220,38,38,.35)_0_8px,rgba(220,38,38,.05)_8px_16px)]"
        style={style}
      >
        {o.label && <span className="absolute right-2 top-2 rounded bg-mark px-2 py-0.5 text-xs font-semibold text-white">{o.label}</span>}
      </div>
    );
  }
  return (
    <div data-testid="ov-nearby" className="absolute border-2 border-dashed border-control" style={style}>
      {/* 근처 박스가 나란히 있으면 이름표가 겹친다("근처 근처: 증권"). 박스 너비 안에서 줄임표로 자른다 */}
      {o.label && (
        <span data-testid="ov-nearby-label" className={cn('absolute left-0 top-full max-w-full truncate bg-white px-1 text-muted', labelText)}>
          {o.label}
        </span>
      )}
    </div>
  );
}
