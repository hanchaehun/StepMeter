import type { Report, Step } from '@/api/mock';
import { actionLabel, effectLabel, stepIssueMap, stepOverlays } from '@/lib/report';
import { Screenshot } from '@/components/Screenshot';

/** Steps 탭: 대표 attempt의 단계 카드 3열. 카드를 누르면 팝업(그 단계). */
export function StepsTab({ report, steps, onOpenStep }: { report: Report; steps: Step[]; onOpenStep: (idx: number) => void }) {
  const rep = report.run.representative_attempt_index;
  const issuesByStep = rep === null ? new Map<number, unknown[]>() : stepIssueMap(report.issues, rep);
  const vp = report.run.viewport === 'mobile' ? { width: 390, height: 844 } : { width: 1280, height: 800 };

  return (
    <div>
      <div className="mb-1 flex items-baseline gap-3">
        <h2 className="text-[18px] font-bold">Steps</h2>
        <span className="text-xs text-faint">Attempt {rep ?? '—'} (대표) · 카드를 누르면 큰 화면</span>
      </div>
      <div className="grid gap-6 pt-2 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((s) => {
          const n = issuesByStep.get(s.idx)?.length ?? 0;
          const title = `Step ${s.idx} · ${actionLabel(s)}`;
          return (
            <button
              key={s.idx}
              type="button"
              onClick={() => onOpenStep(s.idx)}
              aria-label={`${title}${n ? `, 문제 ${n}건` : ''}`}
              className="border-t border-hair pt-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <Screenshot src={s.screenshot_url} viewport={s.element_snapshot?.viewport ?? vp} overlays={stepOverlays(s)} className="outline outline-1 outline-hair" />
              <h3 className="mb-0.5 mt-3 text-[15px] font-semibold">
                <span aria-hidden="true">{title}</span>
                {n > 0 && <span className="ml-2 text-danger">⚠ 문제 {n}</span>}
              </h3>
              <p className="text-sm text-muted">{s.action.thought}</p>
              <p className="mt-1.5 text-xs text-faint">
                {[effectLabel(s.effect_type), s.fitts_id !== null ? `난이도 ${s.fitts_id}bit` : null, s.est_seconds !== null ? `예상 ${s.est_seconds}초` : null]
                  .filter(Boolean)
                  .map((c, i) => (
                    <span key={i}>
                      {i > 0 && <span aria-hidden="true"> · </span>}
                      <span>{c}</span>
                    </span>
                  ))}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
