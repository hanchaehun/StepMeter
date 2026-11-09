// 실제 API에서 리포트 데이터를 읽는다 (apps/api/openapi.yaml, PR #32).
// 순서: GET /runs/{id} → (completed일 때만) GET /runs/{id}/report → GET /runs/{id}/attempts/{n}/steps (대표 attempt).
// 과업 문장·사이트 주소를 주는 엔드포인트(GET /tasks/{id})가 아직 없어 task·project는 null로 둔다.
import type { components } from './types';
import type { ReportData, Report, Step } from './mock';

export type RunStatus = components['schemas']['RunStatus'];
type RunProgress = components['schemas']['RunProgress'];

const ACCESS_CODE_KEY = 'stepmeter.accessCode';

export class ApiError extends Error {
  status: number;
  detail: string;
  /** 409일 때 run 상태 (queued·running = 진행 중, failed·canceled = 리포트 없음). 그 밖에는 null */
  runStatus: RunStatus | null;
  /** 409일 때 GET /runs/{id} 응답 (진행률·최근 step을 안내 화면에 쓴다) */
  run: RunProgress | null;

  constructor(status: number, detail: string, runStatus: RunStatus | null = null, run: RunProgress | null = null) {
    super(`${status}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.runStatus = runStatus;
    this.run = run;
  }
}

interface Options {
  baseUrl: string;
  accessCode: string;
  fetchImpl?: typeof fetch;
  /** 화면이 바뀌어 응답이 필요 없어지면 abort한다 */
  signal?: AbortSignal;
}

async function getJson<T>(url: string, opts: Options): Promise<T> {
  const fetchImpl = opts.fetchImpl ?? fetch;
  const res = await fetchImpl(url, { headers: { Accept: 'application/json', 'X-Access-Code': opts.accessCode }, signal: opts.signal });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* 본문이 JSON이 아니면 statusText 사용 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export async function fetchReportData(runId: number, opts: Options): Promise<ReportData> {
  const base = opts.baseUrl.replace(/\/$/, '');
  const run = await getJson<RunProgress>(`${base}/runs/${runId}`, opts);
  if (run.status !== 'completed') {
    // API도 409를 주지만, 어떤 409인지(진행 중 vs 리포트 없음)를 run 상태로 먼저 가른다
    throw new ApiError(409, `run status is ${run.status}`, run.status, run);
  }
  let report: Report;
  try {
    report = await getJson<Report>(`${base}/runs/${runId}/report`, opts);
  } catch (e) {
    // 사전 확인 뒤에 API가 409 NotFinished를 주는 경우(명세 "상태 전환": 같은 처리). run 상태를 다시 읽어 어떤 409인지 가른다
    if (e instanceof ApiError && e.status === 409) {
      const again = await getJson<RunProgress>(`${base}/runs/${runId}`, opts);
      throw new ApiError(409, e.detail, again.status, again);
    }
    throw e;
  }
  const rep = report.run.representative_attempt_index;
  const steps = rep === null ? [] : await getJson<Step[]>(`${base}/runs/${runId}/attempts/${rep}/steps`, opts);
  return { report, steps, task: null, project: null };
}

export function getAccessCode(): string | null {
  try {
    return window.sessionStorage.getItem(ACCESS_CODE_KEY);
  } catch {
    return null;
  }
}

export function setAccessCode(code: string): void {
  try {
    window.sessionStorage.setItem(ACCESS_CODE_KEY, code);
  } catch {
    /* 비공개 창 등 저장 불가 */
  }
}

export function clearAccessCode(): void {
  try {
    window.sessionStorage.removeItem(ACCESS_CODE_KEY);
  } catch {
    /* ignore */
  }
}

/** 사용자에게 보일 오류 문장. 원문(detail)은 보조로 따로 보여준다. */
export function describeError(e: unknown): { message: string; detail: string } {
  if (e instanceof ApiError) {
    if (e.status >= 500) return { message: `서버 오류가 났습니다 (${e.status}). 잠시 뒤 다시 시도해 주세요.`, detail: e.detail };
    return { message: `서버가 요청을 거절했습니다 (${e.status}).`, detail: e.detail };
  }
  if (e instanceof DOMException && e.name === 'AbortError') return { message: '요청이 취소되었습니다.', detail: '' };
  return { message: '서버에 연결하지 못했습니다. API 서버가 켜져 있는지, 주소(VITE_API_URL)가 맞는지 확인해 주세요.', detail: e instanceof Error ? e.message : String(e) };
}

/** 빌드 시 `VITE_API_URL` (`/api`처럼 같은 출처 경로도 된다). 없으면 목 모드. */
export function apiBaseUrl(): string | null {
  const v = (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_API_URL;
  return v && v.trim() ? v.trim() : null;
}
