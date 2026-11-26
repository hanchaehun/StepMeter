// 측정 생성(F01) 요청 순서. API는 project → task → run 세 단계라 화면 입력 하나를 이 순서로 나눠 보낸다.
// 1. GET /projects에서 같은 주소(base_url)의 프로젝트를 찾고, 없으면 POST /projects (이름은 주소의 호스트)
// 2. GET /projects/{id}/tasks에서 과업 문장·성공 조건이 같은 과업을 찾고, 없으면 POST /projects/{id}/tasks
//    같은 과업을 다시 쓰는 이유: 측정 이력(F11)과 비교(F07)가 과업 단위로 묶인다 (7.1)
// 3. POST /tasks/{id}/runs. 같은 과업·뷰포트에 완료된 측정이 있으면 mode 생략(서버 기본 auto = 재측정),
//    없으면 mode=agent. 기준 run이 없는데 auto로 보내면 재생할 경로가 없다 (#72 참고)
//    #72 임시 회피: 가장 최근 완료 측정에 대표 경로(representative_attempt_index)가 없으면 서버가 그 run을
//    기준으로 골라 auto 재측정이 failed로 끝난다. 그래서 그때도 mode=agent로 보내고 재생만 하기도 주지 않는다.
//    워커가 "대표 경로가 없으면 에이전트로 측정"(#72 제안 2)을 고치면 latestUsableBase의 대표 경로 검사를 지워 되돌린다.
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
type LlmModel = components['schemas']['LlmModel'];
export type SuccessCondition = components['schemas']['SuccessCondition'];
export type ViewportPreset = components['schemas']['ViewportPreset'];

// 측정 모델: 외부 테스트·홀드아웃·발표 측정은 Sonnet. #76 결정, API 기본값은 Haiku(openapi 동결)라 화면이 model을 보낸다.
// 재생 전용(createReplayOnly)은 LLM을 쓰지 않아 보내지 않는다
const MEASURE_MODEL: LlmModel = 'claude-sonnet-5-5';

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
  /** 같은 과업·뷰포트의 가장 최근 완료 측정(대표 경로가 있을 때만, #72). 있으면 재생만 하기(replay_only, 상한에 안 셈)를 보낼 수 있다 */
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

/** 서버가 기준으로 고를 run(같은 뷰포트의 가장 최근 완료 측정)이 재생할 경로를 가졌으면 그 번호, 아니면 null.
 *  history는 GET /tasks/{id}/runs 응답이라 최신순이다.
 *  #72 임시 회피: 대표 경로가 없으면 null로 돌려 mode=agent로 보내고 재생만 하기를 숨긴다 */
export function latestUsableBase(history: RunHistoryItem[], viewport: ViewportPreset): number | null {
  const latest = history.find((h) => h.run.status === 'completed' && h.run.viewport === viewport)?.run;
  if (!latest) return null;
  if (latest.representative_attempt_index === null) return null; // #72
  return latest.id;
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
    baseRunId = latestUsableBase(history, input.viewport);
  } else {
    const body: TaskCreate = { description: input.description, success_condition: input.successCondition };
    task = await requestJson<Task>('POST', `${base}/projects/${project.id}/tasks`, body, opts);
  }

  const runBody: RunCreate = { viewport: input.viewport, repeat_n: input.repeatN, model: MEASURE_MODEL };
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
