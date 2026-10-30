import { ReportPage } from '@/pages/ReportPage';
import { variant } from '@/fixtures/variants';

export default function App() {
  // 개발용: ?variant=allFailed | noIssues | mobile 로 상태 변형을 본다 (API 연결 후 제거)
  const data = variant(new URLSearchParams(window.location.search).get('variant'));
  return (
    <div className="min-h-screen bg-bg">
      <header className="flex h-14 items-center gap-7 border-b border-border px-10">
        <span className="font-bold tracking-tight">StepMeter</span>
        <nav className="flex gap-1">
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
        <span className="ml-auto text-[13px] text-muted">Today 7 / 10 runs left</span>
      </header>
      <ReportPage data={data} />
    </div>
  );
}
