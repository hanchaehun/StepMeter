import type { Config } from 'tailwindcss';

// 색 이름 → CSS 변수. 값은 src/index.css의 :root에 있고 docs/wireframes/f06-report.md "색 토큰" 표가 기준.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        fg: 'var(--fg)',
        muted: 'var(--muted-fg)',
        faint: 'var(--faint-fg)',
        control: 'var(--control-border)',
        border: 'var(--border)',
        hair: 'var(--hair)',
        primary: { DEFAULT: 'var(--primary)', fg: 'var(--primary-fg)' },
        surface: 'var(--surface)',
        danger: 'var(--danger)',
        ok: 'var(--ok)',
        mark: 'var(--mark)',
        bg: 'var(--bg)',
      },
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'Segoe UI', 'Malgun Gothic', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config;
