import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// `process` is a Node global available when Vite loads this config — a
// minimal shape avoids pulling in @types/node for one `cwd()` call.
declare const process: { cwd(): string };

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(process.cwd(), './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: true,
    },
    // The browser only ever talks to the dev server; /api is forwarded to
    // the backend container same-origin, so the API needs no CORS.
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
});
