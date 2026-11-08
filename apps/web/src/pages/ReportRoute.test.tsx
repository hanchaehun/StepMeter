import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { loadMockReport } from '@/api/mock';
import { clearAccessCode, getAccessCode, setAccessCode } from '@/api/client';
import { ReportRoute } from './ReportRoute';

// 명세 "상태 전환" 표: 불러오는 중 / 401 초대 코드 / 404 / 409(진행 중·리포트 없음) / 오류. 기대값은 목 JSON.
const mock = loadMockReport();
const BASE = 'http://api.test';

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
const progress = (over: Record<string, unknown> = {}) => json(200, { ...mock.report.run, latest_step: null, ...over });
const okSeq = () => [progress(), json(200, mock.report), json(200, mock.steps)];

function fetchSeq(responses: Array<Response | Error>) {
  const calls: string[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next ?? json(500, { detail: 'no more responses' });
  });
  return { impl, calls };
}

const at = (pathname: string, search = '') => ({ pathname, search });

beforeEach(() => {
  clearAccessCode();
  window.history.replaceState(null, '', '/');
});

test('목 모드: API 주소가 없으면 목 데이터로 바로 그린다', () => {
  render(<ReportRoute location={at('/runs/42')} baseUrl={null} />);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('러닝화 A를 장바구니에 담는다');
});

test('?mock=1이면 API 주소가 있어도 목 모드', () => {
  const { impl } = fetchSeq([]);
  render(<ReportRoute location={at('/runs/42', '?mock=1')} baseUrl={BASE} fetchImpl={impl} />);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('러닝화 A를 장바구니에 담는다');
  expect(impl).not.toHaveBeenCalled();
});

test('실제 모드: 불러오는 중 → 리포트. /runs/42에서 id를 읽고 과업 번호를 제목으로', async () => {
  setAccessCode('code-1');
  const { impl, calls } = fetchSeq(okSeq());
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  expect(screen.getByText('불러오는 중')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('과업 #7'));
  expect(calls[0]).toBe(`${BASE}/runs/42`);
  expect(screen.getByText('3회 중 2회 성공')).toBeInTheDocument();
});

test('주소에 run id가 없으면 안내', () => {
  render(<ReportRoute location={at('/')} baseUrl={BASE} fetchImpl={fetchSeq([]).impl} />);
  expect(screen.getByText(/측정 번호가 없습니다/)).toBeInTheDocument();
});

test('초대 코드가 없으면 입력 화면, 넣으면 저장하고 같은 run을 불러온다', async () => {
  const { impl, calls } = fetchSeq(okSeq());
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  expect(impl).not.toHaveBeenCalled();
  await userEvent.type(screen.getByLabelText('초대 코드'), 'code-1');
  await userEvent.click(screen.getByRole('button', { name: '확인' }));
  await waitFor(() => expect(screen.getByText('3회 중 2회 성공')).toBeInTheDocument());
  expect(getAccessCode()).toBe('code-1');
  expect(calls[0]).toBe(`${BASE}/runs/42`);
});

test('401이면 코드 입력 화면으로 돌아오고 틀렸다고 알린다', async () => {
  setAccessCode('bad');
  const { impl } = fetchSeq([json(401, { detail: 'invalid access code' }), ...okSeq()]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByLabelText('초대 코드')).toBeInTheDocument());
  expect(screen.getByText(/초대 코드가 맞지 않습니다/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText('초대 코드'), 'code-1');
  await userEvent.click(screen.getByRole('button', { name: '확인' }));
  await waitFor(() => expect(screen.getByText('3회 중 2회 성공')).toBeInTheDocument());
});

test('401이면 저장된 코드를 지운다 (새로고침마다 틀린 코드로 또 부르지 않게)', async () => {
  setAccessCode('bad');
  const { impl } = fetchSeq([json(401, { detail: 'invalid access code' })]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByLabelText('초대 코드')).toBeInTheDocument());
  expect(getAccessCode()).toBeNull();
  expect(screen.getByLabelText('초대 코드')).toHaveFocus();
});

test('404', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([json(404, { detail: 'run not found' })]);
  render(<ReportRoute location={at('/runs/999')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/측정 #999이\(가\) 없습니다/)).toBeInTheDocument());
});

test('409 진행 중(running): 아직 진행 중 안내 + 진행률', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([progress({ status: 'running', progress: 40 })]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/아직 진행 중입니다/)).toBeInTheDocument());
  expect(screen.getByText(/40%/)).toBeInTheDocument();
});

test('409 진행 중(queued): 대기열 문장', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([progress({ status: 'queued', progress: 0 })]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/대기열에 있습니다/)).toBeInTheDocument());
});

test('409 리포트 없음(canceled): 취소 문장', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([progress({ status: 'canceled' })]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/사용자가 취소한 측정입니다/)).toBeInTheDocument());
});

test('409 리포트 없음(failed)', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([progress({ status: 'failed' })]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/리포트가 없습니다/)).toBeInTheDocument());
  expect(screen.getByText(/failed/)).toBeInTheDocument();
});

test('500: 서버 오류 문장과 원문을 나눠 보여준다', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([json(500, { detail: 'db down' })]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/서버 오류가 났습니다 \(500\)/)).toBeInTheDocument());
  expect(screen.getByText(/원문: db down/)).toBeInTheDocument();
});

test('run id가 바뀌면 이전 run의 늦은 응답이 새 화면을 덮지 않는다', async () => {
  setAccessCode('c');
  let resolveFirst: (r: Response) => void = () => {};
  const first = new Promise<Response>((r) => (resolveFirst = r));
  const rest = okSeq();
  const impl = vi.fn(async (input: RequestInfo | URL) => (String(input).endsWith('/runs/41') ? first : (rest.shift() as Response)));
  const { rerender } = render(<ReportRoute location={at('/runs/41')} baseUrl={BASE} fetchImpl={impl} />);
  rerender(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('과업 #7'));
  resolveFirst(progress({ status: 'failed' })); // 41은 실패한 run: 그대로 반영되면 "리포트가 없습니다"가 떠야 한다
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByText(/리포트가 없습니다/)).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('과업 #7');
});

test('네트워크 오류: 오류 화면 + 다시 시도', async () => {
  setAccessCode('c');
  const { impl } = fetchSeq([new TypeError('Failed to fetch'), ...okSeq()]);
  render(<ReportRoute location={at('/runs/42')} baseUrl={BASE} fetchImpl={impl} />);
  await waitFor(() => expect(screen.getByText(/불러오지 못했습니다/)).toBeInTheDocument());
  expect(screen.getByText(/서버에 연결하지 못했습니다/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await waitFor(() => expect(screen.getByText('3회 중 2회 성공')).toBeInTheDocument());
});
