// 목 JSON을 복제해 만든 상태 변형. 개발 중 ?variant= 쿼리와 테스트에서 쓴다 (명세 "상태 전환" 표).
import { loadMockReport, type Issue, type ReportData } from '@/api/mock';

export type VariantName = 'default' | 'allFailed' | 'noIssues' | 'mobile';

const base = () => structuredClone(loadMockReport());

/** 3회 전부 실패: 대표 경로 없음, 지표 없음, 요소 없는 문제(R05) 하나. */
export function allFailed(): ReportData {
  const d = base();
  d.report.run = { ...d.report.run, id: 43, representative_attempt_index: null };
  d.report.attempts = [
    { index: 1, kind: 'agent', replay_status: null, diverged_at_step: null, end_reason: 'loop', end_detail: '이메일 입력 후 같은 오류가 계속 뜬다', success: false, success_estimated: false, steps_count: 12 },
    { index: 2, kind: 'agent', replay_status: null, diverged_at_step: null, end_reason: 'budget_exceeded', end_detail: null, success: false, success_estimated: false, steps_count: 30 },
    { index: 3, kind: 'agent', replay_status: null, diverged_at_step: null, end_reason: 'loop', end_detail: '같은 버튼을 반복해서 눌렀다', success: false, success_estimated: false, steps_count: 11 },
  ];
  d.report.metrics = [];
  d.report.top_fitts_steps = [];
  d.report.slowest_steps = [];
  const loop: Issue = {
    id: 201, rule_id: 'R05', severity: 'high', confidence: 0.88, step: null, element_key: null, measured: null, threshold: null,
    explanation: '세 번의 시도 모두 같은 화면에서 같은 행동을 반복하다 멈췄습니다. 오류 안내가 사용자를 다음 단계로 이끌지 못합니다.',
    suggestion: '입력 오류일 때 무엇을 고쳐야 하는지 입력칸 옆에 문장으로 알려 주세요.', score_reason: '3회 중 3회 발견', is_reference: false,
  };
  d.report.issues = [loop];
  d.steps = [];
  d.task = { ...d.task, id: 8, description: '무료 계정을 만든다' };
  return d;
}

/** 문제 0건: 3회 모두 성공, 참고 2건만. */
export function noIssues(): ReportData {
  const d = base();
  d.report.run = { ...d.report.run, id: 44, representative_attempt_index: 1 };
  d.report.attempts = d.report.attempts.map((a, i) => ({ ...a, index: i + 1, kind: 'agent', replay_status: null, diverged_at_step: null, end_reason: 'success', end_detail: null, success: true, steps_count: 3 }));
  d.report.issues = [
    { ...d.report.issues[1], id: 301, severity: 'low', confidence: 0.2, step: null, element_key: 'a|link|이용약관||contentinfo', measured: 3.8, threshold: 4.5, score_reason: '과업 경로 밖 요소', is_reference: true },
    { ...d.report.issues[1], id: 302, rule_id: 'R10', severity: 'low', confidence: 0.2, step: null, element_key: 'button|button|||banner', measured: null, threshold: null, explanation: '아이콘만 있는 버튼에 이름이 없습니다.', suggestion: null, score_reason: '과업 경로 밖 요소', is_reference: true },
  ];
  return d;
}

/** 모바일 측정: 예상 시간 없음, 세로 뷰포트. */
export function mobile(): ReportData {
  const d = base();
  d.report.run = { ...d.report.run, id: 45, viewport: 'mobile' };
  d.report.metrics = d.report.metrics.filter((m) => m.key !== 'est_task_time');
  d.report.slowest_steps = [];
  d.steps = d.steps.map((s) => ({
    ...s,
    est_seconds: null,
    element_snapshot: s.element_snapshot ? { ...s.element_snapshot, viewport: { width: 390, height: 844 } } : null,
  }));
  return d;
}

export function variant(name: string | null): ReportData {
  switch (name) {
    case 'allFailed':
      return allFailed();
    case 'noIssues':
      return noIssues();
    case 'mobile':
      return mobile();
    default:
      return loadMockReport();
  }
}
