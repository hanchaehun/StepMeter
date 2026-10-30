import { useCallback, useEffect, useRef, useState } from 'react';
import { loadMockReport, type ReportData } from '@/api/mock';
import { passedRules } from '@/lib/report';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ReportHeader } from '@/components/report/ReportHeader';
import { Verdict } from '@/components/report/Verdict';
import { PathMetrics } from '@/components/report/PathMetrics';
import { IssuesPanel } from '@/components/report/IssuesPanel';
import { AttemptsPanel } from '@/components/report/AttemptsPanel';
import { PassedRules } from '@/components/report/PassedRules';
import { MoreMetrics } from '@/components/report/MoreMetrics';
import { IssuesTab } from '@/components/report/IssuesTab';
import { StepsTab } from '@/components/report/StepsTab';
import { IssueDialog, type DialogState } from '@/components/report/IssueDialog';
import { EmptyReport } from '@/components/report/EmptyReport';

type Tab = 'overview' | 'issues' | 'steps';

/**
 * 팝업 상태를 데이터에 맞춰 확정한다. 클릭과 해시 복원이 같은 경로를 탄다.
 * - 없는 issueId면 null (팝업 안 엶)
 * - stepIdx만 있으면 그 단계의 첫 문제를 붙인다
 * - issue에 step이 있으면 stepIdx를 그 단계로 맞춘다
 */
export function resolveDialog(state: DialogState | null, data: ReportData): DialogState | null {
  if (!state) return null;
  const { report, steps } = data;
  const rep = report.run.representative_attempt_index;
  if (state.issueId !== null) {
    const issue = report.issues.find((i) => i.id === state.issueId);
    if (!issue) return null;
    return { issueId: issue.id, stepIdx: issue.step?.idx ?? state.stepIdx };
  }
  if (state.stepIdx !== null) {
    if (!steps.some((s) => s.idx === state.stepIdx)) return null;
    const first = report.issues.find((i) => i.step && i.step.attempt_index === rep && i.step.idx === state.stepIdx);
    return { issueId: first?.id ?? null, stepIdx: state.stepIdx };
  }
  return null;
}

function readHash(data: ReportData): { tab: Tab; dialog: DialogState | null } {
  const h = window.location.hash;
  if (h === '#issues' || h === '#steps') return { tab: h.slice(1) as Tab, dialog: null };
  const mi = /^#issue-(\d+)$/.exec(h);
  if (mi) return { tab: 'overview', dialog: resolveDialog({ issueId: Number(mi[1]), stepIdx: null }, data) };
  const ms = /^#step-(\d+)$/.exec(h);
  if (ms) return { tab: 'overview', dialog: resolveDialog({ issueId: null, stepIdx: Number(ms[1]) }, data) };
  return { tab: 'overview', dialog: null };
}

function hashFor(d: DialogState): string {
  return d.issueId !== null ? `#issue-${d.issueId}` : `#step-${d.stepIdx}`;
}

function replaceHash(hash: string) {
  window.history.replaceState(null, '', hash || window.location.pathname + window.location.search);
}

/** 리포트 화면 (F06). 탭 3개 + 팝업. 탭은 #issues/#steps, 팝업은 #issue-{id}/#step-{idx}와 동기화한다. */
export function ReportPage({ data = loadMockReport() }: { data?: ReportData }) {
  const { report, steps, task, project } = data;
  const [initial] = useState(() => readHash(data));
  const [tab, setTab] = useState<Tab>(initial.tab);
  const [dialog, setDialog] = useState<DialogState | null>(initial.dialog);
  const dialogRef = useRef<DialogState | null>(initial.dialog);
  const pushedRef = useRef(false); // 팝업을 열며 history 항목을 추가했는지

  const changeTab = (t: Tab) => {
    setTab(t);
    replaceHash(t === 'overview' ? '' : `#${t}`);
  };
  // 닫힌 상태에서 열 때만 pushState(뒤로가기로 닫히게), 팝업 안 이동은 replaceState
  const openDialog = useCallback(
    (next: DialogState) => {
      const resolved = resolveDialog(next, data);
      if (!resolved) return;
      if (dialogRef.current === null) {
        window.history.pushState(null, '', hashFor(resolved));
        pushedRef.current = true;
      } else {
        replaceHash(hashFor(resolved));
      }
      dialogRef.current = resolved;
      setDialog(resolved);
    },
    [data],
  );
  const closeDialog = () => {
    dialogRef.current = null;
    setDialog(null);
    if (pushedRef.current) {
      pushedRef.current = false;
      window.history.back();
    } else {
      replaceHash(tab === 'overview' ? '' : `#${tab}`);
    }
  };
  const openIssue = (id: number) => openDialog({ issueId: id, stepIdx: null });
  const openStep = (idx: number) => openDialog({ issueId: null, stepIdx: idx });

  // 뒤로가기(popstate): 해시를 다시 읽어 탭·팝업을 맞춘다
  useEffect(() => {
    const onPop = () => {
      const h = readHash(data);
      setTab(h.tab);
      dialogRef.current = h.dialog;
      setDialog(h.dialog);
      if (!h.dialog) pushedRef.current = false;
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [data]);

  const noPath = report.run.representative_attempt_index === null;
  const issueCount = report.issues.length;

  return (
    <main className="mx-auto max-w-[1200px] px-10 pb-10 pt-7">
      <ReportHeader report={report} task={task} project={project} />

      <Tabs value={tab} onValueChange={(v) => changeTab(v as Tab)} className="mt-5">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="issues">
            Issues<b className="ml-1.5 font-semibold text-faint">{issueCount}</b>
          </TabsTrigger>
          <TabsTrigger value="steps" disabled={noPath}>
            Steps<b className="ml-1.5 font-semibold text-faint">{noPath ? '—' : steps.length}</b>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          {noPath ? (
            <EmptyReport report={report} steps={steps} onOpen={openIssue} onShowAll={() => changeTab('issues')} />
          ) : (
          <div className="flex min-h-[calc(100vh-18.5rem)] flex-col justify-between gap-5">
            <div className="grid items-end gap-10 md:grid-cols-[1fr_auto]">
              <Verdict report={report} />
              <PathMetrics report={report} />
            </div>
            <div className="grid flex-1 gap-10 border-t border-border pt-5 lg:grid-cols-[1.15fr_1fr]">
              <IssuesPanel report={report} steps={steps} onOpen={openIssue} onShowAll={() => changeTab('issues')} />
              <AttemptsPanel report={report} steps={steps} onOpenStep={openStep} onShowSteps={noPath ? undefined : () => changeTab('steps')} />
            </div>
            <div className="flex justify-center pt-1">
              <button
                type="button"
                onClick={() => document.getElementById('below-fold')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-control bg-bg px-5 text-sm font-semibold text-fg hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <span aria-hidden="true">↓</span> 더 보기 · 통과한 규칙 {passedRules(report.issues, report.run.viewport).length}개 · 나머지 측정값
              </button>
            </div>
          </div>
          )}
          <div id="below-fold" className="mt-16 scroll-mt-6" />
          <PassedRules items={passedRules(report.issues, report.run.viewport)} />
          <MoreMetrics report={report} />
        </TabsContent>

        <TabsContent value="issues">
          <IssuesTab report={report} steps={steps} onOpen={openIssue} />
        </TabsContent>

        <TabsContent value="steps">
          <StepsTab report={report} steps={steps} onOpenStep={openStep} />
        </TabsContent>
      </Tabs>

      <IssueDialog open={dialog !== null} state={dialog ?? { issueId: null, stepIdx: null }} report={report} steps={steps} onChange={openDialog} onClose={closeDialog} />
    </main>
  );
}
