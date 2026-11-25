// 비교 화면 (F07). 범위는 #82 결정: B안 + 재생이 끊긴 지점 한 줄.
// 표시 순서(개발계획서 7.5): 문제 변화 → 재생 비교 지표 + 끊긴 지점 → 에이전트 비교 지표 → 경로 정렬(개수만).
// 주소: /compare?base=&target=. 판정은 API의 verdict를 그대로 쓴다.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError, clearAccessCode, describeError, getAccessCode, setAccessCode } from '@/api/client';
import { fetchComparison, type Comparison, type MetricChange } from '@/api/compare';
import type { Issue } from '@/api/mock';
import { createMockServer } from '@/api/mockServer';
import { AccessCodeView } from '@/components/report/ReportStatus';
import { Severity } from '@/components/Severity';
import { issueTitle, ruleName } from '@/lib/report';
import { alignmentCounts, changeText, divergedText, formatMetricValue, metricLabel, splitMetrics, thresholdText, verdictView } from '@/lib/compare';
import { cn } from '@/lib/cn';

interface Props {
  /** null이면 목 모드 */
  baseUrl: string | null;
  search: string;
  fetchImpl?: typeof fetch;
}

function readNum(v: string | null): number | null {
  return v && /^\d+$/.test(v) ? Number(v) : null;
}

export function ComparePage({ baseUrl, search, fetchImpl }: Props) {
  const mock = baseUrl === null;
  const [mockServer] = useState(() => (mock && !fetchImpl ? createMockServer('ok', 200, { seed: true }) : null));
  const params = new URLSearchParams(search);
  const base = readNum(params.get('base'));
  const target = readNum(params.get('target'));
  const suffix = mock ? '?mock=1' : '';

  const [code, setCode] = useState<string | null>(() => (mock ? 'mock' : getAccessCode()));
  const [codeWrong, setCodeWrong] = useState(false);
  const opts = { baseUrl: baseUrl ?? '/api', fetchImpl: fetchImpl ?? mockServer?.fetch, accessCode: code ?? '' };

  const q = useQuery({
    queryKey: ['compare', base, target, code],
    queryFn: ({ signal }) => fetchComparison(base!, target!, { ...opts, signal }),
    enabled: code !== null && base !== null && target !== null,
    retry: false,
  });

  const unauthorized = q.error instanceof ApiError && q.error.status === 401;
  useEffect(() => {
    if (!unauthorized) return;
    if (!mock) clearAccessCode();
    setCode(null);
    setCodeWrong(true);
  }, [unauthorized, mock]);

  if (base === null || target === null) {
    return (
      <Shell>
        <Notice title="비교할 두 측정을 고르세요" body="측정 목록에서 같은 과업·같은 화면 크기의 완료된 측정 두 개를 고른 뒤 비교를 누르면 여기로 옵니다." historyHref={`/history${suffix}`} />
      </Shell>
    );
  }

  if (code === null || unauthorized) {
    return (
      <AccessCodeView
        wrong={codeWrong}
        onSubmit={(c) => {
          if (!mock) setAccessCode(c);
          setCodeWrong(false);
          setCode(c);
        }}
      />
    );
  }

  const heading = (
    <div className="mb-8">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-faint">Compare</p>
      <h1 className="text-2xl font-bold tracking-tight">측정 비교</h1>
      <p className="mt-1 text-sm text-muted">
        기준 <a href={`/runs/${base}${suffix}`} className={inlineLink}>측정 #{base}</a>
        <span aria-hidden="true"> → </span>
        <span className="sr-only">, </span>
        비교 대상 <a href={`/runs/${target}${suffix}`} className={inlineLink}>측정 #{target}</a>
      </p>
    </div>
  );

  if (q.isPending) {
    return (
      <Shell>
        {heading}
        <p role="status" className="text-muted">비교 결과를 불러오는 중</p>
      </Shell>
    );
  }

  if (q.error) {
    const e = q.error;
    if (e instanceof ApiError && e.status === 404) {
      return (
        <Shell>
          {heading}
          <Notice alert title="측정을 찾을 수 없습니다" body={`측정 #${base} 또는 #${target}이 없거나 이 초대 코드로 볼 수 없습니다.`} historyHref={`/history${suffix}`} />
        </Shell>
      );
    }
    if (e instanceof ApiError && e.status === 409) {
      // #82 4번: 그 사이 상태가 바뀐 경우 등. 서버 메시지를 그대로 안내한다
      return (
        <Shell>
          {heading}
          <Notice alert title="이 두 측정은 비교할 수 없습니다" body="같은 과업·같은 화면 크기의 완료된 측정끼리만 비교합니다." detail={e.detail} historyHref={`/history${suffix}`} />
        </Shell>
      );
    }
    const { message, detail } = describeError(e);
    return (
      <Shell>
        {heading}
        <div role="alert" className="rounded-lg border-2 border-danger p-4">
          <p className="flex items-center gap-1.5 font-semibold text-danger">
            <span aria-hidden="true">▲</span> 비교 결과를 읽지 못했습니다
          </p>
          <p className="mt-1 text-sm">{message}</p>
          {detail && <p className="mt-1 text-sm text-muted">서버 응답: {detail}</p>}
          <button type="button" onClick={() => void q.refetch()} className={outlineBtn + ' mt-3'}>
            다시 시도
          </button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      {heading}
      <CompareBody data={q.data} />
    </Shell>
  );
}

export function CompareBody({ data }: { data: Comparison }) {
  const { replay, agent } = data;
  const diverged = divergedText(replay);
  const align = alignmentCounts(data.path_alignment);
  return (
    <div className="space-y-10">
      <Section id="c-issues" title="문제 변화" note="화면 고정 지표 · 경로와 상관없이 같은 화면의 같은 요소끼리 비교합니다.">
        <div className="grid gap-6 md:grid-cols-2">
          <IssueGroup title="새로 생긴 문제" symbol="▲" tone="worse" issues={data.issues_new} empty="새로 생긴 문제가 없습니다." />
          <IssueGroup title="해결된 문제" symbol="▼" tone="better" issues={data.issues_resolved} empty="해결된 문제가 없습니다." />
        </div>
        <p className="mt-4 text-sm text-muted">변화 없이 남은 문제 {data.issues_kept.length}건</p>
      </Section>

      {replay && (
        <Section id="c-replay" title="재생 비교" note="기준 측정의 대표 경로를 그대로 다시 실행해 같은 경로 위에서 비교합니다.">
          <p className="mb-4 font-semibold">
            {diverged ? (
              <>
                <span aria-hidden="true">◆ </span>
                {diverged}
                <span className="font-normal text-muted"> · 그 뒤는 에이전트가 이어서 수행했습니다</span>
              </>
            ) : (
              '끝까지 재생됨'
            )}
          </p>
          <MetricTables changes={replay.metric_changes} kind="replay" idPrefix="replay" />
        </Section>
      )}

      {agent && (
        <Section id="c-agent" title="에이전트 비교" note="에이전트가 각각 과업을 수행한 결과의 중앙값을 비교합니다. 같은 버전에서 잰 편차를 넘는 변화만 판정합니다.">
          {agent.spread_weak && (
            <p className="mb-4 text-sm font-semibold">
              편차 추정 약함 <span className="font-normal text-muted">· 성공한 시도가 2회뿐이라 편차를 값 2개로 추정했습니다.</span>
            </p>
          )}
          <MetricTables changes={agent.metric_changes} kind="agent" spreadWeak={agent.spread_weak} idPrefix="agent" />
        </Section>
      )}

      {!replay && !agent && (
        <Section id="c-metrics" title="경로 지표">
          <p className="text-muted">경로 지표를 비교할 결과가 없습니다. 문제 변화만 비교합니다.</p>
        </Section>
      )}

      <Section id="c-align" title="경로 정렬" note="두 측정의 대표 경로를 행동 순서대로 맞춰 본 결과입니다.">
        {data.path_alignment.length === 0 ? (
          <p className="text-muted">정렬할 대표 경로가 없습니다.</p>
        ) : (
          <p>
            추가된 단계 <strong>{align.added}개</strong> · 삭제된 단계 <strong>{align.removed}개</strong>
          </p>
        )}
      </Section>
    </div>
  );
}

function IssueGroup({ title, symbol, tone, issues, empty }: { title: string; symbol: string; tone: 'worse' | 'better'; issues: Issue[]; empty: string }) {
  return (
    <div>
      <h3 className={cn('mb-2 flex items-center gap-1.5 font-semibold', tone === 'worse' ? 'text-danger' : 'text-ok')}>
        <span aria-hidden="true">{symbol}</span> {title} {issues.length}건
      </h3>
      {issues.length === 0 ? (
        <p className="text-sm text-muted">{empty}</p>
      ) : (
        <ul>
          {issues.map((i) => (
            <li key={i.id} className="grid grid-cols-[80px_minmax(0,1fr)] gap-3 border-t border-hair py-3">
              <Severity level={i.severity} />
              <div className="min-w-0 font-semibold leading-tight [overflow-wrap:anywhere]">
                {issueTitle(i, [])}
                <small className="mt-0.5 block text-xs font-normal text-faint">
                  {i.rule_id} {ruleName(i)}
                  {i.step ? ` · Step ${i.step.idx}` : ''}
                </small>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MetricTables({ changes, kind, spreadWeak = false, idPrefix }: { changes: MetricChange[]; kind: 'replay' | 'agent'; spreadWeak?: boolean; idPrefix: string }) {
  const { judged, reference } = splitMetrics(changes);
  return (
    <>
      {judged.length === 0 ? (
        <p className="text-muted">판정할 지표가 없습니다.</p>
      ) : (
        <TableBox captionId={`${idPrefix}-judged`} caption={`${kind === 'replay' ? '재생' : '에이전트'} 비교 판정 지표`}>
          <thead className="bg-surface text-left">
            <tr>
              <th scope="col" className={th}>지표</th>
              <th scope="col" className={cn(th, 'text-right')}>기준</th>
              <th scope="col" className={cn(th, 'text-right')}>비교 대상</th>
              <th scope="col" className={cn(th, 'text-right')}>변화</th>
              <th scope="col" className={cn(th, 'text-right')}>판정 기준</th>
              <th scope="col" className={th}>판정</th>
            </tr>
          </thead>
          <tbody>
            {judged.map((c) => {
              const v = verdictView(c);
              return (
                <tr key={c.key} className="border-t border-hair">
                  <th scope="row" className={cn(td, 'text-left font-semibold')}>{metricLabel(c.key)}</th>
                  <td className={cn(td, 'text-right tabular-nums')}>{formatMetricValue(c.key, c.base)}</td>
                  <td className={cn(td, 'text-right tabular-nums')}>{formatMetricValue(c.key, c.target)}</td>
                  <td className={cn(td, 'text-right tabular-nums')}>{changeText(c, kind)}</td>
                  <td className={cn(td, 'text-right tabular-nums')}>{thresholdText(c, kind) ?? '—'}</td>
                  <td className={td}>
                    <span className={cn('inline-flex items-center gap-1 font-semibold', v.tone === 'worse' && 'text-danger', v.tone === 'better' && 'text-ok', v.tone === 'neutral' && 'text-muted')}>
                      {v.symbol && <span aria-hidden="true">{v.symbol}</span>}
                      {v.text}
                    </span>
                    {spreadWeak && v.text !== '비교 불가' && <span className="block text-xs text-muted">편차 추정 약함</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </TableBox>
      )}
      {reference.length > 0 && (
        <details className="mt-4">
          <summary className="inline-flex min-h-[44px] cursor-pointer items-center font-semibold">
            참고 지표(판정 안 함) {reference.length}개
          </summary>
          <TableBox captionId={`${idPrefix}-ref`} caption="참고 지표(판정 안 함)">
            <thead className="bg-surface text-left">
              <tr>
                <th scope="col" className={th}>지표</th>
                <th scope="col" className={cn(th, 'text-right')}>기준</th>
                <th scope="col" className={cn(th, 'text-right')}>비교 대상</th>
              </tr>
            </thead>
            <tbody>
              {reference.map((c) => (
                <tr key={c.key} className="border-t border-hair">
                  <th scope="row" className={cn(td, 'text-left font-medium')}>{metricLabel(c.key)}</th>
                  <td className={cn(td, 'text-right tabular-nums')}>{formatMetricValue(c.key, c.base)}</td>
                  <td className={cn(td, 'text-right tabular-nums')}>{formatMetricValue(c.key, c.target)}</td>
                </tr>
              ))}
            </tbody>
          </TableBox>
        </details>
      )}
    </>
  );
}

function TableBox({ captionId, caption, children }: { captionId: string; caption: string; children: React.ReactNode }) {
  // 좁은 화면에서는 표 상자 안에서만 가로 스크롤 (측정 목록과 같은 방식)
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-labelledby={captionId}>
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <caption id={captionId} className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

function Section({ id, title, note, children }: { id: string; title: string; note?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="text-lg font-bold">{title}</h2>
      {note && <p className="mb-4 text-sm text-muted">{note}</p>}
      {!note && <div className="mb-3" />}
      {children}
    </section>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-10">{children}</main>;
}

function Notice({ title, body, detail, historyHref, alert = false }: { title: string; body: string; detail?: string; historyHref: string; alert?: boolean }) {
  return (
    <div role={alert ? 'alert' : undefined} className={cn('rounded-lg p-6', alert ? 'border-2 border-danger' : 'border border-border')}>
      <p className={cn('mb-1 flex items-center gap-1.5 text-lg font-semibold', alert && 'text-danger')}>
        {alert && <span aria-hidden="true">▲</span>}
        {title}
      </p>
      <p className="mb-1 text-muted">{body}</p>
      {detail && <p className="mb-1 text-sm text-muted">서버 응답: {detail}</p>}
      <a href={historyHref} className={outlineBtn + ' mt-3'}>측정 목록으로</a>
    </div>
  );
}

const th = 'px-3 py-2.5 font-semibold whitespace-nowrap';
const td = 'px-3 py-2 align-middle whitespace-nowrap';
const inlineLink = 'inline-flex min-h-[24px] items-center font-semibold text-fg underline underline-offset-4';
const outlineBtn = 'inline-flex min-h-[44px] items-center rounded-lg border border-control px-4 text-sm font-semibold';
