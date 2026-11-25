import { useState } from 'react';
import type { Report, Step } from '@/api/mock';
import { groupIssues, splitIssues, type IssueGroup } from '@/lib/report';
import { Button } from '@/components/ui/button';
import { IssueRow } from './IssueRow';

interface Props {
  report: Report;
  steps: Step[];
  onOpen: (issueId: number) => void;
  /** 넘치는 항목을 보여줄 곳이 있으면 전달. 없으면(기획서 6.1 요약 화면) 전부 보여준다. */
  onShowAll?: () => void;
  /** 기본 목록에 보일 묶음 수 */
  limit?: number;
  /** 참고 구역을 펼쳤을 때 보일 묶음 수 */
  referenceLimit?: number;
}

const toggleCls =
  'inline-flex min-h-[44px] items-center gap-1.5 text-sm font-semibold text-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary';

/**
 * 리포트 요약의 문제 목록(기획서 6.1 "문제 목록(심각도·점수순)").
 * #75 UX 감사 F-02: 같은 (규칙, 요소)는 한 줄로 묶어 "×n"을 보이고 펼치면 원래 행이 나온다.
 * 참고(is_reference)는 기본 목록과 나눠 접어 둔다. 표시만 바꾸며 API·채점은 그대로다.
 */
export function IssuesPanel({ report, steps, onOpen, onShowAll, limit = Infinity, referenceLimit = Infinity }: Props) {
  const { main, reference } = splitIssues(report.issues);
  const mainGroups = groupIssues(main);
  const refGroups = groupIssues(reference);
  const [refOpen, setRefOpen] = useState(false);
  const shownMain = mainGroups.slice(0, limit);
  const shownRef = refGroups.slice(0, referenceLimit);
  const overflow = onShowAll !== undefined && (mainGroups.length > limit || (refOpen && refGroups.length > referenceLimit));

  return (
    <section aria-label="Issues">
      <div className="mb-1 flex items-center gap-3">
        <h2 className="text-[17px] font-bold">Issues</h2>
        <span className="flex-1 text-xs text-faint">심각도 → 점수 순 · 같은 요소는 한 줄 · 행을 누르면 단계 상세</span>
      </div>
      {main.length === 0 && (
        <p className="border-t border-hair py-4 text-muted">
          과업 경로에서 규칙 R01~R11에 걸린 문제가 없습니다.{reference.length > 0 && ` 참고 ${reference.length}건은 과업 경로 밖이거나 점수가 낮은 항목입니다.`}
        </p>
      )}
      {shownMain.map((g) => (
        <GroupRow key={g.key} group={g} steps={steps} onOpen={onOpen} />
      ))}
      {reference.length > 0 && (
        <div className="border-t border-hair">
          <button
            type="button"
            aria-expanded={refOpen}
            aria-controls="issues-reference"
            onClick={() => setRefOpen((v) => !v)}
            className={toggleCls}
          >
            <span aria-hidden="true">{refOpen ? '▾' : '▸'}</span>
            참고 {reference.length}건 {refOpen ? '접기' : '보기'}
            <span className="font-normal text-faint">· 과업 경로 밖이거나 점수가 낮은 항목</span>
          </button>
          {refOpen && (
            <div id="issues-reference">
              {shownRef.map((g) => (
                <GroupRow key={g.key} group={g} steps={steps} onOpen={onOpen} />
              ))}
            </div>
          )}
        </div>
      )}
      {overflow && (
        <div className="border-t border-hair pt-1">
          <Button variant="link" onClick={onShowAll}>
            {mainGroups.length > limit ? `문제 ${main.length}건 전체 보기 →` : `참고 ${reference.length}건 →`}
          </Button>
        </div>
      )}
    </section>
  );
}

/** 묶음 한 줄. 1건이면 원래 행 그대로, 여러 건이면 대표 행 + "×n" 펼치기 */
function GroupRow({ group, steps, onOpen }: { group: IssueGroup; steps: Step[]; onOpen: (issueId: number) => void }) {
  const [open, setOpen] = useState(false);
  const [first] = group.issues;
  const n = group.issues.length;
  if (n === 1) return <IssueRow issue={first} steps={steps} onOpen={onOpen} />;
  const regionId = `issue-group-${first.id}`;
  return (
    <div>
      <div className="flex items-stretch">
        <div className="min-w-0 flex-1">
          <IssueRow issue={first} steps={steps} onOpen={onOpen} />
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={regionId}
          aria-label={`같은 문제 ${n}건 ${open ? '접기' : '펼치기'}`}
          onClick={() => setOpen((v) => !v)}
          className={`${toggleCls} shrink-0 border-t border-hair px-3 tabular-nums`}
        >
          ×{n}
          <span aria-hidden="true">{open ? '▾' : '▸'}</span>
        </button>
      </div>
      {open && (
        <div id={regionId} role="group" aria-label={`같은 문제 ${n}건`} className="pl-6">
          {group.issues.map((i) => (
            <IssueRow key={i.id} issue={i} steps={steps} onOpen={onOpen} />
          ))}
        </div>
      )}
    </div>
  );
}
