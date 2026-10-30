import type { Report, Step } from '@/api/mock';
import { splitIssues } from '@/lib/report';
import { Button } from '@/components/ui/button';
import { IssueRow } from './IssueRow';

interface Props {
  report: Report;
  steps: Step[];
  onOpen: (issueId: number) => void;
  onShowAll: () => void;
  limit?: number;
  referenceLimit?: number;
}

/** Overview의 Issues 컴포넌트. 본목록 limit개 + 참고 referenceLimit개, 넘치면 Issues 탭으로. */
export function IssuesPanel({ report, steps, onOpen, onShowAll, limit = 6, referenceLimit = 3 }: Props) {
  const { main, reference } = splitIssues(report.issues);
  const shownMain = main.slice(0, limit);
  const shownRef = reference.slice(0, referenceLimit);
  const overflow = main.length > limit || reference.length > referenceLimit;

  return (
    <section aria-label="Issues">
      <div className="mb-1 flex items-center gap-3">
        <h2 className="text-[17px] font-bold">Issues</h2>
        <span className="flex-1 text-xs text-faint">심각도 → 점수 순 · 행을 누르면 화면</span>
        <Button variant="link" onClick={onShowAll}>전체 보기 →</Button>
      </div>
      {main.length === 0 && (
        <p className="border-t border-hair py-4 text-muted">
          과업 경로에서 규칙 R01~R11에 걸린 문제가 없습니다.{reference.length > 0 && ` 참고 ${reference.length}건은 과업 경로 밖 요소입니다.`}
        </p>
      )}
      {shownMain.map((i) => (
        <IssueRow key={i.id} issue={i} steps={steps} onOpen={onOpen} />
      ))}
      {shownRef.map((i) => (
        <IssueRow key={i.id} issue={i} steps={steps} onOpen={onOpen} />
      ))}
      {overflow && (
        <div className="border-t border-hair pt-1">
          <Button variant="link" onClick={onShowAll}>
            {main.length > limit ? `문제 ${main.length}건 전체 보기 →` : `참고 ${reference.length}건 →`}
          </Button>
        </div>
      )}
    </section>
  );
}
