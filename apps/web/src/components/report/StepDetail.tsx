import type { Report, Step } from '@/api/mock';
import { actionLabel, effectLabel, issueMeasure, issueTitle, ruleName, stepIssueMap, stepOverlays } from '@/lib/report';
import { cn } from '@/lib/cn';
import { Screenshot } from '@/components/Screenshot';
import { Severity } from '@/components/Severity';
import { AttemptsPanel } from './AttemptsPanel';

export interface DetailState {
  issueId: number | null;
  stepIdx: number | null;
}

interface Props {
  report: Report;
  steps: Step[];
  state: DetailState;
  onChange: (next: DetailState) => void;
}

/**
 * 단계 상세 화면 본문 (기획서 6.1 "단계 상세": 타임라인, 단계별 스크린샷 + 클릭 위치·이동 경로 오버레이, 단계별 예상 시간, 판단 이유).
 * 문제가 선택돼 있으면 그 문제의 What / How to fix를 같이 보여준다. 이전/다음은 issues[] 순서(참고 포함).
 */
export function StepDetail({ report, steps, state, onChange }: Props) {
  const issue = state.issueId !== null ? report.issues.find((i) => i.id === state.issueId) ?? null : null;
  const stepIdx = state.stepIdx ?? issue?.step?.idx ?? null;
  const step = stepIdx !== null ? steps.find((s) => s.idx === stepIdx) ?? null : null;
  const rep = report.run.representative_attempt_index;
  const issuesByStep = rep === null ? new Map<number, typeof report.issues>() : stepIssueMap(report.issues, rep);
  const order = report.issues.map((i) => i.id);
  const pos = issue ? order.indexOf(issue.id) : -1;

  const goStep = (idx: number) => onChange({ issueId: issuesByStep.get(idx)?.[0]?.id ?? null, stepIdx: idx });
  const stepPos = step ? steps.findIndex((s) => s.idx === step.idx) : -1;

  const title = issue ? issueTitle(issue, steps) : step ? `Step ${step.idx} · ${actionLabel(step)}` : '';
  const subtitle = issue ? `${issue.rule_id} ${ruleName(issue)}${issue.is_reference ? ' · Reference' : ''}` : step?.action.thought ?? '';
  const measure = issue ? issueMeasure(issue) : null;
  const vp = report.run.viewport === 'mobile' ? { width: 390, height: 844 } : { width: 1280, height: 800 };
  // 요소 자체가 없는 문제(R05)만 Attempts 띠. 요소는 있는데 경로 밖(step null)이면 안내 문장.
  const noElement = issue !== null && issue.element_key === null;
  const offPath = issue !== null && !noElement && issue.step === null;

  return (
    // 높이 = 창 − (앱 헤더 56 + 리포트 헤더 ~95 + 화면 전환 줄 ~74 + 위아래 여백 ~160) ≈ 100vh − 24rem. 한 화면에 들어가게 (headless Chrome 1280×800에서 확인)
    <div className="grid gap-4 lg:h-[calc(100vh-25.5rem)] lg:min-h-[420px] lg:grid-rows-[auto_auto_1fr]">
      {/* 타임라인 (이전/다음 단계는 여기 하나만) */}
      {steps.length > 0 && (
        <div role="group" aria-label="단계 타임라인" className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Attempt {rep ?? '—'} · timeline</span>
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
          <span className="ml-auto flex items-center gap-1.5">
            <NavButton label="이전 단계" disabled={stepPos <= 0} onClick={() => goStep(steps[stepPos - 1].idx)}>◀</NavButton>
            <NavButton label="다음 단계" disabled={stepPos < 0 || stepPos >= steps.length - 1} onClick={() => goStep(steps[stepPos + 1].idx)}>▶</NavButton>
          </span>
        </div>
      )}

      {/* 제목 줄 */}
      <div className="flex flex-wrap items-center gap-4 border-b border-border pb-3">
        <h3 className="flex flex-1 items-center gap-3 text-[18px] font-semibold">
          {issue && <Severity level={issue.severity} />}
          <span>{title}</span>
          <small className="font-normal text-faint">{subtitle}</small>
        </h3>
        {issue && <span className="text-sm text-faint tabular-nums">{`문제 ${pos + 1} / ${order.length}`}</span>}
      </div>

      <div data-testid="detail-body" className="grid min-h-0 gap-8 lg:grid-cols-[1fr_380px]">
        {/* 스크린샷 + 오버레이: 남은 높이 안에 비율 유지로 맞춤 */}
        <div className="min-h-0 min-w-0">
          {noElement ? (
            <div className="rounded-lg bg-surface p-5">
              <p className="mb-3 text-sm text-muted">요소가 없는 문제라 화면 대신 시도별 경로를 보여줍니다. 반복 구간은 응답에 없어 attempt 전체를 가리킵니다.</p>
              <AttemptsPanel report={report} steps={steps} onOpenStep={goStep} />
            </div>
          ) : offPath ? (
            <div className="flex min-h-[240px] items-center justify-center rounded-lg bg-surface p-5 text-center text-sm text-muted">
              경로 밖 요소라 단계 화면이 없습니다. 과업 경로 위에서 누른 요소가 아니라 스크린샷에 표시할 단계가 없습니다.
            </div>
          ) : step ? (
            <Screenshot src={step.screenshot_url} viewport={step.element_snapshot?.viewport ?? vp} overlays={stepOverlays(step)} fit="contain" className="outline outline-1 outline-border" />
          ) : null}
        </div>

        {/* 오른쪽: What / How to fix / Agent. 길면 이 열만 스크롤 */}
        <div data-testid="detail-right" className="flex min-h-0 flex-col gap-5 overflow-y-auto pr-1">
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
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Agent · 판단 이유</p>
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
    </div>
  );
}

function NavButton({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-control bg-bg text-lg text-fg disabled:opacity-35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      {children}
    </button>
  );
}
