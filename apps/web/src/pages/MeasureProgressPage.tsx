// 측정 진행 화면 (F02). 서비스 기획서 6.1 "측정 진행": 진행 단계, 현재 스크린샷, 에이전트의 최근 판단 한 줄, 취소.
// - GET /runs/{id}를 2초마다 다시 읽는다(2.2). 끝난 상태(completed·failed·canceled)가 되면 멈춘다
// - 진행률은 실행 중 최대 90, 후처리가 끝나야 100이다(docs/worker_api_spec.md 2번). 그래서 90 이상이면 "결과 정리"로 보인다
// - 취소는 POST /runs/{id}/cancel. API가 바로 canceled로 바꾼다(같은 문서 1번 "취소")
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, clearAccessCode, describeError, getAccessCode, setAccessCode } from '@/api/client';
import { cancelRun, fetchRunProgress, isFinished, type RunProgress } from '@/api/progress';
import { createMockServer } from '@/api/mockServer';
import { AccessCodeView } from '@/components/report/ReportStatus';
import { Screenshot } from '@/components/Screenshot';
import { Button } from '@/components/ui/button';

export const POLL_MS = 2000;

const VIEWPORT_SIZE = { desktop: { width: 1280, height: 800 }, mobile: { width: 390, height: 844 } } as const;

export const STAGES = ['대기', '과업 수행', '결과 정리', '완료'] as const;

/** 지금 단계의 번호(STAGES 기준). failed·canceled는 null */
export function stageOf(run: Pick<RunProgress, 'status' | 'progress'>): number | null {
  if (run.status === 'queued') return 0;
  if (run.status === 'running') return run.progress >= 90 ? 2 : 1;
  if (run.status === 'completed') return 3;
  return null;
}

interface Props {
  runId: number;
  /** null이면 목 모드 (화면 안에서 진행을 흉내 낸다) */
  baseUrl: string | null;
  fetchImpl?: typeof fetch;
  pollMs?: number;
}

export function MeasureProgressPage({ runId, baseUrl, fetchImpl, pollMs = POLL_MS }: Props) {
  const mock = baseUrl === null;
  const [mockServer] = useState(() => (mock && !fetchImpl ? createMockServer('ok', 300, { autoRun: true, advance: true }) : null));
  const api = { baseUrl: baseUrl ?? '/api', fetchImpl: fetchImpl ?? mockServer?.fetch };
  const suffix = mock ? '?mock=1' : '';

  const [code, setCode] = useState<string | null>(() => (mock ? 'mock' : getAccessCode()));
  const [codeWrong, setCodeWrong] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['run-progress', runId, code],
    queryFn: ({ signal }) => fetchRunProgress(runId, { ...api, accessCode: code as string, signal }),
    enabled: code !== null,
    retry: false,
    // 끝난 상태거나 다시 읽어도 소용없는 오류(401·404)면 멈춘다. 그 밖의 오류(연결 끊김 등)는 계속 다시 읽는다
    refetchInterval: (q) => {
      const d = q.state.data;
      const e = q.state.error;
      if (d && isFinished(d.status)) return false;
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) return false;
      return pollMs;
    },
  });

  const cancel = useMutation({
    mutationFn: () => cancelRun(runId, { ...api, accessCode: code as string }),
    onSettled: () => {
      setConfirming(false);
      // 성공(202)이든 이미 끝남(409)이든 지금 상태를 다시 읽는다
      void queryClient.invalidateQueries({ queryKey: ['run-progress', runId] });
    },
  });

  const authFailed = (query.error instanceof ApiError && query.error.status === 401) || (cancel.error instanceof ApiError && cancel.error.status === 401);
  // 401: 틀린 코드를 세션에서 지우고 다시 묻는다. 새 코드를 받으면 queryKey가 바뀌어 다시 읽는다
  useEffect(() => {
    if (!authFailed) return;
    if (!mock) clearAccessCode();
    setCode(null);
    setCodeWrong(true);
    cancel.reset();
  }, [authFailed]);

  if (code === null || authFailed) {
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

  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <Main>
        <h1 className="mb-2 text-2xl font-bold">측정 #{runId}을(를) 찾지 못했습니다</h1>
        <p className="mb-5 text-muted">번호가 맞는지, 이 측정을 만든 초대 코드로 들어왔는지 확인해 주세요.</p>
        <a href={`/new${suffix}`} className={linkBtn}>새 측정 만들기</a>
      </Main>
    );
  }

  const run = query.data;
  if (!run) {
    if (query.error) return <Main><ErrorBox error={query.error} retrying /></Main>;
    return (
      <Main>
        <p role="status" className="text-muted">측정 #{runId} 상태를 불러오는 중</p>
      </Main>
    );
  }

  const stage = stageOf(run);
  const active = !isFinished(run.status);
  const step = run.latest_step;
  const vp = VIEWPORT_SIZE[run.viewport];

  return (
    <Main>
      <div className="mb-6 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-2xl font-bold tracking-tight">측정 #{run.id}</h1>
        <span className="text-sm text-muted">
          {run.viewport === 'desktop' ? '데스크톱 1280×800' : '모바일 390×844'} · 반복 {run.repeat_n}회 · {run.mode === 'auto' ? '재측정(재생 먼저)' : run.mode === 'replay_only' ? '재생만' : '에이전트'}
        </span>
      </div>

      {query.error && <ErrorBox error={query.error} retrying={active} />}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-labelledby="p-now" className="min-w-0">
          <h2 id="p-now" className="sr-only">현재 화면</h2>
          {active && step ? (
            <figure>
              <Screenshot src={step.screenshot_url} viewport={vp} overlays={[]} className="rounded-lg border border-border" />
              <figcaption className="mt-3">
                <span className="block text-sm text-muted">
                  에이전트의 최근 판단 · 시도 {step.attempt_index} / {run.repeat_n}, 단계 {step.idx + 1}
                </span>
                <span className="mt-1 block">{step.thought}</span>
              </figcaption>
            </figure>
          ) : (
            <StatusPanel run={run} suffix={suffix} />
          )}
        </section>

        <aside aria-labelledby="p-side" className="h-fit space-y-5 rounded-lg border border-border p-5">
          <h2 id="p-side" className="font-semibold">진행 상황</h2>
          <Progress run={run} />
          <ol className="space-y-1.5 text-sm" aria-label="진행 단계">
            {STAGES.map((label, i) => {
              const now = stage === i;
              const done = stage !== null && i < stage;
              return (
                <li key={label} aria-current={now ? 'step' : undefined} className={now ? 'font-semibold text-fg' : 'text-muted'}>
                  <span aria-hidden="true">{done ? '✓ ' : now ? '▶ ' : '· '}</span>
                  {label}
                  {now && ' (지금)'}
                  {done && <span className="sr-only"> (끝남)</span>}
                </li>
              );
            })}
          </ol>
          <p className="text-sm text-muted">지금까지 쓴 비용 ${run.cost_usd.toFixed(3)}</p>

          {active && (
            <div>
              {confirming ? (
                <div role="alertdialog" aria-labelledby="p-cancel-q" className="rounded-lg border border-control p-3">
                  <p id="p-cancel-q" className="mb-2 text-sm">측정을 취소할까요? 리포트가 만들어지지 않고, 지금까지 쓴 비용은 돌아오지 않습니다.</p>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="default" onClick={() => cancel.mutate()} disabled={cancel.isPending} autoFocus>
                      {cancel.isPending ? '취소하는 중…' : '측정 취소'}
                    </Button>
                    <Button onClick={() => setConfirming(false)} disabled={cancel.isPending}>계속 측정</Button>
                  </div>
                </div>
              ) : (
                <Button onClick={() => setConfirming(true)}>측정 취소</Button>
              )}
              {cancel.error && !(cancel.error instanceof ApiError && cancel.error.status === 409) && (
                <p className="mt-2 text-sm text-danger">▲ 취소 요청을 보내지 못했습니다. {describeError(cancel.error).message}</p>
              )}
            </div>
          )}
        </aside>
      </div>
    </Main>
  );
}

const linkBtn =
  'inline-flex min-h-[44px] items-center justify-center rounded-lg px-4 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary bg-primary text-primary-fg';
const linkOutline =
  'inline-flex min-h-[44px] items-center justify-center rounded-lg px-4 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary border border-control text-fg';

function Main({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-10">{children}</main>;
}

function Progress({ run }: { run: RunProgress }) {
  const label = run.status === 'queued' ? '대기 중' : `${run.progress}%`;
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-sm">
        <span id="p-bar">진행률</span>
        <span aria-hidden="true" className="font-semibold">{label}</span>
      </div>
      <div
        role="progressbar"
        aria-labelledby="p-bar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={run.progress}
        aria-valuetext={label}
        className="h-2.5 overflow-hidden rounded-full border border-control bg-bg"
      >
        <div className="h-full bg-primary" style={{ width: `${run.progress}%` }} />
      </div>
    </div>
  );
}

/** 스크린샷이 아직 없거나 끝난 뒤에 보이는 안내. 상태 바뀜을 스크린 리더에 알린다 */
function StatusPanel({ run, suffix }: { run: RunProgress; suffix: string }) {
  return (
    <div role="status" className="rounded-lg border border-border p-6">
      {run.status === 'queued' && (
        <>
          <p className="mb-1 text-lg font-semibold">대기열에 있습니다</p>
          <p className="text-muted">앞선 측정이 끝나면 시작합니다. 이 화면은 2초마다 새로 고칩니다.</p>
        </>
      )}
      {run.status === 'running' && (
        <>
          <p className="mb-1 text-lg font-semibold">브라우저를 준비하고 있습니다</p>
          <p className="text-muted">에이전트가 첫 행동을 하면 화면과 판단이 여기에 나옵니다.</p>
        </>
      )}
      {run.status === 'completed' && (
        <>
          <p className="mb-1 text-lg font-semibold">측정이 끝났습니다</p>
          <p className="mb-4 text-muted">리포트에서 문제와 지표를 확인하세요.</p>
          <a href={`/runs/${run.id}${suffix}`} className={linkBtn}>리포트 보기</a>
        </>
      )}
      {run.status === 'canceled' && (
        <>
          <p className="mb-1 text-lg font-semibold">측정을 취소했습니다</p>
          <p className="mb-4 text-muted">취소한 측정은 리포트를 만들지 않습니다.</p>
          <a href={`/new${suffix}`} className={linkOutline}>새 측정 만들기</a>
        </>
      )}
      {run.status === 'failed' && (
        <>
          <p className="mb-1 flex items-center gap-1.5 text-lg font-semibold text-danger">
            <span aria-hidden="true">▲</span> 서비스 오류로 측정을 마치지 못했습니다
          </p>
          <p className="mb-4 text-muted">워커가 멈췄거나 결과를 저장하지 못했습니다. 사이트 문제가 아니므로 다시 측정해 주세요.</p>
          <a href={`/new${suffix}`} className={linkBtn}>다시 측정</a>
        </>
      )}
    </div>
  );
}

function ErrorBox({ error, retrying }: { error: unknown; retrying: boolean }) {
  const { message, detail } = describeError(error);
  return (
    <div role="alert" className="mb-6 rounded-lg border-2 border-danger p-3">
      <p className="flex items-center gap-1.5 font-semibold text-danger">
        <span aria-hidden="true">▲</span> 진행 상태를 읽지 못했습니다
      </p>
      <p className="mt-1 text-sm">
        {message}
        {retrying && ' 2초마다 다시 시도합니다.'}
      </p>
      {detail && <p className="mt-1 text-sm text-muted">서버 응답: {detail}</p>}
    </div>
  );
}
