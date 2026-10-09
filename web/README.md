# SAP Utilities chat UI (Phase 11)

React + TypeScript + Vite + Tailwind. The browser calls the Python backend through relative `/api/...` URLs and renders the response it receives. There are no built-in answers, no fake streaming, and the UI never constructs SAP URLs itself.

## Prerequisites

From the repository root, install both the retrieval and API requirements and provision the local model, card store, page store, and admitted page corpus. A fresh checkout may not include the ignored Chroma stores; the API stays fail-closed and reports 503 readiness until required artifacts are available. See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for model/index setup and the exact startup behavior.

`.env.example` is not auto-loaded by Python/Uvicorn. Set environment values in the process/service manager or explicitly load them before startup.

## Run

```bash
# 1. Backend, from the repository root (CLI defaults are HOST=127.0.0.1, PORT=8000)
python scripts/rag_api.py --generator extractive --host 127.0.0.1 --port 8000

# 2a. Production-style: build once; the backend serves web/dist at http://127.0.0.1:8000
cd web
npm ci
npm run build

# 2b. Development with hot reload; Vite proxies /api to the backend -> http://127.0.0.1:5173
npm run dev
```

The Vite proxy target defaults to `http://127.0.0.1:8000` and can be changed with the Vite-process environment variable `VITE_BACKEND_URL`. This is server-side proxy configuration; browser code still calls relative `/api/...` URLs. The production UI and API should be served from the same origin.

Typography: long-form copy (answers, user messages, status notes) uses the `text-answer` token and UI copy the `text-ui`
token, both defined in `src/index.css`. Inter is **self-hosted** from `src/assets/fonts` (SIL OFL 1.1, license shipped
alongside) because the API's Content-Security-Policy allows no external font host; the browser downloads the latin subset
and only fetches latin-ext when the text needs it. `src/__tests__/typography.test.ts` fails if the font named in
`--font-sans` is not actually shipped with the app, if any font URL leaves the bundle, or if the prose heading/table
hierarchy is dropped.

Checks: `npm run typecheck`, `npm test`, and `npm run build`. A real-browser run against the live backend is `e2e/browser_e2e.cjs` (needs `puppeteer-core` and Chromium, intentionally not project dependencies; see the header of that file).
