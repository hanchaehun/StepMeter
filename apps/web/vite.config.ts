/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const mockDir = fileURLToPath(new URL('../../tests/fixtures/mock/api', import.meta.url));

// 실제 API 모드(리포트 v1): 브라우저가 5173 → 8000으로 직접 부르면 X-Access-Code 헤더 때문에 CORS preflight가 걸리고,
// API에는 CORS 설정이 없다. 그래서 /api/* 를 같은 출처에서 받아 API로 넘긴다. .env.local: VITE_API_URL=/api
// (/runs/{id}는 SPA 주소와 겹치므로 /api 접두어를 쓰고 넘길 때 뗀다.) 대상은 API_PROXY_TARGET(기본 http://127.0.0.1:8000).
const apiProxy = {
  '/api': {
    target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@mock': mockDir,
    },
  },
  server: {
    // 목 JSON이 저장소 루트의 tests/fixtures/ 아래에 있어 Vite 루트 밖을 허용한다
    fs: { allow: [repoRoot] },
    proxy: apiProxy,
  },
  preview: { proxy: apiProxy },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
  },
});
