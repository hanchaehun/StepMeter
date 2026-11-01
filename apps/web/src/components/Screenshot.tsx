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
}

const pct = (v: number, base: number) => `${(v / base) * 100}%`;

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
export function Screenshot({ src, viewport, overlays, fit = 'width', className }: Props) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [src]); // 다른 단계로 넘어가면 다시 시도한다
  const showImage = src !== null && !broken;
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
        <img src={src} alt="" className="absolute inset-0 h-full w-full object-contain" onError={() => setBroken(true)} />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-faint">스크린샷 없음</div>
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
        <div data-testid="shot-frame" className={cn('relative overflow-hidden rounded bg-[#f3f4f6]', className)} style={style}>
          {inner}
        </div>
      </div>
    );
  }

  return (
    <div data-testid="shot-frame" className={cn('relative overflow-hidden rounded bg-[#f3f4f6]', className)} style={{ paddingBottom: `${ratio * 100}%` }}>
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
    return (
      <div data-testid="ov-bbox" className="absolute border-[3px] border-mark shadow-[0_0_0_3px_#fff]" style={style}>
        {o.label && (
          <span className="absolute -left-[3px] bottom-full whitespace-nowrap rounded-t bg-mark px-2 py-0.5 text-xs font-semibold text-white">{o.label}</span>
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
      {o.label && <span className="absolute left-0 top-full whitespace-nowrap bg-white px-1 text-[11px] text-muted">{o.label}</span>}
    </div>
  );
}
