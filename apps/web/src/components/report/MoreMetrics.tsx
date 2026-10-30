import type { Report } from '@/api/mock';
import { spreadQualityText, spreadText } from '@/lib/report';

const LABEL: Record<string, string> = {
  est_task_time: '예상 소요 시간',
  click_count: '클릭 수',
  travel_distance: '커서 이동 거리',
  fitts_id_sum: '이동 난이도 합',
};

/** 첫 화면에 없는 나머지 측정값. 지표 원값·편차·편차 품질, attempts 요약, run 메타, 상위 단계. */
export function MoreMetrics({ report }: { report: Report }) {
  const { run, attempts, metrics } = report;
  const ok = attempts.filter((a) => a.success).length;
  const t = (iso: string | null) => (iso ? new Date(iso).toTimeString().slice(0, 8) : '—');

  return (
    <section aria-label="More metrics" className="mt-10 border-t border-border pt-5">
      <div className="mb-1 flex items-baseline gap-3">
        <h2 className="text-[17px] font-bold">More metrics</h2>
        <span className="text-xs text-faint">첫 화면에 없는 나머지 측정값</span>
      </div>
      <div className="grid gap-x-12 md:grid-cols-2">
        <dl>
          {metrics.map((m) => (
            <Row key={m.key} k={LABEL[m.key] ?? m.key} ks={`${m.key}${m.key === 'est_task_time' ? (m.model_version_id === null ? ' · KLM 문헌값 · 보정 전' : ' · 사람 실험 보정') : ''}`}
              v={`${m.value} ${m.unit}`} vs={[spreadText(m), spreadQualityText(m.spread_quality)].filter(Boolean).join(' · ')} />
          ))}
          {metrics.length === 0 && <Row k="경로 지표" ks="성공한 실행이 없어 계산하지 않음" v="—" />}
        </dl>
        <dl>
          <Row k="성공" ks={`${run.repeat_n}회 중`} v={`${ok} / ${attempts.length}`} />
          <Row k="단계 수" ks={attempts.map((a) => `Attempt ${a.index}`).join(' · ')} v={attempts.map((a) => a.steps_count).join(' · ')} />
          <Row k="LLM 비용" ks={[run.model, run.prompt_version ? `prompt ${run.prompt_version}` : null].filter(Boolean).join(' · ')} v={run.mode === 'replay_only' ? '$0 (LLM 호출 없음)' : `$${run.cost_usd}`} />
          <Row k="소요 시간" ks={`${t(run.started_at)} → ${t(run.finished_at)}`} v={duration(run.started_at, run.finished_at)} />
          {report.top_fitts_steps.length > 0 && (
            <Row k="가장 어려운 단계" ks="top_fitts_steps · 최대 3개" v={`Step ${report.top_fitts_steps[0].idx} · ${report.top_fitts_steps[0].value}bit`}
              vs={report.top_fitts_steps.slice(1).map((s) => `Step ${s.idx} · ${s.value}bit`).join(' · ')} />
          )}
          {report.slowest_steps.length > 0 && (
            <Row k="가장 오래 걸린 단계" ks="slowest_steps · 최대 3개" v={`Step ${report.slowest_steps[0].idx} · ${report.slowest_steps[0].value}s`}
              vs={report.slowest_steps.slice(1).map((s) => `Step ${s.idx} · ${s.value}s`).join(' · ')} />
          )}
        </dl>
      </div>
      <p className="mt-3 text-xs text-faint">
        편차 = (최댓값 − 최솟값) / 중앙값. 성공 실행이 2회뿐이면 "추정 약함", 이력을 모아 계산했으면 "이력 기준". 예상 소요 시간은 사람 실험 보정 전이면 문헌값으로만 계산.
      </p>
    </section>
  );
}

function Row({ k, ks, v, vs }: { k: string; ks?: string; v: string; vs?: string }) {
  return (
    <div className="grid grid-cols-[1fr_auto] gap-3 border-t border-hair py-2 text-sm">
      <dt className="text-muted">
        {k}
        {ks && <small className="block text-xs text-faint">{ks}</small>}
      </dt>
      <dd className="m-0 text-right font-semibold tabular-nums">
        {v}
        {vs && <small className="block text-xs font-normal text-faint">{vs}</small>}
      </dd>
    </div>
  );
}

function duration(start: string | null, end: string | null): string {
  if (!start || !end) return '—';
  const s = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}
