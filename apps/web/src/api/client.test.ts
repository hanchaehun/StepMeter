import taskJson from '@mock/task.json';
import projectsJson from '@mock/projects.json';
import { loadMockReport } from './mock';
import { ApiError, clearAccessCode, describeError, fetchReportData, getAccessCode, normalizeAccessCode, setAccessCode } from './client';

// 순서: /runs/{id} → /runs/{id}/report → (동시에) steps·/tasks/{task_id}·/projects. 기대값은 목 JSON에서 사람이 읽은 값.
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

/** 주소별로 응답한다(과업·프로젝트·steps는 동시에 부르므로 순서에 기대지 않는다). 없는 주소는 404 */
function fetchRoutes(routes: Record<string, () => Response | Error>) {
  const calls: Array<{ url: string; headers: Record<string, string> }> = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, headers: Object.fromEntries(new Headers(init?.headers).entries()) });
    const route = routes[url];
    const res = route ? route() : json(404, { detail: 'not found' });
    if (res instanceof Error) throw res;
    return res;
  });
  return { impl, calls };
}

const completedRun = { ...mock.report.run, latest_step: null };

describe('fetchReportData', () => {
  test('정상: run·report·steps·과업·프로젝트 목록, 모두 초대 코드 헤더', async () => {
    const { impl, calls } = fetchRoutes({
      [`${BASE}/runs/42`]: () => json(200, completedRun),
      [`${BASE}/runs/42/report`]: () => json(200, mock.report),
      [`${BASE}/runs/42/attempts/2/steps`]: () => json(200, mock.steps), // representative_attempt_index 2
      [`${BASE}/tasks/7`]: () => json(200, taskJson), // report.run.task_id 7
      [`${BASE}/projects`]: () => json(200, projectsJson),
    });
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'code-1', fetchImpl: impl });
    expect(calls.map((c) => c.url).sort()).toEqual(
      [`${BASE}/runs/42`, `${BASE}/runs/42/report`, `${BASE}/runs/42/attempts/2/steps`, `${BASE}/tasks/7`, `${BASE}/projects`].sort(),
    );
    expect(calls.every((c) => c['headers']['x-access-code'] === 'code-1')).toBe(true);
    expect(data.report.run.id).toBe(42);
    expect(data.steps).toHaveLength(3);
    // task.json: "러닝화 A를 장바구니에 담는다", project_id 1 → projects.json 1번 "https://shop.example"
    expect(data.task?.description).toBe('러닝화 A를 장바구니에 담는다');
    expect(data.project?.base_url).toBe('https://shop.example');
  });

  test('과업 조회가 실패해도(404) 리포트는 열고 과업·프로젝트는 null', async () => {
    const { impl } = fetchRoutes({
      [`${BASE}/runs/42`]: () => json(200, completedRun),
      [`${BASE}/runs/42/report`]: () => json(200, mock.report),
      [`${BASE}/runs/42/attempts/2/steps`]: () => json(200, mock.steps),
      [`${BASE}/projects`]: () => json(200, projectsJson),
    });
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl });
    expect(data.steps).toHaveLength(3);
    expect(data.task).toBeNull();
    expect(data.project).toBeNull();
  });

  test('프로젝트 목록에 과업의 프로젝트가 없으면(다른 초대 코드의 프로젝트) 과업만', async () => {
    const { impl } = fetchRoutes({
      [`${BASE}/runs/42`]: () => json(200, completedRun),
      [`${BASE}/runs/42/report`]: () => json(200, mock.report),
      [`${BASE}/runs/42/attempts/2/steps`]: () => json(200, mock.steps),
      [`${BASE}/tasks/7`]: () => json(200, taskJson),
      [`${BASE}/projects`]: () => json(200, projectsJson.filter((p) => p.id !== 1)),
    });
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl });
    expect(data.task?.id).toBe(7);
    expect(data.project).toBeNull();
  });

  test('프로젝트 목록이 네트워크 오류여도 리포트와 과업은 연다', async () => {
    const { impl } = fetchRoutes({
      [`${BASE}/runs/42`]: () => json(200, completedRun),
      [`${BASE}/runs/42/report`]: () => json(200, mock.report),
      [`${BASE}/runs/42/attempts/2/steps`]: () => json(200, mock.steps),
      [`${BASE}/tasks/7`]: () => json(200, taskJson),
      [`${BASE}/projects`]: () => new TypeError('Failed to fetch'),
    });
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl });
    expect(data.task?.id).toBe(7);
    expect(data.project).toBeNull();
  });

  test('steps가 실패하면 리포트 전체가 실패한다 (과업 조회와 달리 보조 정보가 아니다)', async () => {
    const { impl } = fetchRoutes({
      [`${BASE}/runs/42`]: () => json(200, completedRun),
      [`${BASE}/runs/42/report`]: () => json(200, mock.report),
      [`${BASE}/runs/42/attempts/2/steps`]: () => json(500, { detail: 'db down' }),
      [`${BASE}/tasks/7`]: () => json(200, taskJson),
      [`${BASE}/projects`]: () => json(200, projectsJson),
    });
    await expect(fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl })).rejects.toMatchObject({ status: 500 });
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
    const { impl, calls } = fetchRoutes({
      [`${BASE}/runs/42`]: () => json(200, progress),
      [`${BASE}/runs/42/report`]: () => json(200, report),
      [`${BASE}/tasks/7`]: () => json(200, taskJson),
      [`${BASE}/projects`]: () => json(200, projectsJson),
    });
    const data = await fetchReportData(42, { baseUrl: BASE, accessCode: 'c', fetchImpl: impl });
    expect(calls.some((c) => c.url.includes('/steps'))).toBe(false);
    expect(data.steps).toEqual([]);
    expect(data.task?.id).toBe(7); // 성공한 시도가 없어도 제목은 과업 문장
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

// 브라우저 fetch는 헤더 값에 ISO-8859-1 밖 글자가 있으면 TypeError를 던진다(Fetch 명세 header value).
// 초대 코드는 인쇄 가능한 ASCII(0x20~0x7E)만 받는다. 기대값은 입력 문자열을 사람이 보고 정했다.
describe('normalizeAccessCode', () => {
  test('앞뒤 공백, 붙여넣기로 따라온 제로폭 공백·BOM은 뗀다', () => {
    expect(normalizeAccessCode('  code-1  ')).toBe('code-1');
    expect(normalizeAccessCode('​code-1﻿')).toBe('code-1');
    expect(normalizeAccessCode('code‍-1')).toBe('code-1');
  });
  test('한글·둥근 따옴표·전각 문자가 섞이면 null', () => {
    expect(normalizeAccessCode('챙ㄷ-1')).toBeNull();
    expect(normalizeAccessCode('“code-1”')).toBeNull(); // “code-1”
    expect(normalizeAccessCode('ｃｏｄｅ')).toBeNull();
  });
  test('비었으면 null', () => {
    expect(normalizeAccessCode('   ')).toBeNull();
    expect(normalizeAccessCode('​')).toBeNull();
  });
});

test('저장된 코드가 보낼 수 없는 글자면 getAccessCode는 null을 주고 지운다', () => {
  window.sessionStorage.setItem('stepmeter.accessCode', '챙ㄷ-1');
  expect(getAccessCode()).toBeNull();
  expect(window.sessionStorage.getItem('stepmeter.accessCode')).toBeNull();
});
