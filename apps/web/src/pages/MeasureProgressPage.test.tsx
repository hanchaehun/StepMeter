// 측정 진행 화면(F02) 테스트.
// 기대값 근거: 상태 값·RunProgress 형식은 apps/api/openapi.yaml, 실행 중 진행률 최대 90·후처리 뒤 100과
// 취소 즉시 canceled는 docs/worker_api_spec.md 1·2번, 화면 요소(진행 단계·현재 스크린샷·최근 판단 한 줄·취소)는 서비스 기획서 6.1.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, test } from 'vitest';
import { MeasureProgressPage, stageOf } from './MeasureProgressPage';
import type { RunProgress } from '@/api/progress';

function run(over: Partial<RunProgress> = {}): RunProgress {
  return {
    id: 7, task_id: 1, viewport: 'desktop', mode: 'agent', base_run_id: null, repeat_n: 3, model: 'claude-haiku-5-5',
    prompt_version: 'v3', status: 'running', progress: 45, cost_usd: 0.012, created_at: '2026-11-22T00:00:00Z',
    started_at: '2026-11-22T00:00:05Z', finished_at: null, representative_attempt_index: null, latest_step: null, ...over,
  };
}

/** GET /runs/7은 responses를 차례로 주고 마지막 것을 반복한다. POST /runs/7/cancel은 cancelResponse */
function fakeApi(responses: Array<[number, unknown]>, cancelResponse: [number, unknown] = [202, run({ status: 'canceled' })]) {
  const calls: string[] = [];
  let i = 0;
  let canceled = false;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const path = String(input);
    calls.push(`${method} ${path}`);
    if (method === 'POST' && path === '/api/runs/7/cancel') {
      canceled = cancelResponse[0] === 202;
      return new Response(JSON.stringify(cancelResponse[1]), { status: cancelResponse[0] });
    }
    if (canceled) return new Response(JSON.stringify(run({ status: 'canceled' })), { status: 200 });
    const [status, body] = responses[Math.min(i, responses.length - 1)];
    i += 1;
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  return { fetchImpl, calls };
}

function setup(fetchImpl: typeof fetch) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MeasureProgressPage runId={7} baseUrl="/api" fetchImpl={fetchImpl} pollMs={20} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.sessionStorage.setItem('stepmeter.accessCode', 'code-1');
});

test('진행 단계: queued=대기, running 90 미만=과업 수행, 90 이상=결과 정리, completed=완료, 실패·취소는 단계 없음', () => {
  expect(stageOf({ status: 'queued', progress: 0 })).toBe(0);
  expect(stageOf({ status: 'running', progress: 89 })).toBe(1);
  expect(stageOf({ status: 'running', progress: 90 })).toBe(2);
  expect(stageOf({ status: 'completed', progress: 100 })).toBe(3);
  expect(stageOf({ status: 'failed', progress: 40 })).toBeNull();
  expect(stageOf({ status: 'canceled', progress: 40 })).toBeNull();
});

test('실행 중: 진행률, 현재 단계, 최근 판단 한 줄과 시도 번호를 보인다', async () => {
  const latest = { attempt_index: 2, idx: 4, screenshot_url: null, thought: '가입 버튼을 누릅니다.' };
  const { fetchImpl } = fakeApi([[200, run({ latest_step: latest })]]);
  setup(fetchImpl);
  expect(await screen.findByText('가입 버튼을 누릅니다.')).toBeInTheDocument();
  // idx는 0부터라 화면에는 단계 5로 보인다
  expect(screen.getByText(/시도 2 \/ 3, 단계 5/)).toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: '진행률' })).toHaveAttribute('aria-valuenow', '45');
  expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('과업 수행 (지금)');
});

test('2초 간격 폴링으로 queued → running → completed를 따라가고, 끝나면 더 읽지 않는다', async () => {
  const { fetchImpl, calls } = fakeApi([
    [200, run({ status: 'queued', progress: 0, started_at: null })],
    [200, run({ status: 'running', progress: 30 })],
    [200, run({ status: 'completed', progress: 100, finished_at: '2026-11-22T00:05:00Z', representative_attempt_index: 1 })],
  ]);
  setup(fetchImpl);
  expect(await screen.findByText('대기열에 있습니다')).toBeInTheDocument();
  expect(await screen.findByText('측정이 끝났습니다')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '리포트 보기' })).toHaveAttribute('href', '/runs/7');
  expect(screen.queryByRole('button', { name: '측정 취소' })).not.toBeInTheDocument();
  const n = calls.length;
  await new Promise((r) => setTimeout(r, 100));
  expect(calls.length).toBe(n);
  expect(calls.every((c) => c === 'GET /api/runs/7')).toBe(true);
});

test('취소: 한 번 더 묻고 POST /runs/{id}/cancel을 보낸 뒤 취소됨을 보인다', async () => {
  const { fetchImpl, calls } = fakeApi([[200, run()]]);
  const user = setup(fetchImpl);
  await user.click(await screen.findByRole('button', { name: '측정 취소' }));
  expect(screen.getByText(/측정을 취소할까요\?/)).toBeInTheDocument();
  expect(calls).not.toContain('POST /api/runs/7/cancel');
  await user.click(screen.getByRole('button', { name: '측정 취소' }));
  expect(await screen.findByText('측정을 취소했습니다')).toBeInTheDocument();
  expect(calls).toContain('POST /api/runs/7/cancel');
});

test('취소 확인에서 계속 측정을 누르면 요청하지 않는다', async () => {
  const { fetchImpl, calls } = fakeApi([[200, run()]]);
  const user = setup(fetchImpl);
  await user.click(await screen.findByRole('button', { name: '측정 취소' }));
  await user.click(screen.getByRole('button', { name: '계속 측정' }));
  expect(screen.queryByText(/측정을 취소할까요\?/)).not.toBeInTheDocument();
  expect(calls).not.toContain('POST /api/runs/7/cancel');
});

test('failed: 서비스 오류 안내와 다시 측정 링크', async () => {
  const { fetchImpl } = fakeApi([[200, run({ status: 'failed', finished_at: '2026-11-22T00:01:00Z' })]]);
  setup(fetchImpl);
  expect(await screen.findByText(/서비스 오류로 측정을 마치지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '다시 측정' })).toHaveAttribute('href', '/new');
});

test('401: 저장된 초대 코드를 지우고 다시 묻는다', async () => {
  const { fetchImpl } = fakeApi([[401, { detail: 'invalid access code' }]]);
  setup(fetchImpl);
  expect(await screen.findByText(/초대 코드가 맞지 않습니다/)).toBeInTheDocument();
  await waitFor(() => expect(window.sessionStorage.getItem('stepmeter.accessCode')).toBeNull());
});

test('404: 측정을 찾지 못했다고 쓰고 폴링을 멈춘다', async () => {
  const { fetchImpl, calls } = fakeApi([[404, { detail: 'not found' }]]);
  setup(fetchImpl);
  expect(await screen.findByText('측정 #7을(를) 찾지 못했습니다')).toBeInTheDocument();
  const n = calls.length;
  await new Promise((r) => setTimeout(r, 100));
  expect(calls.length).toBe(n);
});
