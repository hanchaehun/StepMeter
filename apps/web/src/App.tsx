import { ReportRoute } from '@/pages/ReportRoute';
import { MeasureCreatePage } from '@/pages/MeasureCreatePage';
import { apiBaseUrl } from '@/api/client';
import type { MockScenario } from '@/api/mockServer';

// 라우터 라이브러리 없이 주소로 화면을 고른다. /new = 측정 생성(F01), 나머지 = 리포트(ReportRoute가 /runs/{id}를 읽는다)
export function pageFromPath(pathname: string): 'new' | 'report' {
  return /^\/new\/?$/.test(pathname) ? 'new' : 'report';
}

function mockScenario(search: string): MockScenario {
  const v = new URLSearchParams(search).get('variant');
  return v === 'limit' || v === 'unauthorized' ? v : 'ok';
}

const NAV = [
  { label: 'New run', href: '/new', page: 'new' },
  { label: 'History', href: '#', page: null },
  { label: 'Report', href: '#', page: 'report' },
  { label: 'Compare', href: '#', page: null },
] as const;

export default function App() {
  // VITE_API_URL이 없거나 ?mock=1이면 목 모드 (?variant=allFailed | noIssues | mobile). 있으면 /runs/{id}를 API에서 읽는다
  const page = pageFromPath(window.location.pathname);
  const params = new URLSearchParams(window.location.search);
  const base = apiBaseUrl();
  return (
    <div className="min-h-screen bg-bg">
      <header className="flex min-h-14 flex-wrap items-center gap-x-7 gap-y-1 border-b border-border px-4 py-2 sm:px-10 sm:py-0">
        <span className="font-bold tracking-tight">StepMeter</span>
        <nav className="flex gap-1 overflow-x-auto">
          {NAV.map((n) => (
            <a
              key={n.label}
              href={n.href === '/new' && params.get('mock') === '1' ? '/new?mock=1' : n.href}
              aria-current={n.page === page ? 'page' : undefined}
              className="inline-flex min-h-[44px] items-center rounded-md px-3 text-muted aria-[current=page]:bg-surface aria-[current=page]:font-semibold aria-[current=page]:text-fg"
            >
              {n.label}
            </a>
          ))}
        </nav>
        <span className="ml-auto whitespace-nowrap text-[13px] text-muted">Today 7 / 10 runs left</span>
      </header>
      {page === 'new' ? (
        <MeasureCreatePage baseUrl={params.get('mock') === '1' ? null : base} mockScenario={mockScenario(window.location.search)} />
      ) : (
        <ReportRoute location={window.location} baseUrl={base} />
      )}
    </div>
  );
}
