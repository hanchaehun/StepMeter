import { render, screen } from '@testing-library/react';
import { loadMockReport } from '@/api/mock';
import { IssueRow } from './IssueRow';

const { report, steps } = loadMockReport();

// ADR 0010 3번: 단계 없는 문제의 썸네일 글자. R05는 "구간", 그 밖의 경로 밖 이슈는 element_key가 null이어도 "경로 밖"
test('썸네일: 단계 없는 R05는 "구간"', () => {
  render(<IssueRow issue={{ ...report.issues[0], rule_id: 'R05', step: null, element_key: null }} steps={steps} onOpen={() => {}} />);
  expect(screen.getByText('구간')).toBeInTheDocument();
});

test('썸네일: 경로 밖 참고 이슈(R10, element_key null)는 "경로 밖"', () => {
  render(<IssueRow issue={{ ...report.issues[0], rule_id: 'R10', step: null, element_key: null, is_reference: true }} steps={steps} onOpen={() => {}} />);
  expect(screen.getByText('경로 밖')).toBeInTheDocument();
  expect(screen.queryByText('구간')).not.toBeInTheDocument();
});
