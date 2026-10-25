# Vercel Frontend Deployment — SURA RAG

## Frontend root
- **Root Directory:** `web`
- **Build Command:** `npm run build`  (runs `tsc --noEmit && vite build`)
- **Output Directory:** `dist`
- **Install Command:** `npm ci`
- **Node Version:** 20.x (see `web/package.json` engines, Dockerfile uses `node:20.19.3-alpine`)

No additional `vercel.json` is required — set Root Directory to `web` in Vercel dashboard (Project Settings → General → Root Directory).

## API communication (secure)
- Frontend `web/src/api.ts` uses **relative `/api/...` by default**:
  ```ts
  const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? ''
  fetch(`${BASE}/api/chat`, ...)
  ```
- **Local dev:** Vite `vite.config.ts` proxies `/api` → `http://127.0.0.1:8000` (FastAPI).
- **Production (Vercel):** Set **Environment Variable** `VITE_API_BASE=https://<backend-host>` in Vercel dashboard (Project → Settings → Environment Variables, exposed to Build only). Do **not** set secrets here.
- **Alternative (same-origin):** Leave `VITE_API_BASE` empty and configure Vercel `rewrites` to proxy `/api` to backend — or host backend separately and use CORS.

## Backend hosting (separate — Vercel cannot host it)
Vercel **does not** run the FastAPI service or persistent Chroma stores.

- Host FastAPI separately: e.g., Fly.io, Render, AWS ECS/EC2, Docker host with `docker-compose.yml` (`api:8000` private + `proxy: nginx:443` TLS).
- Backend requires: `SURA_PROFILE=production`, `SURA_API_TOKEN` (secret manager, 32–256 ASCII), `SURA_ALLOWED_HOSTS=<frontend-host>,<backend-host>`, `RAG_CORS_ORIGINS=https://<vercel-app>.vercel.app`, `SURA_CARD_VECTOR_DIR=/app/data/vector_store` (external volume).
- **Auth:** Browser → Vercel → Backend via HTTPS; frontend **never** holds `SURA_API_TOKEN`. Backend validates `Authorization: Bearer <token>` injected by proxy (`deploy/nginx.conf`). Vercel frontend sends no token.

## What Vercel builds
- `web/dist` ( `index.html` 0.73kB, `index-B1Z0Izr9.js` 367kB / 114kB gzip, `index-CAPWrhd9.css` 41kB) — verified `npm run build` passes.
- No `data/vector_store/*.sqlite3`, no `data/source_corpus.json` corpus, no secrets in build.

## Required Vercel settings
- Root Directory: `web`
- Build Command: `npm run build`
- Output Directory: `dist`
- Environment Variables: `VITE_API_BASE` (backend URL, no secret)

See `deploy/README.md` for backend Docker bundle and smoke tests.
