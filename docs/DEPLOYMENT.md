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

The API stack is pinned in `requirements-phase11.txt`; `requirements.txt` retains minimum-version ranges for the retrieval stack. The direct Chroma/Sentence Transformers/Ollama-client versions above match the tested versions recorded in `requirements.txt`; the model-wheel pin is the only published PyPI version retrieved for this audit.

**Byte-for-byte environment reproduction:** `requirements.lock.txt` holds the locked runtime/test closure (127 pins; pip/setuptools bootstrap tooling excluded) of the environment the release suite and the benchmark baseline were verified on (Python **3.11**, Linux). Install it with `python -m pip install -r requirements.lock.txt` in a fresh 3.11 venv. The complete closure requires Python ≥3.11 (numpy/scipy/scikit-learn/filelock/networkx/onnxruntime/rpds-py/websockets declare `>=3.11`); on a Python **3.10** interpreter (e.g. an existing 3.10.11 venv) do **not** use the lock file as-is — install with the ranged command above instead and let pip resolve 3.10-compatible versions. That produces a *different, non-byte-identical* closure which this repository's CI has not verified; treat results from it as environment-specific.

Alternatively to the model wheel, place an approved local model directory somewhere outside Git and set `M2C_MODEL_DIR` to its absolute path; it must contain at least `model.safetensors` and `tokenizer.json`. No personal Hugging Face cache path is required by any runtime code path: resolution order is `--model-path` → `$M2C_MODEL_DIR` → the `gt-all-minilm-l6-v2` pip package; if none provides the weights, startup fails with an explicit `FileNotFoundError` telling you exactly which of those to supply. There is no automatic Hugging Face download or fallback to a generative model.

### Windows line endings and hash-pinned files

`data/phase7_checkpoint.md` pins SHA-256 hashes of file **bytes**, and tests such as `tests/test_phase7b.py` and `tests/test_chunk_candidates.py` verify them. Historically, checkouts on Windows with `core.autocrlf=true` rewrote LF text files to CRLF on disk, every pinned hash mismatched, and those two suites failed for environment reasons (the "blocked legacy tests"). The repository now carries a `.gitattributes` with `* -text`, which disables **all** Git line-ending conversion so every platform checks out the exact stored bytes (historical CRLF-blob artifacts keep their CRLF bytes too — nothing is renormalized and no pinned hash changes).

An **existing** Windows checkout created before `.gitattributes` still has CRLF-converted files on disk. Refresh it once, safely:

```powershell
# First preserve local edits (including untracked files), then update by fast-forward only.
git stash push -u -m "pre-hardening verification backup"   # only if git status shows edits
git fetch origin
git merge --ff-only origin/arena/b450cda2-chatbot
# Materialize stored bytes without reset/clean/history changes:
python scripts/refresh_checkout_bytes.py --apply
# Keep the stash until verification succeeds; restore separately, resolving conflicts safely.
```

The refresh helper refuses to write if tracked files differ from HEAD after newline normalization; it preserves untracked/ignored directories and verifies exact blob bytes. No reset or clean is used. Untracked/ignored directories (`av\`, `scratch\`, `chroma_db\`, `.venv\`, `data\vector_store\`, `web\node_modules\`) are **not** touched by this procedure. Afterwards run `python -m pytest tests/test_phase7b.py tests/test_chunk_candidates.py -q`. **Native Windows caveat:** the sealed, checkpoint-pinned chunk-candidate writer uses `Path.write_text()` without an explicit newline, so generated candidates can still use CRLF and fail its byte-equivalence test. `.gitattributes` fixes checkout bytes, not Python-generated output. This gate remains unverified on native Windows; do not skip or weaken it. The complete suite is verified on Linux. Use WSL/Linux for exact sealed-artifact reproduction until an explicitly approved versioned producer/checkpoint migration is available.

### Legacy `chroma_db/` directory

Older working copies may contain a root-level `chroma_db/` (the pre-Phase-4 vector store, collection `sap_docs`). It is **inert**: no runtime or evaluation code reads it, the current stores live in `data/vector_store/` (cards) and `data/vector_store/page_collection/` (pages), and `build_card_collection.py`/`build_page_collection.py` actively refuse those legacy names/paths. It is untracked and git-ignored. Keeping it is harmless; deleting it cannot affect the shipped system — but nothing requires deleting it.

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

Provision the complete card store at `data/vector_store/` and the complete page store at `data/vector_store/page_collection/` (for example, mount them as persistent read-only runtime assets). Keep each Chroma database with the collection it was built for. Expected collection names are `sap_m2c_card_v1` and `sap_pages_v1`; both use cosine distance. Current manifests describe 29 card vectors and 113 page chunks, but those counts must be verified against the supplied databases.

Startup now fails readiness for missing/empty required stores, an incompatible page distance metric, or card/page vector counts inconsistent with their collection metadata when those counts are present. These checks do **not** recompute every embedding/content hash or prove that a supplied store matches every checked-in manifest field. Validate the build manifests and corpus fingerprints when promoting replacement indexes.

### Rebuild from the checked-in source inputs

Install the requirements/model first, then run from the repository root:

```bash
# The checked-in retrieval units/page corpus are sealed inputs, not things to regenerate.
# In a FRESH checkout (stores absent), write new build manifests to scratch, not over provenance:
mkdir -p /tmp/sura-build
python scripts/build_card_collection.py --manifest /tmp/sura-build/cards.json
python scripts/build_page_collection.py --manifest /tmp/sura-build/pages.json
```

The card/page builders write vector stores to the default locations above. Do not use `--rebuild` on an existing user store without a verified backup and explicit intent: it deletes and recreates its named collection. The commands above preserve the checked-in corpus/manifests; scratch build manifests must be compared to the stored expected counts/fingerprints before promotion. To keep a deployed checkout immutable, use each script’s `--out`, `--units`, `--token-stats`, `--manifest`, `--out-dir`, and `--vector-dir` options to direct generated artifacts to an approved build workspace or persistent volume.

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
| `RAG_GENERATOR` | `extractive` | `extractive` or optional `ollama`. With `ollama`, `/ready` probes the local server and configured model and reports `503 model_unavailable` when either is missing; chat requests then fail closed with `502 generator_failed` (never a fabricated answer, never a silent fallback to extractive). |
| `SURA_OLLAMA_TIMEOUT_SECONDS` | `60` | Finite Ollama HTTP connect/read/write/pool timeout (seconds). Invalid, non-positive or non-finite values fall back to 60. Readiness is separately bounded at 5 seconds. This is a network-operation timeout, not an interruptible wall-clock deadline for arbitrary Python code. |
| `SURA_QUEUE_TIMEOUT_SECONDS` | `30` | FIFO request/generation queue wait deadline. Expiry returns HTTP 504 `request_timeout`, removes the waiter and does not mutate conversation state or leak a slot. Invalid settings fall back to 30 seconds. |
| `M2C_MODEL_DIR` | unset | Optional absolute path to local model files; no download is attempted. |
| `RAG_STATIC_DIR` | repository `web/dist` | Built frontend directory served by the API. |
| `RAG_CORS_ORIGINS` | localhost development origins | Comma-separated exact origins. Same-origin UI/API deployment does not require cross-origin access. If a separate browser origin is deliberately used, configure CORS and account for the current UI Content-Security-Policy `connect-src 'self'`; the frontend is designed for same-origin API requests. |
| `RAG_ENABLE_DEBUG` | `0` | Allows debug payloads when requested (`1`/`true`/`yes`). Off by default; debug requests are rejected with 403 while it is off. Leave it at `0` in production unless debug output is explicitly needed. |
| `RAG_CSP_FRAME_ANCESTORS` | `'none'` | CSP `frame-ancestors` value; the CSP keyword needs its literal apostrophes (for example, `'none'`). |
| `SURA_LOG_QUERIES` | `0` | Hashes query text in structured request logs by default. Set to `1` only if raw-query logging is approved. |
| `SURA_RATE_LIMIT_PER_MINUTE` | `60` | Per-client-IP request limit; `0` disables that limit. Rejections: HTTP 429 + `Retry-After: 60`. |
| `SURA_MAX_CONCURRENT_REQUESTS` | `4` | Fail-fast admission cap on simultaneously in-flight chat requests. Rejections: HTTP 429 + `Retry-After: 1` (standard error envelope, code `rate_limited`). Admitted requests beyond `RagService.max_concurrency` (4) queue FIFO inside the service (`queue_wait_ms` in debug telemetry), and actual LLM generation is serialized (`generation_concurrency` 1) — raising the cap therefore converts fast rejections into graceful queuing, not unbounded parallel generation. Must be an integer ≥ 1; invalid values fail startup validation. |
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

The factory form can initialize the API, but it does not call the CLI structured-logging setup. Use the recommended CLI for production verification, or supply an operator logging configuration explicitly before using the factory form:

```bash
python -m uvicorn scripts.rag_api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --log-level info
```

The factory alone is not the fully verified production logging entrypoint. It takes generator/configuration values from the process environment; Uvicorn’s explicit host/port options control the socket. One worker avoids duplicating the model and in-process conversation/rate-limit state on a small host. If deploying multiple workers/replicas, account for separate memory use and per-process state.

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

The backend imposes a finite Ollama network-operation timeout (60 seconds by default) and a FIFO queue wait deadline (30 seconds by default), but does not interrupt arbitrary Python/C++ execution with a hard wall-clock request deadline. The browser API client aborts a chat request after 60 seconds (including response-body reading); configure any reverse proxy/load balancer for a timeout longer than that or deliberately change the client timeout.

## 6. Health and operational behavior

- `GET /health` is **liveness**: it can return 200 while required artifacts are missing.
- `GET /ready` is **readiness**: it checks the service, non-empty page collection, admitted corpus, card collection health, and Ollama availability when selected. It returns 503 when a required check fails.
- `GET /api/health` is the UI-facing startup/service summary and returns 503 if startup could not construct the service. Use `/ready` for orchestration because it runs the store/readiness checks.
- `POST /api/chat` returns a service-not-ready 503 rather than an answer when startup failed.

The lifespan intentionally captures essential-artifact startup errors instead of terminating the process: this allows liveness diagnostics, but it does **not** mean the deployment is ready. Gate traffic on `/ready` (not `/health`). Missing local model files, the card store, the page store, or the local corpus must be provisioned before the service can answer. A fresh checkout excludes the ignored vector stores and embedding weights. The current pre-deployment pass provisioned them and verified real-store extractive startup, HTTP smoke and golden-reference evaluation on Linux; native Windows and real Ollama inference remain separate pending gates. See `PRE_DEPLOYMENT_AUDIT.md`.

## Pre-deployment verification (no public deployment)

See `LOCAL_PRODUCTION_VERIFICATION.md` for the compact Windows procedure and `benchmarks/README.md` for repeatable measurements. No public deployment was performed by this hardening pass.

Request bodies are capped on **received bytes** (16 KiB), including chunked bodies with no Content-Length, and must arrive within 10 seconds (HTTP 408 on expiry). Request identifiers are bounded ASCII tokens; arbitrary header text is not forwarded into logs. Unexpected request exception logs retain only the exception type, not its message/traceback.
