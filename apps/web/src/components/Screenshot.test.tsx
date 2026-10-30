import { render, screen } from '@testing-library/react';
import { Screenshot } from './Screenshot';
import { Severity } from './Severity';

// 백분율 기대값은 손으로 계산: x/width, y/height (1280×800 기준)
test('bbox 오버레이를 뷰포트 대비 백분율로 배치한다', () => {
  render(
    <Screenshot
      src="x.jpg"
      viewport={{ width: 1280, height: 800 }}
      overlays={[{ kind: 'bbox', bbox: { x: 100, y: 700, width: 120, height: 40 }, label: '구매 버튼' }]}
    />,
  );
  const box = screen.getByTestId('ov-bbox');
  // 100/1280 = 7.8125%, 700/800 = 87.5%, 120/1280 = 9.375%, 40/800 = 5%
  expect(box).toHaveStyle({ left: '7.8125%', top: '87.5%', width: '9.375%', height: '5%' });
});

test('가린 요소·근처 요소·클릭 지점 오버레이도 같은 방식으로 그린다', () => {
  render(
    <Screenshot
      src="x.jpg"
      viewport={{ width: 1280, height: 800 }}
      overlays={[
        { kind: 'occluder', bbox: { x: 0, y: 680, width: 1280, height: 120 }, label: '가린 요소: 이름 없는 div' },
        { kind: 'nearby', bbox: { x: 230, y: 705, width: 90, height: 30 }, label: '근처: 장바구니 보기' },
        { kind: 'click', bbox: { x: 100, y: 700, width: 120, height: 40 } },
      ]}
    />,
  );
  expect(screen.getByTestId('ov-occluder')).toHaveStyle({ top: '85%', width: '100%', height: '15%' }); // 680/800, 1280/1280, 120/800
  expect(screen.getByTestId('ov-nearby')).toHaveStyle({ left: '17.96875%' });                        // 230/1280
  // 클릭 지점은 bbox 중심: (100+60)/1280 = 12.5%, (700+20)/800 = 90%
  expect(screen.getByTestId('ov-click')).toHaveStyle({ left: '12.5%', top: '90%' });
});

test('src가 null이면 같은 비율의 자리표시와 문구', () => {
  render(<Screenshot src={null} viewport={{ width: 390, height: 844 }} overlays={[]} />);
  expect(screen.getByText('스크린샷 없음')).toBeInTheDocument();
  expect(screen.queryByRole('img')).toBeNull();
});

test('오버레이 영역은 보조 기술에서 숨긴다', () => {
  render(<Screenshot src="x.jpg" viewport={{ width: 1280, height: 800 }} overlays={[{ kind: 'click', bbox: { x: 0, y: 0, width: 10, height: 10 } }]} />);
  expect(screen.getByTestId('overlays')).toHaveAttribute('aria-hidden', 'true');
});

test('Severity는 기호와 글자를 함께 쓴다', () => {
  render(
    <>
      <Severity level="high" />
      <Severity level="medium" />
      <Severity level="low" />
    </>,
  );
  expect(screen.getByText('▲ High')).toBeInTheDocument();
  expect(screen.getByText('■ Medium')).toBeInTheDocument();
  expect(screen.getByText('● Low')).toBeInTheDocument();
});

// ---- 리뷰 수정 패스 (Critical #1, Important #2) ----
import { fireEvent } from '@testing-library/react';
import { fitContain } from './Screenshot';

test('fitContain: 비율 유지로 컨테이너 안에 맞춘 크기', () => {
  expect(fitContain(1000, 500, 1280, 800)).toEqual({ width: 800, height: 500 });  // 높이 제한: 500*1280/800 = 800
  expect(fitContain(600, 900, 1280, 800)).toEqual({ width: 600, height: 375 });   // 너비 제한: 600*800/1280 = 375
  const m = fitContain(780, 488, 390, 844);                                       // 세로 스크린샷: 488*390/844 = 225.497…
  expect(m.height).toBe(488);
  expect(m.width).toBeCloseTo(225.5, 0);
});

test('contain 모드는 컨테이너를 재서 px 크기를 준다 (0×0이 되지 않는다)', () => {
  class RO {
    cb: ResizeObserverCallback;
    constructor(cb: ResizeObserverCallback) { this.cb = cb; }
    observe() { this.cb([{ contentRect: { width: 1000, height: 500 } } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', RO);
  render(<Screenshot src={null} viewport={{ width: 1280, height: 800 }} overlays={[]} fit="contain" />);
  expect(screen.getByTestId('shot-frame')).toHaveStyle({ width: '800px', height: '500px' });
  vi.unstubAllGlobals();
});

test('이미지가 깨지면 자리표시, src가 바뀌면 다시 이미지를 시도한다', () => {
  const { rerender } = render(<Screenshot src="a.jpg" viewport={{ width: 1280, height: 800 }} overlays={[]} />);
  fireEvent.error(screen.getByRole('presentation', { hidden: true }));
  expect(screen.getByText('스크린샷 없음')).toBeInTheDocument();
  rerender(<Screenshot src="b.jpg" viewport={{ width: 1280, height: 800 }} overlays={[]} />);
  expect(screen.queryByText('스크린샷 없음')).toBeNull();
  expect(screen.getByRole('presentation', { hidden: true })).toHaveAttribute('src', 'b.jpg');
});
