import { ReportRoute } from '@/pages/ReportRoute';
import { MeasureCreatePage } from '@/pages/MeasureCreatePage';
import { MeasureProgressPage } from '@/pages/MeasureProgressPage';
import { RunHistoryPage } from '@/pages/RunHistoryPage';
import { apiBaseUrl } from '@/api/client';
import type { MockScenario } from '@/api/mockServer';

// 라우터 라이브러리 없이 주소로 화면을 고른다.
// /new = 측정 생성(F01), /runs/{id}/progress = 측정 진행(F02), /history = 측정 목록(F11),
// 나머지 = 리포트(ReportRoute가 /runs/{id}를 읽는다)
// rootIsHistory: 실제 API 모드에서 / 는 측정 목록이다(#75 UX 감사 F-01: "측정 번호가 없습니다" 막다른 첫 화면 대신).
// 목 모드의 / 는 지금처럼 데모 리포트다(infra/scripts/check_web.py).
export type Page = { kind: 'new' } | { kind: 'progress'; runId: number } | { kind: 'history' } | { kind: 'report' };
export function pageFromPath(pathname: string, rootIsHistory = false): Page {
  if (rootIsHistory && /^\/?$/.test(pathname)) return { kind: 'history' };
  if (/^\/new\/?$/.test(pathname)) return { kind: 'new' };
  if (/^\/history\/?$/.test(pathname)) return { kind: 'history' };
  const m = /^\/runs\/(\d+)\/progress\/?$/.exec(pathname);
  if (m) return { kind: 'progress', runId: Number(m[1]) };
  return { kind: 'report' };
}

function mockScenario(search: string): MockScenario {
  const v = new URLSearchParams(search).get('variant');
  return v === 'limit' || v === 'unauthorized' ? v : 'ok';
}

// #75 UX 감사 F-09: 갈 곳 없는 링크(href="#")는 메뉴에 두지 않는다. 비교(Compare)는 비교 화면(#82)이 생기면 더한다.
// Report는 링크가 아니라 리포트 화면에 있을 때만 현재 위치로 보인다.
const NAV = [
  { label: 'New run', href: '/new', page: 'new' },
  { label: 'History', href: '/history', page: 'history' },
] as const;
const navCls = 'inline-flex min-h-[44px] items-center rounded-md px-3 text-muted aria-[current=page]:bg-surface aria-[current=page]:font-semibold aria-[current=page]:text-fg';

export default function App() {
  // VITE_API_URL이 없거나 ?mock=1이면 목 모드 (?variant=allFailed | noIssues | mobile). 있으면 /runs/{id}를 API에서 읽는다
  const params = new URLSearchParams(window.location.search);
  const base = apiBaseUrl();
  const mock = base === null || params.get('mock') === '1';
  const page = pageFromPath(window.location.pathname, !mock);
  return (
    <div className="min-h-screen bg-bg">
      <header className="flex min-h-14 flex-wrap items-center gap-x-7 gap-y-1 border-b border-border px-4 py-2 sm:px-10 sm:py-0">
        <span className="font-bold tracking-tight">StepMeter</span>
        <nav className="flex gap-1 overflow-x-auto">
          {NAV.map((n) => (
            <a
              key={n.label}
              href={n.href.startsWith('/') && params.get('mock') === '1' ? `${n.href}?mock=1` : n.href}
              aria-current={n.page === page.kind ? 'page' : undefined}
              className={navCls}
            >
              {n.label}
            </a>
          ))}
          {page.kind === 'report' && (
            <span aria-current="page" className={navCls}>
              Report
            </span>
          )}
        </nav>
      </header>
      {page.kind === 'new' ? (
        <MeasureCreatePage baseUrl={mock ? null : base} mockScenario={mockScenario(window.location.search)} />
      ) : page.kind === 'history' ? (
        <RunHistoryPage baseUrl={mock ? null : base} search={window.location.search} />
      ) : page.kind === 'progress' ? (
        <MeasureProgressPage runId={page.runId} baseUrl={mock ? null : base} />
      ) : (
        <ReportRoute location={window.location} baseUrl={base} />
      )}
    </div>
  );
}
