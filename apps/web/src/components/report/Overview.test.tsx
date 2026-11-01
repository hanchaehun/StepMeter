import { render, screen } from '@testing-library/react';
import { loadMockReport } from '@/api/mock';
import { passedRules } from '@/lib/report';
import { Verdict } from './Verdict';
import { PathMetrics } from './PathMetrics';
import { IssuesPanel } from './IssuesPanel';
import { AttemptsPanel } from './AttemptsPanel';
import { PassedRules } from './PassedRules';
import { ReportHeader } from './ReportHeader';

// 기대값은 목 JSON을 사람이 읽고 센 값 (근거는 주석).
const data = loadMockReport();
const { report, steps } = data;

test('ReportHeader: 과업 문장, 호스트, Compare 링크', () => {
  render(<ReportHeader report={report} task={data.task} project={data.project} />);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('러닝화 A를 장바구니에 담는다'); // task.description
  expect(screen.getByText(/shop\.example/)).toBeInTheDocument();                                   // project.base_url
  expect(screen.getByRole('link', { name: 'Compare with #41' })).toBeInTheDocument();              // run.base_run_id 41
});

test('ReportHeader: 재생 전용이면 표시', () => {
  const r = structuredClone(report);
  r.run.mode = 'replay_only';
  render(<ReportHeader report={r} task={data.task} project={data.project} />);
  expect(screen.getByText(/재생 전용/)).toBeInTheDocument();
});

test('Verdict와 보조 줄', () => {
  render(<Verdict report={report} />);
  expect(screen.getByText('3회 중 2회 성공')).toBeInTheDocument();
  // est 7.9 문헌값, 문제 2(is_reference=false), 참고 1, 통과 8
  expect(screen.getByText(/예상 소요 시간 7\.9초 \(문헌값 기준\) · 문제 2건 · 참고 1건 · 통과 8/)).toBeInTheDocument();
});

test('PathMetrics 데스크톱 4타일, 모바일이면 예상 시간 대체 문구', () => {
  const { rerender } = render(<PathMetrics report={report} />);
  expect(screen.getByText('813')).toBeInTheDocument(); // travel_distance 812.5 → 813
  const r = structuredClone(report);
  r.run.viewport = 'mobile';
  rerender(<PathMetrics report={r} />);
  expect(screen.getByText('예상 시간은 데스크톱에서만')).toBeInTheDocument();
});

test('IssuesPanel: 본목록 2, 참고 1, 단계 번호, 심각도', () => {
  render(<IssuesPanel report={report} steps={steps} onOpen={() => {}} onShowAll={() => {}} />);
  expect(screen.getByText('구매 버튼이 이름 없는 div에 가려짐')).toBeInTheDocument();
  expect(screen.getByText('러닝화 A 링크 글자 대비 2.9 : 1')).toBeInTheDocument();
  expect(screen.getByText('장바구니 보기 링크 높이 30px')).toBeInTheDocument(); // 참고(옅게)
  expect(screen.getByText('Step 1')).toBeInTheDocument();
  expect(screen.getByText('Step 0')).toBeInTheDocument();
  expect(screen.getAllByText('▲ High')).toHaveLength(1);
  expect(screen.getAllByText('● Low')).toHaveLength(1);
});

test('IssuesPanel: limit을 넘으면 "전체 보기" 안내', () => {
  render(<IssuesPanel report={report} steps={steps} onOpen={() => {}} onShowAll={() => {}} limit={1} />);
  expect(screen.getByRole('button', { name: /문제 2건 전체 보기/ })).toBeInTheDocument();
});

test('AttemptsPanel: 대표 attempt 점 3개는 버튼, 재생 끊김 문장, 상위 단계', () => {
  render(<AttemptsPanel report={report} steps={steps} onOpenStep={() => {}} />);
  expect(screen.getAllByRole('button', { name: /^Step \d/ })).toHaveLength(3);   // attempt 2 steps_count 3
  expect(screen.getByText(/Step 1에서 끊김 · 포기/)).toBeInTheDocument();          // attempt 1
  expect(screen.getByText(/가장 어려운 단계/)).toHaveTextContent('Step 1');        // top_fitts_steps[0] idx 1
  expect(screen.getByText(/가장 오래 걸린 단계/)).toHaveTextContent('Step 0');     // slowest_steps[0] idx 0
});

test('AttemptsPanel: 모바일이면 가장 오래 걸린 단계 줄 없음', () => {
  const r = structuredClone(report);
  r.run.viewport = 'mobile';
  r.slowest_steps = [];
  render(<AttemptsPanel report={r} steps={steps} onOpenStep={() => {}} />);
  expect(screen.queryByText(/가장 오래 걸린 단계/)).toBeNull();
});

test('PassedRules 8개', () => {
  render(<PassedRules items={passedRules(report.issues, 'desktop')} />);
  expect(screen.getAllByRole('listitem')).toHaveLength(8);
  expect(screen.getByText('모바일만 해당')).toBeInTheDocument();
});
