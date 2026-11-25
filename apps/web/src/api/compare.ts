// 비교 화면(F07): GET /compare?base=&target= (openapi compareRuns). 409는 과업·뷰포트가 다르거나 끝나지 않은 측정이다.
import type { components } from './types';
import { requestJson, type Options } from './client';

export type Comparison = components['schemas']['Comparison'];
export type MetricChange = components['schemas']['MetricChange'];

export function fetchComparison(base: number, target: number, opts: Options): Promise<Comparison> {
  return requestJson<Comparison>('GET', `${opts.baseUrl.replace(/\/$/, '')}/compare?base=${base}&target=${target}`, undefined, opts);
}
