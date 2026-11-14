import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { configDefaults, defineConfig } from 'vitest/config'

// Dev server proxies the backend (python -m server on :8000), so the app always calls /api and /ws.
const API = process.env.SHREEAGENT_API ?? 'http://127.0.0.1:8000'
const proxy = {
  '/api': { target: API, changeOrigin: true },
  '/ws': { target: API.replace(/^http/, 'ws'), ws: true },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy,
  },
  preview: { port: 4173, proxy }, // production build served locally (npm run build && npm run preview)
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // Separate long-lived vendor chunks, so app updates don't re-download the chart library.
        manualChunks: (id: string) =>
          id.includes('lightweight-charts') ? 'charts' : /node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id) ? 'react' : undefined,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: [...configDefaults.exclude, 'e2e/**'], // Playwright specs run with `npx playwright test`
  },
})
