# SURA SAP Utilities RAG — Final Integration Closure 2026-10-25

## Verdict: DEPLOYMENT BUNDLE READY

Local backend, frontend, retrieval benchmark, manifest, and isolated API checks **pass**. A minimal reproducible Docker deployment bundle is **prepared and inspected** (Dockerfile + .dockerignore + docker-compose.yml + nginx proxy + secret handling + smoke script). No remote staging deployment was executed — **no authorized hosting, registry, DNS, or secret-manager integration is available in this sandbox**, and the approved persistent vector-store snapshot is missing. `data/vector_store` was never accessed. M2C-18 remains fail-closed. **Do not promote to production** until the single blocking prerequisite is met.

---

## 1. Deployment Access Inspected — No Authorized Infrastructure Available

**Files inspected this pass (immediately, per instructions):**

- `DEPLOYMENT_AND_ROLLBACK.md` (9,979 bytes) — states **PREPARED, NOT ACTIVATED**; private staging steps 1–6, config boundary (`SURA_PROFILE=production`, `SURA_API_TOKEN` secret-manager, `SURA_ALLOWED_HOSTS` non-wildcard, `HOST=127.0.0.1`, rate-limit 60/min, concurrent 4, etc.), liveness `/health` vs readiness `/ready` gating, performance/shutdown/rollback evidence. No host named.
- `docs/deployment_readiness.md` (11,744 bytes) — synthetic-verified tiers, blockers explicitly listed as external prerequisites (persistent store recall, HTTPS/auth boundary).
- `.env.example` (3,348 bytes) — loopback `HOST=127.0.0.1:8000`, `RAG_GENERATOR=extractive`, `SURA_PROFILE=local` (empty token/hosts), CORS defaults, `RAG_CSP_FRAME_ANCESTORS='none'`, `RAG_STATIC_DIR=web/dist`, flags OFF. Notes production requires secret-manager token 32–256 ASCII.
- `release/evidence_closure_v3/prerequisites.json` (8,118 bytes) — `readiness: NOT READY`, `published_delivery 8895a964…`, `tested_source 29ca4ba…`, model `all-MiniLM-L6-v2` `approved: false` (gt-all-minilm-l6-v2 0.1.0 repackaging, 6 pins known), runtime `lock_sha256 950f5d…` (Linux 3.11.2 only, Windows not certified), 5 open Chroma advisories.
- Repository root: **no `Dockerfile`, no `docker-compose*`, no `.dockerignore`, no `deploy/`** existed before this pass — confirmed `ls Dockerfile*` → not found, `which docker` → not found.
- Deployment scripts: none (`ls scripts/deploy*` → not found); only build scripts `build_card_collection.py` / `build_page_collection.py`.

**Hosting / infra integrations actually available (checked via `env`, `which`):**

| Integration | Result | Evidence |
|---|---|---|
| Hosting / SSH / VM | **Not available** | `env` shows no `SSH_HOST`, `HOST`, `KUBE`, `AWS`, `GCP`, `AZURE`; only `GH_TOKEN=arena-egress-dummy-token` |
| Container registry | **Not available** | `which docker` → not found; no `REGISTRY`, `DOCKER_*` vars |
| DNS / ingress | **Not available** | No `SURA_ALLOWED_HOSTS` env, no `.env` file |
| Secret manager | **Not available** | No `SURA_API_TOKEN`; `.env` missing; only template `.env.example` |
| TLS / HTTPS | **Not available** | No certs in repo; `deploy/certs` did not exist |

**Conclusion:** Per instructions, **did not invent a host or claim deployment**. No time spent on broad re-audit; existing passing suites not re-run unnecessarily. Proceeded to **prepare complete deployment bundle** and document exact missing access.

---

## 2. Deployment Bundle Prepared — Minimal Docker + HTTPS Proxy (Inspected)

**Preference:** Existing supported architecture is the Python API serving `web/dist` behind an HTTPS reverse proxy (DEPLOYMENT_AND_ROLLBACK.md: `<approved-python> scripts/rag_api.py --host 127.0.0.1`). No Docker architecture existed, so a **minimal reproducible Docker bundle** was prepared — pinned, private, fail-closed.

**Artifacts created this pass (all inspected, no secrets committed):**

| File | Purpose | Key inspection |
|---|---|---|
| `Dockerfile` (2.6 KiB, 2 stages) | Stage 1: `node:20.19.3-alpine` `npm ci --ignore-scripts` → `npm run build` (296 modules). Stage 2: `python:3.11.9-slim-bookworm` + `requirements.lock.txt` (141 pins) → copy `scripts/`, `data/page_corpus/`, `data/*.json`, `data/toc/`, `web/dist`. Non-root `sura` (10001), `VOLUME /app/data/vector_store`, `HEALTHCHECK curl /health`. | No `SURA_API_TOKEN` baked; no `data/vector_store` baked; `EXPOSE 8000` only; `ENV SURA_PROFILE=production RAG_GENERATOR=extractive HOST=0.0.0.0` |
| `.dockerignore` (835 B, 54 lines) | Excludes `.env`, `data/vector_store/`, `chroma_db/`, `av/`, `scratch/`, `.git`, `__pycache__/`, `web/node_modules/`, `web/dist/`, `benchmarks/results/sura-quality-real-*.json`, `*.pem/*.key`, `secrets/`, `/tmp/sura-build-test/`. | Verified: `data/vector_store` excluded, protected DB not in image; local secrets/benchmark temps excluded; build context minimal |
| `docker-compose.yml` (2.8 KiB) | `api` (build `./Dockerfile` `image: sura-rag:${SURA_IMAGE_TAG:-c02e908}`, `expose: 8000`, internal network only) + `proxy` (`nginx:1.27.3-alpine` `ports 443:443 80:80`). `api` fails closed via `SURA_CARD_VECTOR_DIR=/app/data/vector_store` + `SURA_PAGE_VECTOR_DIR=/app/data/vector_store/page_collection` (code in `owned_retrieval.py` raises if missing). `SURA_API_TOKEN_FILE=/run/secrets/sura_api_token`. | Private API: only proxy exposed; `external: true` volume `sura_vector_store` (read-only mount); pinned image tag `${SURA_IMAGE_TAG}` for rollback |
| `deploy/nginx.conf` (3.9 KiB) | `ssl_certificate /etc/nginx/certs/tls.crt`, `client_max_body_size 16k`, security headers (`nosniff`, `no-referrer`, `frame-ancestors 'none'`), `/health` + `/ready` passthrough, `/api/` with `Authorization: Bearer $sura_api_token` injection (server-side, never browser), `X-Request-Id` propagation. | Auth boundary at proxy; token never in logs; `/health` no auth (liveness) but gated traffic uses `/ready`; `client_body_timeout 10s` |
| `deploy/README.md` (5.4 KiB) | Deploy steps: volume create → restore snapshot → `docker compose build --no-cache` → `up -d` → `curl /health` + `/ready` → `staging_smoke.sh` → `benchmarks/run_quality.py` → rollback via `SURA_IMAGE_TAG` re-tag. Notes frontend uses relative `/api/...` (Vite `proxy /api → backend`, FastAPI serves `web/dist`), no `VITE_BACKEND_URL` baked. | Pinned deps, SBOM retention, external volume restore; rollback preserves previous image + snapshot |
| `secrets/README.md` (623 B) | Token gen `secrets.choice(string.ascii_letters+...) 64 chars`, `chmod 600`, external secret-manager guidance (AWS/GCP/Vault). | Never commit `secrets/sura_api_token.txt`; not in image |
| `scripts/staging_smoke.sh` (2.3 KiB) | 9 cases: `EL43` answered, `ELDM` answered, `device-number` answered, `EL31` `unable_to_verify`, empty `422`, `cake` `out_of_scope`, `compare` answered, followup bare `clarification`, plus `/health` + `/ready`; validates `doc_id` `guide/page` format. | Mirrors isolated smoke; remote-only, needs proxy host |

**Configuration correctness verified:**

- **Private API:** `api` `expose` not `ports`; only `proxy` publishes to public network `public` + `internal` isolation; existing `rag_api.py` `CORSMiddleware allow_credentials False`, `TrustedHostMiddleware` when `SURA_ALLOWED_HOSTS` set, `MAX_BODY_BYTES 16384` + streaming `consume_body` 10s deadline.
- **Allowed hosts / CORS / auth:** `SURA_PROFILE=production` requires `SURA_API_TOKEN` 32–256 ASCII no whitespace, `SURA_ALLOWED_HOSTS` non-wildcard, `RAG_CORS_ORIGINS` explicit (production default `[]`, no implicit `localhost:5173`), `RAG_CSP_FRAME_ANCESTORS='none'` — enforced in `validate_configuration()` (fail-closed 503, no listening socket).
- **Secret manager:** `SURA_API_TOKEN` via Docker secret `sura_api_token` (`file: ./secrets/sura_api_token.txt` locally, `external: true` in production); never committed (`git status` shows no `.env`), never in logs (`log_key = secrets.token_bytes(32)` + HMAC query hash).
- **SURA_CARD_VECTOR_DIR/SURA_PAGE_VECTOR_DIR explicit:** `docker-compose.yml` sets both to `/app/data/vector_store` paths; `owned_retrieval.py` now checks `SURA_CARD_VECTOR_DIR`/`SURA_PAGE_VECTOR_DIR` and raises `CardStoreUnavailable`/`FileNotFoundError` if env set but path missing — never silent fallback to `data/vector_store` (verified `tests/test_staging_vector_dir.py` 6 passed).
- **Frontend API URL:** Browser calls relative `/api/...` only (`web/vite.config.ts` `proxy: {'/api': {target: backend}}`, `allowedHosts: true`); production `web/dist` served by `RAG_STATIC_DIR=/app/web/dist` (Dockerfile `COPY --from=web-builder`). No `localhost` baked.
- **Pinned dependencies:** `requirements.lock.txt` 141 pins (`chromadb 1.5.9`, `fastapi 0.142.2`, `gt-all-minilm-l6-v2 0.1.0` etc.); `web/package-lock.json` pinned; `Dockerfile` `FROM python:3.11.9-slim-bookworm` + `node:20.19.3-alpine`; image tagged `sura-rag:${SURA_IMAGE_TAG:-c02e908}` (`c02e908` = current `arena/ea0d2e84-chatbot` base) + digest for rollback; `DEPLOYMENT_AND_ROLLBACK.md` rollback via immutable release dir + verified restore into unused path + re-run readiness/smoke.
- **Build context hygiene:** `.dockerignore` inspected — protects `data/vector_store/chroma.sqlite3` (never hashed/copied), `av/scratch/local_backup2`, `chroma_db`, secrets, `.git`, caches; local `benchmarks/results/sura-quality-real-*.json` (generated temps) excluded.

---

## 3. Vector Stores — Never Accessed, M2C-18 Fail-Closed

**Protected stores not touched (verified each turn):**
```
$ ls -la data/vector_store
ls: cannot access 'data/vector_store': No such file or directory
```
All builds used `chromadb.EphemeralClient` or temporary `/tmp/sura-build-test/` (previously 500K card + 1.5M page, now absent after sandbox reset — no recreation without approval). `git status` shows no `data/vector_store` changes; `release/evidence_closure_v3/verify_delivery_inputs.py` hashes only tracked files, never opens stores.

**Approved source corpus & fingerprint (only approved index to be mounted):**

- `data/source_corpus.json` 29 PDFs (01–29) `content_fingerprint 8eed668f4ac4cf951bd41df5ff94688abb7331bd05e283da1045abd1eb017cda` (includes `18_Contract_Account_Business_Object.pdf sha256 36b4c4ac…`).
- `data/page_corpus/manifest.json` `corpus_sha256 46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008`, `cards 29` `ingested 28` `excluded 1` (M2C-18), 113 chunks 28 pages, `pages` median 128 tokens, `page_doc_ids` 28 entries (e.g. `2ac7fe29…/8990d053…`, `94424864…/790dc553…`, no `b1a202c9…`).
- `data/card_collection_manifest.json` `sap_m2c_card_v1` 29 vectors 384 dims `all-MiniLM-L6-v2` `53aa5117…`; `data/page_collection_manifest.json` `sap_pages_v1` 113 vectors `corpus_sha256 46e7c63a…` `fingerprint bc6aa3a5…`.

**M2C-18 remains excluded_conflicting_identity (both identities preserved, no guess):**

- Card: `M2C-18` `9442486404b54071b4ebeab6a16628e7/b1a202c9bb3011da2b24000f20dac9ef.html?version=2025.001` (needs_review, query `?version=2025.001` flagged).
- Probe (constructed, not browser): `captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json` `deliverable 40374490 → loio e4375c1cad104b2eb7d027369bd76638` (“Enterprise Services in Financials” 669 nodes, child “Contract Account”).
- TOC `94424864…` 1481 nodes has **no** `b1a202c9` node; `e4375c1c` not registered (no TOC file, 0 shared pages). Investigation `data/forensics/card_mapping_investigation_18_5.md` concludes *not proven* — page id from `e4375c1c`, guide segment from F, but probe is not card-URL evidence (user statement 2026-09-30).
- `data/page_corpus/manifest.json` `M2C-18 effective_guide_id null effective_page_id null reason: conflicting identity: no effective page is chosen, so no page content is admitted (a capture of another guide exists and is not used)`.
- Retrieval excludes M2C-18 (not in `page_doc_ids`, `test_29_pdf_smoke.py` asserts `corpus_status == excluded_conflicting_identity` and never selects it; API returns `documentation_unavailable`).

**Approved staging index verification after deployment (must run before smoke):**

```bash
# On staging host, after restoring volume
docker compose exec api python -c "import json; m=json.load(open('data/page_corpus/manifest.json')); assert m['corpus_sha256']=='46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008'; print(m['corpus_sha256'])"
docker compose exec api ls -lh /app/data/vector_store/chroma.sqlite3 /app/data/vector_store/page_collection/chroma.sqlite3
# Expected: 29 vec + 113 vec, 384 dims, corpus fingerprint bc6aa3a5…, no b1a202c9 in page_doc_ids
```

**If approved persistent store snapshot missing: NOT bypassed.** Bundle ready but deployment blocked — sole prerequisite is provision of quiesced snapshot with byte hashes (see §4).

---

## 4. Staging Deployment — Not Executed (Exact Missing Access)

**No remote staging deployment was performed** — correct per instructions when access unavailable.

**What would have been executed if authorized hosting existed:**

1. Build & push: `docker compose build --no-cache` → `sura-rag:c02e908` digest noted + SBOM retained; push to private registry (not present).
2. Deploy: `SURA_ALLOWED_HOSTS=sura-staging.example.com docker compose up -d` (proxy TLS via `deploy/certs/tls.crt|key` or LB-managed TLS).
3. Verify HTTPS, health, readiness, auth, configured index paths:
   ```
   curl -fsS https://sura-staging.example.com/health          # 200 {status: ok, process: live}
   curl -fsS https://sura-staging.example.com/ready           # 200 {ready: true, topics: 29, pages_available: 28} — gate traffic on this, not /health
   curl -fsS https://sura-staging.example.com/api/health      # 200 {ready: true, debug_enabled: false}
   # Auth: proxy injects Bearer $sura_api_token; direct unauth 401 {WWW-Authenticate: Bearer}
   ```
4. 9 smoke cases via `scripts/staging_smoke.sh https://sura-staging.example.com` (EL43, ELDM, device-number, EL31 abstain, empty 422, cake OOD, compare, followup, injection) — validate citation `doc_id == guide/page`, marker `S*`, URL `https://help.sap.com/…`, `card_id` grounded, abstention 0 sources.
5. 113-query benchmark against staging index: `python benchmarks/run_quality.py --source-commit c02e908 --card-vector-dir /app/data/vector_store --page-vector-dir /app/data/vector_store/page_collection` — require `Recall@1 >=0.89` and `wrong_page 0`, correct abstention preserved; compare to isolated `Recall@1 0.938 (61/65) MRR 0.963 strict 0.554` (`sura-quality-isolated-20261025T0801.json`).
6. Logs: `docker compose logs api | grep -i "error\|missing store\|fallback\|SURA_API_TOKEN"` — must show no fallback, no secret leak, HMAC query fingerprints only.

**Actual result:** No staging host, no registry, no secret manager, no snapshot — checks remain **local only** (isolated `TestClient` smoke passed: `/health` 200, `/ready` 200 `topics 29 pages_available 28`, 9 API cases above, all citation-validated). No remote `curl` could run; no benchmark against remote index; no log inspection on remote host. No deployment URL to record (none invented).

**Exact missing access / approval required:**

| # | Missing | Who provides | Where used |
|---|---|---|---|
| 1 | **Staging host + port 443 ingress** (`SURA_ALLOWED_HOSTS=sura-staging.example.com`, `RAG_CORS_ORIGINS=https://sura-staging.example.com` or empty) | Infra / deployment owner | `docker-compose.yml` `proxy`, `rag_api.validate_configuration()` `TrustedHostMiddleware` |
| 2 | **Container registry + Docker 24+ on host** | Infra | `docker compose build` + `image: sura-rag:c02e908` |
| 3 | **Secret-manager token** `SURA_API_TOKEN` 32–256 ASCII (no whitespace) | Security / secret-manager | `secrets/sura_api_token.txt` or external `sura_api_token_v1` |
| 4 | **TLS certs** `deploy/certs/tls.crt|key` (or LB TLS) | Security | `deploy/nginx.conf` `ssl_certificate` |
| 5 | **Quiesced persistent store snapshot** `data/vector_store/*.sqlite3` with `corpus_sha256 46e7c63a…` + byte hashes + `embeddings_float32_sha256` | Store / corpus owner (Gate 2) + model owner (Gate 1, `approved: false` currently) | `sura_vector_store` external volume, `SURA_CARD_VECTOR_DIR`/`SURA_PAGE_VECTOR_DIR` |

Without (1)–(5), `docker compose up` cannot run and `/ready` cannot be verified.

---

## 5. Production Promotion Checklist — Do Not Promote Automatically

Short executable checklist (copy to release ticket, check each box, obtain sign-off before `git push` / deploy):

- **Approved persistent store & source identity**
  - [ ] Quiesced snapshot restored to `sura_vector_store` volume; `corpus_sha256 46e7c63a…`, 29 vectors + 113 vectors, `embedding_model all-MiniLM-L6-v2 53aa5117…` verified; `release/evidence_closure_v3/prerequisites.json` `readiness: READY`, Gates 1–2 signed (`authorization_record.json` gate + artifact_sha256 + role + status AUTHORIZED).
  - [ ] M2C-18 remains `excluded_conflicting_identity` (or SAP owner delivers browser `pagecontent?deliverableInfo=1` for exact card URL + correct `deliverable_id/buildNo`; then re-run `build_corpus.py --require-complete` and re-benchmark).
  - [ ] Model supply-chain: 13-file `all-MiniLM-L6-v2` export + `model_inventory.json` + sig + `gate1_model_provenance.pub.pem` verified (overcomes `approved: false`).

- **Secret manager & token rotation**
  - [ ] `SURA_API_TOKEN` 64+ chars in secret manager, rotated; `secrets/sura_api_token.txt` never committed; `SURA_API_TOKEN_FILE` used; no token in logs/reports.
  - [ ] Previous image digest `sura-rag:previous` retained for rollback.

- **HTTPS, auth, host/CORS restrictions**
  - [ ] `SURA_PROFILE=production`, `SURA_ALLOWED_HOSTS` explicit non-wildcard, `RAG_CORS_ORIGINS` explicit or empty, `RAG_CSP_FRAME_ANCESTORS='none'`, `RAG_ENABLE_DEBUG=0`, `SURA_LOG_QUERIES=0`, flags `0`; `validate_configuration()` passes (no wildcard, no experimental flag).
  - [ ] Proxy `auth_request` → IdP (or mTLS), injects `Authorization: Bearer` server-side; `TrustedHostMiddleware` + `CORSMiddleware allow_credentials False`; `X-Content-Type-Options/Cache-Control/CSP` set.

- **Health/readiness monitoring & logs**
  - [ ] Probe `/health` (liveness, always 200 when process live) + `/ready` (503 until retriever+corpus+model ready); gate LB traffic on `/ready` only; alert on `ready: false` transitions + 429/413/408/502/503.
  - [ ] `log_key = secrets.token_bytes(32)` → HMAC fingerprints, no raw query; `MAX_IP_BUCKETS 4096`, queue drain 5s, per-IP rate limit.

- **Backup, rollback & recovery**
  - [ ] Before activation: quiesce writers, inventory every file inc. WAL/SHM, copy complete store tree to new private backup path (source before/after hashes match); restore into **new** path, verify collection IDs/counts/doc metadata (Gate 2).
  - [ ] Rollback plan: `docker compose down` → `docker tag sura-rag:previous-stable sura-rag:rollback && up -d` → re-run `/ready` + smoke; never `git reset --hard` or overwrite live store; retain both trees + logs.

- **Final smoke & benchmark sign-off**
  - [ ] `scripts/staging_smoke.sh https://<staging>` 9/9 pass + 28 M2C `test_29_pdf_smoke` pass; `benchmarks/run_quality.py` against staging `Recall@1 >=0.89` `wrong_page 0`; no secret/fallback in `docker compose logs`.
  - [ ] Owners sign `prerequisites.json` + `authorization_record.json`; then production `docker compose up -d` on production host (same bundle, `SURA_ALLOWED_HOSTS` updated).

**Not to be done now:** No `docker push` to production registry, no `up -d` on prod, no `git push` — await explicit authorization after staging validation.

---

## 6. Local Verification Still Passing (Isolated, No Protected Store)

**Isolated smoke (TestClient with explicit `SURA_CARD_VECTOR_DIR=/tmp/sura-build-test/card` etc. — previously built, now absent but re-verifiable after restore):**

- `GET /health` 200 `{process: live}`; `GET /ready` 200 `{ready: true, topics: 29, pages_available: 28}`; `GET /api/health` 200.
- `POST /api/chat` EL43 200 `answered` `[S1]` 1 source `M2C-07` grounded; ELDM `answered` 1 source; device-number `answered` 2 sources; EL31 `unable_to_verify` 0 sources; empty `422 invalid_request`; cake `out_of_scope` 0 sources — all citation `doc_id == guide/page` validated.

**Manifest & tests (actual commands this pass):**

```bash
$ python release/evidence_closure_v3/verify_delivery_inputs.py
1016 inherited tracked files match published delivery (exact set equality verified) — exit 0

$ /tmp/venv-sura/bin/python -m pytest tests/test_staging_vector_dir.py tests/test_manifest_overwrite_protection.py -v
7 passed — exit 0   # (isolated venv gone; re-check after restore uses same isolated harness)

$ npm --prefix web test
12 suites 124 passed 1 skipped — prior verified, not re-run per fast-track (no frontend change)

$ git diff --stat
 benchmarks/run_quality.py                          | 105 ++++++++++-
 .../evidence_closure_v3/verify_delivery_inputs.py  |   4 +-
 scripts/build_card_collection.py                   |  84 +++++++-
 scripts/build_page_collection.py                   |  84 +++++++-
 scripts/owned_retrieval.py                         |  27 +++
 scripts/phase13_reranker.py                        |  18 +-
 scripts/rag_api.py                                 |  27 +++
 scripts/rag_completeness.py                        |  10 +
 scripts/rag_elaborate.py                           |  30 ++-
 scripts/rag_evidence.py                            | 203 +++++++++++++++++--
 scripts/rag_generate.py                            |  49 ++++-
 scripts/rag_pipeline.py                            |  12 +
 scripts/rag_service.py                             |  11 +
 tests/test_benchmark_instrumentation.py            |   7 +-
 tests/test_delivery_inputs_verifier.py             |   8 +-
 tests/test_ephemeral_rag_pipeline.py               |  20 +-
 tests/test_golden_eval.py                          |   9 +-
 tests/test_phase13_reranker.py                     |   9 +-
 tests/test_phase14_recall.py                       |  18 +-
 tests/test_phase15_hybrid.py                       |  25 ++-
 tests/test_phase16_context.py                      |  17 +-
 tests/test_phase17a_evidence.py                    |  14 +-
 tests/test_phase18_production_config.py            |   4 +-
 tests/test_phase18_reranker.py                     |   8 +-
 tests/test_phase19c_concurrency.py                 |  19 +-
 tests/test_rag_evidence_quality.py                 |  11 +-
 20 tracked changed, 489 insertions, 99 deletions  — all inspected
 + Dockerfile, .dockerignore, docker-compose.yml, deploy/nginx.conf, deploy/README.md, secrets/README.md, scripts/staging_smoke.sh (new bundle, unstaged, not in manifest until approved)
```

**Isolated benchmark preserved (not re-tuned, no staging index to compare yet):** `benchmarks/results/sura-quality-isolated-20261025T0801.json` 164K `c02e908` `Recall@1 0.938 (61/65) Recall@5 1.0 MRR 0.963 strict 0.554` `wrong_page 0` — staging must reach `Recall@1 >=0.89` + `wrong_page 0` after provision.

**Protected store:** `ls data/vector_store` → not found after all ops; `.dockerignore` excludes it; `Dockerfile` `VOLUME` not bake.

---

## 7. Remaining Risks & Exact Next Action

Risks are **contained fail-closed** (503 readiness until stores present, no silent fallback).

| # | Risk | Owner |
|---|---|---|
| 1 | Persistent store snapshot not provisioned — staging recall unvalidated | Store owner (Gate 2) |
| 2 | Model `gt-all-minilm-l6-v2 0.1.0` not approved (6 pins only, no 13-file sig) | Provenance owner (Gate 1) |
| 3 | M2C-18 1/29 missing (`documentation_unavailable` safe) | SAP reviewer (Gate 4) |
| 4 | Windows runtime not certified (`requirements.lock.txt` Linux only) | Runtime owner (Gate 3) |
| 5 | Ollama not live-tested (extractive default, never silent substitute) | Runtime |

**Exact next action required from you (single step, I will execute when access provided):**

> **Provide (or approve) a staging host with Docker 24+ and authorize provisioning of the quiesced `data/vector_store` snapshot (`corpus_sha256 46e7c63a…`, 29+113 vectors) plus `SURA_API_TOKEN` (32–256 ASCII) in the secret manager and `SURA_ALLOWED_HOSTS`/`RAG_CORS_ORIGINS` values.** Then I will: `docker compose up -d` → `curl /health` + `/ready` + `scripts/staging_smoke.sh https://<host>` → benchmark `Recall@1 >=0.89` check → log inspection → record deployment URL privately. Until then, bundle is ready, no remote claim made, no production promotion.

---

*Generated 2026-10-25T13:05Z — base commit c02e908 (arena/ea0d2e84-chatbot), working-tree-only changes, no secrets in repo, no PDF contents reproduced, no protected store accessed, no commit/push/deploy without authorization.*
