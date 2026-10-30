import type { Issue } from '@/api/mock';
import { severityLabel } from '@/lib/report';
import { cn } from '@/lib/cn';

// 심각도는 색만으로 전하지 않는다: 기호(▲■●) + 영어 글자 (기획서 6.2, 명세 자체 UX 기준).
const COLOR: Record<Issue['severity'], string> = {
  high: 'text-danger',
  medium: 'text-[#b45309]',
  low: 'text-faint',
};

export function Severity({ level, className }: { level: Issue['severity']; className?: string }) {
  return (
    <span className={cn('inline-flex items-center whitespace-nowrap text-sm font-semibold', COLOR[level], className)}>
      {severityLabel(level)}
    </span>
  );
}
