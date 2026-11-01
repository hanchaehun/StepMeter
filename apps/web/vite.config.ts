/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const mockDir = fileURLToPath(new URL('../../tests/fixtures/mock/api', import.meta.url));

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
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
  },
});
