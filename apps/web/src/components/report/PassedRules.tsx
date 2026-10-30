import type { PassedRule } from '@/lib/report';

/** 통과한 규칙. 접지 않는다. 규칙마다 "왜 통과인지" 근거 한 줄. */
export function PassedRules({ items }: { items: PassedRule[] }) {
  return (
    <section aria-label="Passed rules" className="border-t border-border pt-5">
      <div className="mb-1 flex items-baseline gap-3">
        <h2 className="text-[17px] font-bold">Passed rules</h2>
        <span className="text-xs text-faint">{items.length} · 이번 경로에서 걸리지 않은 규칙</span>
      </div>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-3 pt-2 md:grid-cols-4">
        {items.map((r) => (
          <li key={r.id} className="text-[15px] font-semibold">
            <span className="mr-2 font-bold text-ok">✓</span>
            {r.name}
            <small className="ml-5 block text-xs font-normal text-faint">
              {r.id} · <span>{r.reason}</span>
            </small>
          </li>
        ))}
      </ul>
    </section>
  );
}
