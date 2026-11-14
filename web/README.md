# ShreeAgent AI web app

React + TypeScript single-page app (Vite, Tailwind, TradingView Lightweight Charts™, TanStack Query, Zustand).
It talks to the FastAPI backend (`python -m server` in the repo root) via `/api/*` and the `/ws` WebSocket.

```bash
npm install
npm run dev            # http://localhost:5173 (proxies /api and /ws to http://127.0.0.1:8000)
npm test               # unit + component tests (Vitest)
npx playwright test    # browser smoke tests on desktop + mobile (starts backend and production preview)
npm run build          # production build in dist/
```

- `src/lib/indicators.ts` mirrors `analysis/indicators.py` exactly. After changing the Python indicators, run
  `python scripts/make_web_fixtures.py` to refresh the golden fixtures.
- `npm test` goes through `scripts/vitest.mjs`, which fixes a Windows drive-letter quirk ("c:" vs "C:") that
  otherwise makes every test fail with "Vitest failed to find the current suite".
- Charts by TradingView Lightweight Charts™ (Apache-2.0). The attribution logo stays on, as its licence requires.
