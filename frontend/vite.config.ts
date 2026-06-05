import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite blocks unknown Host headers by default. Allow any subdomain of the
// configured preview suffix — in dev that's `.localhost`, in prod it's the
// wildcard preview domain (e.g. `.preview.staging.understand.tech`). The
// suffix is forwarded into the container by docker-compose; the leading
// dot tells Vite to match the host and any subdomain of it.
//
// `process` is a Node global available when Vite loads this config — we
// declare a minimal shape here so we don't have to pull in `@types/node`
// just for one env var read.
declare const process: { env: Record<string, string | undefined> };
const previewDomainSuffix = process.env.PREVIEW_DOMAIN_SUFFIX || 'localhost';

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Vite loads this file with the project root as CWD, so resolving
    // `./src` against `process.cwd()` is equivalent to the `__dirname`
    // form people are used to from CJS examples — and it avoids pulling
    // in @types/node just to get `__dirname`.
    alias: {
      '@': path.resolve(process.cwd(), './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: [`.${previewDomainSuffix}`],
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
});
