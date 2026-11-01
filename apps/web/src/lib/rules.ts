// 규칙 R01~R11 (개발계획서 6장)과 문제 제목 템플릿 (docs/wireframes/f06-report.md "문제 제목 템플릿").
// 숫자는 템플릿에 끼워 넣기만 하고 여기서 계산하지 않는다.

export const RULE_IDS = ['R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11'] as const;
export type RuleId = (typeof RULE_IDS)[number];

export interface TitleCtx {
  element: string;            // elementLabel() 결과
  measured: number | null;
  threshold: number | null;
  occluder?: string;          // R04: 가린 요소 이름 ("이름 없는 div" 등)
  size?: { w: number; h: number }; // R07
}

export interface RuleDef {
  name: string;
  title: (c: TitleCtx) => string;
  measure?: (c: TitleCtx) => string | null;
  passedReason: string;
  mobileOnly?: boolean;
}

const n = (v: number | null, fallback = '?') => (v === null ? fallback : String(v));

/** 마지막 글자의 받침 유무로 조사를 고른다. 한글이 아니면 받침 없는 쪽. */
export function josa(word: string, pair: '이/가' | '을/를'): string {
  const [withBatchim, without] = pair.split('/');
  const code = word.charCodeAt(word.length - 1);
  const hangul = code >= 0xac00 && code <= 0xd7a3;
  const hasBatchim = hangul && (code - 0xac00) % 28 !== 0;
  return word + (hasBatchim ? withBatchim : without);
}

export const RULES: Record<RuleId, RuleDef> = {
  R01: {
    name: '작은 타겟',
    title: (c) => `${c.element} 높이 ${n(c.measured)}px`,
    measure: (c) => (c.measured === null ? null : `${c.measured}px · 권장 ${n(c.threshold, '44')}px (최소 24px)`),
    passedReason: '24px 미만 타겟 없음',
  },
  R02: {
    name: '대비 부족',
    title: (c) => `${c.element} 글자 대비 ${n(c.measured)} : 1`,
    measure: (c) => (c.measured === null ? null : `${c.measured} : 1 · 기준 ${n(c.threshold, '4.5')} : 1 (WCAG AA)`),
    passedReason: '경로 위 요소 대비 모두 기준 이상',
  },
  R03: {
    name: '무반응 클릭',
    title: (c) => `${josa(c.element, '을/를')} 눌렀는데 반응 없음`,
    passedReason: '반응 없는 클릭 0건',
  },
  R04: {
    name: '가려진 요소',
    title: (c) => `${josa(c.element, '이/가')} ${c.occluder ?? '다른 요소'}에 가려짐`,
    passedReason: '경로 위 요소가 가려지지 않음',
  },
  R05: {
    name: '반복 루프',
    title: () => '같은 화면에서 같은 행동을 반복함',
    passedReason: '같은 행동 반복 없음',
  },
  R06: {
    name: '첫 화면 밖 핵심 요소',
    title: (c) => `${josa(c.element, '이/가')} 첫 화면 밖 (${n(c.measured)}px 아래)`,
    measure: (c) => (c.measured === null ? null : `스크롤 ${c.measured}px 필요`),
    passedReason: '첫 행동 대상이 화면 안',
  },
  R07: {
    name: '먼 이동 + 작은 타겟',
    title: (c) => `${c.element}까지 멀고 작음 (ID ${n(c.measured)}bit)`,
    measure: (c) => (c.measured === null ? null : `${c.measured}bit${c.size ? ` · 크기 ${c.size.w}×${c.size.h}px` : ''}`),
    passedReason: '32px 미만 타겟 없음',
  },
  R08: {
    name: '되돌아감',
    title: (c) => `뒤로 가기 ${n(c.measured)}회`,
    passedReason: '뒤로 가기 0회',
  },
  R09: {
    name: '기대 불일치',
    title: (c) => `${c.element} 뒤 결과가 기대와 다름`,
    passedReason: '기대와 결과 일치',
  },
  R10: {
    name: '이름 없는 요소',
    title: (c) => `${c.element}에 이름 없음`,
    passedReason: '경로 위 요소 모두 이름 있음',
  },
  R11: {
    name: '키보드 가림',
    title: (c) => `${josa(c.element, '이/가')} 가상 키보드에 가릴 수 있음`,
    passedReason: '입력 중 다음 행동 대상이 하단 40% 밖',
    mobileOnly: true,
  },
};

export function isRuleId(id: string): id is RuleId {
  return (RULE_IDS as readonly string[]).includes(id);
}
