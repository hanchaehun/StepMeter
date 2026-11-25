import type { Report } from '@/api/mock';
import { passedCount, passedRules, splitIssues, verdictText } from '@/lib/report';

export function Verdict({ report }: { report: Report }) {
  const v = verdictText(report);
  const { main, reference } = splitIssues(report.issues);
  const passed = passedCount(passedRules(report.issues, report.run.viewport));
  const est = report.metrics.find((m) => m.key === 'est_task_time');
  const mobile = report.run.viewport === 'mobile';

  const estText = mobile || !est
    ? '예상 시간은 데스크톱에서만'
    // ADR 0011 3번: 예측에 R(시스템 응답)을 넣지 않으므로 보정 여부와 관계없이 "시스템 응답 시간 제외"
    : `예상 소요 시간 ${fmt(est.value)}초 (${est.model_version_id === null ? '문헌값 기준 추정' : '사람 실험 보정'} · 시스템 응답 시간 제외)`;

  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Verdict</p>
      <p className="text-4xl font-bold leading-none tracking-tight">
        {v.main}
        {v.estimated && <span className="ml-2 text-xl font-semibold text-muted">(추정)</span>}
      </p>
      <p className="mt-2 text-base text-muted">{`${estText} · 문제 ${main.length}건 · 참고 ${reference.length}건 · 통과 ${passed}`}</p>
    </div>
  );
}

function fmt(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
