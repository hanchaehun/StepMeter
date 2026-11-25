import { render, screen } from '@testing-library/react';
import App, { pageFromPath } from './App';

test('앱 제목이 보인다', () => {
  render(<App />);
  expect(screen.getByText('StepMeter')).toBeInTheDocument();
});

test('헤더에 고정된 남은 측정 횟수(가짜 값)를 보이지 않는다', () => {
  render(<App />);
  expect(screen.queryByText(/runs left/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/Today \d+ \/ \d+/)).not.toBeInTheDocument();
});

// #75 UX 감사 F-09: 갈 곳 없는 메뉴(href="#")를 두지 않는다. Report는 리포트 화면에서만 현재 위치로 보인다
test('F-09: 헤더 메뉴에 href="#" 링크와 Compare가 없다', () => {
  const { container } = render(<App />);
  const header = container.querySelector('header') as HTMLElement;
  expect(header.querySelectorAll('a[href="#"]')).toHaveLength(0);
  expect(screen.queryByText('Compare')).toBeNull();
  expect(screen.getByRole('link', { name: 'New run' })).toHaveAttribute('href', '/new');
  expect(screen.getByRole('link', { name: 'History' })).toHaveAttribute('href', '/history');
});

test('F-09: 리포트 화면이면 Report는 링크가 아닌 현재 위치 표시', () => {
  render(<App />); // jsdom 주소 / + 목 모드 = 데모 리포트
  const report = screen.getByText('Report', { selector: 'header span' });
  expect(report).toHaveAttribute('aria-current', 'page');
  expect(screen.queryByRole('link', { name: 'Report' })).toBeNull();
});

// #75 UX 감사 F-01: 실제 API 모드의 / 는 측정 목록(막다른 "측정 번호가 없습니다" 대신). 목 모드 / 는 데모 리포트 그대로
test('F-01: / 는 실제 API 모드에서 측정 목록, 목 모드에서 리포트', () => {
  expect(pageFromPath('/', true)).toEqual({ kind: 'history' });
  expect(pageFromPath('/', false)).toEqual({ kind: 'report' });
  expect(pageFromPath('/runs/3', true)).toEqual({ kind: 'report' });
  expect(pageFromPath('/runs/3/progress', true)).toEqual({ kind: 'progress', runId: 3 });
  expect(pageFromPath('/compare', true)).toEqual({ kind: 'compare' });
});
