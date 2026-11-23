// 화면에 보이는 숫자 표기 (#75 UX 감사 F-03). 계산 값은 바꾸지 않고 보이는 글자만 다듬는다.

/** 소수 최대 digits자리, 끝의 0은 뺀다. 4.451695969857692 → "4.45", 1077.0458 (digits 0) → "1077", 30 → "30" */
export function formatNumber(v: number, digits = 2): string {
  return String(Number(v.toFixed(digits)));
}

/** LLM 비용. 측정 1회가 1센트 안팎이라 소수 4자리: 0.015764550000000002 → "$0.0158" */
export function formatUsd(v: number): string {
  return `$${v.toFixed(4)}`;
}

/** 지표 값 + 단위. px은 정수, 나머지는 소수 1자리까지 (리포트 첫 화면 타일과 같은 자릿수) */
export function formatMetricValue(value: number, unit: string): string {
  return `${formatNumber(value, unit === 'px' ? 0 : 1)} ${unit}`;
}
