// 비교 화면(F07) 테스트.
// 기대값 근거: 표시 순서는 개발계획서 7.5, 범위·문구는 이슈 #82 결정(1·2·4번), 응답 형식은 openapi.yaml compareRuns.
// 값은 tests/fixtures/mock/api/comparison.json을 사람이 읽어 옮겼다. 409 경우는 src/api/mockServer.ts seedHistory의
// 측정 상태(#4 취소, #2 모바일)를 읽어 골랐다.
import { render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, test } from 'vitest';
import comparison from '@mock/comparison.json';
import { ComparePage } from './ComparePage';
import { createMockServer } from '@/api/mockServer';
import type { Comparison } from '@/api/compare';

function setup(search: string, fetchImpl: typeof fetch = createMockServer('ok', 0, { seed: true }).fetch) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ComparePage baseUrl="/api" search={search} fetchImpl={fetchImpl} />
    </QueryClientProvider>,
  );
}

function respond(body: unknown, status = 200): typeof fetch {
  return (async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;
}

const rowOf = (table: HTMLElement, name: string) => within(table).getByRole('rowheader', { name }).closest('tr') as HTMLElement;

beforeEach(() => {
  window.sessionStorage.clear();
  window.sessionStorage.setItem('stepmeter.accessCode', 'code-1');
});

test('7.5 순서: 문제 변화 → 재생 비교 → 에이전트 비교 → 경로 정렬', async () => {
  setup('?base=41&target=42');
  await screen.findByRole('heading', { name: '문제 변화' });
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['문제 변화', '재생 비교', '에이전트 비교', '경로 정렬']);
  expect(screen.getByRole('link', { name: '측정 #41' })).toHaveAttribute('href', '/runs/41');
  expect(screen.getByRole('link', { name: '측정 #42' })).toHaveAttribute('href', '/runs/42');
});

test('문제 변화: 새로 생김·해결됨은 목록, 유지는 건수만', async () => {
  setup('?base=41&target=42');
  expect(await screen.findByRole('heading', { name: /새로 생긴 문제 1건/ })).toBeInTheDocument(); // issues_new 1개 (R04)
  expect(screen.getByRole('heading', { name: /해결된 문제 1건/ })).toBeInTheDocument(); // issues_resolved 1개 (R10)
  expect(screen.getByText('변화 없이 남은 문제 1건')).toBeInTheDocument(); // issues_kept 1개
  expect(screen.getByText(/R04/)).toBeInTheDocument();
  expect(screen.getByText(/R10/)).toBeInTheDocument();
  expect(screen.queryByText(/R02/)).toBeNull(); // 유지된 R02는 목록에 보이지 않는다
});

test('재생 비교: 끊긴 지점 한 줄, threshold null은 비교 불가', async () => {
  setup('?base=41&target=42');
  expect(await screen.findByText('Step 1에서 경로가 바뀜')).toBeInTheDocument(); // partial, diverged_at_step 1
  const table = screen.getByRole('table', { name: '재생 비교 판정 지표' });
  const row = within(rowOf(table, '커서 이동 거리'));
  expect(row.getByText('420px')).toBeInTheDocument();
  expect(row.getByText('395px')).toBeInTheDocument();
  expect(row.getByText('-6%')).toBeInTheDocument();
  expect(row.getByText('비교 불가')).toBeInTheDocument();
});

test('에이전트 비교: 판정 기준 %, verdict 그대로, 편차 추정 약함', async () => {
  setup('?base=41&target=42');
  const table = await screen.findByRole('table', { name: '에이전트 비교 판정 지표' });
  // 판정 지표 순서: 클릭 수 → 커서 이동 거리 → 예상 소요 시간
  expect(within(table).getAllByRole('rowheader').map((h) => h.textContent)).toEqual(['클릭 수', '커서 이동 거리', '예상 소요 시간']);

  const click = within(rowOf(table, '클릭 수'));
  expect(click.getByText('3회')).toBeInTheDocument();
  expect(click.getByText('2회')).toBeInTheDocument();
  expect(click.getByText('-33%')).toBeInTheDocument();
  expect(click.getByText('±20%')).toBeInTheDocument(); // threshold 0.2
  expect(click.getByText('개선')).toBeInTheDocument(); // verdict better
  expect(click.getByText('▼')).toBeInTheDocument();
  expect(click.getByText('편차 추정 약함')).toBeInTheDocument(); // spread_weak true

  const time = within(rowOf(table, '예상 소요 시간'));
  expect(time.getByText('비교 불가')).toBeInTheDocument(); // not_comparable
  expect(time.queryByText('편차 추정 약함')).toBeNull();
  expect(screen.queryByText(/편차 ±/)).toBeNull(); // "편차"가 아니라 "판정 기준"으로 쓴다
});

test('경로 정렬: 추가·삭제 개수만', async () => {
  setup('?base=41&target=42');
  const section = (await screen.findByRole('heading', { name: '경로 정렬' })).closest('section') as HTMLElement;
  expect(section).toHaveTextContent('추가된 단계 0개 · 삭제된 단계 1개'); // removed 1행
});

test('null 블록은 숨기고, 판정하지 않는 지표는 참고 지표로 값만', async () => {
  const c = structuredClone(comparison) as Comparison;
  c.agent = null;
  c.replay = {
    replay_status: 'full',
    diverged_at_step: null,
    metric_changes: [
      { key: 'click_count', base: 2, target: 3, change_rate: 0.5, threshold: 1, verdict: 'worse' },
      { key: 'step_count', base: 4, target: 5, change_rate: 0.25, threshold: null, verdict: 'not_comparable' },
    ],
  };
  setup('?base=1&target=3', respond(c));
  expect(await screen.findByText('끝까지 재생됨')).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '에이전트 비교' })).toBeNull();

  const judged = screen.getByRole('table', { name: '재생 비교 판정 지표' });
  const click = within(rowOf(judged, '클릭 수'));
  expect(click.getByText('+1회')).toBeInTheDocument(); // 3 - 2
  expect(click.getByText('±1회')).toBeInTheDocument(); // 7.4 재생 "+1 이상"
  expect(click.getByText('악화')).toBeInTheDocument();
  expect(click.getByText('▲')).toBeInTheDocument();
  expect(within(judged).queryByRole('rowheader', { name: '단계 수' })).toBeNull();

  expect(screen.getByText('참고 지표(판정 안 함) 1개')).toBeInTheDocument();
  const ref = screen.getByRole('table', { name: '참고 지표(판정 안 함)', hidden: true });
  const step = within(rowOf(ref, '단계 수'));
  expect(step.getByText('4회')).toBeInTheDocument();
  expect(step.queryByText('비교 불가')).toBeNull();
});

test('409: 서버 메시지를 그대로 안내', async () => {
  setup('?base=3&target=4'); // #4는 취소된 측정
  expect(await screen.findByText('이 두 측정은 비교할 수 없습니다')).toBeInTheDocument();
  expect(screen.getByText('서버 응답: both runs must be completed')).toBeInTheDocument();
});

test('409: 화면 크기가 다른 측정', async () => {
  setup('?base=1&target=2'); // #2는 모바일
  expect(await screen.findByText('서버 응답: runs differ in task or viewport')).toBeInTheDocument();
});

test('401이면 초대 코드 입력', async () => {
  setup('?base=1&target=3', createMockServer('unauthorized').fetch);
  expect(await screen.findByText('초대 코드가 맞지 않습니다. 다시 확인해 주세요.')).toBeInTheDocument();
});

test('번호가 없으면 측정 목록으로 안내하고 요청하지 않는다', () => {
  const server = createMockServer('ok', 0, { seed: true });
  setup('?base=1', server.fetch);
  expect(screen.getByText('비교할 두 측정을 고르세요')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '측정 목록으로' })).toHaveAttribute('href', '/history');
  expect(server.requests).toHaveLength(0);
});
