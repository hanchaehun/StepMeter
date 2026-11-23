// #75 UX 감사 반영 테스트 (C:\git\stepmeter-ux-audit-2026-11-23\report.md).
// 기대값 근거: F-02 사용자 결정(같은 (규칙, 요소)는 한 줄 + "×n", 펼치면 원래 행, 참고는 분리·접힘·"참고" 표시),
// F-03 가이드 86행(숫자 표기), F-04 WCAG 1.4.3(--muted-fg #525252 on --surface #f5f5f5 ≈ 7.2:1),
// F-06 가이드 111행(긴 토큰은 overflow-wrap:anywhere).
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { loadMockReport, type Issue, type Report } from '@/api/mock';
import { groupIssues } from '@/lib/report';
import { formatMetricValue, formatNumber, formatUsd } from '@/lib/format';
import { issueTitle } from '@/lib/report';
import { IssuesPanel } from './IssuesPanel';
import { IssueRow } from './IssueRow';
import { MoreMetrics } from './MoreMetrics';
import { ReportHeader } from './ReportHeader';

const data = loadMockReport();
const base = data.report.issues[1]; // R02, step 0, element 러닝화 A

/** 같은 R02·같은 요소가 6단계에서 반복 + 다른 기본 1건 + 참고 3건(그중 2건은 같은 요소) */
function crowded(): Report {
  const r = structuredClone(data.report);
  const same = Array.from({ length: 6 }, (_, k): Issue => ({ ...base, id: 500 + k, step: { attempt_index: 2, idx: k % 3 } }));
  const other: Issue = { ...data.report.issues[0], id: 600 };
  const refA: Issue = { ...data.report.issues[2], id: 700, element_key: 'a|link|이용약관||contentinfo', is_reference: true };
  const refB: Issue = { ...refA, id: 701 };
  const refC: Issue = { ...data.report.issues[2], id: 702, element_key: 'a|link|개인정보||contentinfo', is_reference: true };
  r.issues = [...same, other, refA, refB, refC];
  return r;
}

test('groupIssues: 같은 rule_id+element_key만 묶고, element_key가 없으면 묶지 않으며, 순서는 처음 나온 순서', () => {
  const issues = crowded().issues;
  const loopA: Issue = { ...base, id: 800, rule_id: 'R05', element_key: null, step: null };
  const loopB: Issue = { ...loopA, id: 801 };
  const groups = groupIssues([...issues, loopA, loopB]);
  expect(groups.map((g) => g.issues.length)).toEqual([6, 1, 2, 1, 1, 1]);
  expect(groups[0].issues.map((i) => i.id)).toEqual([500, 501, 502, 503, 504, 505]);
});

test('F-02: 반복된 문제는 한 줄에 ×6, 펼치면 원래 6행이 보인다', async () => {
  const report = crowded();
  render(<IssuesPanel report={report} steps={data.steps} onOpen={() => {}} />);
  const section = screen.getByRole('region', { name: 'Issues' });
  // 기본 목록: 묶음 2줄(R02 ×6, R04 1건). 참고는 접혀 있어 행이 없다
  expect(within(section).getAllByText('러닝화 A 링크 글자 대비 2.9 : 1')).toHaveLength(1);
  expect(within(section).getAllByText('구매 버튼이 이름 없는 div에 가려짐')).toHaveLength(1);
  const toggle = screen.getByRole('button', { name: '같은 문제 6건 펼치기' });
  expect(toggle).toHaveTextContent('×6');
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await userEvent.click(toggle);
  expect(screen.getByRole('button', { name: '같은 문제 6건 접기' })).toHaveAttribute('aria-expanded', 'true');
  const expanded = screen.getByRole('group', { name: '같은 문제 6건' });
  expect(within(expanded).getAllByText('러닝화 A 링크 글자 대비 2.9 : 1')).toHaveLength(6);
});

test('F-02: 참고는 기본 목록과 나뉘어 접혀 있고, 펼치면 심각도 대신 "참고"로 보인다(같은 요소는 묶임)', async () => {
  render(<IssuesPanel report={crowded()} steps={data.steps} onOpen={() => {}} />);
  expect(screen.queryByText('참고', { selector: 'span' })).toBeNull();
  const toggle = screen.getByRole('button', { name: /참고 3건 보기/ });
  await userEvent.click(toggle);
  const region = document.getElementById('issues-reference') as HTMLElement;
  // 참고 3건 → 묶음 2줄(이용약관 ×2, 개인정보 1)
  expect(within(region).getAllByText('참고', { selector: 'span' })).toHaveLength(2);
  expect(within(region).getByRole('button', { name: '같은 문제 2건 펼치기' })).toHaveTextContent('×2');
  expect(within(region).queryByText(/High|Medium|Low/)).toBeNull();
  expect(screen.getByRole('button', { name: /참고 3건 접기/ })).toHaveAttribute('aria-expanded', 'true');
});

test('F-03: 숫자 표기 — 소수 최대 자리, 끝의 0 제거, 비용은 4자리', () => {
  expect(formatNumber(4.451695969857692)).toBe('4.45');
  expect(formatNumber(30)).toBe('30');
  expect(formatNumber(5.765529622897033, 1)).toBe('5.8');
  expect(formatUsd(0.015764550000000002)).toBe('$0.0158');
  expect(formatMetricValue(1077.0458081646998, 'px')).toBe('1077 px');
  expect(formatMetricValue(8.57, 's')).toBe('8.6 s');
  // R07 제목은 화면 템플릿(rules.ts)이 만든다
  const r07: Issue = { ...base, rule_id: 'R07', measured: 4.451695969857692, threshold: null };
  expect(issueTitle(r07, data.steps)).toMatch(/\(ID 4\.45bit\)$/);
});

test('F-03: More metrics에 날것의 소수가 보이지 않는다', () => {
  const r = structuredClone(data.report);
  r.run.cost_usd = 0.015764550000000002;
  r.metrics = r.metrics.map((m) => (m.key === 'travel_distance' ? { ...m, value: 1077.0458081646998 } : m));
  r.top_fitts_steps = [{ attempt_index: 2, idx: 0, value: 4.451695969857692 }];
  render(<MoreMetrics report={r} />);
  expect(screen.getByText('$0.0158')).toBeInTheDocument();
  expect(screen.getByText('1077 px')).toBeInTheDocument();
  expect(screen.getByText('Step 0 · 4.5bit')).toBeInTheDocument();
  expect(screen.queryByText(/\d\.\d{5,}/)).toBeNull();
});

test('F-04: 썸네일 자리 글자는 회색 바탕 위 AA를 넘는 muted 토큰(faint 아님)', () => {
  render(<IssueRow issue={{ ...base, step: null, element_key: null, is_reference: true }} steps={data.steps} onOpen={() => {}} />);
  const placeholder = screen.getByText('경로 밖');
  expect(placeholder).toHaveClass('text-muted');
  expect(placeholder).not.toHaveClass('text-faint');
});

test('F-06: 리포트 제목과 주소 줄은 긴 토큰에서 줄을 바꾼다', () => {
  const longTask = { id: 7, project_id: 1, description: '확인 https://example.com/' + 'a'.repeat(120), success_condition: null };
  render(<ReportHeader report={data.report} task={longTask} project={null} />);
  expect(screen.getByRole('heading', { level: 1 })).toHaveClass('[overflow-wrap:anywhere]');
});
