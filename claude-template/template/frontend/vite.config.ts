import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The single frontend↔backend seam: every `/api/*` request the browser
// makes is proxied to the backend container. The frontend holds no AI
// credentials and no knowledge of which model answers.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    watch: { usePolling: true },
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
});
