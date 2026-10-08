# SURA Production Deployment Guide

## 1. System Architecture Overview

SURA (SAP Utilities Documentation Assistant) is composed of:
1. **Frontend:** React + TypeScript + Vite SPA (`web/`). Serves modern SAP Horizon / Stone styled interface with full keyboard accessibility (WCAG 2.1 AA compliant), structured answer view, citation badges, source inspector, and conversation history.
2. **Backend API:** FastAPI application (`scripts/rag_api.py`) exposing `/api/chat`, `/api/health`, `/health` (liveness), and `/ready` (readiness).
3. **Retrieval & Pipeline Engine:** Chroma vector database over 29 SAP reference cards (`data/card_collection`), deterministic two-stage routing, and exact-citation support chain against 25 ingested SAP Help documentation pages (`data/page_corpus`).
4. **Generator:** Deterministic extractive synthesizer by default (`extractive`). Generates zero hallucinated or generative claims. Optional local Ollama integration (`ollama`).

---

## 2. Prerequisites

- **Python:** 3.10+ (tested with 3.10 and 3.11)
- **Node.js:** 18+ (tested with 20+)
- **System Memory:** Minimum 4 GB RAM recommended for SentenceTransformer embedding cache and Chroma in-memory index.
- **Disk:** ~1 GB for corpus, vector indices, and virtual environments.

---

## 3. Installation & Build

### 3.1 Backend Setup
```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3.2 Frontend Production Build
```bash
cd web
npm ci
npm run build
cd ..
```
The build artifacts will be written to `web/dist`. The FastAPI backend serves these static files directly if `RAG_STATIC_DIR` is set to `web/dist`.

---

## 4. Configuration & Environment Variables

Copy the provided template to configure the environment:
```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HOST` | `127.0.0.1` | Network interface to bind. Use `0.0.0.0` inside containers. |
| `PORT` | `8000` | Port for the HTTP API. |
| `RAG_GENERATOR` | `extractive` | Answer generation strategy (`extractive` or `ollama`). |
| `RAG_CORS_ORIGINS` | Localhost origins | Comma-separated list of allowed origins. Restrict in production. |
| `RAG_CSP_FRAME_ANCESTORS` | `'none'` | Allowed frame ancestors for Content-Security-Policy. |
| `RAG_STATIC_DIR` | `web/dist` | Directory containing built static frontend assets. |
| `RAG_ENABLE_DEBUG` | `1` | Whether clients can request debug timing and routing payloads. |
| `SURA_LOG_QUERIES` | `0` | If `0`, query strings are hashed via SHA-256 for privacy. If `1`, raw queries are logged. |
| `SURA_LOG_JSON` | `1` | Outputs machine-readable structured JSON logs per request. |
| `SURA_RATE_LIMIT_PER_MINUTE` | `60` | Per-client IP rate limit per 60 seconds (0 to disable). |
| `SURA_INTENT_AWARE` | `0` | Phase 3 feature flag (default: OFF). |
| `SURA_SECTION_SELECTION` | `0` | Phase 3 feature flag (default: OFF). |
| `SURA_ADDITIONAL_EVIDENCE` | `0` | Phase 3 feature flag (default: OFF). |

---

## 5. Production Startup

### 5.1 Direct Uvicorn Execution
```bash
python -m uvicorn scripts.rag_api:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info
```
> [!NOTE]
> Single-worker execution is strongly recommended when running on a single host to avoid duplicating the in-memory SentenceTransformer and Chroma embeddings model across multiple processes. For multi-node scaling, run independent single-worker containers behind a load balancer.

### 5.2 Systemd Service Definition (`/etc/systemd/system/sura.service`)
```ini
[Unit]
Description=SURA SAP Utilities Documentation Assistant
After=network.target

[Service]
Type=simple
User=sura
WorkingDirectory=/opt/sura
EnvironmentFile=/opt/sura/.env
ExecStart=/opt/sura/.venv/bin/uvicorn scripts.rag_api:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

---

## 6. Health Checks & Monitoring

The API provides dedicated operational endpoints:

1. **Liveness Probe:** `GET /health`
   - Returns `HTTP 200 {"status": "ok", "process": "live"}` if the Python process is alive.
2. **Readiness Probe:** `GET /ready`
   - Validates that:
     - Vector retriever is loaded and initialized.
     - Document corpus is populated (at least 25 pages).
     - Generator model is responsive (if using Ollama).
   - Returns `HTTP 200` with topic counts when ready, or `HTTP 503` if initializing or impaired.
3. **Structured Observability:**
   - Every `/api/chat` request generates a structured JSON log entry on stdout containing `request_id`, SHA-256 query hash, selected chunks, latency breakdown (`timings_ms`), and validation metrics.
