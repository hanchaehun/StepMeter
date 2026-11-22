// 측정 생성 화면의 목 API (백엔드 없이 개발할 때와 테스트에서 쓴다). fetch와 같은 모양이다.
// 경로와 응답 형식은 apps/api/openapi.yaml을 따른다. 상태는 만든 객체 안에만 있다.
// scenario: 'ok' | 'unauthorized'(항상 401) | 'limit'(POST /tasks/{id}/runs가 429, replay_only는 통과)
import type { components } from './types';

type Project = components['schemas']['Project'];
type Task = components['schemas']['Task'];
type Run = components['schemas']['Run'];
type RunHistoryItem = components['schemas']['RunHistoryItem'];

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

export function createMockServer(scenario: MockScenario = 'ok', delayMs = 0): MockServer {
  const s: MockServer = { fetch: undefined as unknown as typeof fetch, projects: [], tasks: [], runs: [], requests: [] };

  const handle = (method: string, path: string, body: Record<string, unknown> | null): Response => {
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
        const items: RunHistoryItem[] = s.runs
          .filter((r) => r.task_id === taskId)
          .map((run) => ({ run, success_count: 0, attempt_count: 0, metrics: [] }));
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
    return json({ detail: 'not found' }, 404);
  };

  s.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://mock.local');
    const path = url.pathname.replace(/^\/api/, '');
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    s.requests.push({ method, path: path + url.search, body });
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    return handle(method, path, body);
  }) as typeof fetch;

  return s;
}
