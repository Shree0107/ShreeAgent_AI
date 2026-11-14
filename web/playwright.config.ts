import { defineConfig, devices } from '@playwright/test'

// End-to-end smoke tests against the real backend (python -m server) and the Vite dev server.
//   npx playwright test            (starts both servers if they aren't already running)
const isWin = process.platform === 'win32'
// Path relative to the repo root (the backend webServer runs with cwd '..'). cmd.exe needs backslashes.
const python = process.env.PYTHON ?? (isWin ? '.venv\\Scripts\\python.exe' : '.venv/bin/python')

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    { command: `${python} -m server --port 8000`, cwd: '..', url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: true, timeout: 120_000 },
    // The production build (what Docker serves), so timings are realistic. Bound to 127.0.0.1: on Windows
    // "localhost" may resolve to IPv6 only and the readiness check would never pass.
    { command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort', url: 'http://127.0.0.1:4173',
      reuseExistingServer: true, timeout: 120_000 },
  ],
})
