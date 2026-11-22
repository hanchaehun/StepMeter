// 측정 생성 화면(F01) 테스트.
// 기대값 근거: 요청 경로·본문은 apps/api/openapi.yaml(createProject·createTask·createRun, RunCreate 기본값),
// 상태 전환·오류 문구는 docs/wireframes/f01-measure-create.md, 과업 안내는 ADR 0011 1번, 상한은 Project.daily_run_limit 기본 10.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, test, vi } from 'vitest';
import { MeasureCreatePage, MESSAGES, TASK_EXAMPLES, validate } from './MeasureCreatePage';
import { createMockServer, type MockServer } from '@/api/mockServer';

function setup(server: MockServer, opts: { mock?: boolean } = {}) {
  const navigate = vi.fn();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MeasureCreatePage baseUrl={opts.mock ? null : '/api'} fetchImpl={server.fetch} navigate={navigate} />
    </QueryClientProvider>,
  );
  return { navigate, user: userEvent.setup() };
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.sessionStorage.setItem('stepmeter.accessCode', 'code-1');
});

test('주소 검사: http(s)://로 시작해야 하고 과업은 공백만이면 거절', () => {
  expect(validate('example.com', '가입한다').url).toBe(MESSAGES.url);
  expect(validate('ftp://example.com', '가입한다').url).toBe(MESSAGES.url);
  expect(validate('https://', '가입한다').url).toBe(MESSAGES.url);
  expect(validate('https://example.com', '   ').description).toBe(MESSAGES.description);
  expect(validate('http://localhost:5173/signup', '가입한다')).toEqual({});
});

test('빈 폼으로 제출하면 두 칸에 오류, 남은 항목 수, 첫 오류 칸으로 포커스, 요청 없음', async () => {
  const server = createMockServer();
  const { user } = setup(server);
  await user.click(screen.getByRole('button', { name: '측정 시작' }));
  expect(screen.getByText(MESSAGES.url)).toBeInTheDocument();
  expect(screen.getByText(MESSAGES.description)).toBeInTheDocument();
  expect(screen.getByText(/고칠 항목 2개/)).toBeInTheDocument();
  expect(screen.getByLabelText('측정할 주소')).toHaveFocus();
  expect(screen.getByLabelText('측정할 주소')).toHaveAttribute('aria-describedby', 'm-url-err');
  expect(server.requests).toHaveLength(0);
});

test('과업 칸 옆에 가짜 값 안내가 있고 과업 칸과 연결된다 (ADR 0011 1번)', () => {
  setup(createMockServer());
  const hint = screen.getByText(/실제 계정 정보는 적지 않습니다/);
  expect(screen.getByLabelText('과업').getAttribute('aria-describedby')).toContain(hint.id);
});

test('첫 측정: 프로젝트·과업을 만들고 mode=agent, 반복 3회·데스크톱으로 요청한 뒤 /runs/{id}로 이동', async () => {
  const server = createMockServer();
  const { user, navigate } = setup(server);
  await user.type(screen.getByLabelText('측정할 주소'), 'https://shop.example.com');
  await user.type(screen.getByLabelText('과업'), '장바구니에 상품을 담는다');
  await user.click(screen.getByRole('button', { name: '측정 시작' }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/runs/1'));
  expect(server.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
    'GET /projects',
    'POST /projects',
    'GET /projects/1/tasks',
    'POST /projects/1/tasks',
    'POST /tasks/1/runs',
  ]);
  expect(server.requests[1].body).toEqual({ name: 'shop.example.com', base_url: 'https://shop.example.com' });
  expect(server.requests[3].body).toEqual({ description: '장바구니에 상품을 담는다', success_condition: null });
  expect(server.requests[4].body).toEqual({ viewport: 'desktop', repeat_n: 3, mode: 'agent' });
});

test('성공 조건·모바일·5회를 고르면 그대로 보낸다', async () => {
  const server = createMockServer();
  const { user, navigate } = setup(server);
  await user.type(screen.getByLabelText('측정할 주소'), 'https://example.com');
  await user.type(screen.getByLabelText('과업'), '가입한다');
  await user.type(screen.getByLabelText('화면에 보이는 문구'), '환영합니다');
  await user.click(screen.getByRole('radio', { name: /모바일/ }));
  await user.click(screen.getByText('고급 설정 — 측정 신뢰도 높이기'));
  await user.click(screen.getByRole('radio', { name: /반복 5회/ }));
  await user.click(screen.getByRole('button', { name: '측정 시작' }));

  await waitFor(() => expect(navigate).toHaveBeenCalled());
  expect(server.requests[3].body).toEqual({ description: '가입한다', success_condition: { text_present: '환영합니다' } });
  expect(server.requests[4].body).toEqual({ viewport: 'mobile', repeat_n: 5, mode: 'agent' });
});

test('같은 주소·과업이고 같은 화면 크기의 완료 측정이 있으면 프로젝트·과업을 다시 쓰고 mode를 생략(auto)', async () => {
  const server = createMockServer();
  server.projects.push({ id: 7, name: 'example.com', base_url: 'https://example.com/', daily_run_limit: 10, created_at: '2026-11-19T00:00:00Z' });
  server.tasks.push({ id: 3, project_id: 7, description: '가입한다', success_condition: null });
  server.runs.push(completedRun(1, 3));
  // 목 서버는 run id를 runs 길이 + 1로 준다
  const { user, navigate } = setup(server);
  await user.type(screen.getByLabelText('측정할 주소'), 'https://example.com');
  await user.type(screen.getByLabelText('과업'), '가입한다');
  await user.click(screen.getByRole('button', { name: '측정 시작' }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/runs/2'));
  expect(server.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
    'GET /projects',
    'GET /projects/7/tasks',
    'GET /tasks/3/runs?viewport=desktop',
    'POST /tasks/3/runs',
  ]);
  expect(server.requests[3].body).toEqual({ viewport: 'desktop', repeat_n: 3 });
});

test('예시 칩: 빈 칸이면 바로 넣고, 적어 둔 과업이 있으면 바꿀지 묻는다', async () => {
  const { user } = setup(createMockServer());
  const desc = screen.getByLabelText('과업');
  await user.click(screen.getByRole('button', { name: TASK_EXAMPLES[1].label }));
  expect(desc).toHaveValue(TASK_EXAMPLES[1].text);

  await user.click(screen.getByRole('button', { name: TASK_EXAMPLES[2].label }));
  expect(screen.getByText('적어 둔 과업을 예시 문장으로 바꿀까요?')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '그대로 두기' }));
  expect(desc).toHaveValue(TASK_EXAMPLES[1].text);

  await user.click(screen.getByRole('button', { name: TASK_EXAMPLES[2].label }));
  await user.click(screen.getByRole('button', { name: '바꾸기' }));
  expect(desc).toHaveValue(TASK_EXAMPLES[2].text);
});

test('예상 시간 근거가 없으면 숫자 대신 이유를 보이고, 모바일은 시간 추정이 없다고 쓴다', async () => {
  const { user } = setup(createMockServer());
  expect(screen.getByText('예상 소요 시간은 추정 근거를 준비하고 있습니다.')).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: /모바일/ }));
  expect(screen.getByText(/모바일은 시간 추정을 제공하지 않습니다/)).toBeInTheDocument();
});

test('초대 코드가 없으면 코드부터 묻는다', () => {
  window.sessionStorage.clear();
  setup(createMockServer());
  expect(screen.getByRole('heading', { name: '초대 코드를 입력하세요' })).toBeInTheDocument();
});

test('401이면 코드를 지우고 다시 묻고, 입력값은 남긴 채 새 코드로 다시 보낸다', async () => {
  const server = createMockServer();
  const realFetch = server.fetch;
  let first = true;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (first) {
      first = false;
      return new Response(JSON.stringify({ detail: 'invalid access code' }), { status: 401 });
    }
    return realFetch(input, init);
  }) as typeof fetch;
  const { user, navigate } = setup({ ...server, fetch: fetchImpl });
  await user.type(screen.getByLabelText('측정할 주소'), 'https://example.com');
  await user.type(screen.getByLabelText('과업'), '가입한다');
  await user.click(screen.getByRole('button', { name: '측정 시작' }));

  expect(await screen.findByText(/초대 코드가 맞지 않습니다/)).toBeInTheDocument();
  expect(window.sessionStorage.getItem('stepmeter.accessCode')).toBeNull();
  await user.type(screen.getByLabelText('초대 코드'), 'code-2');
  await user.click(screen.getByRole('button', { name: '확인' }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/runs/1'));
  expect(window.sessionStorage.getItem('stepmeter.accessCode')).toBe('code-2');
});

test('429: 상한 회수를 쓰고, 끝난 측정이 없으면 재생만 하기를 주지 않는다', async () => {
  const server = createMockServer('limit');
  const { user, navigate } = setup(server);
  await user.type(screen.getByLabelText('측정할 주소'), 'https://example.com');
  await user.type(screen.getByLabelText('과업'), '가입한다');
  await user.click(screen.getByRole('button', { name: '측정 시작' }));

  expect(await screen.findByText('오늘 측정 상한(10회)을 넘었습니다')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '재생만 하기' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('과업')).toHaveValue('가입한다');
  expect(navigate).not.toHaveBeenCalled();
});

test('429: 끝난 측정이 있으면 재생만 하기로 replay_only를 보낸다 (상한에 세지 않음)', async () => {
  const server = createMockServer('limit');
  server.projects.push({ id: 1, name: 'example.com', base_url: 'https://example.com/', daily_run_limit: 10, created_at: '2026-11-19T00:00:00Z' });
  server.tasks.push({ id: 1, project_id: 1, description: '가입한다', success_condition: null });
  server.runs.push(completedRun(1, 1));
  const { user, navigate } = setup(server);
  await user.type(screen.getByLabelText('측정할 주소'), 'https://example.com');
  await user.type(screen.getByLabelText('과업'), '가입한다');
  await user.click(screen.getByRole('button', { name: '측정 시작' }));
  await user.click(await screen.findByRole('button', { name: '재생만 하기' }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/runs/2'));
  expect(server.requests.at(-1)).toEqual({
    method: 'POST',
    path: '/tasks/1/runs',
    body: { viewport: 'desktop', mode: 'replay_only', base_run_id: 1 },
  });
});

test('목 모드에서는 이동 주소에 ?mock=1을 붙인다', async () => {
  const { user, navigate } = setup(createMockServer(), { mock: true });
  await user.type(screen.getByLabelText('측정할 주소'), 'https://example.com');
  await user.type(screen.getByLabelText('과업'), '가입한다');
  await user.click(screen.getByRole('button', { name: '측정 시작' }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/runs/1?mock=1'));
});

function completedRun(id: number, taskId: number) {
  return {
    id,
    task_id: taskId,
    viewport: 'desktop' as const,
    mode: 'agent' as const,
    base_run_id: null,
    repeat_n: 3,
    model: 'claude-haiku-5-5' as const,
    prompt_version: 'v1',
    status: 'completed' as const,
    progress: 100,
    cost_usd: 0,
    created_at: '2026-11-19T00:00:00Z',
    started_at: '2026-11-19T00:00:00Z',
    finished_at: '2026-11-19T00:05:00Z',
    representative_attempt_index: 1,
  };
}
