import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { loadMockReport } from '@/api/mock';
import { ReportPage } from './ReportPage';

// 기획서 6.1: "리포트 요약"과 "단계 상세" 두 화면. 기대값은 목 JSON을 사람이 읽고 센 값.
beforeEach(() => {
  window.history.replaceState(null, '', ' ');
});

const summaryHeading = () => screen.getByRole('heading', { level: 2, name: '리포트 요약' });
const detailHeading = () => screen.getByRole('heading', { level: 2, name: '단계 상세' });

test('처음에는 리포트 요약 화면이고 문제 목록 전체(참고 포함)가 보인다', () => {
  render(<ReportPage />);
  expect(summaryHeading()).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: '리포트 화면' })).toHaveTextContent('리포트 요약');
  expect(screen.getByRole('navigation', { name: '리포트 화면' })).toHaveTextContent('단계 상세');
  expect(screen.queryByRole('heading', { level: 2, name: '단계 상세' })).toBeNull();
  expect(screen.getByText('구매 버튼이 이름 없는 div에 가려짐')).toBeInTheDocument();
  expect(screen.getByText('장바구니 보기 링크 높이 30px')).toBeInTheDocument(); // 참고도 요약 화면에
  expect(screen.getByRole('heading', { name: 'Passed rules' })).toBeInTheDocument();
});

test('문제 행을 누르면 단계 상세 화면으로 가고 해시·history가 바뀐다', async () => {
  render(<ReportPage />);
  const before = window.history.length;
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  expect(detailHeading()).toBeInTheDocument();
  expect(screen.queryByRole('heading', { level: 2, name: '리포트 요약' })).toBeNull();
  expect(screen.getByText('하단 배너가 버튼을 덮지 않도록 위치를 옮기거나 닫기 버튼을 주세요.')).toBeInTheDocument(); // issues[0].suggestion
  expect(screen.getByText('점수 이유 · 과업 경로 위 요소')).toBeInTheDocument();
  expect(window.location.hash).toBe('#issue-102');
  expect(window.history.length).toBe(before + 1);
});

test('단계 상세로 이동하면 제목에 포커스가 간다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  expect(document.activeElement).toBe(detailHeading());
});

test('단계 상세의 화살표는 이전/다음 단계 하나뿐이고, 화면 안 이동은 history를 늘리지 않는다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐')); // step 1
  const before = window.history.length;
  expect(screen.queryByRole('button', { name: /문제$/ })).toBeNull();            // "이전 문제"/"다음 문제" 없음
  await userEvent.click(screen.getByRole('button', { name: '이전 단계' }));        // step 0 → 그 단계의 문제 101
  expect(screen.getByText('2.9 : 1 · 기준 4.5 : 1 (WCAG AA)')).toBeInTheDocument();
  expect(window.location.hash).toBe('#issue-101');
  expect(window.history.length).toBe(before);
  expect(screen.getByRole('button', { name: '이전 단계' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: '다음 단계' }));
  await userEvent.click(screen.getByRole('button', { name: '다음 단계' }));        // step 2
  expect(screen.getByRole('button', { name: '다음 단계' })).toBeDisabled();
  expect(screen.getByText('이 단계에서 찾은 문제가 없습니다.')).toBeInTheDocument();
});

test('참고(103)를 열면 제안 생략 문구', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('장바구니 보기 링크 높이 30px'));
  expect(screen.getByText('참고 항목이라 제안은 생략합니다.')).toBeInTheDocument();
});

test('단계 띠에서 단계를 고르면 그 단계의 판단 이유와 문제가 바뀐다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  await userEvent.click(screen.getByRole('button', { name: /^0 · 러닝화 A 링크/ }));
  expect(screen.getByText('검색 결과에서 러닝화 A를 연다')).toBeInTheDocument(); // steps[0].thought
  expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('러닝화 A 링크 글자 대비 2.9 : 1');
});

test('"리포트 요약" 링크로 돌아오면 해시가 비고 요약 화면', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  await userEvent.click(screen.getByRole('link', { name: '리포트 요약' }));
  expect(summaryHeading()).toBeInTheDocument();
  expect(window.location.hash).toBe('');
});

test('브라우저 뒤로가기는 요약 화면으로 돌아온다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByText('구매 버튼이 이름 없는 div에 가려짐'));
  window.history.back();
  await waitFor(() => expect(summaryHeading()).toBeInTheDocument());
  expect(window.location.hash).toBe('');
});

test('#step-1 딥링크는 단계 상세를 그 단계의 첫 문제(102)로 연다', () => {
  window.location.hash = '#step-1';
  render(<ReportPage />);
  expect(detailHeading()).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('구매 버튼이 이름 없는 div에 가려짐');
});

test('#issue-101 딥링크는 단계 상세가 열린 채로 뜬다', () => {
  window.location.hash = '#issue-101';
  render(<ReportPage />);
  expect(detailHeading()).toBeInTheDocument();
  expect(screen.getByText('2.9 : 1 · 기준 4.5 : 1 (WCAG AA)')).toBeInTheDocument();
});

test('없는 #issue-999는 요약 화면에 머문다', () => {
  window.location.hash = '#issue-999';
  render(<ReportPage />);
  expect(summaryHeading()).toBeInTheDocument();
});

test('Attempts 점을 누르면 그 단계의 단계 상세', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByRole('button', { name: /^Step 2:/ }));
  expect(detailHeading()).toBeInTheDocument();
  expect(screen.getByText('이 단계에서 찾은 문제가 없습니다.')).toBeInTheDocument();
  expect(window.location.hash).toBe('#step-2');
});

test('"단계 상세" 링크는 0단계부터 연다', async () => {
  render(<ReportPage />);
  await userEvent.click(screen.getByRole('link', { name: '단계 상세' }));
  expect(detailHeading()).toBeInTheDocument();
  expect(window.location.hash).toBe('#step-0');
});

test('step은 null이지만 요소가 있는 참고(103)는 경로 밖 안내', async () => {
  render(<ReportPage />);
  expect(screen.getByText('경로 밖')).toBeInTheDocument();
  await userEvent.click(screen.getByText('장바구니 보기 링크 높이 30px'));
  expect(screen.getByText(/경로 밖 요소라 단계 화면이 없습니다/)).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Attempts' })).toBeNull();
});

test('요소가 없는 문제(R05)는 단계 상세에 스크린샷 대신 Attempts 띠', async () => {
  const data = loadMockReport();
  const r = structuredClone(data.report);
  r.issues[0] = { ...r.issues[0], rule_id: 'R05', step: null, element_key: null, measured: null, threshold: null };
  render(<ReportPage data={{ ...data, report: r }} />);
  await userEvent.click(screen.getByText('같은 화면에서 같은 행동을 반복함'));
  expect(detailHeading()).toBeInTheDocument();
  expect(within(screen.getByRole('main')).getByRole('region', { name: 'Attempts' })).toBeInTheDocument();
  expect(screen.queryByTestId('overlays')).toBeNull();
});

test('문제 행의 접근 이름은 심각도로 시작한다', () => {
  render(<ReportPage />);
  expect(screen.getByRole('button', { name: /^▲ High 구매 버튼이 이름 없는 div에 가려짐/ })).toBeInTheDocument();
});
