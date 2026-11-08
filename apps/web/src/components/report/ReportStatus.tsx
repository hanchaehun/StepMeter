// 리포트 화면의 상태 뷰 (docs/wireframes/f06-report.md "상태 전환"): 불러오는 중 / 초대 코드 / 404 / 409 / 오류.
// 숫자 자리를 비우지 않고 이유를 쓴다. 막다른 길로 끝내지 않는다(다시 시도·돌아가기).
// TODO(리포트 UI↔대시보드 UI): 측정 이력(F11)·측정 진행(F02)·새 측정(F01) 화면이 생기면 아래 href="#" 링크를 그 경로로 바꾼다.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { RunStatus } from '@/api/client';

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex justify-center px-6 py-14">
      <div className="w-full max-w-[560px] rounded-lg border border-border p-6">{children}</div>
    </div>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return <span className="mb-3 inline-flex items-center rounded-full border border-control px-2.5 py-0.5 text-xs font-semibold">{children}</span>;
}

const btn = 'inline-flex min-h-[44px] items-center justify-center rounded-lg px-4 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary';
const primary = `${btn} bg-primary text-primary-fg`;
const outline = `${btn} border border-control bg-bg text-fg`;

export function LoadingView({ runId }: { runId: number }) {
  return (
    <Shell>
      <p role="status" className="text-muted">
        불러오는 중<span className="sr-only"> · 측정 #{runId}</span>
      </p>
    </Shell>
  );
}

export function NoRunIdView() {
  return (
    <Shell>
      <h2 className="mb-2 text-lg font-bold">측정 번호가 없습니다</h2>
      <p className="mb-5 text-muted">리포트 주소는 <code className="rounded bg-surface px-1">/runs/&lt;번호&gt;</code> 형식입니다. 측정 이력에서 리포트를 고르세요.</p>
      <a href="#" className={outline}>측정 이력으로</a>
    </Shell>
  );
}

export function AccessCodeView({ wrong, onSubmit }: { wrong: boolean; onSubmit: (code: string) => void }) {
  const [code, setCode] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (wrong) inputRef.current?.focus(); // 틀렸다는 알림 뒤 바로 다시 입력할 수 있게
  }, [wrong]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (code.trim()) onSubmit(code.trim());
  };
  return (
    <Shell>
      <Tag>초대 코드 필요</Tag>
      <h2 className="mb-2 text-lg font-bold">초대 코드를 입력하세요</h2>
      <p className="mb-4 text-muted">StepMeter는 초대 코드로 사용자를 제한합니다(F17). 코드는 이 브라우저 세션에만 저장됩니다.</p>
      {wrong && (
        <p className="mb-3 flex items-center gap-1.5 text-sm text-danger" role="alert">
          <span aria-hidden="true">▲</span> 초대 코드가 맞지 않습니다. 다시 확인해 주세요.
        </p>
      )}
      <form onSubmit={submit} className="flex gap-3">
        <label className="sr-only" htmlFor="access-code">초대 코드</label>
        <input
          id="access-code"
          ref={inputRef}
          type="password"
          autoComplete="off"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="min-h-[44px] flex-1 rounded-lg border border-control bg-bg px-3 text-fg"
        />
        <button type="submit" className={primary}>확인</button>
      </form>
    </Shell>
  );
}

export function NotFoundView({ runId }: { runId: number }) {
  return (
    <Shell>
      <Tag>404</Tag>
      <h2 className="mb-2 text-lg font-bold">측정 #{runId}이(가) 없습니다</h2>
      <p className="mb-5 text-muted">번호가 틀렸거나 다른 초대 코드의 측정입니다. 다른 코드의 측정은 보이지 않습니다.</p>
      <a href="#" className={outline}>측정 이력으로</a>
    </Shell>
  );
}

export function NotFinishedView({ runId, status, progress }: { runId: number; status: RunStatus; progress: number | null }) {
  const inProgress = status === 'queued' || status === 'running';
  return (
    <Shell>
      <Tag>{inProgress ? '진행 중' : '리포트 없음'}</Tag>
      {inProgress ? (
        <>
          <h2 className="mb-2 text-lg font-bold">측정 #{runId}은(는) 아직 진행 중입니다</h2>
          <p className="mb-5 text-muted">
            {status === 'queued' ? '대기열에 있습니다.' : `진행률 ${progress ?? 0}%.`} 끝나면 리포트가 만들어집니다. 측정 진행 화면에서 기다려 주세요.
          </p>
          <a href="#" className={primary}>측정 진행 화면으로</a>
        </>
      ) : (
        <>
          <h2 className="mb-2 text-lg font-bold">이 측정은 리포트가 없습니다</h2>
          <p className="mb-5 text-muted">
            상태가 <code className="rounded bg-surface px-1">{status}</code>라 후처리를 하지 않았습니다.{' '}
            {status === 'failed' ? '서비스 장애(워커 충돌·저장 실패)입니다. 다시 측정해 주세요.' : '사용자가 취소한 측정입니다.'}
          </p>
          <a href="#" className={primary}>다시 측정</a>
        </>
      )}
    </Shell>
  );
}

export function ErrorView({ message, detail, onRetry }: { message: string; detail: string; onRetry: () => void }) {
  return (
    <Shell>
      <Tag>오류</Tag>
      <h2 className="mb-2 text-lg font-bold">리포트를 불러오지 못했습니다</h2>
      <p className="mb-2 text-muted">{message}</p>
      {detail && <p className="mb-5 break-all text-xs text-faint">원문: {detail}</p>}
      <button type="button" onClick={onRetry} className={primary}>다시 시도</button>
    </Shell>
  );
}
