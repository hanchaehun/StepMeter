import type { Report } from '@/api/mock';
import { metricTiles } from '@/lib/report';

/** 경로 의존 지표 4개. 화면 고정 항목(크기·대비 등)은 숫자가 아니라 규칙 결과라 Issues에만 있다. */
export function PathMetrics({ report }: { report: Report }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Path metrics</p>
      <div className="flex flex-wrap gap-x-9 gap-y-4">
        {metricTiles(report).map((t) => (
          <div key={t.key}>
            <div className="text-[26px] font-bold leading-none tabular-nums">
              {t.value}
              {t.unit && <small className="ml-1 text-[13px] font-normal text-muted">{t.unit}</small>}
            </div>
            <div className="mt-1 text-[13px] text-muted">{t.label}</div>
            {t.note && <div className="text-xs text-faint">{t.note}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
