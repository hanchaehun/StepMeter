import type { Report, Step } from '@/api/mock';
import { passedRules, splitIssues } from '@/lib/report';
import { IssueRow } from './IssueRow';

/** Issues 탭: 본목록 전부 → Reference → Passed rules. */
export function IssuesTab({ report, steps, onOpen }: { report: Report; steps: Step[]; onOpen: (id: number) => void }) {
  const { main, reference } = splitIssues(report.issues);
  const passed = passedRules(report.issues, report.run.viewport);

  return (
    <div>
      <div className="mb-1 flex items-baseline gap-3">
        <h2 className="text-[18px] font-bold">Issues</h2>
        <span className="text-xs text-faint">{main.length} · 심각도 → 점수 순 (서버 정렬)</span>
      </div>
      {main.length === 0 && <p className="border-t border-hair py-4 text-muted">과업 경로에서 규칙 R01~R11에 걸린 문제가 없습니다.</p>}
      {main.map((i) => (
        <IssueRow key={i.id} issue={i} steps={steps} variant="full" onOpen={onOpen} />
      ))}

      <div className="mt-8 flex items-baseline gap-3 text-sm text-faint">
        <b className="font-semibold text-muted">Reference</b>
        <span>{reference.length} · 점수 미달이거나 과업 경로 밖이라 기본 목록에서 뺀 것</span>
      </div>
      {reference.length === 0 && <p className="border-t border-hair py-3 text-sm text-faint">없음</p>}
      {reference.map((i) => (
        <IssueRow key={i.id} issue={i} steps={steps} variant="full" onOpen={onOpen} />
      ))}

      <div className="mt-8 flex items-baseline gap-3 text-sm text-faint">
        <b className="font-semibold text-muted">Passed rules</b>
        <span>{passed.length}</span>
      </div>
      <ul className="flex flex-wrap gap-x-6 gap-y-1.5 pt-3 text-sm text-muted">
        {passed.map((r) => (
          <li key={r.id}>
            <span className="mr-2 font-bold text-ok">✓</span>
            {r.id} {r.name}
            {r.reason === '모바일만 해당' && <span className="text-faint"> (모바일만)</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
