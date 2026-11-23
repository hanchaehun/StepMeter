// #75 UX 감사 F-01(막다른 링크 연결)·F-11(내부 기능 번호 숨김). 경로는 App.tsx pageFromPath의 화면 주소.
import { render, screen } from '@testing-library/react';
import { AccessCodeView, NoRunIdView, NotFinishedView, NotFoundView } from './ReportStatus';

test('F-01: 측정 이력으로는 /history, 리포트 없는 측정의 다시 측정은 /new', () => {
  const { unmount } = render(<NoRunIdView />);
  expect(screen.getByRole('link', { name: '측정 이력으로' })).toHaveAttribute('href', '/history');
  unmount();
  const second = render(<NotFoundView runId={9} />);
  expect(screen.getByRole('link', { name: '측정 이력으로' })).toHaveAttribute('href', '/history');
  second.unmount();
  for (const status of ['failed', 'canceled'] as const) {
    const view = render(<NotFinishedView runId={9} status={status} progress={null} />);
    expect(screen.getByRole('link', { name: '다시 측정' })).toHaveAttribute('href', '/new');
    view.unmount();
  }
  render(<NotFinishedView runId={9} status="running" progress={40} />);
  expect(screen.getByRole('link', { name: '측정 진행 화면으로' })).toHaveAttribute('href', '/runs/9/progress');
  expect(document.querySelectorAll('a[href="#"]')).toHaveLength(0);
});

test('F-11: 초대 코드 안내에 내부 기능 번호(F17)가 보이지 않는다', () => {
  render(<AccessCodeView wrong={false} onSubmit={() => {}} />);
  expect(screen.getByText(/초대 코드로 사용자를 제한합니다/)).toBeInTheDocument();
  expect(screen.queryByText(/F17/)).toBeNull();
});
