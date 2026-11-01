import { loadMockReport } from './mock';

// 기대값은 tests/fixtures/mock/api/*.json을 사람이 읽고 센 값이다.
test('목 리포트는 run 42, attempts 3, issues 3, steps 3', () => {
  const { report, steps, task } = loadMockReport();
  expect(report.run.id).toBe(42);           // report.json run.id
  expect(report.attempts).toHaveLength(3);  // attempts 배열 길이
  expect(report.issues).toHaveLength(3);    // issues 배열 길이 (참고 1건 포함)
  expect(steps).toHaveLength(3);            // steps.json 배열 길이
  expect(task.description).toBe('러닝화 A를 장바구니에 담는다'); // task.json description
});
