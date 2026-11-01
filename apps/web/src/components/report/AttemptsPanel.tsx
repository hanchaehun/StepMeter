import type { Attempt, Report, Step } from '@/api/mock';
import { elementLabel, endReasonText, stepIssueMap } from '@/lib/report';
import { cn } from '@/lib/cn';
import { Button } from '@/components/ui/button';

interface Props {
  report: Report;
  steps: Step[];
  onOpenStep: (idx: number) => void;
  onShowSteps?: () => void;
}

/** 시도별 경로. 대표 attempt의 점만 버튼(스냅샷이 대표 경로만 온다). 문제 있는 단계는 빨간 테두리 + 범례. */
export function AttemptsPanel({ report, steps, onOpenStep, onShowSteps }: Props) {
  const rep = report.run.representative_attempt_index;
  const issuesByStep = rep === null ? new Map() : stepIssueMap(report.issues, rep);
  const ordered = [...report.attempts].sort((a, b) => (a.index === rep ? -1 : b.index === rep ? 1 : a.index - b.index));
  const hardest = report.top_fitts_steps[0];
  const slowest = report.slowest_steps[0];
  const stepName = (idx: number) => {
    const s = steps.find((x) => x.idx === idx);
    if (!s) return `Step ${idx}`;
    return s.element_snapshot ? elementLabel(keyOf(s)) : s.action.action === 'done' ? '완료' : s.action.action;
  };

  return (
    <section aria-label="Attempts">
      <div className="mb-1 flex items-center gap-3">
        <h2 className="text-[17px] font-bold">Attempts</h2>
        <span className="flex-1 text-xs text-faint">점을 누르면 그 단계의 화면</span>
        {onShowSteps && <Button variant="link" onClick={onShowSteps}>단계 보기 →</Button>}
      </div>
      {ordered.map((a) => (
        <AttemptRow key={a.index} attempt={a} representative={a.index === rep} steps={steps} issuesByStep={issuesByStep} onOpenStep={onOpenStep} />
      ))}
      <p className="mt-3 text-xs text-faint">
        <i className="mr-1 inline-block h-2 w-2 rounded-full border-2 border-mark bg-[#fee2e2] align-[-1px]" /> 문제 있는 단계
        <span className="ml-3 mr-1 inline-block h-2 w-2 rotate-45 bg-danger align-[-1px]" /> 재생 끊김 · 종료
      </p>
      {(hardest || slowest) && (
        <p className="mt-3 text-[13px] leading-7 text-muted">
          {hardest && (
            <span>가장 어려운 단계 <b className="font-semibold text-fg">Step {hardest.idx} {stepName(hardest.idx)}</b> {hardest.value}bit</span>
          )}
          {hardest && slowest && ' · '}
          {slowest && (
            <span>가장 오래 걸린 단계 <b className="font-semibold text-fg">Step {slowest.idx} {stepName(slowest.idx)}</b> {slowest.value}초</span>
          )}
        </p>
      )}
    </section>
  );
}

function keyOf(s: Step): string {
  const e = s.element_snapshot!;
  return `${e.tag}|${e.role ?? ''}|${e.name ?? ''}|${e.label_text ?? ''}|${e.landmark ?? ''}`;
}

function AttemptRow({
  attempt: a, representative, steps, issuesByStep, onOpenStep,
}: { attempt: Attempt; representative: boolean; steps: Step[]; issuesByStep: Map<number, unknown[]>; onOpenStep: (idx: number) => void }) {
  const cut = a.success === false || (a.kind === 'replay' && a.replay_status === 'partial');
  const count = representative ? steps.length : Math.min(a.steps_count, 6);
  const dots = Array.from({ length: count }, (_, i) => i);

  return (
    <div className="flex items-center gap-3 border-t border-hair py-2 first:border-t-0">
      <span className="w-24 text-sm text-muted">
        <b className="font-semibold text-fg">Attempt {a.index}</b>{representative ? ' 대표' : a.kind === 'replay' ? ' 재생' : ''}
      </span>
      <div className="flex items-center">
        {dots.map((i) => {
          const isLast = i === dots.length - 1;
          const issues = representative ? (issuesByStep.get(i)?.length ?? 0) : 0;
          const label = representative ? `Step ${i}: ${stepSummary(steps[i])}, 문제 ${issues}건` : undefined;
          const dot = (
            <span
              className={cn(
                'block h-[11px] w-[11px] rounded-full border-2 border-control bg-bg',
                issues > 0 && 'border-mark bg-[#fee2e2]',
                cut && isLast && !representative && 'rotate-45 rounded-none border-danger bg-danger',
              )}
            />
          );
          return (
            <span key={i} className="flex items-center">
              {representative ? (
                <button type="button" aria-label={label} onClick={() => onOpenStep(i)} className="flex h-9 w-9 items-center justify-center rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                  {dot}
                </button>
              ) : (
                <span className="flex h-9 w-9 items-center justify-center">{dot}</span>
              )}
              {!isLast && <span className="h-px w-3.5 bg-control" />}
            </span>
          );
        })}
      </div>
      <span className="flex-1 text-xs text-faint">
        {a.steps_count} steps · {endReasonText(a)}
      </span>
    </div>
  );
}

function stepSummary(s: Step | undefined): string {
  if (!s) return '';
  if (s.element_snapshot) return elementLabel(keyOf(s));
  return s.action.action === 'done' ? '완료' : s.action.action;
}
