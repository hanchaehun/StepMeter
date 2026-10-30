import { render, screen } from '@testing-library/react';
import App from './App';

test('앱 제목이 보인다', () => {
  render(<App />);
  expect(screen.getByText('StepMeter')).toBeInTheDocument();
});
