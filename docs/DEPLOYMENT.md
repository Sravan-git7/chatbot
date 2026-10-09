# SURA deployment guide

This guide describes the current React/FastAPI application and the local artifacts it needs. No public deployment is performed by this repository audit.

## 1. Runtime layout and required artifacts

- **UI and API:** The Vite-built React UI is served by FastAPI from `web/dist`. Browser requests use relative `/api/...` URLs, so the supported production layout is one origin for UI and API. In development, Vite proxies `/api` to the Python process.
- **Card router index:** Chroma collection `sap_m2c_card_v1` in `data/vector_store/` (`chroma.sqlite3` at that directory).
- **Page-chunk index:** Chroma collection `sap_pages_v1` in `data/vector_store/page_collection/`.
- **Admitted page text:** `data/page_corpus/` and its manifest. This corpus records which registered topic cards have locally admitted page text; it is separate from the page vectors.
- **Embedding model:** local `all-MiniLM-L6-v2` files. Runtime and index-building code use offline/local files only; they do not fetch model weights on demand.
- **Generation:** `extractive` is the default deterministic, evidence-grounded generator. `ollama` is optional and requires a separately managed local Ollama service/model.

The checked-in card/page collection manifests describe expected collection names, counts, configuration, and provenance; **they are not the Chroma stores**. `data/vector_store/` is git-ignored and is absent from a fresh checkout unless it is provisioned separately. Do not infer that an index exists from the manifest counts.

## 2. Install the runtime

Python 3.11 is the tested target noted in `requirements.txt`; the checked-in model provenance path reflects a Windows/Python 3.10 installation, so validate the complete stack on the target platform. Use the repository root as the working directory:

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-phase11.txt \
  "chromadb==1.5.9" "sentence-transformers==6.1.0" "ollama==0.6.3" \
  "gt-all-minilm-l6-v2==0.1.0"
```

The API stack is pinned in `requirements-phase11.txt`; `requirements.txt` retains minimum-version ranges for the retrieval stack. The direct Chroma/Sentence Transformers/Ollama-client versions above match the tested versions recorded in `requirements.txt`; the model-wheel pin is the only published PyPI version retrieved for this audit. The repository does not include a complete transitive dependency lock, so use a deployment-specific lock/wheelhouse if byte-for-byte environment reproduction is required. Alternatively, place an approved local model directory somewhere outside Git and set `M2C_MODEL_DIR` to its absolute path; it must contain at least `model.safetensors` and `tokenizer.json`. An explicit `--model-path` used by a build script takes precedence over `M2C_MODEL_DIR`. There is no automatic Hugging Face download or fallback to a generative model.

Build the UI (Node.js 20+ recommended; `npm ci` uses the checked-in lockfile):

```bash
cd web
npm ci
npm run build
cd ..
```

The default static directory is `web/dist`. If the build is deployed elsewhere, set `RAG_STATIC_DIR` to that directory. The API still runs without a UI build, but it will not serve the React app.

## 3. Provision or reproduce the local data stores

### Supply prebuilt stores

Provision the complete card store at `data/vector_store/` and the complete page store at `data/vector_store/page_collection/` (for example, mount them as persistent read-only runtime assets). Keep each Chroma database with the collection it was built for. Expected collection names are `sap_m2c_card_v1` and `sap_pages_v1`; both use cosine distance. Current manifests describe 29 card vectors and 106 page chunks, but those counts must be verified against the supplied databases.

Startup now fails readiness for missing/empty required stores, an incompatible page distance metric, or card/page vector counts inconsistent with their collection metadata when those counts are present. These checks do **not** recompute every embedding/content hash or prove that a supplied store matches every checked-in manifest field. Validate the build manifests and corpus fingerprints when promoting replacement indexes.

### Rebuild from the checked-in source inputs

Install the requirements/model first, then run from the repository root:

```bash
python scripts/build_retrieval_units.py
python scripts/validate_token_lengths.py
python scripts/build_card_collection.py --rebuild
python scripts/page_corpus.py
python scripts/build_page_collection.py --rebuild
```

The card and page builders write to the default locations above. Each `--rebuild` deletes and recreates **only its named collection**; the page builder does not modify the card collection. The rebuild commands also write manifests and the earlier card preparation commands write generated retrieval-unit/token-stat files under `data/`. Review those generated files before committing them. To keep a deployed checkout immutable, use each script’s `--out`, `--units`, `--token-stats`, `--manifest`, `--out-dir`, and `--vector-dir` options to direct generated artifacts to an approved build workspace or persistent volume.

The page-corpus builder consumes the repository’s saved verified page material and does not download SAP Help pages. Building either vector index requires the exact local model/tokenizer and the project’s build dependencies. Preserve the model/index provenance alongside any copied store.

## 4. Environment and secrets

`.env.example` is a template, **not an automatically loaded file**. Neither `python scripts/rag_api.py` nor a plain Uvicorn invocation reads `.env` by itself. Supply values with the process environment, a service manager, or explicitly source the file in a shell. For example, from the repository root on Linux/macOS:

```bash
cp .env.example .env
set -a
. ./.env
set +a
export HOST=0.0.0.0
python scripts/rag_api.py
```

Systemd’s `EnvironmentFile=` is another option. Protect any real `.env` file and do not commit secrets. `HOST` and `PORT` are read by the Python CLI; direct Uvicorn factory startup takes explicit `--host`/`--port` arguments.

| Variable | Default | Effect |
| :--- | :--- | :--- |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | CLI bind address and port. Use `0.0.0.0` only when the service must be reachable through a container/proxy. Explicit CLI flags override these defaults. |
| `RAG_GENERATOR` | `extractive` | `extractive` or optional `ollama`. |
| `M2C_MODEL_DIR` | unset | Optional absolute path to local model files; no download is attempted. |
| `RAG_STATIC_DIR` | repository `web/dist` | Built frontend directory served by the API. |
| `RAG_CORS_ORIGINS` | localhost development origins | Comma-separated exact origins. Same-origin UI/API deployment does not require cross-origin access. If a separate browser origin is deliberately used, configure CORS and account for the current UI Content-Security-Policy `connect-src 'self'`; the frontend is designed for same-origin API requests. |
| `RAG_ENABLE_DEBUG` | `1` | Allows debug payloads when requested. Set to `0` for production unless debug output is explicitly needed. |
| `RAG_CSP_FRAME_ANCESTORS` | `'none'` | CSP `frame-ancestors` value; the CSP keyword needs its literal apostrophes (for example, `'none'`). |
| `SURA_LOG_QUERIES` | `0` | Hashes query text in structured request logs by default. Set to `1` only if raw-query logging is approved. |
| `SURA_RATE_LIMIT_PER_MINUTE` | `60` | Per-client-IP request limit; `0` disables that limit. A separate in-process concurrency cap is also enforced. |
| `SURA_INTENT_AWARE`, `SURA_SECTION_SELECTION`, `SURA_ADDITIONAL_EVIDENCE` | `0` | Experimental Phase 3 flags. Keep off; deployment configuration does not enable them. |

Structured JSON request records are emitted by the API; there is no `SURA_LOG_JSON` toggle. The API does not provide user authentication or TLS termination; place it behind the organization’s approved access-control/TLS boundary and do not expose it directly to an untrusted network.

## 5. Startup

`scripts/rag_api.py` defines `create_app()`; it does **not** export a module-level `app` object. Therefore `uvicorn scripts.rag_api:app` is not a valid target.

Recommended CLI startup (uses `HOST`, `PORT`, and `RAG_GENERATOR` from the process environment):

```bash
python scripts/rag_api.py
# or override the environment defaults explicitly
python scripts/rag_api.py --host 0.0.0.0 --port 8000 --generator extractive
```

A valid Uvicorn ASGI-factory form is:

```bash
python -m uvicorn scripts.rag_api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --log-level info
```

The factory takes generator/configuration values from the process environment; Uvicorn’s explicit host/port options control the socket. One worker avoids duplicating the model and in-process conversation/rate-limit state on a small host. If deploying multiple workers/replicas, account for separate memory use and per-process state.

Example systemd unit (set production environment values in the referenced `EnvironmentFile`):

```ini
[Unit]
Description=SURA SAP Utilities Documentation Assistant
After=network.target

[Service]
Type=simple
User=sura
WorkingDirectory=/opt/sura
EnvironmentFile=/opt/sura/.env
ExecStart=/opt/sura/.venv/bin/python /opt/sura/scripts/rag_api.py
Restart=on-failure
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

The backend does not impose a separate per-request generation timeout. The browser API client aborts a chat request after 60 seconds (including response-body reading); configure any reverse proxy/load balancer for a timeout longer than that or deliberately change the client timeout.

## 6. Health and operational behavior

- `GET /health` is **liveness**: it can return 200 while required artifacts are missing.
- `GET /ready` is **readiness**: it checks the service, non-empty page collection, admitted corpus, card collection health, and Ollama availability when selected. It returns 503 when a required check fails.
- `GET /api/health` is the UI-facing startup/service summary and returns 503 if startup could not construct the service. Use `/ready` for orchestration because it runs the store/readiness checks.
- `POST /api/chat` returns a service-not-ready 503 rather than an answer when startup failed.

The lifespan intentionally captures essential-artifact startup errors instead of terminating the process: this allows liveness diagnostics, but it does **not** mean the deployment is ready. Gate traffic on `/ready` (not `/health`). Missing local model files, the card store, the page store, or the local corpus must be provisioned before the service can answer. The current checkout audited here does not include the ignored vector stores or local model files, so a live production startup and real-store golden run have not been validated from this checkout.
