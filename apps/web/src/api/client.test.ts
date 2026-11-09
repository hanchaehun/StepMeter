import { loadMockReport } from './mock';
import { ApiError, clearAccessCode, describeError, fetchReportData, getAccessCode, setAccessCode } from './client';

// 응답 순서는 /runs/{id} → /runs/{id}/report → /runs/{id}/attempts/{n}/steps. 기대값은 목 JSON에서 사람이 읽은 값.
const mock = loadMockReport();
const BASE = 'http://api.test';

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function fetchSeq(responses: Array<Response | Error>) {
  const calls: Array<{ url: string; headers: Record<string, string> }> = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), headers: Object.fromEntries(new Headers(init?.headers).entries()) });
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next ?? json(500, { detail: 'no more responses' });
  });
  return { impl, calls };
}

describe('fetchReportData', () => {
  test('정상: 3번 호출, 초대 코드 헤더, 대표 attempt의 steps', async () => {
    const progress = { ...mock.report.run, latest_step: null };
    const { impl, calls } = fetchSeq([json(200, progress), json(200, mock.report), json(200, mock.steps)]);
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'code-1', fetchImpl: impl });
    expect(calls.map((c) => c.url)).toEqual([
      `${BASE}/runs/42`,
      `${BASE}/runs/42/report`,
      `${BASE}/runs/42/attempts/2/steps`, // representative_attempt_index 2
    ]);
    expect(calls.every((c) => c['headers']['x-access-code'] === 'code-1')).toBe(true);
    expect(data.report.run.id).toBe(42);
    expect(data.steps).toHaveLength(3);
    expect(data.task ?? null).toBeNull(); // GET /tasks/{id}가 없어 과업은 못 받는다
  });

  test('401 → ApiError 401, 더 부르지 않음', async () => {
    const { impl, calls } = fetchSeq([json(401, { detail: 'invalid access code' })]);
    await expect(fetchReportData(42, { baseUrl: BASE, accessCode: 'bad', fetchImpl: impl })).rejects.toMatchObject({ status: 401 });
    expect(calls).toHaveLength(1);
  });

  test('404 → ApiError 404', async () => {
    const { impl } = fetchSeq([json(404, { detail: 'run not found' })]);
    await expect(fetchReportData(999, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl })).rejects.toMatchObject({ status: 404 });
  });

  test('run이 running이면 리포트를 부르지 않고 409 + runStatus', async () => {
    const progress = { ...mock.report.run, status: 'running', progress: 40, latest_step: null };
    const { impl, calls } = fetchSeq([json(200, progress)]);
    const err = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.runStatus).toBe('running');
    expect(calls).toHaveLength(1);
  });

  test('failed run도 409 + runStatus failed', async () => {
    const progress = { ...mock.report.run, status: 'failed', latest_step: null };
    const { impl } = fetchSeq([json(200, progress)]);
    await expect(fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl })).rejects.toMatchObject({ status: 409, runStatus: 'failed' });
  });

  test('대표 경로가 없으면(전부 실패) steps를 부르지 않는다', async () => {
    const progress = { ...mock.report.run, latest_step: null, representative_attempt_index: null };
    const report = { ...mock.report, run: { ...mock.report.run, representative_attempt_index: null } };
    const { impl, calls } = fetchSeq([json(200, progress), json(200, report)]);
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl });
    expect(calls).toHaveLength(2);
    expect(data.steps).toEqual([]);
  });

  test('/report가 409를 주면 /runs/{id}를 다시 읽어 runStatus를 채운다 (명세: API 409도 같은 처리)', async () => {
    const completed = { ...mock.report.run, latest_step: null };
    const running = { ...mock.report.run, status: 'running', progress: 90, latest_step: null };
    const { impl, calls } = fetchSeq([json(200, completed), json(409, { detail: 'run not completed' }), json(200, running)]);
    const err = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl }).catch((e) => e);
    expect(err).toMatchObject({ status: 409, runStatus: 'running', detail: 'run not completed' });
    expect(err.run.progress).toBe(90);
    expect(calls.map((c) => c.url)).toEqual([`${BASE}/runs/42`, `${BASE}/runs/42/report`, `${BASE}/runs/42`]);
  });

  test('500 → ApiError 500 + 본문 detail', async () => {
    const { impl } = fetchSeq([json(500, { detail: 'db down' })]);
    await expect(fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl })).rejects.toMatchObject({ status: 500, detail: 'db down' });
  });

  test('fetch에 AbortSignal을 넘긴다', async () => {
    const ctrl = new AbortController();
    const impl = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.signal).toBe(ctrl.signal);
      return json(404, { detail: 'x' });
    });
    await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl, signal: ctrl.signal }).catch(() => {});
    expect(impl).toHaveBeenCalledTimes(1);
  });

  test('네트워크 오류는 그대로 던진다', async () => {
    const { impl } = fetchSeq([new TypeError('Failed to fetch')]);
    await expect(fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl })).rejects.toThrow('Failed to fetch');
  });
});

describe('describeError', () => {
  test('500은 서버 오류 문장 + 원문, 네트워크 오류는 연결 안내, 4xx는 거절 문장', () => {
    expect(describeError(new ApiError(500, 'db down'))).toEqual({ message: '서버 오류가 났습니다 (500). 잠시 뒤 다시 시도해 주세요.', detail: 'db down' });
    expect(describeError(new TypeError('Failed to fetch'))).toMatchObject({ message: expect.stringContaining('서버에 연결하지 못했습니다'), detail: 'Failed to fetch' });
    expect(describeError(new ApiError(422, 'bad id'))).toMatchObject({ message: '서버가 요청을 거절했습니다 (422).', detail: 'bad id' });
  });
});

describe('access code storage', () => {
  beforeEach(() => clearAccessCode());
  test('sessionStorage에 넣고 꺼낸다', () => {
    expect(getAccessCode()).toBeNull();
    setAccessCode('abc');
    expect(getAccessCode()).toBe('abc');
    expect(window.sessionStorage.getItem('stepmeter.accessCode')).toBe('abc');
    clearAccessCode();
    expect(getAccessCode()).toBeNull();
  });
});
