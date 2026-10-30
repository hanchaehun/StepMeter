import { useCallback, useEffect, useRef, useState } from 'react';
import { loadMockReport, type ReportData } from '@/api/mock';
import { passedRules } from '@/lib/report';
import { ReportHeader } from '@/components/report/ReportHeader';
import { Verdict } from '@/components/report/Verdict';
import { PathMetrics } from '@/components/report/PathMetrics';
import { IssuesPanel } from '@/components/report/IssuesPanel';
import { AttemptsPanel } from '@/components/report/AttemptsPanel';
import { PassedRules } from '@/components/report/PassedRules';
import { MoreMetrics } from '@/components/report/MoreMetrics';
import { EmptyReport } from '@/components/report/EmptyReport';
import { StepDetail, type DetailState } from '@/components/report/StepDetail';

/**
 * 단계 상세 상태를 데이터에 맞춰 확정한다. 클릭과 해시 복원이 같은 경로를 탄다.
 * - 없는 issueId면 null (요약 화면에 머문다)
 * - stepIdx만 있으면 그 단계의 첫 문제를 붙인다
 * - issue에 step이 있으면 stepIdx를 그 단계로 맞춘다
 */
export function resolveDetail(state: DetailState | null, data: ReportData): DetailState | null {
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

/** 해시 → 화면. ''는 리포트 요약, #issue-{id} / #step-{idx}는 단계 상세. */
function readHash(data: ReportData): DetailState | null {
  const h = window.location.hash;
  const mi = /^#issue-(\d+)$/.exec(h);
  if (mi) return resolveDetail({ issueId: Number(mi[1]), stepIdx: null }, data);
  const ms = /^#step-(\d+)$/.exec(h);
  if (ms) return resolveDetail({ issueId: null, stepIdx: Number(ms[1]) }, data);
  return null;
}

function hashFor(d: DetailState): string {
  return d.issueId !== null ? `#issue-${d.issueId}` : `#step-${d.stepIdx}`;
}

function clearHash() {
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
}

/**
 * 리포트 (F06). 기획서 6.1대로 두 화면: "리포트 요약"(Verdict, 지표, 문제 목록, 시도, 통과 규칙, 나머지 측정값)과
 * "단계 상세"(타임라인, 스크린샷 오버레이, 판단 이유). 문제 행·시도 점을 누르면 단계 상세로 간다.
 */
export function ReportPage({ data = loadMockReport() }: { data?: ReportData }) {
  const { report, steps, task, project } = data;
  const [detail, setDetail] = useState<DetailState | null>(() => readHash(data));
  const detailRef = useRef<DetailState | null>(detail);
  const pushedRef = useRef(false); // 요약 → 단계 상세로 갈 때 history 항목을 추가했는지
  const headingRef = useRef<HTMLHeadingElement>(null);

  // 요약에서 상세로 갈 때만 pushState(뒤로가기로 돌아오게), 상세 안 이동은 replaceState
  const goDetail = useCallback(
    (next: DetailState) => {
      const resolved = resolveDetail(next, data);
      if (!resolved) return;
      // 해시는 "어떻게 왔는지"를 남긴다: 문제로 왔으면 #issue-{id}, 단계로 왔으면 #step-{idx}
      const hash = next.issueId !== null ? hashFor(resolved) : `#step-${resolved.stepIdx}`;
      if (detailRef.current === null) {
        window.history.pushState(null, '', hash);
        pushedRef.current = true;
      } else {
        window.history.replaceState(null, '', hash);
      }
      detailRef.current = resolved;
      setDetail(resolved);
    },
    [data],
  );
  const goSummary = () => {
    detailRef.current = null;
    setDetail(null);
    if (pushedRef.current) {
      pushedRef.current = false;
      window.history.back();
    } else {
      clearHash();
    }
  };

  // 뒤로가기(popstate): 해시를 다시 읽는다
  useEffect(() => {
    const onPop = () => {
      const d = readHash(data);
      detailRef.current = d;
      setDetail(d);
      if (!d) pushedRef.current = false;
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [data]);

  // 화면이 바뀌면 제목에 포커스 (스크린 리더·키보드 사용자에게 화면 전환을 알린다)
  useEffect(() => {
    if (detail) headingRef.current?.focus();
  }, [detail?.issueId === null && detail?.stepIdx === null ? null : detail !== null]);

  const noPath = report.run.representative_attempt_index === null;
  const openIssue = (id: number) => goDetail({ issueId: id, stepIdx: null });
  const openStep = (idx: number) => goDetail({ issueId: null, stepIdx: idx });

  return (
    <main className="mx-auto max-w-[1200px] px-10 pb-10 pt-7">
      <ReportHeader report={report} task={task} project={project} />

      {detail === null ? (
        <>
          <nav aria-label="리포트 화면" className="mt-6 flex items-end gap-7 border-b border-border">
            <h2 className="-mb-px border-b-[3px] border-primary pb-2 text-[22px] font-bold tracking-tight">리포트 요약</h2>
            {!noPath && (
              <a
                href="#step-0"
                onClick={(e) => {
                  e.preventDefault();
                  openStep(steps[0]?.idx ?? 0);
                }}
                className="inline-flex min-h-[44px] items-center pb-2 text-[22px] font-semibold text-faint hover:text-fg"
              >
                단계 상세
              </a>
            )}
          </nav>

          {noPath ? (
            <div className="pt-6">
              <EmptyReport report={report} steps={steps} onOpen={openIssue} onShowAll={() => {}} />
            </div>
          ) : (
            <div className="flex min-h-[calc(100vh-18.5rem)] flex-col justify-between gap-5 pt-6">
              <div className="grid items-end gap-10 md:grid-cols-[1fr_auto]">
                <Verdict report={report} />
                <PathMetrics report={report} />
              </div>
              <div className="grid flex-1 gap-10 border-t border-border pt-5 lg:grid-cols-[1.15fr_1fr]">
                <IssuesPanel report={report} steps={steps} onOpen={openIssue} />
                <AttemptsPanel report={report} steps={steps} onOpenStep={openStep} onShowSteps={() => openStep(steps[0]?.idx ?? 0)} />
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
        </>
      ) : (
        <>
          <nav aria-label="리포트 화면" className="mt-6 flex items-end gap-7 border-b border-border">
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                goSummary();
              }}
              className="inline-flex min-h-[44px] items-center pb-2 text-[22px] font-semibold text-faint hover:text-fg"
            >
              리포트 요약
            </a>
            <h2 ref={headingRef} tabIndex={-1} className="-mb-px border-b-[3px] border-primary pb-2 text-[22px] font-bold tracking-tight focus:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              단계 상세
            </h2>
            <span className="pb-3 text-sm text-faint">타임라인 · 스크린샷 오버레이 · 판단 이유</span>
          </nav>
          <div className="pt-6">
            <StepDetail report={report} steps={steps} state={detail} onChange={goDetail} />
          </div>
        </>
      )}
    </main>
  );
}
