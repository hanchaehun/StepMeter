// 측정 생성 화면 요약 열의 "측정 예상" (docs/wireframes/f01-measure-create.md "예상 시간과 비용").
// 시간: 화면이 추정 = 시도당 평균 시간 × 반복 횟수 + 고정 오버헤드. 비용: 서버 응답 (와이어프레임 리뷰 질문 1번).
// 두 값 모두 근거가 아직 없다(실측 시도 시간 없음, 예상 비용 API 없음). 값이 정해지기 전에는 null로 두고
// 화면은 "추정 근거 준비 중"을 보인다. 숫자를 넣을 때는 출처를 이 주석에 적는다.

/** 시도 1회 평균 소요 시간(초). 출처 미정 */
export const ATTEMPT_SECONDS: number | null = null;
/** 반복 횟수와 무관한 고정 시간(초, 큐 대기·브라우저 준비 등). 출처 미정 */
export const OVERHEAD_SECONDS: number | null = null;

/** 반복 횟수에 따른 예상 소요 시간(초). 상수가 정해지지 않았으면 null */
export function estimateSeconds(repeatN: number, attempt = ATTEMPT_SECONDS, overhead = OVERHEAD_SECONDS): number | null {
  if (attempt === null || overhead === null) return null;
  return attempt * repeatN + overhead;
}

/** "약 4분 30초". 1분 미만은 "약 40초" */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m === 0) return `약 ${s}초`;
  return s === 0 ? `약 ${m}분` : `약 ${m}분 ${s}초`;
}
