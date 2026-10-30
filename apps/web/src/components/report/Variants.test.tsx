import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReportPage } from '@/pages/ReportPage';
import { allFailed, noIssues, mobile } from '@/fixtures/variants';

beforeEach(() => {
  window.history.replaceState(null, '', ' ');
});

test('전부 실패: EmptyReport, Steps 탭 비활성, 다시 측정 버튼', () => {
  render(<ReportPage data={allFailed()} />);
  expect(screen.getByText('3회 중 0회 성공')).toBeInTheDocument();                       // success 0 / repeat_n 3
  expect(screen.getByText(/성공한 실행이 없어 경로 지표를 계산하지 않았습니다/)).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: /Steps/ })).toBeDisabled();
  expect(screen.getByRole('link', { name: '과업 문장 고쳐서 다시 측정' })).toBeInTheDocument();
  expect(screen.getByText(/30단계 초과/)).toBeInTheDocument();                           // attempts[1] budget_exceeded
});

test('전부 실패: 요소 없는 문제를 누르면 팝업에 Attempts 띠', async () => {
  render(<ReportPage data={allFailed()} />);
  await userEvent.click(screen.getByText('같은 화면에서 같은 행동을 반복함'));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.queryByTestId('overlays')).toBeNull();
});

test('문제 0건: 문장으로 표시, 참고 2건, 통과 9', () => {
  render(<ReportPage data={noIssues()} />);
  expect(screen.getByText(/규칙 R01~R11에 걸린 문제가 없습니다/)).toBeInTheDocument();
  expect(screen.getByText(/문제 0건 · 참고 2건 · 통과 9/)).toBeInTheDocument();          // 11 − {R02, R10} = 9
});

test('모바일: 예상 시간 숨김, 가장 오래 걸린 단계 줄 없음, 뷰포트 표기', () => {
  render(<ReportPage data={mobile()} />);
  expect(screen.getAllByText('예상 시간은 데스크톱에서만').length).toBeGreaterThanOrEqual(1);
  expect(screen.queryByText(/가장 오래 걸린 단계/)).toBeNull();
  expect(screen.getByText(/Mobile 390×844/)).toBeInTheDocument();
});
