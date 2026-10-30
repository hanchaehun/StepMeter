# apps/web/

- **담당 역할:** 리포트 UI · 대시보드 UI
- **하는 일:** React 대시보드. 리포트·단계 상세·오버레이는 리포트 UI, 측정 생성·진행·비교·재생 확인 화면과 측정 이력·추이 차트(F11)는 대시보드 UI가 맡는다.
- **참고:** 개발계획서 3장, 13장 / 서비스 기획서 6장

## 실행 (리포트 UI · W1 정적 리포트 화면)

레이아웃 명세는 [`docs/wireframes/f06-report.md`](../../docs/wireframes/f06-report.md). 이 슬라이스는 API 없이 `tests/fixtures/mock/api/*.json`(10/27 동결)을 읽어 그린다.

```
cd apps/web
npm install
npm run dev        # http://localhost:5173
npm test           # vitest (watch). CI처럼 한 번만: npx vitest run
npm run typecheck  # tsc
npm run gen:api    # apps/api/openapi.yaml → src/api/types.ts (손으로 고치지 않는다)
```

- 스택: Vite 5, React 18, TypeScript, Tailwind 3.4, shadcn/ui 스타일 컴포넌트(@radix-ui), Vitest + Testing Library.
- 색 토큰은 `src/index.css`의 `:root`. 값은 F06 명세 "색 토큰" 표와 같다.
- 테스트 기대값은 목 JSON을 사람이 읽고 계산한 값이며 각 테스트에 근거 주석을 둔다 (개발계획서 15.2).
- 상태 변형 보기: `http://localhost:5173/?variant=allFailed` (전부 실패), `?variant=noIssues` (문제 0건), `?variant=mobile` (모바일 측정). 변형 데이터는 `src/fixtures/variants.ts`.
- 팝업·탭은 주소 해시와 동기화된다: `#issues`, `#steps`, `#issue-102`, `#step-1`.
