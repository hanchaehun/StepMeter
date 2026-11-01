import type { Project, Report, Task } from '@/api/mock';

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function duration(start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  const s = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

export function ReportHeader({ report, task, project }: { report: Report; task: Task; project: Project }) {
  const { run } = report;
  const viewport = run.viewport === 'mobile' ? 'Mobile 390×844' : 'Desktop 1280×800';
  const parts = [hostOf(project.base_url), viewport, fmtDate(run.created_at), `${report.attempts.length} attempts`];
  const dur = duration(run.started_at, run.finished_at);
  if (dur) parts.push(dur);
  if (run.mode === 'replay_only') parts.push('재생 전용 · LLM 비용 없음');

  return (
    <header>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Report · Run #{run.id}</p>
      <h1 className="mb-1 text-[22px] font-bold tracking-tight">{task.description}</h1>
      <p className="text-sm text-muted">
        {parts.join(' · ')}
        {run.base_run_id !== null && (
          <a href={`#compare-${run.base_run_id}`} className="ml-3 font-semibold text-fg underline-offset-4 hover:underline">
            Compare with #{run.base_run_id}
          </a>
        )}
      </p>
    </header>
  );
}
