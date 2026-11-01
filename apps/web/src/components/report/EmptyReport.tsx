import type { Report, Step } from '@/api/mock';
import { splitIssues, verdictText } from '@/lib/report';
import { IssuesPanel } from './IssuesPanel';
import { AttemptsPanel } from './AttemptsPanel';

interface Props {
  report: Report;
  steps: Step[];
  onOpen: (issueId: number) => void;
  onShowAll: () => void;
}

/**
 * 전부 실패 상태 (representative_attempt_index === null, 목업 프레임 6).
 * 숫자 자리를 비우지 않고 이유를 쓰고, 막다른 길로 끝내지 않는다 (기획서 11장 "실패 원인 분류 후 리포트에 표시").
 */
export function EmptyReport({ report, steps, onOpen, onShowAll }: Props) {
  const v = verdictText(report);
  const { main, reference } = splitIssues(report.issues);

  return (
    <div className="flex flex-col gap-5">
      <div className="grid items-end gap-10 md:grid-cols-[1fr_auto]">
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Verdict</p>
          <p className="text-4xl font-bold leading-none tracking-tight">{v.main}</p>
          <p className="mt-2 text-base text-muted">{`지표 없음 · 문제 ${main.length}건 · 참고 ${reference.length}건`}</p>
        </div>
        <div className="max-w-[360px]">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Path metrics</p>
          <p className="text-sm text-muted">성공한 실행이 없어 경로 지표를 계산하지 않았습니다. 흐름 자체를 점검하세요 (기획서 7장: 3회 중 2회 미만).</p>
        </div>
      </div>
      <div className="grid gap-10 border-t border-border pt-5 lg:grid-cols-[1.15fr_1fr]">
        <IssuesPanel report={report} steps={steps} onOpen={onOpen} onShowAll={onShowAll} />
        <div>
          <AttemptsPanel report={report} steps={steps} onOpenStep={() => {}} />
          <div className="mt-4 flex flex-wrap gap-3">
            <a href="#new-run" className="inline-flex min-h-[44px] items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg">과업 문장 고쳐서 다시 측정</a>
            <a href="#new-run-condition" className="inline-flex min-h-[44px] items-center rounded-lg border border-control bg-bg px-4 text-sm font-semibold text-fg">성공 조건 추가</a>
          </div>
        </div>
      </div>
    </div>
  );
}
