import type { Issue, Step } from '@/api/mock';
import { issueMeasure, issueTitle, ruleName } from '@/lib/report';
import { cn } from '@/lib/cn';
import { Severity } from '@/components/Severity';
import { Screenshot } from '@/components/Screenshot';

interface Props {
  issue: Issue;
  steps: Step[];
  variant?: 'compact' | 'full';
  onOpen: (issueId: number) => void;
}

/**
 * 문제 한 줄: [썸네일] 심각도 · 제목(+규칙·점수 이유) · 단계. 행 전체가 버튼(min-height 44).
 * 썸네일은 Lighthouse 요소 셀 방식: 단계 스크린샷을 요소 bbox 중심으로 잘라낸다.
 */
export function IssueRow({ issue, steps, variant = 'compact', onOpen }: Props) {
  const full = variant === 'full';
  const step = issue.step ? steps.find((s) => s.idx === issue.step!.idx) : undefined;
  const title = issueTitle(issue, steps);
  const measure = issueMeasure(issue);
  const sub = [`${issue.rule_id} ${ruleName(issue)}`, measure, issue.score_reason, issue.is_reference ? '참고' : null]
    .filter(Boolean)
    .join(' · ');

  return (
    <button
      type="button"
      onClick={() => onOpen(issue.id)}
      className={cn(
        // 좁은 화면: 썸네일 | (심각도 / 제목 / 단계) 2열. sm 이상: 한 줄 4열. 390px에서 넘치지 않게 1fr은 minmax(0,1fr)
        'grid w-full items-center gap-x-3 gap-y-1 border-t border-hair py-3 text-left hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        'grid-cols-[72px_minmax(0,1fr)]',
        full ? 'sm:grid-cols-[128px_90px_minmax(0,1fr)_72px] sm:gap-6 sm:py-5' : 'sm:grid-cols-[72px_80px_minmax(0,1fr)_56px] sm:gap-4',
        issue.is_reference && 'text-muted',
      )}
    >
      <div className="row-span-3 sm:row-span-1">
        <Thumb step={step} issue={issue} full={full} />
      </div>
      <Severity level={issue.severity} />
      <div className={cn('min-w-0 font-semibold leading-tight', full && 'text-base', issue.is_reference && 'font-medium')}>
        {title}
        <small className="mt-0.5 block text-xs font-normal text-faint">
          {sub}
          {full && issue.explanation ? ` · ${issue.explanation}` : ''}
        </small>
      </div>
      <span className="text-xs text-faint sm:text-right">{issue.step ? `Step ${issue.step.idx}` : '—'}</span>
    </button>
  );
}

function Thumb({ step, issue, full }: { step?: Step; issue: Issue; full: boolean }) {
  const size = full ? 'h-[84px] w-[128px]' : 'h-12 w-[72px]';
  const snap = step?.element_snapshot;
  if (!step || !snap) {
    // 단계가 없는 문제: 요소도 없으면(R05) "구간", 요소는 있는데 경로 밖이면 "경로 밖"
    const text = issue.step ? '화면' : issue.element_key === null ? '구간' : '경로 밖';
    return (
      <div className={cn(size, 'flex items-center justify-center rounded bg-surface text-[11px] text-faint outline outline-1 outline-hair')}>
        {text}
      </div>
    );
  }
  const { viewport, bbox } = snap;
  // 요소 중심이 썸네일 가운데 오도록 스크린샷을 2.5배(원본 대비 약 1:2 축소)로 두고 옮긴다
  const zoom = full ? 0.5 : 0.35;
  const w = viewport.width * zoom;
  const cx = (bbox.x + bbox.width / 2) * zoom;
  const cy = (bbox.y + bbox.height / 2) * zoom;
  const boxW = full ? 128 : 72;
  const boxH = full ? 84 : 48;
  return (
    <div className={cn(size, 'relative overflow-hidden rounded bg-bg outline outline-1 outline-hair', issue.is_reference && 'opacity-70')}>
      <div className="absolute" style={{ width: w, left: boxW / 2 - cx, top: boxH / 2 - cy }}>
        <Screenshot src={step.screenshot_url} viewport={viewport} overlays={[{ kind: 'bbox', bbox }]} className="rounded-none" />
      </div>
    </div>
  );
}
