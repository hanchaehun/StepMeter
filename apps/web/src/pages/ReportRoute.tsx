import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, clearAccessCode, describeError, fetchReportData, fetchSteps, getAccessCode, setAccessCode, type RunStatus } from '@/api/client';
import type { ReportData } from '@/api/mock';
import { variant } from '@/fixtures/variants';
import { ReportPage } from './ReportPage';
import { AccessCodeView, ErrorView, LoadingView, NoRunIdView, NotFinishedView, NotFoundView } from '@/components/report/ReportStatus';

/**
 * 주소를 읽어 목 모드/실제 모드를 고르고, 실제 모드에서는 상태별 화면을 거쳐 ReportPage를 그린다.
 * - 목 모드: API 주소가 없거나 ?mock=1. ?variant=로 상태 변형.
 * - 실제 모드: /runs/{id} → 초대 코드 → GET /runs/{id} → report → steps.
 * 라우터 라이브러리는 아직 쓰지 않는다(대시보드 UI와 합의 전). 주소 해석은 여기 한 곳.
 */
interface Props {
  location: { pathname: string; search: string };
  baseUrl: string | null;
  fetchImpl?: typeof fetch;
}

type State =
  | { kind: 'need-code'; wrong: boolean }
  | { kind: 'loading' }
  | { kind: 'ready'; data: ReportData }
  | { kind: 'not-found' }
  | { kind: 'not-finished'; status: RunStatus; progress: number | null }
  | { kind: 'error'; message: string; detail: string };

export function runIdFromPath(pathname: string): number | null {
  const m = /^\/runs\/(\d+)\/?$/.exec(pathname);
  return m ? Number(m[1]) : null;
}

export function ReportRoute({ location, baseUrl, fetchImpl }: Props) {
  const params = new URLSearchParams(location.search);
  const mockMode = baseUrl === null || params.get('mock') === '1';
  const runId = runIdFromPath(location.pathname);

  const [state, setState] = useState<State>(() => (getAccessCode() ? { kind: 'loading' } : { kind: 'need-code', wrong: false }));
  // 진행 중인 요청. 새 요청을 시작하거나 화면을 떠나면 abort해서, 늦게 온 응답이 새 화면을 덮지 않게 한다
  const inflight = useRef<AbortController | null>(null);

  const load = useCallback(
    async (id: number, code: string) => {
      inflight.current?.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      setState({ kind: 'loading' });
      try {
        const data = await fetchReportData(id, { baseUrl: baseUrl ?? '', accessCode: code, fetchImpl, signal: ctrl.signal });
        if (ctrl.signal.aborted) return;
        setState({ kind: 'ready', data });
      } catch (e) {
        if (ctrl.signal.aborted) return;
        if (e instanceof ApiError) {
          if (e.status === 401) {
            clearAccessCode(); // 틀린 코드를 세션에 남기지 않는다
            return setState({ kind: 'need-code', wrong: true });
          }
          if (e.status === 404) return setState({ kind: 'not-found' });
          if (e.status === 409 && e.runStatus) return setState({ kind: 'not-finished', status: e.runStatus, progress: e.run?.progress ?? null });
        }
        setState({ kind: 'error', ...describeError(e) });
      }
    },
    [baseUrl, fetchImpl],
  );

  // 스크린샷 서명 URL(900초, 이슈 #51)이 만료됐을 때: 대표 attempt의 steps만 다시 받아 새 주소로 바꾼다.
  // 리포트 전체를 다시 불러오지 않으므로 화면이 "불러오는 중"으로 돌아가지 않고 보던 단계에 머문다. 실패하면 그대로 둔다
  const reloadSteps = useCallback(
    async (id: number, data: ReportData) => {
      const rep = data.report.run.representative_attempt_index;
      const code = getAccessCode();
      if (rep === null || !code) return;
      try {
        const steps = await fetchSteps(id, rep, { baseUrl: baseUrl ?? '', accessCode: code, fetchImpl });
        setState((s) => (s.kind === 'ready' && s.data === data ? { kind: 'ready', data: { ...data, steps } } : s));
      } catch {
        /* 다시 깨지면 같은 "다시 불러오기"가 다시 보인다 */
      }
    },
    [baseUrl, fetchImpl],
  );

  useEffect(() => {
    if (mockMode || runId === null) return;
    const code = getAccessCode();
    if (code) void load(runId, code);
    // StrictMode의 이중 effect, run id 변경: 이전 요청은 취소한다
    return () => inflight.current?.abort();
  }, [mockMode, runId, load]);

  if (mockMode) return <ReportPage data={variant(params.get('variant'))} />;
  if (runId === null) return <NoRunIdView />;

  switch (state.kind) {
    case 'need-code':
      return (
        <AccessCodeView
          wrong={state.wrong}
          onSubmit={(code) => {
            setAccessCode(code);
            void load(runId, code);
          }}
        />
      );
    case 'loading':
      return <LoadingView runId={runId} />;
    case 'ready':
      return <ReportPage data={state.data} onReloadSteps={() => void reloadSteps(runId, state.data)} />;
    case 'not-found':
      return <NotFoundView runId={runId} />;
    case 'not-finished':
      return <NotFinishedView runId={runId} status={state.status} progress={state.progress} />;
    case 'error':
      return (
        <ErrorView
          message={state.message}
          detail={state.detail}
          onRetry={() => {
            const code = getAccessCode();
            if (code) void load(runId, code);
            else setState({ kind: 'need-code', wrong: false }); // 저장이 막힌 브라우저: 빈 헤더로 보내지 않고 다시 묻는다
          }}
        />
      );
  }
}
