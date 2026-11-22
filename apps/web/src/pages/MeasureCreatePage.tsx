// 측정 생성 화면 (F01). 명세: docs/wireframes/f01-measure-create.md
// - 입력: 측정할 주소, 과업(예시 칩), 성공 조건(선택), 화면 크기, 반복 횟수(고급 설정)
// - 테스트 계정은 이번 일정에서 구현하지 않는다 (ADR 0004). 과업 문장에 가짜 값만 적도록 안내한다 (ADR 0011 1번)
// - 요청 순서는 src/api/measure.ts. 성공하면 측정 진행 화면(/runs/{id}/progress, F02)으로 간다
// - 401이면 초대 코드를 다시 묻고 입력값은 그대로 둔 채 다시 보낸다. 429면 상한 안내 + 재생만 하기
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ApiError, clearAccessCode, describeError, getAccessCode, setAccessCode } from '@/api/client';
import { createMeasurement, createReplayOnly, DailyLimitError, type MeasureInput, type ViewportPreset } from '@/api/measure';
import { createMockServer, type MockScenario } from '@/api/mockServer';
import { AccessCodeView } from '@/components/report/ReportStatus';
import { Button } from '@/components/ui/button';
import { estimateSeconds, formatDuration } from '@/lib/estimate';
import { cn } from '@/lib/cn';

/** 과업 예시. 라벨은 짧게, 넣는 문장은 완전하게 (명세 "칩 라벨과 넣는 문장은 다르다").
 *  입력값이 필요한 과업은 가짜 값을 문장에 적는다. 에이전트는 과업에 적힌 값만 입력한다 (ADR 0011 1번) */
export const TASK_EXAMPLES = [
  { label: '계정 만들기', text: '이름 Minsu Kim, 이메일 study@example.com, 비밀번호 Study1234로 무료 계정을 만든다' },
  { label: '장바구니 담기', text: '장바구니에 상품 하나를 담고 결제 화면까지 간다' },
  { label: '요금제 고르기', text: '가장 싼 요금제를 찾아 신청 화면까지 간다' },
] as const;

const VIEWPORTS: Array<{ value: ViewportPreset; label: string; size: string }> = [
  { value: 'desktop', label: '데스크톱', size: '1280×800' },
  { value: 'mobile', label: '모바일', size: '390×844' },
];

type Field = 'url' | 'description';
type Errors = Partial<Record<Field, string>>;

export const MESSAGES = {
  url: '주소는 https:// 또는 http:// 로 시작해야 합니다.',
  description: '과업을 한 문장으로 적어 주세요. 아래 예시를 눌러 넣을 수 있습니다.',
  descriptionTooLong: '과업은 1000자까지 적을 수 있습니다.',
};

export function validate(url: string, description: string): Errors {
  const errors: Errors = {};
  const u = url.trim();
  let ok = /^https?:\/\//i.test(u);
  if (ok) {
    try {
      ok = Boolean(new URL(u).host);
    } catch {
      ok = false;
    }
  }
  if (!ok) errors.url = MESSAGES.url;
  const d = description.trim();
  if (!d) errors.description = MESSAGES.description;
  else if (d.length > 1000) errors.description = MESSAGES.descriptionTooLong;
  return errors;
}

interface Props {
  /** null이면 목 모드 (백엔드 없이 개발) */
  baseUrl: string | null;
  /** 목 모드의 응답 시나리오 (?variant=limit | unauthorized) */
  mockScenario?: MockScenario;
  fetchImpl?: typeof fetch;
  navigate?: (path: string) => void;
}

export function MeasureCreatePage({ baseUrl, mockScenario = 'ok', fetchImpl, navigate = (p) => window.location.assign(p) }: Props) {
  const mock = baseUrl === null;
  const mockServer = useMemo(() => (mock && !fetchImpl ? createMockServer(mockScenario, 600) : null), [mock, mockScenario, fetchImpl]);
  const api = { baseUrl: baseUrl ?? '/api', fetchImpl: fetchImpl ?? mockServer?.fetch };

  const [code, setCode] = useState<string | null>(() => (mock ? 'mock' : getAccessCode()));
  const [codeWrong, setCodeWrong] = useState(false);

  const [url, setUrl] = useState('');
  const [description, setDescription] = useState('');
  const [urlContains, setUrlContains] = useState('');
  const [textPresent, setTextPresent] = useState('');
  const [viewport, setViewport] = useState<ViewportPreset>('desktop');
  const [repeatN, setRepeatN] = useState<3 | 5>(3);
  const [errors, setErrors] = useState<Errors>({});
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({});
  const [pendingChip, setPendingChip] = useState<string | null>(null);
  /** 401로 멈춘 요청. 코드를 다시 받으면 이 값으로 다시 보낸다 */
  const [retryInput, setRetryInput] = useState<MeasureInput | null>(null);

  const urlRef = useRef<HTMLInputElement>(null);
  const descRef = useRef<HTMLTextAreaElement>(null);

  const go = (runId: number) => navigate(`/runs/${runId}/progress${mock ? '?mock=1' : ''}`);

  const onAuthError = (e: unknown, input: MeasureInput | null) => {
    if (e instanceof ApiError && e.status === 401) {
      if (!mock) clearAccessCode(); // 틀린 코드를 세션에 남기지 않는다
      setCode(null);
      setCodeWrong(true);
      setRetryInput(input);
      return true;
    }
    return false;
  };

  const create = useMutation({
    mutationFn: ({ input, accessCode }: { input: MeasureInput; accessCode: string }) => createMeasurement(input, { ...api, accessCode }),
    onSuccess: (r) => go(r.run.id),
    onError: (e, vars) => {
      onAuthError(e, vars.input);
    },
  });

  const replay = useMutation({
    mutationFn: ({ e, accessCode }: { e: DailyLimitError; accessCode: string }) =>
      createReplayOnly(e.task.id, e.baseRunId as number, viewport, { ...api, accessCode }),
    onSuccess: (run) => go(run.id),
    onError: (e) => {
      onAuthError(e, null);
    },
  });

  const busy = create.isPending || replay.isPending;

  const buildInput = (): MeasureInput => {
    const cond = { url_contains: urlContains.trim() || undefined, text_present: textPresent.trim() || undefined };
    return {
      url: url.trim(),
      description: description.trim(),
      successCondition: cond.url_contains || cond.text_present ? cond : null,
      viewport,
      repeatN,
    };
  };

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const next = validate(url, description);
    setErrors(next);
    setTouched({ url: true, description: true });
    if (next.url) return urlRef.current?.focus();
    if (next.description) return descRef.current?.focus();
    if (!code) return;
    create.mutate({ input: buildInput(), accessCode: code });
  };

  // 칩: 비어 있으면 바로 넣고, 이미 적은 과업이 있으면 바꿀지 묻는다
  const pickChip = (text: string) => {
    if (description.trim() && description.trim() !== text) setPendingChip(text);
    else applyChip(text);
  };
  const applyChip = (text: string) => {
    setDescription(text);
    setPendingChip(null);
    if (touched.description) setErrors((e) => ({ ...e, description: validate(url, text).description }));
    descRef.current?.focus();
  };

  // 칸을 떠날 때 그 칸만 검사 (명세: 포커스 이탈과 제출 시점)
  const blur = (f: Field) => {
    setTouched((t) => ({ ...t, [f]: true }));
    setErrors((e) => ({ ...e, [f]: validate(url, description)[f] }));
  };
  // 이미 오류가 보이는 칸은 고치는 즉시 오류를 지운다
  useEffect(() => {
    setErrors((e) => {
      const v = validate(url, description);
      return { url: e.url ? v.url : undefined, description: e.description ? v.description : undefined };
    });
  }, [url, description]);

  if (!code) {
    return (
      <AccessCodeView
        wrong={codeWrong}
        onSubmit={(c) => {
          if (!mock) setAccessCode(c);
          setCode(c);
          setCodeWrong(false);
          if (retryInput) create.mutate({ input: retryInput, accessCode: c });
          setRetryInput(null);
        }}
      />
    );
  }

  const errorCount = Object.values(errors).filter(Boolean).length;
  const limitError = create.error instanceof DailyLimitError ? create.error : null;
  const otherError =
    create.error && !limitError && !(create.error instanceof ApiError && create.error.status === 401) ? describeError(create.error) : null;
  const replayError = replay.error && !(replay.error instanceof ApiError && replay.error.status === 401) ? describeError(replay.error) : null;

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-8 sm:px-10">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">새 측정 만들기</h1>
      {mock && (
        <p className="mb-6 rounded-lg bg-surface px-3 py-2 text-sm text-muted">
          목 모드: 서버에 보내지 않고 화면 안에서 응답을 흉내 냅니다.
        </p>
      )}
      <form onSubmit={submit} noValidate className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <fieldset disabled={busy} className="min-w-0 space-y-6">
          <legend className="sr-only">측정 정보</legend>

          {/* 측정할 주소 */}
          <div>
            <label htmlFor="m-url" className="mb-1.5 block font-semibold">측정할 주소</label>
            <input
              id="m-url"
              ref={urlRef}
              type="url"
              inputMode="url"
              autoComplete="url"
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onBlur={() => blur('url')}
              aria-invalid={errors.url ? true : undefined}
              aria-describedby={errors.url ? 'm-url-err' : undefined}
              className={inputCls(Boolean(errors.url))}
            />
            <FieldError id="m-url-err" message={errors.url} />
          </div>

          {/* 과업 */}
          <div>
            <label htmlFor="m-desc" className="mb-1.5 block font-semibold">과업</label>
            <p id="m-desc-hint" className="mb-2 text-sm text-muted">
              에이전트가 할 일을 한 문장으로 적습니다. 이름·이메일·비밀번호처럼 입력해야 하는 값은 <strong className="font-semibold text-fg">가짜 값으로</strong> 문장에 적고, 실제 계정 정보는 적지 않습니다. 에이전트는 과업에 적힌 값만 입력합니다.
            </p>
            <textarea
              id="m-desc"
              ref={descRef}
              rows={3}
              maxLength={1000}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={() => blur('description')}
              aria-invalid={errors.description ? true : undefined}
              aria-describedby={`m-desc-hint${errors.description ? ' m-desc-err' : ''}`}
              className={cn(inputCls(Boolean(errors.description)), 'py-2.5')}
            />
            <FieldError id="m-desc-err" message={errors.description} />
            <div className="mt-3">
              <p id="m-chips-hint" className="mb-2 text-sm text-muted">예시를 누르면 완전한 문장이 들어갑니다.</p>
              <div role="group" aria-labelledby="m-chips-hint" className="flex flex-wrap gap-2">
                {TASK_EXAMPLES.map((c) => (
                  <Button key={c.label} onClick={() => pickChip(c.text)} className="rounded-full font-medium">
                    {c.label}
                  </Button>
                ))}
              </div>
              {pendingChip && (
                <div role="alertdialog" aria-labelledby="m-chip-q" className="mt-3 rounded-lg border border-control p-3">
                  <p id="m-chip-q" className="mb-2 text-sm">적어 둔 과업을 예시 문장으로 바꿀까요?</p>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="default" onClick={() => applyChip(pendingChip)} autoFocus>바꾸기</Button>
                    <Button onClick={() => setPendingChip(null)}>그대로 두기</Button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 성공 조건 (선택) */}
          <fieldset>
            <legend className="mb-1.5 font-semibold">
              성공 조건 <span className="text-sm font-normal text-muted">(선택)</span>
            </legend>
            <p id="m-cond-hint" className="mb-3 text-sm text-muted">
              비워 두면 에이전트가 마지막 화면을 보고 성공 여부를 추정합니다. 둘 다 적으면 둘 다 맞아야 성공입니다.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="m-cond-url" className="mb-1 block text-sm font-medium">주소에 들어 있는 글자</label>
                <input id="m-cond-url" placeholder="/welcome" value={urlContains} onChange={(e) => setUrlContains(e.target.value)} aria-describedby="m-cond-hint" className={inputCls(false)} />
              </div>
              <div>
                <label htmlFor="m-cond-text" className="mb-1 block text-sm font-medium">화면에 보이는 문구</label>
                <input id="m-cond-text" placeholder="가입이 완료되었습니다" value={textPresent} onChange={(e) => setTextPresent(e.target.value)} aria-describedby="m-cond-hint" className={inputCls(false)} />
              </div>
            </div>
          </fieldset>

          {/* 테스트 계정: 이번 일정에서는 만들지 않는다 (ADR 0004) */}
          <div>
            <p className="mb-1 font-semibold">
              테스트 계정 <span className="text-sm font-normal text-muted">(지원 예정)</span>
            </p>
            <p className="text-sm text-muted">계정 정보를 따로 받는 기능은 아직 없습니다. 로그인·가입이 필요한 과업은 가짜 값을 과업 문장에 적어 주세요.</p>
          </div>

          {/* 화면 크기 */}
          <fieldset>
            <legend className="mb-2 font-semibold">화면 크기</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {VIEWPORTS.map((v) => (
                <label
                  key={v.value}
                  className={cn(
                    'flex min-h-[44px] cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5',
                    viewport === v.value ? 'border-2 border-fg' : 'border-control',
                  )}
                >
                  <input type="radio" name="viewport" value={v.value} checked={viewport === v.value} onChange={() => setViewport(v.value)} className="h-5 w-5 accent-[var(--primary)]" />
                  <span>
                    <span className="font-medium">{v.label}</span> <span className="text-sm text-muted">{v.size}</span>
                    {viewport === v.value && <span className="text-sm text-muted"> · 선택됨</span>}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {/* 고급 설정 */}
          <details className="rounded-lg border border-control">
            <summary className="flex min-h-[44px] cursor-pointer items-center px-3 font-semibold">고급 설정 — 측정 신뢰도 높이기</summary>
            <fieldset className="border-t border-border px-3 py-3">
              <legend className="sr-only">반복 횟수</legend>
              <p className="mb-2 text-sm text-muted">같은 과업을 여러 번 돌려 중앙값을 씁니다. 5회는 편차 추정이 안정되지만 시간과 비용이 늘어납니다.</p>
              <div className="flex flex-wrap gap-3">
                {([3, 5] as const).map((n) => (
                  <label key={n} className="flex min-h-[44px] cursor-pointer items-center gap-2 rounded-lg border border-control px-3">
                    <input type="radio" name="repeat" value={n} checked={repeatN === n} onChange={() => setRepeatN(n)} className="h-5 w-5 accent-[var(--primary)]" />
                    반복 {n}회{n === 3 ? ' (기본)' : ''}
                  </label>
                ))}
              </div>
            </fieldset>
          </details>
        </fieldset>

        {/* 요약 열. 좁은 화면에서는 시작 버튼 바로 위 (DOM 순서), 넓은 화면에서는 오른쪽 열 */}
        <Summary repeatN={repeatN} viewport={viewport} />

        <div className="space-y-4 lg:col-start-1 lg:row-start-2">
          {limitError && (
            <LimitNotice
              e={limitError}
              busy={busy}
              onReplay={() => code && replay.mutate({ e: limitError, accessCode: code })}
              replayError={replayError}
            />
          )}
          {otherError && (
            <div role="alert" className="rounded-lg border-2 border-danger p-3">
              <p className="flex items-center gap-1.5 font-semibold text-danger">
                <span aria-hidden="true">▲</span> 측정을 만들지 못했습니다
              </p>
              <p className="mt-1 text-sm">{otherError.message}</p>
              {otherError.detail && <p className="mt-1 text-sm text-muted">서버 응답: {otherError.detail}</p>}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="default" disabled={busy} className="min-w-[120px]">
              {create.isPending ? '측정 요청 중…' : '측정 시작'}
            </Button>
            <span className="text-sm text-muted">반복 {repeatN}회{repeatN === 3 ? ' (기본)' : ''}</span>
            <span aria-live="polite" className="text-sm text-danger">
              {errorCount > 0 && (
                <>
                  <span aria-hidden="true">▲ </span>고칠 항목 {errorCount}개
                </>
              )}
            </span>
          </div>
        </div>
      </form>
    </main>
  );
}

function inputCls(invalid: boolean) {
  return cn(
    'block min-h-[44px] w-full rounded-lg bg-bg px-3 text-fg placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1',
    invalid ? 'border-2 border-danger' : 'border border-control',
  );
}

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1.5 flex items-start gap-1.5 text-sm text-danger">
      <span aria-hidden="true">▲</span>
      {message}
    </p>
  );
}

function Summary({ repeatN, viewport }: { repeatN: number; viewport: ViewportPreset }) {
  const seconds = estimateSeconds(repeatN);
  return (
    <aside aria-labelledby="m-sum" className="h-fit rounded-lg border border-border p-5 lg:col-start-2 lg:row-span-2 lg:row-start-1">
      <h2 id="m-sum" className="mb-3 font-semibold">측정 예상</h2>
      {viewport === 'mobile' ? (
        <p className="text-sm">모바일은 시간 추정을 제공하지 않습니다. 시간은 데스크톱 기준으로만 계산합니다.</p>
      ) : seconds === null ? (
        <p className="text-sm">
          <span className="text-lg font-semibold">—</span>
          <br />
          예상 소요 시간은 추정 근거를 준비하고 있습니다.
        </p>
      ) : (
        <p>
          <span className="text-lg font-semibold">{formatDuration(seconds)}</span>
          <span className="block text-sm text-muted">반복 {repeatN}회 기준 · 데스크톱</span>
        </p>
      )}
      {repeatN === 5 && <p className="mt-2 text-sm text-muted">예상 비용도 추정 근거를 준비하고 있습니다.</p>}
      <hr className="my-4 border-border" />
      <ul className="space-y-1.5 text-sm text-muted">
        <li>· 반복 {repeatN}회의 중앙값을 결과로 씁니다</li>
        <li>· 걸리는 시간은 측정할 사이트의 응답 속도에 따라 달라집니다</li>
        <li>· 진행 중에도 취소할 수 있습니다</li>
      </ul>
    </aside>
  );
}

function LimitNotice({ e, busy, onReplay, replayError }: { e: DailyLimitError; busy: boolean; onReplay: () => void; replayError: { message: string; detail: string } | null }) {
  return (
    <div role="alert" className="rounded-lg border-2 border-danger p-4">
      <p className="flex items-center gap-1.5 font-semibold text-danger">
        <span aria-hidden="true">▲</span> 오늘 측정 상한({e.project.daily_run_limit}회)을 넘었습니다
      </p>
      <p className="mt-1 text-sm">이 프로젝트의 측정 횟수는 한국 시간 자정에 다시 채워집니다. 입력한 내용은 그대로 남아 있습니다.</p>
      {e.baseRunId !== null ? (
        <div className="mt-3">
          <p className="mb-2 text-sm">
            이전 측정(#{e.baseRunId})의 경로를 그대로 다시 재생하는 것은 상한에 세지 않습니다. 에이전트는 돌리지 않으며, 재생이 끊기면 그 지점에서 멈춥니다.
          </p>
          <Button onClick={onReplay} disabled={busy}>재생만 하기</Button>
          {replayError && <p className="mt-2 text-sm text-danger">▲ {replayError.message}</p>}
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted">이 과업·화면 크기로 끝난 측정이 없어 재생만 하기는 쓸 수 없습니다.</p>
      )}
    </div>
  );
}
