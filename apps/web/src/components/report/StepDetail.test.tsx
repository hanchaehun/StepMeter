import { render, screen } from '@testing-library/react';
import { loadMockReport } from '@/api/mock';
import { StepDetail } from './StepDetail';
import { actionLabel, effectLabel } from '@/lib/report';

const { report, steps } = loadMockReport();
const noop = () => {};

test('단계 상세: 타임라인 버튼 3개, 현재 단계 표시, 문제 있는 단계 ⚠', () => {
  render(<StepDetail report={report} steps={steps} state={{ issueId: 102, stepIdx: 1 }} onChange={noop} />);
  const strip = screen.getByRole('group', { name: /타임라인/ });
  const buttons = screen.getAllByRole('button', { name: /^\d · / });
  expect(buttons).toHaveLength(3);                                                   // steps.json 3단계
  expect(strip.querySelector('[aria-current="step"]')).toHaveTextContent('1 · 구매 버튼');
  expect(screen.getAllByText('⚠')).toHaveLength(2);                                  // Step 0(101), Step 1(102)
});

test('단계 상세: 스크린샷 오버레이 3종 + 클릭 지점, 단계별 예상 시간', () => {
  render(<StepDetail report={report} steps={steps} state={{ issueId: 102, stepIdx: 1 }} onChange={noop} />);
  expect(screen.getByTestId('ov-bbox')).toBeInTheDocument();
  expect(screen.getByTestId('ov-occluder')).toBeInTheDocument();     // steps[1].occluder
  expect(screen.getByTestId('ov-nearby')).toBeInTheDocument();       // steps[1].nearby_targets 1개
  expect(screen.getByTestId('ov-click')).toBeInTheDocument();
  expect(screen.getByText(/예상 2\.9초/)).toBeInTheDocument();        // steps[1].est_seconds
  expect(screen.getByText(/난이도 3\.1bit/)).toBeInTheDocument();     // steps[1].fitts_id
});

test('단계 상세: 한 화면에 맞춤 — 본문이 높이 고정 그리드, 스크린샷은 contain, 오른쪽 글만 스크롤', () => {
  render(<StepDetail report={report} steps={steps} state={{ issueId: 102, stepIdx: 1 }} onChange={noop} />);
  expect(screen.getByTestId('detail-body')).toHaveClass('min-h-0');
  expect(screen.getByTestId('detail-right')).toHaveClass('overflow-y-auto');
  expect(screen.getByTestId('shot-frame').parentElement).toHaveClass('h-full'); // fit="contain" 래퍼
});

test('단계 상세: 이전/다음 단계 버튼', async () => {
  const onChange = vi.fn();
  render(<StepDetail report={report} steps={steps} state={{ issueId: null, stepIdx: 1 }} onChange={onChange} />);
  screen.getByRole('button', { name: '다음 단계' }).click();
  expect(onChange).toHaveBeenCalledWith({ issueId: null, stepIdx: 2 });
  screen.getByRole('button', { name: '이전 단계' }).click();
  expect(onChange).toHaveBeenCalledWith({ issueId: 101, stepIdx: 0 }); // 0단계의 첫 문제 101
});

test('actionLabel / effectLabel', () => {
  expect(actionLabel(steps[0])).toBe('러닝화 A 링크 클릭');
  expect(actionLabel(steps[2])).toBe('완료');
  expect(actionLabel({ ...steps[2], action: { action: 'scroll', direction: 'down', thought: '', expectation: '', confusion: null } })).toBe('스크롤 ↓');
  expect(actionLabel({ ...steps[2], action: { action: 'back', thought: '', expectation: '', confusion: null } })).toBe('뒤로');
  expect(effectLabel('url_change')).toBe('주소 바뀜');
  expect(effectLabel('no_change')).toBe('변화 없음');
});
