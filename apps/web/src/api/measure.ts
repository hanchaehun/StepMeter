// 측정 생성(F01) 요청 순서. API는 project → task → run 세 단계라 화면 입력 하나를 이 순서로 나눠 보낸다.
// 1. GET /projects에서 같은 주소(base_url)의 프로젝트를 찾고, 없으면 POST /projects (이름은 주소의 호스트)
// 2. GET /projects/{id}/tasks에서 과업 문장·성공 조건이 같은 과업을 찾고, 없으면 POST /projects/{id}/tasks
//    같은 과업을 다시 쓰는 이유: 측정 이력(F11)과 비교(F07)가 과업 단위로 묶인다 (7.1)
// 3. POST /tasks/{id}/runs. 같은 과업·뷰포트에 완료된 측정이 있으면 mode 생략(서버 기본 auto = 재측정),
//    없으면 mode=agent. 기준 run이 없는데 auto로 보내면 재생할 경로가 없다 (#72 참고)
import type { components } from './types';
import { ApiError, requestJson, type Options } from './client';

type Project = components['schemas']['Project'];
type ProjectCreate = components['schemas']['ProjectCreate'];
type Task = components['schemas']['Task'];
type TaskCreate = components['schemas']['TaskCreate'];
type Run = components['schemas']['Run'];
// 생성 타입은 default가 있는 칸도 필수로 만든다. API는 생략을 받으므로(기본값 적용) 요청 본문은 Partial로 쓴다
type RunCreate = Partial<components['schemas']['RunCreate']>;
type RunHistoryItem = components['schemas']['RunHistoryItem'];
export type SuccessCondition = components['schemas']['SuccessCondition'];
export type ViewportPreset = components['schemas']['ViewportPreset'];

export interface MeasureInput {
  url: string;
  description: string;
  successCondition: SuccessCondition | null;
  viewport: ViewportPreset;
  repeatN: 3 | 5;
}

export interface MeasureCreated {
  run: Run;
  project: Project;
  task: Task;
}

/** 429(당일 상한 초과). 안내 문구에 상한값을 쓰고, 재생만 하기를 줄 수 있는지 함께 넘긴다 */
export class DailyLimitError extends Error {
  project: Project;
  task: Task;
  /** 같은 과업·뷰포트의 완료 측정. 있으면 재생만 하기(replay_only, 상한에 안 셈)를 보낼 수 있다 */
  baseRunId: number | null;
  detail: string;

  constructor(project: Project, task: Task, baseRunId: number | null, detail: string) {
    super(`429: ${detail}`);
    this.name = 'DailyLimitError';
    this.project = project;
    this.task = task;
    this.baseRunId = baseRunId;
    this.detail = detail;
  }
}

/** 주소 비교용. 서버가 끝의 /를 붙여 돌려줄 수 있어 URL 파서로 맞춘다 */
export function sameUrl(a: string, b: string): boolean {
  try {
    return new URL(a).href === new URL(b).href;
  } catch {
    return a === b;
  }
}

function sameCondition(a: SuccessCondition | null, b: SuccessCondition | null): boolean {
  return (a?.url_contains ?? null) === (b?.url_contains ?? null) && (a?.text_present ?? null) === (b?.text_present ?? null);
}

export async function createMeasurement(input: MeasureInput, opts: Options): Promise<MeasureCreated> {
  const base = opts.baseUrl.replace(/\/$/, '');

  const projects = await requestJson<Project[]>('GET', `${base}/projects`, undefined, opts);
  let project = projects.find((p) => sameUrl(p.base_url, input.url));
  if (!project) {
    const body: ProjectCreate = { name: new URL(input.url).host.slice(0, 100), base_url: input.url };
    project = await requestJson<Project>('POST', `${base}/projects`, body, opts);
  }

  const tasks = await requestJson<Task[]>('GET', `${base}/projects/${project.id}/tasks`, undefined, opts);
  let task = tasks.find((t) => t.description === input.description && sameCondition(t.success_condition, input.successCondition));
  let baseRunId: number | null = null;
  if (task) {
    const history = await requestJson<RunHistoryItem[]>('GET', `${base}/tasks/${task.id}/runs?viewport=${input.viewport}`, undefined, opts);
    baseRunId = history.find((h) => h.run.status === 'completed' && h.run.viewport === input.viewport)?.run.id ?? null;
  } else {
    const body: TaskCreate = { description: input.description, success_condition: input.successCondition };
    task = await requestJson<Task>('POST', `${base}/projects/${project.id}/tasks`, body, opts);
  }

  const runBody: RunCreate = { viewport: input.viewport, repeat_n: input.repeatN };
  if (baseRunId === null) runBody.mode = 'agent';
  try {
    const run = await requestJson<Run>('POST', `${base}/tasks/${task.id}/runs`, runBody, opts);
    return { run, project, task };
  } catch (e) {
    if (e instanceof ApiError && e.status === 429) throw new DailyLimitError(project, task, baseRunId, e.detail);
    throw e;
  }
}

/** 상한 초과 뒤 "재생만 하기". replay_only는 일일 상한에 세지 않는다 (F17) */
export async function createReplayOnly(taskId: number, baseRunId: number, viewport: ViewportPreset, opts: Options): Promise<Run> {
  const base = opts.baseUrl.replace(/\/$/, '');
  const body: RunCreate = { viewport, mode: 'replay_only', base_run_id: baseRunId };
  return requestJson<Run>('POST', `${base}/tasks/${taskId}/runs`, body, opts);
}
