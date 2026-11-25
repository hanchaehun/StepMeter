// 측정 생성 화면의 목 API (백엔드 없이 개발할 때와 테스트에서 쓴다). fetch와 같은 모양이다.
// 경로와 응답 형식은 apps/api/openapi.yaml을 따른다. 상태는 만든 객체 안에만 있다.
// scenario: 'ok' | 'unauthorized'(항상 401) | 'limit'(POST /tasks/{id}/runs가 429, replay_only는 통과)
import comparisonJson from '@mock/comparison.json';
import type { components } from './types';

type Project = components['schemas']['Project'];
type Task = components['schemas']['Task'];
type Run = components['schemas']['Run'];
type RunHistoryItem = components['schemas']['RunHistoryItem'];
type RunProgress = components['schemas']['RunProgress'];
type Comparison = components['schemas']['Comparison'];

export type MockScenario = 'ok' | 'unauthorized' | 'limit';

export interface MockServer {
  fetch: typeof fetch;
  projects: Project[];
  tasks: Task[];
  runs: Run[];
  /** 받은 요청 기록 (테스트 확인용) */
  requests: Array<{ method: string; path: string; body: unknown }>;
}

const NOW = '2026-11-20T00:00:00Z';

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export interface MockOptions {
  /** GET /runs/{id}에 없는 id가 오면 진행 중인 측정을 만들어 준다 (진행 화면을 목 모드로 열 때) */
  autoRun?: boolean;
  /** GET /runs/{id}를 부를 때마다 진행을 한 칸 앞으로 (queued → running 15…90 → completed 100) */
  advance?: boolean;
  /** 측정 목록 화면을 목 모드로 볼 때 쓸 이력(프로젝트 1개, 과업 2개, 측정 5개)을 미리 넣는다 */
  seed?: boolean;
}

type Metric = components['schemas']['Metric'];
const history = new WeakMap<Run, { success: number; attempts: number; metrics: Metric[] }>();

function metric(key: string, value: number, unit: string): Metric {
  return { key, value, unit, spread: 0.08, spread_quality: 'ok', model_version_id: null };
}

/** 목 이력. 값은 화면 모양을 보기 위한 예시다 */
function seedHistory(s: MockServer) {
  s.projects.push({ id: 1, name: 'shop.example.com', base_url: 'https://shop.example.com/', daily_run_limit: 10, created_at: '2026-11-18T01:00:00Z' });
  s.tasks.push(
    { id: 1, project_id: 1, description: '장바구니에 상품 하나를 담고 결제 화면까지 간다', success_condition: { url_contains: '/checkout' } },
    { id: 2, project_id: 1, description: '가장 싼 요금제를 찾아 신청 화면까지 간다', success_condition: null },
  );
  const base = { task_id: 1, base_run_id: null, model: 'claude-haiku-5-5' as const, prompt_version: 'v3', cost_usd: 0.012, representative_attempt_index: 1 };
  const rows: Array<[Run, { success: number; attempts: number; metrics: Metric[] }]> = [
    [{ ...base, id: 1, viewport: 'desktop', mode: 'agent', repeat_n: 3, status: 'completed', progress: 100, created_at: '2026-11-18T02:00:00Z', started_at: '2026-11-18T02:00:03Z', finished_at: '2026-11-18T02:04:30Z' },
      { success: 3, attempts: 3, metrics: [metric('est_task_time', 24.6, 's'), metric('click_count', 7, 'count'), metric('travel_distance', 3120.4, 'px'), metric('fitts_id_sum', 18.3, 'bit')] }],
    [{ ...base, id: 2, viewport: 'mobile', mode: 'agent', repeat_n: 3, status: 'completed', progress: 100, created_at: '2026-11-18T03:00:00Z', started_at: '2026-11-18T03:00:02Z', finished_at: '2026-11-18T03:05:10Z' },
      { success: 2, attempts: 3, metrics: [metric('click_count', 8, 'count'), metric('travel_distance', 980, 'px'), metric('fitts_id_sum', 15.1, 'bit')] }],
    [{ ...base, id: 3, viewport: 'desktop', mode: 'auto', base_run_id: 1, repeat_n: 3, status: 'completed', progress: 100, created_at: '2026-11-20T05:00:00Z', started_at: '2026-11-20T05:00:04Z', finished_at: '2026-11-20T05:01:40Z' },
      { success: 1, attempts: 1, metrics: [metric('est_task_time', 21.2, 's'), metric('click_count', 6, 'count'), metric('travel_distance', 2650, 'px'), metric('fitts_id_sum', 15.9, 'bit')] }],
    [{ ...base, id: 4, viewport: 'desktop', mode: 'auto', base_run_id: 3, repeat_n: 3, status: 'canceled', progress: 30, created_at: '2026-11-21T06:00:00Z', started_at: '2026-11-21T06:00:05Z', finished_at: '2026-11-21T06:01:00Z', representative_attempt_index: null },
      { success: 0, attempts: 0, metrics: [] }],
    [{ ...base, id: 5, viewport: 'desktop', mode: 'auto', base_run_id: 3, repeat_n: 3, status: 'running', progress: 45, created_at: '2026-11-22T07:00:00Z', started_at: '2026-11-22T07:00:03Z', finished_at: null, representative_attempt_index: null },
      { success: 0, attempts: 0, metrics: [] }],
  ];
  for (const [r, h] of rows) {
    s.runs.push(r);
    history.set(r, h);
  }
}

/** 진행 화면 목 모드에서 보여 줄 판단 문장 */
const DEMO_THOUGHTS = [
  '첫 화면에서 회원가입 버튼을 찾았습니다. 눌러서 가입 양식으로 이동합니다.',
  '이름 칸에 과업에 적힌 값 Minsu Kim을 입력합니다.',
  '이메일 칸에 study@example.com을 입력합니다.',
  '비밀번호 칸에 과업에 적힌 값을 입력합니다.',
  '가입 버튼이 화면 아래에 있어 스크롤합니다.',
  'Register Account 버튼을 누릅니다.',
];

const latest = new WeakMap<Run, RunProgress['latest_step']>();

function addDemoRun(s: MockServer, id: number): Run {
  const r: Run = {
    id, task_id: 1, viewport: 'desktop', mode: 'agent', base_run_id: null, repeat_n: 3, model: 'claude-haiku-5-5',
    prompt_version: null, status: 'queued', progress: 0, cost_usd: 0, created_at: NOW, started_at: null, finished_at: null,
    representative_attempt_index: null,
  };
  s.runs.push(r);
  return r;
}

function advanceDemo(r: Run) {
  if (r.status === 'queued') {
    r.status = 'running';
    r.started_at = NOW;
    r.prompt_version = 'v3';
    return;
  }
  if (r.status !== 'running') return;
  // 실행 중 진행률은 최대 90, 후처리가 끝나야 100 (docs/worker_api_spec.md 2번)
  if (r.progress >= 90) {
    r.progress = 100;
    r.status = 'completed';
    r.finished_at = NOW;
    r.representative_attempt_index = 1;
    return;
  }
  r.progress = Math.min(90, r.progress + 15);
  const n = Math.round(r.progress / 15);
  r.cost_usd = Math.round(n * 0.002 * 1000) / 1000;
  latest.set(r, { attempt_index: (n % r.repeat_n) + 1, idx: n, screenshot_url: null, thought: DEMO_THOUGHTS[n % DEMO_THOUGHTS.length] });
}

function progressOf(r: Run): RunProgress {
  return { ...r, latest_step: latest.get(r) ?? null };
}

export function createMockServer(scenario: MockScenario = 'ok', delayMs = 0, opts: MockOptions = {}): MockServer {
  const s: MockServer = { fetch: undefined as unknown as typeof fetch, projects: [], tasks: [], runs: [], requests: [] };

  if (opts.seed) seedHistory(s);

  const handle = (method: string, path: string, body: Record<string, unknown> | null, query: URLSearchParams): Response => {
    if (scenario === 'unauthorized') return json({ detail: 'invalid access code' }, 401);
    let m: RegExpExecArray | null;
    if (path === '/projects' && method === 'GET') return json(s.projects, 200);
    if (path === '/projects' && method === 'POST') {
      const p: Project = { id: s.projects.length + 1, name: String(body?.name), base_url: String(body?.base_url), daily_run_limit: 10, created_at: NOW };
      s.projects.push(p);
      return json(p, 201);
    }
    if ((m = /^\/projects\/(\d+)\/tasks$/.exec(path))) {
      const projectId = Number(m[1]);
      if (!s.projects.some((p) => p.id === projectId)) return json({ detail: 'not found' }, 404);
      if (method === 'GET') return json(s.tasks.filter((t) => t.project_id === projectId), 200);
      const t: Task = {
        id: s.tasks.length + 1,
        project_id: projectId,
        description: String(body?.description),
        success_condition: (body?.success_condition as Task['success_condition']) ?? null,
      };
      s.tasks.push(t);
      return json(t, 201);
    }
    if ((m = /^\/tasks\/(\d+)\/runs$/.exec(path))) {
      const taskId = Number(m[1]);
      if (!s.tasks.some((t) => t.id === taskId)) return json({ detail: 'not found' }, 404);
      if (method === 'GET') {
        const vp = query.get('viewport');
        const items: RunHistoryItem[] = s.runs
          .filter((r) => r.task_id === taskId && (!vp || r.viewport === vp))
          .sort((a, b) => b.created_at.localeCompare(a.created_at)) // created_at 내림차순 (openapi listTaskRuns)
          .map((run) => {
            const h = history.get(run);
            return { run, success_count: h?.success ?? 0, attempt_count: h?.attempts ?? 0, metrics: h?.metrics ?? [] };
          });
        return json(items, 200);
      }
      const mode = (body?.mode as Run['mode']) ?? 'auto';
      if (scenario === 'limit' && mode !== 'replay_only') return json({ detail: 'daily run limit exceeded' }, 429);
      const r: Run = {
        id: s.runs.length + 1,
        task_id: taskId,
        viewport: (body?.viewport as Run['viewport']) ?? 'desktop',
        mode,
        base_run_id: (body?.base_run_id as number | null) ?? null,
        repeat_n: (body?.repeat_n as number) ?? 3,
        model: 'claude-haiku-5-5',
        prompt_version: null,
        status: 'queued',
        progress: 0,
        cost_usd: 0,
        created_at: NOW,
        started_at: null,
        finished_at: null,
        representative_attempt_index: null,
      };
      s.runs.push(r);
      return json(r, 202);
    }
    if ((m = /^\/runs\/(\d+)$/.exec(path)) && method === 'GET') {
      const run = s.runs.find((r) => r.id === Number(m![1])) ?? (opts.autoRun ? addDemoRun(s, Number(m[1])) : null);
      if (!run) return json({ detail: 'not found' }, 404);
      if (opts.advance) advanceDemo(run);
      return json(progressOf(run), 200);
    }
    if (path === '/compare' && method === 'GET') {
      // 아는 측정끼리면 API처럼 확인한다(완료·같은 과업·같은 뷰포트가 아니면 409). 모르는 번호(데모 리포트 #41·#42 등)는
      // 목 JSON(tests/fixtures/mock/api/comparison.json)을 번호만 바꿔 돌려준다
      const baseId = Number(query.get('base'));
      const targetId = Number(query.get('target'));
      const a = s.runs.find((r) => r.id === baseId);
      const b = s.runs.find((r) => r.id === targetId);
      if (a && b) {
        if (a.status !== 'completed' || b.status !== 'completed') return json({ detail: 'both runs must be completed' }, 409);
        if (a.task_id !== b.task_id || a.viewport !== b.viewport) return json({ detail: 'runs differ in task or viewport' }, 409);
      }
      const c = structuredClone(comparisonJson) as Comparison;
      return json({ ...c, base_run_id: baseId, target_run_id: targetId }, 200);
    }
    if ((m = /^\/runs\/(\d+)\/cancel$/.exec(path)) && method === 'POST') {
      const run = s.runs.find((r) => r.id === Number(m![1]));
      if (!run) return json({ detail: 'not found' }, 404);
      if (run.status !== 'queued' && run.status !== 'running') return json({ detail: `run is already ${run.status}` }, 409);
      // 명세(docs/worker_api_spec.md 1번 "취소"): API가 바로 canceled·finished_at으로 바꾼다
      run.status = 'canceled';
      run.finished_at = NOW;
      return json(run, 202);
    }
    return json({ detail: 'not found' }, 404);
  };

  s.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://mock.local');
    const path = url.pathname.replace(/^\/api/, '');
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    s.requests.push({ method, path: path + url.search, body });
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    return handle(method, path, body, url.searchParams);
  }) as typeof fetch;

  return s;
}
