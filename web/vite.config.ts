import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The browser only ever calls relative URLs (/api/...). In development Vite proxies them to the Python backend; in production the backend serves web/dist itself.
const backend = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: '0.0.0.0', port: 5173, allowedHosts: true, proxy: { '/api': { target: backend, changeOrigin: false } } },
  preview: { host: '0.0.0.0', port: 4173, allowedHosts: true, proxy: { '/api': { target: backend, changeOrigin: false } } },
  build: { sourcemap: false, chunkSizeWarningLimit: 600 },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/__tests__/setup.ts'], css: false, include: ['src/__tests__/**/*.test.{ts,tsx}'] },
})
