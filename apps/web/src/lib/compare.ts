// 비교 결과 → 화면 문장. 전부 순수 함수. 판정은 다시 계산하지 않고 API의 verdict를 그대로 쓴다 (#82 2번).
// 판정 기준(threshold)의 뜻은 개발계획서 7.4 표: 재생 비교의 클릭 수는 "+1 이상"(회 단위), 나머지는 변화율.
import type { Comparison, MetricChange } from '@/api/compare';

/** 비교 엔진이 판정하는 지표 (#82: 클릭 수·커서 이동·예상 소요 시간). 나머지는 참고 지표(판정 안 함) */
export const JUDGED_KEYS = ['click_count', 'travel_distance', 'est_task_time'] as const;

/** 지표 이름. 리포트의 MoreMetrics와 같은 이름을 쓴다(리포트 파일을 건드리지 않으려고 따로 둔다) */
export const METRIC_LABEL: Record<string, string> = {
  est_task_time: '예상 소요 시간',
  click_count: '클릭 수',
  type_count: '입력 수',
  step_count: '단계 수',
  back_count: '뒤로 가기 수',
  no_response_click_count: '무반응 클릭 수',
  repeated_click_count: '반복 클릭 수',
  page_transition_count: '페이지 전환 수',
  travel_distance: '커서 이동 거리',
  scroll_distance: '스크롤 거리',
  fitts_id_sum: '이동 난이도 합',
};

const ORDER = [...JUDGED_KEYS, ...Object.keys(METRIC_LABEL).filter((k) => !(JUDGED_KEYS as readonly string[]).includes(k))];

export function metricLabel(key: string): string {
  return METRIC_LABEL[key] ?? key;
}

/** 판정 지표(정해진 순서)와 참고 지표(나머지)로 나눈다. 모르는 key는 참고 지표 끝에 둔다 */
export function splitMetrics(changes: MetricChange[]): { judged: MetricChange[]; reference: MetricChange[] } {
  const rank = (k: string) => (ORDER.indexOf(k) === -1 ? ORDER.length : ORDER.indexOf(k));
  const sorted = [...changes].sort((a, b) => rank(a.key) - rank(b.key));
  const isJudged = (k: string) => (JUDGED_KEYS as readonly string[]).includes(k);
  return { judged: sorted.filter((c) => isJudged(c.key)), reference: sorted.filter((c) => !isJudged(c.key)) };
}

/** 지표 값 + 단위. 횟수는 정수 "회", 거리는 반올림 px, 시간은 소수 1자리 초, 난이도는 소수 1자리 bit */
export function formatMetricValue(key: string, v: number | null): string {
  if (v === null) return '—';
  if (key === 'est_task_time') return `${v.toFixed(1)}초`;
  if (key === 'travel_distance' || key === 'scroll_distance') return `${Math.round(v).toLocaleString('ko-KR')}px`;
  if (key === 'fitts_id_sum') return `${v.toFixed(1)} bit`;
  return `${Number.isInteger(v) ? v : v.toFixed(1)}회`;
}

/** 변화율 0.23 → "+23%", -0.06 → "-6%", 0 → "0%", null → "—" */
export function formatRate(rate: number | null): string {
  if (rate === null) return '—';
  const pct = Math.round(rate * 100);
  return `${pct > 0 ? '+' : ''}${pct}%`;
}

/** 판정 기준. 재생 비교의 클릭 수는 회 단위(개발계획서 7.4 "+1 이상"), 그 밖은 변화율. null이면 null */
export function thresholdText(c: MetricChange, kind: 'replay' | 'agent'): string | null {
  if (c.threshold === null) return null;
  if (kind === 'replay' && c.key === 'click_count') return `±${formatNumber(c.threshold)}회`;
  return `±${Math.round(c.threshold * 100)}%`;
}

function formatNumber(v: number): string {
  return String(Number(v.toFixed(1)));
}

export interface VerdictView {
  /** 색만으로 전하지 않는다: 기호 + 문구 */
  symbol: string;
  text: string;
  tone: 'worse' | 'better' | 'neutral';
}

/** #82 2번: not_comparable이거나 threshold가 null이면 "비교 불가". 나머지는 verdict 그대로 */
export function verdictView(c: MetricChange): VerdictView {
  if (c.verdict === 'not_comparable' || c.threshold === null) return { symbol: '', text: '비교 불가', tone: 'neutral' };
  if (c.verdict === 'worse') return { symbol: '▲', text: '악화', tone: 'worse' };
  if (c.verdict === 'better') return { symbol: '▼', text: '개선', tone: 'better' };
  return { symbol: '=', text: '변화 없음', tone: 'neutral' };
}

/** 변화 칸. 판정 기준과 같은 단위로 쓴다: 재생 비교의 클릭 수는 회 차이("+1회"), 그 밖은 변화율("+23%") */
export function changeText(c: MetricChange, kind: 'replay' | 'agent'): string {
  if (kind === 'replay' && c.key === 'click_count') {
    if (c.base === null || c.target === null) return '—';
    const d = c.target - c.base;
    return `${d > 0 ? '+' : ''}${formatNumber(d)}회`;
  }
  return formatRate(c.change_rate);
}
/** 재생이 끊긴 지점. 끝까지 재생됐거나 지점이 없으면 null. 표기는 리포트와 같은 "Step N" */
export function divergedText(replay: Comparison['replay']): string | null {
  if (!replay || replay.replay_status !== 'partial' || replay.diverged_at_step === null) return null;
  return `Step ${replay.diverged_at_step}에서 경로가 바뀜`;
}

/** 경로 정렬: 추가·삭제된 단계 개수만 (#82 1번) */
export function alignmentCounts(rows: Comparison['path_alignment']): { added: number; removed: number } {
  return {
    added: rows.filter((r) => r.op === 'added').length,
    removed: rows.filter((r) => r.op === 'removed').length,
  };
}

/** 목록에서 고른 두 측정 → base(먼저 만든 것)·target (#82 3번) */
export function orderPair<T extends { id: number; created_at: string }>(a: T, b: T): { base: T; target: T } {
  const aFirst = a.created_at < b.created_at || (a.created_at === b.created_at && a.id < b.id);
  return aFirst ? { base: a, target: b } : { base: b, target: a };
}
