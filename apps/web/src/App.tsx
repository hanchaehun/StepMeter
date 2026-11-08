import { ReportRoute } from '@/pages/ReportRoute';
import { apiBaseUrl } from '@/api/client';

export default function App() {
  // VITE_API_URL이 없거나 ?mock=1이면 목 모드 (?variant=allFailed | noIssues | mobile). 있으면 /runs/{id}를 API에서 읽는다
  return (
    <div className="min-h-screen bg-bg">
      <header className="flex min-h-14 flex-wrap items-center gap-x-7 gap-y-1 border-b border-border px-4 py-2 sm:px-10 sm:py-0">
        <span className="font-bold tracking-tight">StepMeter</span>
        <nav className="flex gap-1 overflow-x-auto">
          {['New run', 'History', 'Report', 'Compare'].map((n) => (
            <a
              key={n}
              href="#"
              aria-current={n === 'Report' ? 'page' : undefined}
              className="inline-flex min-h-[44px] items-center rounded-md px-3 text-muted aria-[current=page]:bg-surface aria-[current=page]:font-semibold aria-[current=page]:text-fg"
            >
              {n}
            </a>
          ))}
        </nav>
        <span className="ml-auto whitespace-nowrap text-[13px] text-muted">Today 7 / 10 runs left</span>
      </header>
      <ReportRoute location={window.location} baseUrl={apiBaseUrl()} />
    </div>
  );
}
