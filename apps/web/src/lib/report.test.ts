import { loadMockReport } from '@/api/mock';
import type { Issue } from '@/api/mock';
import {
  elementLabel,
  verdictText,
  issueTitle,
  issueMeasure,
  metricTiles,
  spreadQualityText,
  endReasonText,
  passedRules,
  splitIssues,
  stepIssueMap,
} from './report';

// 기대값은 전부 tests/fixtures/mock/api/report.json, steps.json을 사람이 읽고 계산한 값이다.
// 근거는 각 줄의 주석에 적는다 (개발계획서 15.2: 기대값은 사람이 계산).
const { report, steps } = loadMockReport();

describe('verdictText', () => {
  test('성공 2/3, 추정 아님', () => {
    // attempts[1], attempts[2]의 success=true, 세 attempt 모두 success_estimated=false, repeat_n=3
    expect(verdictText(report)).toEqual({ main: '3회 중 2회 성공', estimated: false });
  });
  test('success_estimated가 하나라도 true면 추정', () => {
    const r = structuredClone(report);
    r.attempts[1].success_estimated = true;
    expect(verdictText(r).estimated).toBe(true);
  });
});

describe('elementLabel', () => {
  test('name + role 접미', () => {
    expect(elementLabel('button|button|구매||main')).toBe('구매 버튼');
    expect(elementLabel('a|link|러닝화 A||main')).toBe('러닝화 A 링크');
  });
  test('name이 비면 role 이름, 둘 다 비면 요소, null이면 요소 없음', () => {
    expect(elementLabel('button|button|||main')).toBe('버튼');
    expect(elementLabel('div||||main')).toBe('요소');
    expect(elementLabel(null)).toBe('요소 없음');
  });
});

describe('issueTitle', () => {
  test('R04 / R02 / R01 템플릿', () => {
    // issues[0]: R04, 구매 버튼, step idx 1의 occluder tag "div" name "" → "이름 없는 div"
    expect(issueTitle(report.issues[0], steps)).toBe('구매 버튼이 이름 없는 div에 가려짐');
    // issues[1]: R02, measured 2.9
    expect(issueTitle(report.issues[1], steps)).toBe('러닝화 A 링크 글자 대비 2.9 : 1');
    // issues[2]: R01, measured 30
    expect(issueTitle(report.issues[2], steps)).toBe('장바구니 보기 링크 높이 30px');
  });
  test('step null인 R05는 요소 없이 문장만', () => {
    const i: Issue = { ...report.issues[0], rule_id: 'R05', step: null, element_key: null };
    expect(issueTitle(i, steps)).toBe('같은 화면에서 같은 행동을 반복함');
  });
});

describe('issueMeasure', () => {
  test('R02는 대비 + 기준, R01은 px + 권장, R04는 null', () => {
    expect(issueMeasure(report.issues[1])).toBe('2.9 : 1 · 기준 4.5 : 1 (WCAG AA)'); // measured 2.9, threshold 4.5
    expect(issueMeasure(report.issues[2])).toBe('30px · 권장 44px (최소 24px)');     // measured 30, threshold 44
    expect(issueMeasure(report.issues[0])).toBeNull();                                // measured null
  });
});

describe('metricTiles', () => {
  test('데스크톱: 순서·값·꼬리표', () => {
    const t = metricTiles(report);
    expect(t.map((x) => x.key)).toEqual(['est_task_time', 'click_count', 'travel_distance', 'fitts_id_sum']);
    // 7.9 → "7.9", 2 → "2", 812.5 → Math.round → "813", 5.4 → "5.4"
    expect(t.map((x) => x.value)).toEqual(['7.9', '2', '813', '5.4']);
    expect(t[0].note).toBe('보정 전');        // est_task_time.model_version_id === null
    expect(t[2].note).toBe('편차 ±12%');      // travel_distance.spread 0.12
    expect(t[1].note).toBe('편차 ±0%');       // click_count.spread 0.0
  });
  test('모바일: 예상 시간 타일은 대체 문구', () => {
    const r = structuredClone(report);
    r.run.viewport = 'mobile';
    expect(metricTiles(r)[0]).toMatchObject({ value: '—', note: '예상 시간은 데스크톱에서만' });
  });
});

describe('spreadQualityText', () => {
  test('ok/weak/pooled/null', () => {
    expect(spreadQualityText('ok')).toBe('');
    expect(spreadQualityText('weak')).toBe('추정 약함');
    expect(spreadQualityText('pooled')).toBe('이력 기준');
    expect(spreadQualityText(null)).toBe('');
  });
});

describe('endReasonText', () => {
  test('partial 재생 + gave_up, success', () => {
    // attempts[0]: kind replay, replay_status partial, diverged_at_step 1, end_reason gave_up, end_detail "장바구니 담기 버튼을 찾지 못했다"
    expect(endReasonText(report.attempts[0])).toBe('Step 1에서 끊김 · 포기 · "장바구니 담기 버튼을 찾지 못했다"');
    expect(endReasonText(report.attempts[1])).toBe('성공');
  });
});

describe('passedRules', () => {
  test('11 − {R04, R02, R01} = 8, R11은 데스크톱에서 모바일만 해당', () => {
    const p = passedRules(report.issues, 'desktop');
    expect(p.map((x) => x.id)).toEqual(['R03', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11']);
    expect(p.find((x) => x.id === 'R11')!.reason).toBe('모바일만 해당');
  });
});

describe('splitIssues / stepIssueMap', () => {
  test('본목록 [102, 101], 참고 [103]', () => {
    expect(splitIssues(report.issues).main.map((i) => i.id)).toEqual([102, 101]);
    expect(splitIssues(report.issues).reference.map((i) => i.id)).toEqual([103]);
  });
  test('대표 attempt 2의 단계 → 문제', () => {
    // 102 → attempt 2 idx 1, 101 → attempt 2 idx 0, 103 → step null (제외)
    const m = stepIssueMap(report.issues, 2);
    expect([...m.keys()].sort()).toEqual([0, 1]);
    expect(m.get(1)!.map((i) => i.id)).toEqual([102]);
  });
});
