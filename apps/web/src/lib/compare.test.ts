// 비교 화면 문장 테스트.
// 기대값 근거: 판정 문구·"판정 기준"·"비교 불가"·"편차 추정 약함"은 이슈 #82 결정(2번), 판정 기준 단위는 개발계획서 7.4 표
// (재생: 클릭 수 "+1 이상", 이동 거리·예상 시간 "+10% 이상" / 에이전트: max(20%, 기준 편차 × 2)),
// 표시 순서·개수만 보이기는 #82 1번. 값은 tests/fixtures/mock/api/comparison.json을 사람이 읽어 옮겼다.
import { expect, test } from 'vitest';
import comparison from '@mock/comparison.json';
import type { Comparison, MetricChange } from '@/api/compare';
import { alignmentCounts, changeText, divergedText, formatMetricValue, formatRate, orderPair, splitMetrics, thresholdText, verdictView } from './compare';

const data = comparison as Comparison;
const mc = (o: Partial<MetricChange>): MetricChange => ({ key: 'click_count', base: 1, target: 1, change_rate: 0, threshold: 0.2, verdict: 'unchanged', ...o });

test('변화율: 부호를 붙인 정수 %', () => {
  expect(formatRate(0.23)).toBe('+23%');
  expect(formatRate(-0.06)).toBe('-6%');
  expect(formatRate(-0.33)).toBe('-33%');
  expect(formatRate(0)).toBe('0%');
  expect(formatRate(null)).toBe('—');
});

test('판정 기준: 재생 비교의 클릭 수는 회, 나머지는 %', () => {
  expect(thresholdText(mc({ key: 'click_count', threshold: 1 }), 'replay')).toBe('±1회'); // 7.4 재생 "+1 이상이면 악화"
  expect(thresholdText(mc({ key: 'travel_distance', threshold: 0.1 }), 'replay')).toBe('±10%'); // 7.4 재생 "+10% 이상"
  expect(thresholdText(mc({ key: 'click_count', threshold: 0.2 }), 'agent')).toBe('±20%'); // 7.4 하한선 20%
  expect(thresholdText(mc({ key: 'travel_distance', threshold: 0.24 }), 'agent')).toBe('±24%'); // comparison.json agent 0.24
  expect(thresholdText(mc({ threshold: null }), 'agent')).toBeNull();
});

test('판정: verdict를 그대로, not_comparable이나 threshold null은 "비교 불가". 색 말고 기호도 함께', () => {
  expect(verdictView(mc({ verdict: 'worse' }))).toEqual({ symbol: '▲', text: '악화', tone: 'worse' });
  expect(verdictView(mc({ verdict: 'better' }))).toEqual({ symbol: '▼', text: '개선', tone: 'better' });
  expect(verdictView(mc({ verdict: 'unchanged' }))).toEqual({ symbol: '=', text: '변화 없음', tone: 'neutral' });
  expect(verdictView(mc({ verdict: 'not_comparable' })).text).toBe('비교 불가');
  // comparison.json replay의 travel_distance: verdict unchanged인데 threshold null → #82 2번에 따라 비교 불가
  expect(verdictView(data.replay!.metric_changes[0]).text).toBe('비교 불가');
});

test('변화 칸: 재생 클릭 수는 회 차이, 에이전트는 변화율', () => {
  expect(changeText(mc({ key: 'click_count', base: 3, target: 2 }), 'replay')).toBe('-1회'); // 2 - 3
  expect(changeText(mc({ key: 'click_count', base: 2, target: 4 }), 'replay')).toBe('+2회');
  expect(changeText(data.agent!.metric_changes[0], 'agent')).toBe('-33%'); // change_rate -0.33
});

test('지표 나누기: 판정 지표는 클릭 수·커서 이동·예상 소요 시간 순, 나머지는 참고 지표', () => {
  const keys = ['type_count', 'est_task_time', 'scroll_distance', 'click_count', 'travel_distance'];
  const { judged, reference } = splitMetrics(keys.map((key) => mc({ key })));
  expect(judged.map((c) => c.key)).toEqual(['click_count', 'travel_distance', 'est_task_time']);
  expect(reference.map((c) => c.key)).toEqual(['type_count', 'scroll_distance']);
});

test('지표 값 표기', () => {
  expect(formatMetricValue('est_task_time', 10.3)).toBe('10.3초');
  expect(formatMetricValue('travel_distance', 1104)).toBe('1,104px');
  expect(formatMetricValue('click_count', 3)).toBe('3회');
  expect(formatMetricValue('fitts_id_sum', 18.25)).toBe('18.3 bit');
  expect(formatMetricValue('click_count', null)).toBe('—');
});

test('끊긴 지점: partial일 때만 한 줄', () => {
  expect(divergedText(data.replay)).toBe('Step 1에서 경로가 바뀜'); // replay_status partial, diverged_at_step 1
  expect(divergedText({ replay_status: 'full', diverged_at_step: null, metric_changes: [] })).toBeNull();
  expect(divergedText(null)).toBeNull();
});

test('경로 정렬: 추가·삭제 개수만', () => {
  // comparison.json path_alignment: kept, removed, kept, kept
  expect(alignmentCounts(data.path_alignment)).toEqual({ added: 0, removed: 1 });
});

test('고른 두 측정: 먼저 만든 측정이 기준', () => {
  const early = { id: 9, created_at: '2026-11-18T02:00:00Z' };
  const late = { id: 3, created_at: '2026-11-20T05:00:00Z' };
  expect(orderPair(late, early)).toEqual({ base: early, target: late });
  expect(orderPair(early, late)).toEqual({ base: early, target: late });
});
