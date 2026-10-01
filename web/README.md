# SAP Utilities chat UI (Phase 11)

React + TypeScript + Vite + Tailwind. It only calls the Python backend (`scripts/rag_api.py`) through relative `/api/...` URLs and shows exactly what that
backend returns. There are no built-in answers, no fake streaming, and the UI never builds SAP URLs itself.

```powershell
# 1. backend (repo root; needs the local vector stores from Phase 8 and requirements-phase11.txt)
python scripts/rag_api.py --generator extractive --host 127.0.0.1 --port 8000

# 2a. production-style: build once, the backend then serves the UI too -> http://127.0.0.1:8000
cd web; npm install; npm run build

# 2b. development with hot reload (proxies /api to the backend) -> http://127.0.0.1:5173
cd web; npm run dev
```

Checks: `npm run typecheck`, `npm test` (vitest, 48 tests). A real-browser run against the live backend is `e2e/browser_e2e.cjs`
(needs `puppeteer-core` and a Chromium, which are intentionally not project dependencies; see the header of that file).
