import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { loadMockReport } from '@/api/mock';
import { ReportPage } from './ReportPage';

beforeEach(() => {
  window.history.replaceState(null, '', ' ');
});

test('문제 행을 누르면 팝업이 열리고 해시가 바뀐다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  const dlg = screen.getByRole('dialog');
  expect(within(dlg).getByRole('heading')).toHaveTextContent('구매 버튼이 이름 없는 div에 가려짐');
  expect(within(dlg).getByText('하단 배너가 버튼을 덮지 않도록 위치를 옮기거나 닫기 버튼을 주세요.')).toBeInTheDocument(); // issues[0].suggestion
  expect(within(dlg).getByText('점수 이유 · 과업 경로 위 요소')).toBeInTheDocument();                          // issues[0].score_reason
  expect(window.location.hash).toBe('#issue-102');
});

test('다음 문제로 넘기면 R02, 참고(103)까지 간 뒤 다음 버튼 비활성', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  await userEvent.click(screen.getByRole('button', { name: '다음 문제' }));
  expect(screen.getByText('2.9 : 1 · 기준 4.5 : 1 (WCAG AA)')).toBeInTheDocument();   // issues[1] measured/threshold
  expect(window.location.hash).toBe('#issue-101');
  await userEvent.click(screen.getByRole('button', { name: '다음 문제' }));            // issues[2] = 103 (참고)
  expect(screen.getByRole('button', { name: '다음 문제' })).toBeDisabled();
  expect(screen.getByText('참고 항목이라 제안은 생략합니다.')).toBeInTheDocument();      // suggestion null
});

test('팝업 안 단계 띠에서 단계를 고르면 그 단계의 판단 이유와 문제가 바뀐다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐')); // step 1
  await userEvent.click(screen.getByRole('button', { name: /^0 · 러닝화 A 링크/ }));
  const dlg = screen.getByRole('dialog');
  expect(within(dlg).getByText('검색 결과에서 러닝화 A를 연다')).toBeInTheDocument(); // steps[0].thought
  expect(within(dlg).getByRole('heading')).toHaveTextContent('러닝화 A 링크 글자 대비 2.9 : 1'); // step 0의 문제 101
});

test('Esc로 닫히고 해시가 지워진다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(window.location.hash).toBe('');
});

test('#issues 해시로 열면 Issues 탭이 선택된다', () => {
  window.location.hash = '#issues';
  render(<ReportPage />);
  expect(screen.getByRole('tab', { name: /Issues/ })).toHaveAttribute('aria-selected', 'true');
});

test('#issue-101 해시로 열면 팝업이 열린 채로 뜬다', () => {
  window.location.hash = '#issue-101';
  render(<ReportPage />);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByText('2.9 : 1 · 기준 4.5 : 1 (WCAG AA)')).toBeInTheDocument();
});

test('Attempts 점을 누르면 그 단계로 팝업이 열린다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByRole('button', { name: /^Step 2:/ }));
  const dlg = screen.getByRole('dialog');
  expect(within(dlg).getByRole('heading')).toHaveTextContent('Step 2');
  expect(within(dlg).getByText('이 단계에서 찾은 문제가 없습니다.')).toBeInTheDocument();
  expect(window.location.hash).toBe('#step-2');
});

test('step이 null인 문제는 팝업에 스크린샷 대신 Attempts 띠', async () => {
  const data = loadMockReport();
  const r = structuredClone(data.report);
  r.issues[0] = { ...r.issues[0], rule_id: 'R05', step: null, element_key: null, measured: null, threshold: null };
  render(<ReportPage data={{ ...data, report: r }} />);
  await userEvent.click(screen.getByText('같은 화면에서 같은 행동을 반복함'));
  const dlg = screen.getByRole('dialog');
  expect(within(dlg).getByRole('region', { name: 'Attempts' })).toBeInTheDocument();
  expect(within(dlg).queryByTestId('overlays')).toBeNull();
});

// ---- 리뷰 수정 패스 (Important #3, #4, #5, 접근 이름, 포커스, 반응형) ----
test('#step-1 딥링크는 그 단계의 첫 문제(102)를 함께 연다', () => {
  window.location.hash = '#step-1';
  render(<ReportPage />);
  expect(within(screen.getByRole('dialog')).getByRole('heading')).toHaveTextContent('구매 버튼이 이름 없는 div에 가려짐');
});

test('없는 #issue-999는 팝업을 열지 않는다', () => {
  window.location.hash = '#issue-999';
  render(<ReportPage />);
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('step은 null이지만 요소가 있는 참고(103)는 R05처럼 다루지 않는다', async () => {
  render(<ReportPage />);
  expect(screen.getByText('경로 밖')).toBeInTheDocument();                       // 썸네일 자리표시 ("구간" 아님)
  await userEvent.click(screen.getByText('장바구니 보기 링크 높이 30px'));
  const dlg = screen.getByRole('dialog');
  expect(within(dlg).getByText(/경로 밖 요소라 단계 화면이 없습니다/)).toBeInTheDocument();
  expect(within(dlg).queryByRole('region', { name: 'Attempts' })).toBeNull();
});

test('팝업을 열면 history 항목이 하나 늘고, 닫으면 해시가 비고 항목이 돌아간다', async () => {
  render(<ReportPage />);
  const before = window.history.length;
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  expect(window.history.length).toBe(before + 1);
  await userEvent.click(screen.getByRole('button', { name: '다음 문제' }));   // 팝업 안 이동은 항목을 늘리지 않는다
  expect(window.history.length).toBe(before + 1);
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(window.location.hash).toBe('');
});

test('문제 행의 접근 이름은 심각도로 시작한다 (디버그 글자 없음)', () => {
  render(<ReportPage />);
  expect(screen.getByRole('button', { name: /^▲ High 구매 버튼이 이름 없는 div에 가려짐/ })).toBeInTheDocument();
});

test('팝업이 열리면 닫기 버튼에 포커스', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  expect(document.activeElement).toHaveAttribute('aria-label', '닫기');
});

test('팝업 본문은 좁은 화면에서 1열, 넓은 화면에서 2열이고 오른쪽 글은 스크롤된다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  expect(screen.getByTestId('dlg-body')).toHaveClass('grid-cols-1', 'lg:grid-cols-[1fr_400px]');
  expect(screen.getByTestId('dlg-right')).toHaveClass('overflow-y-auto');
});
