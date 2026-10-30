import { render, screen } from '@testing-library/react';
import { loadMockReport } from '@/api/mock';
import { IssuesTab } from './IssuesTab';
import { StepsTab } from './StepsTab';
import { actionLabel, effectLabel } from '@/lib/report';

const { report, steps } = loadMockReport();

test('StepsTab: 카드 3개, 문제 배지, 효과 칩', () => {
  render(<StepsTab report={report} steps={steps} onOpenStep={() => {}} />);
  expect(screen.getByText('Step 1 · 구매 버튼 클릭')).toBeInTheDocument();   // steps[1] click, name 구매, role button
  expect(screen.getAllByText('⚠ 문제 1')).toHaveLength(2);                 // Step 0(101), Step 1(102)
  expect(screen.getByText('Step 2 · 완료')).toBeInTheDocument();           // steps[2] done
  expect(screen.getByText('모달 열림')).toBeInTheDocument();                // steps[1] effect_type modal_change
  expect(screen.getByText('난이도 3.1bit')).toBeInTheDocument();           // steps[1] fitts_id 3.1
});

test('StepsTab: 카드를 누르면 그 단계 idx로 연다', async () => {
  const onOpenStep = vi.fn();
  render(<StepsTab report={report} steps={steps} onOpenStep={onOpenStep} />);
  screen.getByRole('button', { name: /Step 2 · 완료/ }).click();
  expect(onOpenStep).toHaveBeenCalledWith(2);
});

test('IssuesTab: 본목록, Reference, Passed rules 소제목', () => {
  render(<IssuesTab report={report} steps={steps} onOpen={() => {}} />);
  expect(screen.getByText('Reference')).toBeInTheDocument();
  expect(screen.getByText('Passed rules')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /가려짐|대비|높이/ })).toHaveLength(3); // 102, 101, 103
});

test('actionLabel / effectLabel', () => {
  expect(actionLabel(steps[0])).toBe('러닝화 A 링크 클릭');
  expect(actionLabel(steps[2])).toBe('완료');
  expect(actionLabel({ ...steps[2], action: { action: 'scroll', direction: 'down', thought: '', expectation: '', confusion: null } })).toBe('스크롤 ↓');
  expect(actionLabel({ ...steps[2], action: { action: 'back', thought: '', expectation: '', confusion: null } })).toBe('뒤로');
  expect(effectLabel('url_change')).toBe('주소 바뀜');
  expect(effectLabel('no_change')).toBe('변화 없음');
});
