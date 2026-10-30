import type { Report, Step } from '@/api/mock';
import { actionLabel, effectLabel, issueMeasure, issueTitle, ruleName, stepIssueMap, stepOverlays } from '@/lib/report';
import { cn } from '@/lib/cn';
import { forwardRef, useRef } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Screenshot } from '@/components/Screenshot';
import { Severity } from '@/components/Severity';
import { AttemptsPanel } from './AttemptsPanel';

export interface DialogState {
  issueId: number | null;
  stepIdx: number | null;
}

interface Props {
  open: boolean;
  state: DialogState;
  report: Report;
  steps: Step[];
  onChange: (next: DialogState) => void;
  onClose: () => void;
}

/**
 * 문제 상세 팝업 (명세 "팝업 동작", 목업 프레임 5). 스크롤 없이 한 화면: 왼쪽 단계 띠 + 스크린샷, 오른쪽 What / How to fix / Agent.
 * 이전/다음은 issues[] 순서(참고 포함). 단계 띠를 누르면 그 단계로, 그 단계에 문제가 있으면 What도 바뀐다.
 */
export function IssueDialog({ open, state, report, steps, onChange, onClose }: Props) {
  const issue = state.issueId !== null ? report.issues.find((i) => i.id === state.issueId) ?? null : null;
  const stepIdx = state.stepIdx ?? issue?.step?.idx ?? null;
  const step = stepIdx !== null ? steps.find((s) => s.idx === stepIdx) ?? null : null;
  const rep = report.run.representative_attempt_index;
  const issuesByStep = rep === null ? new Map<number, typeof report.issues>() : stepIssueMap(report.issues, rep);
  const order = report.issues.map((i) => i.id);
  const pos = issue ? order.indexOf(issue.id) : -1;

  const goIssue = (id: number) => {
    const target = report.issues.find((i) => i.id === id)!;
    onChange({ issueId: id, stepIdx: target.step?.idx ?? null });
  };
  const goStep = (idx: number) => onChange({ issueId: issuesByStep.get(idx)?.[0]?.id ?? null, stepIdx: idx });

  const title = issue ? issueTitle(issue, steps) : step ? `Step ${step.idx}` : '';
  const subtitle = issue ? `${issue.rule_id} ${ruleName(issue)}${issue.is_reference ? ' · Reference' : ''}` : step?.action.thought ?? '';
  const measure = issue ? issueMeasure(issue) : null;
  const vp = report.run.viewport === 'mobile' ? { width: 390, height: 844 } : { width: 1280, height: 800 };
  // 요소 자체가 없는 문제(R05)만 Attempts 띠. 요소는 있는데 경로 밖(step null)이면 자리표시 문장.
  const noElement = issue !== null && issue.element_key === null;
  const offPath = issue !== null && !noElement && issue.step === null;
  const closeRef = useRef<HTMLButtonElement>(null);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent onOpenAutoFocus={(e) => { e.preventDefault(); closeRef.current?.focus(); }}>
        <div className="flex items-center gap-4 border-b border-border px-6 py-3">
          <DialogTitle className="flex flex-1 items-center gap-3 text-[17px] font-semibold">
            {issue && <Severity level={issue.severity} />}
            <span>{title}</span>
            <small className="font-normal text-faint">{subtitle}</small>
          </DialogTitle>
          <DialogDescription className="sr-only">문제 상세와 단계 화면</DialogDescription>
          <div className="flex items-center gap-1.5 text-sm text-faint">
            <IconButton label="이전 문제" disabled={pos <= 0} onClick={() => goIssue(order[pos - 1])}>◀</IconButton>
            <span className="min-w-[60px] text-center tabular-nums">{issue ? `${pos + 1} / ${order.length}` : 'Step view'}</span>
            <IconButton label="다음 문제" disabled={pos < 0 || pos >= order.length - 1} onClick={() => goIssue(order[pos + 1])}>▶</IconButton>
          </div>
          <IconButton ref={closeRef} label="닫기" onClick={onClose}>✕</IconButton>
        </div>

        <div data-testid="dlg-body" className="grid min-h-0 grid-cols-1 overflow-y-auto lg:grid-cols-[1fr_400px] lg:overflow-hidden">
          <div className="grid min-h-0 grid-rows-[auto_1fr] gap-3 px-5 py-4 lg:pr-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="mr-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Attempt {rep ?? '—'} · steps</span>
              {steps.map((s) => {
                const n = issuesByStep.get(s.idx)?.length ?? 0;
                const current = s.idx === stepIdx;
                return (
                  <button
                    key={s.idx}
                    type="button"
                    aria-current={current ? 'step' : undefined}
                    onClick={() => goStep(s.idx)}
                    className={cn(
                      'inline-flex min-h-[44px] items-center gap-2 rounded-md border border-control bg-bg px-3.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
                      current && 'border-primary bg-primary text-primary-fg',
                    )}
                  >
                    {s.idx} · {actionLabel(s).replace(/ (클릭|입력|선택)$/, '')}
                    {n > 0 && <span className={cn('font-bold text-danger', current && 'text-[#fecaca]')}>⚠</span>}
                  </button>
                );
              })}
            </div>
            <div className="min-h-0 overflow-hidden rounded-lg bg-[#f3f4f6]">
              {noElement ? (
                <div className="p-5">
                  <p className="mb-3 text-sm text-muted">요소가 없는 문제라 화면 대신 시도별 경로를 보여줍니다. 반복 구간은 응답에 없어 attempt 전체를 가리킵니다.</p>
                  <AttemptsPanel report={report} steps={steps} onOpenStep={goStep} />
                </div>
              ) : offPath ? (
                <div className="flex h-full min-h-[240px] items-center justify-center p-5 text-center text-sm text-muted">
                  경로 밖 요소라 단계 화면이 없습니다. 과업 경로 위에서 누른 요소가 아니라 스크린샷에 표시할 단계가 없습니다.
                </div>
              ) : step ? (
                <Screenshot src={step.screenshot_url} viewport={step.element_snapshot?.viewport ?? vp} overlays={stepOverlays(step)} fit="contain" />
              ) : null}
            </div>
          </div>

          <div data-testid="dlg-right" className="flex min-h-0 flex-col gap-6 overflow-y-auto border-t border-border px-8 py-6 lg:border-l lg:border-t-0">
            <section>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">What</p>
              {issue ? (
                <>
                  {measure && <p className="text-[17px] font-semibold tabular-nums">{measure}</p>}
                  <p className="mt-1">{issue.explanation}</p>
                  {issue.score_reason && <p className="mt-1 text-[13px] text-faint">{`점수 이유 · ${issue.score_reason}`}</p>}
                </>
              ) : (
                <p className="text-[13px] text-faint">이 단계에서 찾은 문제가 없습니다.</p>
              )}
            </section>
            {issue && (
              <section>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">How to fix</p>
                {issue.suggestion ? <p>{issue.suggestion}</p> : <p className="text-[13px] text-faint">참고 항목이라 제안은 생략합니다.</p>}
              </section>
            )}
            {step && (
              <section>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Agent</p>
                <p className="font-semibold">{actionLabel(step)}</p>
                <p className="break-all text-[13px] text-faint">{step.url}</p>
                <p className="mt-1">{step.action.thought}</p>
                <p className="text-[13px] text-faint">{`기대 · ${step.action.expectation}`}</p>
                {step.action.confusion && <p className="text-[13px] text-faint">{`헷갈림 · ${step.action.confusion}`}</p>}
                <p className="mt-2 text-[13px] text-faint">
                  {[effectLabel(step.effect_type), step.fitts_id !== null ? `난이도 ${step.fitts_id}bit` : null, step.est_seconds !== null ? `예상 ${step.est_seconds}초` : null]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </section>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const IconButton = forwardRef<HTMLButtonElement, { label: string; disabled?: boolean; onClick: () => void; children: string }>(function IconButton({ label, disabled, onClick, children }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-control bg-bg text-lg text-fg disabled:opacity-35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      {children}
    </button>
  );
});
