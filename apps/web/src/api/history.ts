// 측정 목록(F11): GET /projects → GET /projects/{id}/tasks → GET /tasks/{id}/runs?viewport= (ADR 0011 7번)
import type { components } from './types';
import { requestJson, type Options } from './client';

export type ProjectListItem = components['schemas']['ProjectListItem'];
export type Task = components['schemas']['Task'];
export type RunHistoryItem = components['schemas']['RunHistoryItem'];
export type ViewportPreset = components['schemas']['ViewportPreset'];

const base = (opts: Options) => opts.baseUrl.replace(/\/$/, '');

export function listProjects(opts: Options): Promise<ProjectListItem[]> {
  return requestJson('GET', `${base(opts)}/projects`, undefined, opts);
}

export function listTasks(projectId: number, opts: Options): Promise<Task[]> {
  return requestJson('GET', `${base(opts)}/projects/${projectId}/tasks`, undefined, opts);
}

/** 같은 뷰포트끼리만 비교한다 (7.1). created_at 내림차순 */
export function listTaskRuns(taskId: number, viewport: ViewportPreset, opts: Options): Promise<RunHistoryItem[]> {
  return requestJson('GET', `${base(opts)}/tasks/${taskId}/runs?viewport=${viewport}`, undefined, opts);
}
