// 측정 목록(F11) 테스트.
// 기대값 근거: 요청 경로·순서는 ADR 0011 7번과 openapi.yaml(listProjects·listTasks·listTaskRuns, viewport 쿼리, created_at 내림차순),
// 표의 값은 src/api/mockServer.ts seedHistory의 예시 값을 사람이 읽어 옮겼다. 예상 소요 시간은 데스크톱만(개발계획서 5.10).
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, test } from 'vitest';
import { formatMetric, RunHistoryPage, runLink } from './RunHistoryPage';
import { createMockServer, type MockServer } from '@/api/mockServer';
import type { RunHistoryItem } from '@/api/history';

function setup(server: MockServer, search = '') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RunHistoryPage baseUrl="/api" search={search} fetchImpl={server.fetch} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const rowOf = (id: number) => screen.getByRole('rowheader', { name: `#${id}` }).closest('tr') as HTMLElement;

beforeEach(() => {
  window.sessionStorage.clear();
  window.sessionStorage.setItem('stepmeter.accessCode', 'code-1');
  window.history.replaceState(null, '', '/history');
});

test('지표 표기: 시간은 소수 한 자리 초, 클릭은 회, 이동은 반올림한 px에 천 단위 쉼표, 난이도는 bit', () => {
  expect(formatMetric('est_task_time', 24.6)).toBe('24.6초');
  expect(formatMetric('click_count', 7)).toBe('7회');
  expect(formatMetric('travel_distance', 3120.4)).toBe('3,120px');
  expect(formatMetric('fitts_id_sum', 18.3)).toBe('18.3 bit');
});

test('줄의 링크: 완료면 리포트, 대기·진행 중이면 진행 화면, 취소·오류면 상태 보기(진행 화면)', () => {
  const item = (status: RunHistoryItem['run']['status']) => ({ run: { id: 9, status } }) as RunHistoryItem;
  expect(runLink(item('completed'))).toEqual({ href: '/runs/9', label: '리포트' });
  expect(runLink(item('running'))).toEqual({ href: '/runs/9/progress', label: '진행 화면' });
  expect(runLink(item('queued'))).toEqual({ href: '/runs/9/progress', label: '진행 화면' });
  expect(runLink(item('canceled'))).toEqual({ href: '/runs/9/progress', label: '상태 보기' });
  expect(runLink(item('failed'), '?mock=1')).toEqual({ href: '/runs/9/progress?mock=1', label: '상태 보기' });
});

test('첫 프로젝트·첫 과업·데스크톱 측정을 최신순으로 보인다', async () => {
  const server = createMockServer('ok', 0, { seed: true });
  setup(server);
  await screen.findByRole('rowheader', { name: '#5' });
  expect(server.requests.map((r) => `${r.method} ${r.path}`)).toEqual([
    'GET /projects',
    'GET /projects/1/tasks',
    'GET /tasks/1/runs?viewport=desktop',
  ]);
  // 과업 1의 데스크톱 측정은 #1·#3·#4·#5, created_at 내림차순
  expect(screen.getAllByRole('rowheader').map((h) => h.textContent)).toEqual(['#5', '#4', '#3', '#1']);

  const r3 = within(rowOf(3));
  expect(r3.getByText('재측정')).toBeInTheDocument();
  expect(r3.getByText('1 / 1')).toBeInTheDocument();
  expect(r3.getByText('21.2초')).toBeInTheDocument();
  expect(r3.getByText('6회')).toBeInTheDocument();
  expect(r3.getByText('2,650px')).toBeInTheDocument();
  expect(r3.getByText('15.9 bit')).toBeInTheDocument();
  expect(r3.getByRole('link', { name: /리포트/ })).toHaveAttribute('href', '/runs/3');

  const r5 = within(rowOf(5));
  expect(r5.getByText('진행 중 45%')).toBeInTheDocument();
  expect(r5.getByRole('link', { name: /진행 화면/ })).toHaveAttribute('href', '/runs/5/progress');

  expect(screen.getByRole('columnheader', { name: '예상 소요 시간' })).toBeInTheDocument();
  expect(Object.fromEntries(new URLSearchParams(window.location.search))).toEqual({ project: '1', task: '1', viewport: 'desktop' });
});

test('모바일로 바꾸면 viewport=mobile로 다시 읽고 예상 소요 시간 열을 뺀다', async () => {
  const server = createMockServer('ok', 0, { seed: true });
  const user = setup(server);
  await screen.findByRole('rowheader', { name: '#5' });
  await user.click(screen.getByRole('radio', { name: '모바일' }));
  await screen.findByRole('rowheader', { name: '#2' });
  expect(server.requests.at(-1)?.path).toBe('/tasks/1/runs?viewport=mobile');
  expect(screen.getAllByRole('rowheader').map((h) => h.textContent)).toEqual(['#2']);
  expect(screen.queryByRole('columnheader', { name: '예상 소요 시간' })).not.toBeInTheDocument();
  expect(screen.getByText(/모바일은 예상 소요 시간을 계산하지 않습니다/)).toBeInTheDocument();
});

test('측정이 없는 과업을 고르면 빈 안내와 새 측정 링크', async () => {
  const server = createMockServer('ok', 0, { seed: true });
  const user = setup(server);
  await screen.findByRole('rowheader', { name: '#5' });
  await user.selectOptions(screen.getByLabelText('과업'), '2');
  expect(await screen.findByText('데스크톱으로 잰 측정이 없습니다')).toBeInTheDocument();
  expect(server.requests.at(-1)?.path).toBe('/tasks/2/runs?viewport=desktop');
});

test('주소의 project·task·viewport 값으로 시작한다', async () => {
  const server = createMockServer('ok', 0, { seed: true });
  setup(server, '?project=1&task=1&viewport=mobile');
  await screen.findByRole('rowheader', { name: '#2' });
  expect(screen.getByRole('radio', { name: '모바일' })).toBeChecked();
});

test('프로젝트가 없으면 아직 측정한 사이트가 없다고 쓴다', async () => {
  setup(createMockServer());
  expect(await screen.findByText('아직 측정한 사이트가 없습니다')).toBeInTheDocument();
});

test('401이면 저장된 초대 코드를 지우고 다시 묻는다', async () => {
  setup(createMockServer('unauthorized'));
  expect(await screen.findByText(/초대 코드가 맞지 않습니다/)).toBeInTheDocument();
  await waitFor(() => expect(window.sessionStorage.getItem('stepmeter.accessCode')).toBeNull());
});

// #75 UX 감사 F-10: 주석은 예상 소요 시간이 "—"인 경우를 그대로 적는다. 값은 측정이 끝날 때 성공한 시도로 만든 run 지표이고,
// 예상 시간 계산은 #78(2026-11-20)부터, 재생 재측정의 저장은 2026-11-23 커밋부터다(ADR 0011 10번)
test('F-10: 데스크톱 표 아래 주석이 "—"가 나오는 경우를 적고, 모바일에서는 그 줄이 없다', async () => {
  const server = createMockServer('ok', 0, { seed: true });
  const user = setup(server);
  await screen.findByRole('rowheader', { name: '#5' });
  expect(screen.getByText('· 예상 소요 시간은 데스크톱에서만 계산합니다. —는 값이 없는 경우입니다(아직 끝나지 않았거나 취소·실패한 측정, 성공한 시도가 없는 측정, 2026-11-20 이전 측정, 2026-11-23 이전의 재생 재측정).')).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: /모바일/ }));
  await screen.findByText('· 모바일은 예상 소요 시간을 계산하지 않습니다.');
  expect(screen.queryByText(/—는 값이 없는 경우입니다/)).toBeNull();
});

// 재생 재측정도 예상 소요 시간을 저장하면(2026-11-23 커밋) 그 줄에 숫자가 보인다. 목 예시 #3은 재생 1/1 성공, est_task_time 21.2초
test('F-10: 예상 소요 시간 값이 있는 재생 재측정 줄은 "—"가 아니라 숫자를 보인다', async () => {
  const server = createMockServer('ok', 0, { seed: true });
  setup(server);
  await screen.findByRole('rowheader', { name: '#5' });
  const r3 = within(rowOf(3));
  expect(r3.getByText('재측정')).toBeInTheDocument();
  expect(r3.getByText('1 / 1')).toBeInTheDocument();
  expect(r3.getByText('21.2초')).toBeInTheDocument();
  // 진행 중(#5)은 아직 값이 없어 "—"
  expect(within(rowOf(5)).getAllByText('—').length).toBeGreaterThan(0);
});
