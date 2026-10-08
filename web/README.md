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

Typography: long-form copy (answers, user messages, status notes) uses the `text-answer` token and UI copy the `text-ui`
token, both defined in `src/index.css`. Inter is **self-hosted** from `src/assets/fonts` (SIL OFL 1.1, license shipped
alongside) because the API's Content-Security-Policy allows no external font host; the browser downloads the latin subset
and only fetches latin-ext when the text needs it. `src/__tests__/typography.test.ts` fails if the font named in
`--font-sans` is not actually shipped with the app, if any font URL leaves the bundle, or if the prose heading/table
hierarchy is dropped.

Checks: `npm run typecheck` and `npm test` (Vitest). A real-browser run against the live backend is `e2e/browser_e2e.cjs`
(needs `puppeteer-core` and a Chromium, which are intentionally not project dependencies; see the header of that file).
