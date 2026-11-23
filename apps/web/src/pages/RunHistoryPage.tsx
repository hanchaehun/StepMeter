// 측정 목록 (F11). ADR 0011 4번: 목록은 필수, 추이 차트는 선택 → 이번에는 목록만.
// 프로젝트 → 과업 → 화면 크기를 고르면 그 과업의 측정을 최신순으로 보인다(GET /tasks/{id}/runs?viewport=).
// 같은 뷰포트끼리만 보인다(7.1). 고른 값은 주소(?project=&task=&viewport=)에 남겨 새로 고침·공유해도 유지한다.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError, clearAccessCode, describeError, getAccessCode, setAccessCode } from '@/api/client';
import { listProjects, listTaskRuns, listTasks, type RunHistoryItem, type ViewportPreset } from '@/api/history';
import { createMockServer } from '@/api/mockServer';
import { AccessCodeView } from '@/components/report/ReportStatus';
import { cn } from '@/lib/cn';

const STATUS_LABEL = { queued: '대기', running: '진행 중', completed: '완료', failed: '오류', canceled: '취소' } as const;
const MODE_LABEL = { agent: '에이전트', auto: '재측정', replay_only: '재생만' } as const;

/** 리포트와 같은 네 지표 (src/lib/report.ts TILE_ORDER의 key). 예상 소요 시간은 데스크톱만 (5.10) */
export const METRIC_COLUMNS = [
  { key: 'est_task_time', label: '예상 소요 시간', desktopOnly: true },
  { key: 'click_count', label: '클릭', desktopOnly: false },
  { key: 'travel_distance', label: '커서 이동', desktopOnly: false },
  { key: 'fitts_id_sum', label: '이동 난이도', desktopOnly: false },
] as const;

export function formatMetric(key: string, value: number): string {
  if (key === 'est_task_time') return `${value.toFixed(1)}초`;
  if (key === 'click_count') return `${Math.round(value)}회`;
  if (key === 'travel_distance') return `${Math.round(value).toLocaleString('ko-KR')}px`;
  if (key === 'fitts_id_sum') return `${value.toFixed(1)} bit`;
  return String(value);
}

const timeFmt = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });

/** 측정 줄에서 갈 화면: 완료면 리포트, 아니면 진행 화면(진행 중·취소·오류 상태를 그 화면이 보인다) */
export function runLink(item: RunHistoryItem, suffix = ''): { href: string; label: string } {
  const r = item.run;
  if (r.status === 'completed') return { href: `/runs/${r.id}${suffix}`, label: '리포트' };
  if (r.status === 'queued' || r.status === 'running') return { href: `/runs/${r.id}/progress${suffix}`, label: '진행 화면' };
  return { href: `/runs/${r.id}/progress${suffix}`, label: '상태 보기' };
}

interface Props {
  /** null이면 목 모드 */
  baseUrl: string | null;
  search: string;
  fetchImpl?: typeof fetch;
}

function readNum(v: string | null): number | null {
  return v && /^\d+$/.test(v) ? Number(v) : null;
}

export function RunHistoryPage({ baseUrl, search, fetchImpl }: Props) {
  const mock = baseUrl === null;
  const [mockServer] = useState(() => (mock && !fetchImpl ? createMockServer('ok', 200, { seed: true }) : null));
  const api = { baseUrl: baseUrl ?? '/api', fetchImpl: fetchImpl ?? mockServer?.fetch };
  const suffix = mock ? '?mock=1' : '';

  const initial = new URLSearchParams(search);
  const [projectId, setProjectId] = useState<number | null>(readNum(initial.get('project')));
  const [taskId, setTaskId] = useState<number | null>(readNum(initial.get('task')));
  const [viewport, setViewport] = useState<ViewportPreset>(initial.get('viewport') === 'mobile' ? 'mobile' : 'desktop');
  const [code, setCode] = useState<string | null>(() => (mock ? 'mock' : getAccessCode()));
  const [codeWrong, setCodeWrong] = useState(false);
  const opts = { ...api, accessCode: code ?? '' };

  const projects = useQuery({ queryKey: ['projects', code], queryFn: ({ signal }) => listProjects({ ...opts, signal }), enabled: code !== null, retry: false });
  // 주소에 없거나 목록에 없는 프로젝트면 가장 최근 것(created_at 내림차순의 첫째)
  const project = projects.data?.find((p) => p.id === projectId) ?? projects.data?.[0] ?? null;

  const tasks = useQuery({
    queryKey: ['tasks', project?.id, code],
    queryFn: ({ signal }) => listTasks(project!.id, { ...opts, signal }),
    enabled: code !== null && project !== null,
    retry: false,
  });
  const task = tasks.data?.find((t) => t.id === taskId) ?? tasks.data?.[0] ?? null;

  const runs = useQuery({
    queryKey: ['task-runs', task?.id, viewport, code],
    queryFn: ({ signal }) => listTaskRuns(task!.id, viewport, { ...opts, signal }),
    enabled: code !== null && task !== null,
    retry: false,
  });

  // 고른 값을 주소에 남긴다 (?mock=1 등 다른 값은 유지)
  useEffect(() => {
    if (!project) return;
    const p = new URLSearchParams(window.location.search);
    p.set('project', String(project.id));
    if (task) p.set('task', String(task.id));
    else p.delete('task');
    p.set('viewport', viewport);
    window.history.replaceState(null, '', `${window.location.pathname}?${p.toString()}`);
  }, [project, task, viewport]);

  const errors = [projects.error, tasks.error, runs.error];
  const unauthorized = errors.some((e) => e instanceof ApiError && e.status === 401);
  useEffect(() => {
    if (!unauthorized) return;
    if (!mock) clearAccessCode();
    setCode(null);
    setCodeWrong(true);
  }, [unauthorized, mock]);

  if (code === null || unauthorized) {
    return (
      <AccessCodeView
        wrong={codeWrong}
        onSubmit={(c) => {
          if (!mock) setAccessCode(c);
          setCodeWrong(false);
          setCode(c);
        }}
      />
    );
  }

  const error = errors.find((e) => e);
  const newLink = `/new${suffix}`;

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-10">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">측정 목록</h1>
        <a href={newLink} className={btnPrimary}>새 측정</a>
      </div>

      {error ? (
        <ErrorBox error={error} onRetry={() => void Promise.all([projects.refetch(), tasks.refetch(), runs.refetch()])} />
      ) : projects.isPending ? (
        <p role="status" className="text-muted">프로젝트를 불러오는 중</p>
      ) : !project ? (
        <Empty title="아직 측정한 사이트가 없습니다" body="새 측정을 만들면 사이트별로 여기에 모입니다." link={newLink} />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_2fr_auto]">
            <div>
              <label htmlFor="h-project" className="mb-1.5 block text-sm font-semibold">사이트</label>
              <select
                id="h-project"
                value={project.id}
                onChange={(e) => {
                  setProjectId(Number(e.target.value));
                  setTaskId(null);
                }}
                className={selectCls}
              >
                {projects.data!.map((p) => (
                  <option key={p.id} value={p.id}>{p.base_url}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="h-task" className="mb-1.5 block text-sm font-semibold">과업</label>
              <select
                id="h-task"
                value={task?.id ?? ''}
                disabled={!tasks.data?.length}
                onChange={(e) => setTaskId(Number(e.target.value))}
                className={selectCls}
              >
                {tasks.isPending && <option value="">불러오는 중</option>}
                {tasks.data?.length === 0 && <option value="">과업 없음</option>}
                {tasks.data?.map((t) => (
                  <option key={t.id} value={t.id}>{t.description}</option>
                ))}
              </select>
            </div>
            <fieldset className="sm:col-span-2 lg:col-span-1">
              <legend className="mb-1.5 text-sm font-semibold">화면 크기</legend>
              <div className="flex gap-2">
                {(['desktop', 'mobile'] as const).map((v) => (
                  <label key={v} className={cn('flex min-h-[44px] cursor-pointer items-center gap-2 rounded-lg px-3', viewport === v ? 'border-2 border-fg font-semibold' : 'border border-control')}>
                    <input type="radio" name="h-viewport" value={v} checked={viewport === v} onChange={() => setViewport(v)} className="h-5 w-5 accent-[var(--primary)]" />
                    {v === 'desktop' ? '데스크톱' : '모바일'}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          {tasks.isPending ? (
            <p role="status" className="text-muted">과업을 불러오는 중</p>
          ) : !task ? (
            <Empty title="이 사이트에는 과업이 없습니다" body="새 측정에서 과업을 적으면 여기에 생깁니다." link={newLink} />
          ) : runs.isPending ? (
            <p role="status" className="text-muted">측정을 불러오는 중</p>
          ) : runs.data!.length === 0 ? (
            <Empty
              title={`${viewport === 'desktop' ? '데스크톱' : '모바일'}으로 잰 측정이 없습니다`}
              body="화면 크기를 바꿔 보거나 새 측정을 만들어 주세요. 측정은 같은 화면 크기끼리만 비교합니다."
              link={newLink}
            />
          ) : (
            <RunTable items={runs.data!} viewport={viewport} suffix={suffix} />
          )}
        </>
      )}
    </main>
  );
}

function RunTable({ items, viewport, suffix }: { items: RunHistoryItem[]; viewport: ViewportPreset; suffix: string }) {
  const cols = METRIC_COLUMNS.filter((c) => viewport === 'desktop' || !c.desktopOnly);
  return (
    <div>
      {/* 좁은 화면에서는 표 상자 안에서만 가로로 스크롤한다.
          relative: 표 안의 sr-only(absolute) 글자가 이 상자를 벗어나 페이지를 넓히지 않게 한다 */}
      <div className="relative overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-labelledby="h-caption">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <caption id="h-caption" className="sr-only">측정 목록, 최신순</caption>
          <thead className="bg-surface text-left">
            <tr>
              <th scope="col" className={th}>측정</th>
              <th scope="col" className={th}>요청 시각</th>
              <th scope="col" className={th}>방식</th>
              <th scope="col" className={th}>상태</th>
              <th scope="col" className={th}>성공 시도</th>
              {cols.map((c) => (
                <th key={c.key} scope="col" className={cn(th, 'text-right')}>{c.label}</th>
              ))}
              <th scope="col" className={th}><span className="sr-only">열기</span></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const r = item.run;
              const link = runLink(item, suffix);
              const done = r.status === 'completed';
              return (
                <tr key={r.id} className="border-t border-hair">
                  <th scope="row" className={cn(td, 'font-semibold')}>#{r.id}</th>
                  <td className={td}><time dateTime={r.created_at}>{timeFmt.format(new Date(r.created_at))}</time></td>
                  <td className={td}>{MODE_LABEL[r.mode]}</td>
                  <td className={td}>
                    {STATUS_LABEL[r.status]}
                    {r.status === 'running' && ` ${r.progress}%`}
                  </td>
                  <td className={td}>{done ? `${item.success_count} / ${item.attempt_count}` : '—'}</td>
                  {cols.map((c) => {
                    const m = item.metrics.find((x) => x.key === c.key);
                    return (
                      <td key={c.key} className={cn(td, 'text-right tabular-nums')}>
                        {m ? formatMetric(c.key, m.value) : '—'}
                        {m?.spread_quality === 'weak' && <span className="block text-xs text-muted">편차 추정 약함</span>}
                      </td>
                    );
                  })}
                  <td className={td}>
                    <a href={link.href} className="inline-flex min-h-[44px] items-center px-1 font-semibold underline underline-offset-4">
                      {link.label}
                      <span className="sr-only"> · 측정 #{r.id}</span>
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ul className="mt-3 space-y-1 text-sm text-muted">
        <li>· 지표는 성공한 시도의 중앙값이고, 클릭·커서 이동·이동 난이도는 에이전트가 간 경로에 따라 달라집니다.</li>
        {viewport === 'desktop' ? (
          <>
            <li>· 예상 소요 시간은 문헌값 기준 추정이며 시스템 응답 시간을 뺀 값입니다.</li>
            {/* #75 UX 감사 F-10: 재생은 예상 소요 시간을 저장하지 않아 성공해도 "—"다 */}
            <li>· 이전 경로를 재생한 재측정은 예상 소요 시간을 계산하지 않습니다(—).</li>
          </>
        ) : (
          <li>· 모바일은 예상 소요 시간을 계산하지 않습니다.</li>
        )}
        <li>· 성공한 시도가 없으면 지표가 없습니다(—).</li>
      </ul>
    </div>
  );
}

const th = 'px-3 py-2.5 font-semibold whitespace-nowrap';
const td = 'px-3 py-1 align-middle whitespace-nowrap';
const selectCls = 'block min-h-[44px] w-full rounded-lg border border-control bg-bg px-3 text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60';
const btnPrimary =
  'inline-flex min-h-[44px] items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2';

function Empty({ title, body, link }: { title: string; body: string; link: string }) {
  return (
    <div className="rounded-lg border border-border p-6">
      <p className="mb-1 text-lg font-semibold">{title}</p>
      <p className="mb-4 text-muted">{body}</p>
      <a href={link} className={btnPrimary}>새 측정</a>
    </div>
  );
}

function ErrorBox({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { message, detail } = describeError(error);
  return (
    <div role="alert" className="rounded-lg border-2 border-danger p-4">
      <p className="flex items-center gap-1.5 font-semibold text-danger">
        <span aria-hidden="true">▲</span> 측정 목록을 읽지 못했습니다
      </p>
      <p className="mt-1 text-sm">{message}</p>
      {detail && <p className="mt-1 text-sm text-muted">서버 응답: {detail}</p>}
      <button type="button" onClick={onRetry} className="mt-3 inline-flex min-h-[44px] items-center rounded-lg border border-control px-4 text-sm font-semibold">
        다시 시도
      </button>
    </div>
  );
}
