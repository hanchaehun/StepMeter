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

export function ReportHeader({ report, task, project }: { report: Report; task?: Task | null; project?: Project | null }) {
  const { run } = report;
  const viewport = run.viewport === 'mobile' ? 'Mobile 390×844' : 'Desktop 1280×800';
  // GET /tasks/{id}가 아직 없어 실제 API 모드에서는 과업 문장·사이트 주소가 없다 → 과업 번호만
  const title = task?.description ?? `과업 #${run.task_id}`;
  const parts = [project ? hostOf(project.base_url) : null, viewport, fmtDate(run.created_at), `${report.attempts.length} attempts`].filter(
    (p): p is string => p !== null,
  );
  const dur = duration(run.started_at, run.finished_at);
  if (dur) parts.push(dur);
  if (run.mode === 'replay_only') parts.push('재생 전용 · LLM 비용 없음');

  return (
    <header>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Report · Run #{run.id}</p>
      <h1 className="mb-1 text-[22px] font-bold tracking-tight">{title}</h1>
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
