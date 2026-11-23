// 측정 진행(F02): GET /runs/{id}를 2초마다 읽고(2.2), 취소는 POST /runs/{id}/cancel.
import type { components } from './types';
import { requestJson, type Options } from './client';

export type RunProgress = components['schemas']['RunProgress'];
type Run = components['schemas']['Run'];

export function fetchRunProgress(runId: number, opts: Options): Promise<RunProgress> {
  return requestJson<RunProgress>('GET', `${opts.baseUrl.replace(/\/$/, '')}/runs/${runId}`, undefined, opts);
}

/** 202면 바뀐 Run. 이미 끝난 측정이면 409 (ApiError) */
export function cancelRun(runId: number, opts: Options): Promise<Run> {
  return requestJson<Run>('POST', `${opts.baseUrl.replace(/\/$/, '')}/runs/${runId}/cancel`, undefined, opts);
}

/** 더 읽을 필요가 없는 상태 */
export function isFinished(status: RunProgress['status']): boolean {
  return status === 'completed' || status === 'failed' || status === 'canceled';
}
