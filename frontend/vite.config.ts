import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// In containers/VPS the backend is a separate service — override via VITE_API_TARGET
// (e.g. http://api:8000). Defaults to the local backend for `run-local.sh`.
const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': {
        target: apiTarget,
        ws: true,
        changeOrigin: true,
        rewriteWsOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
