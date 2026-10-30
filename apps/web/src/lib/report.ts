// 리포트 데이터 → 화면 문장·숫자 변환. 전부 순수 함수. 표기 규칙은 docs/wireframes/f06-report.md "데이터 출처" 표.
import type { Attempt, Issue, Metric, Report, Step } from '@/api/mock';
import { RULES, RULE_IDS, isRuleId, type RuleId, type TitleCtx } from './rules';

const ROLE_KO: Record<string, string> = {
  button: '버튼',
  link: '링크',
  textbox: '입력칸',
  combobox: '선택 상자',
  checkbox: '체크박스',
  radio: '라디오',
  menuitem: '메뉴 항목',
  tab: '탭',
};

/** element_key `tag|role|name|label_text|landmark` → "구매 버튼". name 비면 role, 둘 다 비면 "요소". */
export function elementLabel(elementKey: string | null): string {
  if (elementKey === null) return '요소 없음';
  const [, role = '', name = ''] = elementKey.split('|');
  const roleKo = ROLE_KO[role];
  if (name) return roleKo ? `${name} ${roleKo}` : name;
  return roleKo ?? '요소';
}

export function verdictText(report: Report): { main: string; estimated: boolean } {
  const ok = report.attempts.filter((a) => a.success);
  return {
    main: `${report.run.repeat_n}회 중 ${ok.length}회 성공`,
    estimated: ok.some((a) => a.success_estimated),
  };
}

function ruleOf(issue: Issue): RuleId {
  return isRuleId(issue.rule_id) ? issue.rule_id : 'R09';
}

function titleCtx(issue: Issue, steps: Step[]): TitleCtx {
  const ctx: TitleCtx = {
    element: elementLabel(issue.element_key),
    measured: issue.measured,
    threshold: issue.threshold,
  };
  const step = issue.step ? steps.find((s) => s.idx === issue.step!.idx) : undefined;
  const snap = step?.element_snapshot;
  if (snap?.occluder) {
    const { tag, name } = snap.occluder;
    ctx.occluder = name ? name : `이름 없는 ${tag}`;
  }
  if (snap?.bbox) ctx.size = { w: snap.bbox.width, h: snap.bbox.height };
  return ctx;
}

export function issueTitle(issue: Issue, steps: Step[]): string {
  return RULES[ruleOf(issue)].title(titleCtx(issue, steps));
}

export function issueMeasure(issue: Issue): string | null {
  const rule = RULES[ruleOf(issue)];
  if (!rule.measure) return null;
  return rule.measure({ element: '', measured: issue.measured, threshold: issue.threshold });
}

export function ruleName(issue: Issue): string {
  return RULES[ruleOf(issue)].name;
}

export interface MetricTile {
  key: string;
  label: string;
  value: string;
  unit: string;
  note: string;
}

const TILE_ORDER: Array<{ key: string; label: string; unit: string }> = [
  { key: 'est_task_time', label: '예상 소요 시간', unit: 's' },
  { key: 'click_count', label: '클릭', unit: 'clicks' },
  { key: 'travel_distance', label: '커서 이동', unit: 'px' },
  { key: 'fitts_id_sum', label: '이동 난이도', unit: 'bit' },
];

export function spreadText(m: Metric): string {
  return m.spread === null ? '' : `편차 ±${Math.round(m.spread * 100)}%`;
}

/** Overview 타일. 값은 소수 1자리까지, 정수형(px)은 Math.round. 모바일은 예상 시간 자리에 대체 문구. */
export function metricTiles(report: Report): MetricTile[] {
  const mobile = report.run.viewport === 'mobile';
  return TILE_ORDER.map(({ key, label, unit }) => {
    const m = report.metrics.find((x) => x.key === key);
    if (key === 'est_task_time') {
      if (mobile || !m) return { key, label, value: '—', unit: '', note: '예상 시간은 데스크톱에서만' };
      return { key, label, value: fmt(m.value, 1), unit, note: m.model_version_id === null ? '보정 전' : '사람 실험 보정' };
    }
    if (!m) return { key, label, value: '—', unit: '', note: '값 없음' };
    const value = key === 'travel_distance' ? String(Math.round(m.value)) : fmt(m.value, 1);
    return { key, label, value, unit, note: spreadText(m) };
  });
}

function fmt(v: number, digits: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(digits);
}

export function spreadQualityText(q: Metric['spread_quality']): string {
  switch (q) {
    case 'weak':
      return '추정 약함';
    case 'pooled':
      return '이력 기준';
    default:
      return '';
  }
}

const END_REASON_KO: Record<Attempt['end_reason'], string> = {
  success: '성공',
  gave_up: '포기',
  loop: '반복 루프',
  budget_exceeded: '30단계 초과',
  blocked: '차단됨',
  error: '오류',
  safety_stop: '위험 행동 직전 멈춤',
};

export function endReasonText(a: Attempt): string {
  const parts: string[] = [];
  if (a.kind === 'replay' && a.replay_status === 'partial' && a.diverged_at_step !== null) {
    parts.push(`Step ${a.diverged_at_step}에서 끊김`);
  }
  parts.push(END_REASON_KO[a.end_reason]);
  if (a.end_detail && a.end_reason !== 'success' && a.end_reason !== 'budget_exceeded') {
    parts.push(`"${a.end_detail}"`);
  }
  return parts.join(' · ');
}

export interface PassedRule {
  id: RuleId;
  name: string;
  reason: string;
}

/** 이번 측정에서 이슈(참고 포함)가 없는 규칙. */
export function passedRules(issues: Issue[], viewport: 'desktop' | 'mobile'): PassedRule[] {
  const hit = new Set(issues.map((i) => i.rule_id));
  return RULE_IDS.filter((id) => !hit.has(id)).map((id) => {
    const r = RULES[id];
    const reason = r.mobileOnly && viewport !== 'mobile' ? '모바일만 해당' : r.passedReason;
    return { id, name: r.name, reason };
  });
}

export function splitIssues(issues: Issue[]): { main: Issue[]; reference: Issue[] } {
  return {
    main: issues.filter((i) => !i.is_reference),
    reference: issues.filter((i) => i.is_reference),
  };
}

/** 대표 attempt의 단계 idx → 그 단계에서 찾은 문제들. step이 null인 문제는 제외. */
export function stepIssueMap(issues: Issue[], representative: number): Map<number, Issue[]> {
  const m = new Map<number, Issue[]>();
  for (const i of issues) {
    if (!i.step || i.step.attempt_index !== representative) continue;
    const list = m.get(i.step.idx) ?? [];
    list.push(i);
    m.set(i.step.idx, list);
  }
  return m;
}

export function severityLabel(s: Issue['severity']): string {
  return { high: '▲ High', medium: '■ Medium', low: '● Low' }[s];
}

/** element_snapshot → element_key 형식 문자열 (elementLabel에 넣기 위해). */
export function snapshotKey(s: Step): string | null {
  const e = s.element_snapshot;
  if (!e) return null;
  return `${e.tag}|${e.role ?? ''}|${e.name ?? ''}|${e.label_text ?? ''}|${e.landmark ?? ''}`;
}

/** 단계 제목용 행동 문구 (명세 Steps 탭 주석 2). */
export function actionLabel(s: Step): string {
  const el = () => elementLabel(snapshotKey(s));
  switch (s.action.action) {
    case 'click':
      return `${el()} 클릭`;
    case 'type':
      return `${el()} 입력`;
    case 'select':
      return `${el()} 선택`;
    case 'scroll':
      return `스크롤 ${s.action.direction === 'down' ? '↓' : '↑'}`;
    case 'back':
      return '뒤로';
    case 'wait':
      return '대기';
    case 'done':
      return '완료';
    case 'fail':
      return '포기';
  }
}

const EFFECT_KO: Record<Step['effect_type'], string> = {
  url_change: '주소 바뀜',
  modal_change: '모달 열림',
  dom_mutation: '화면 바뀜',
  no_change: '변화 없음',
};

export function effectLabel(e: Step['effect_type']): string {
  return EFFECT_KO[e];
}

/** 단계 하나의 오버레이: 누른 요소 bbox, 가린 요소, 근처 요소, 클릭 지점. element_snapshot이 없으면 빈 배열. */
export function stepOverlays(s: Step, highlightLabel?: string) {
  const e = s.element_snapshot;
  if (!e) return [];
  const out: Array<{ kind: 'bbox' | 'occluder' | 'nearby' | 'click'; bbox: Step['element_snapshot'] extends infer T ? (T extends { bbox: infer B } ? B : never) : never; label?: string }> = [];
  if (e.occluded && e.occluder) {
    out.push({ kind: 'occluder', bbox: e.occluder.bbox, label: `가린 요소: ${e.occluder.name ? e.occluder.name : `이름 없는 ${e.occluder.tag}`}` });
  }
  for (const n of e.nearby_targets) out.push({ kind: 'nearby', bbox: n.bbox, label: `근처: ${n.name}` });
  out.push({ kind: 'bbox', bbox: e.bbox, label: highlightLabel ?? elementLabel(snapshotKey(s)) });
  if (s.action.action === 'click' || s.action.action === 'type' || s.action.action === 'select') out.push({ kind: 'click', bbox: e.bbox });
  return out;
}
