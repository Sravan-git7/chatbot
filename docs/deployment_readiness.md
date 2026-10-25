# Deployment Readiness — SURA SAP Utilities RAG (synthetic-verified)

## Scope
- Source PDFs: 29 cards (M2C-01..M2C-29). M2C-18 identity conflict (9442486404b54071b4ebeab6a16628e7 vs e4375c1cad104b2eb7d027369bd76638) remains **excluded_conflicting_identity** — 28 admitted, 1 excluded, fail-closed. Verified via `data/page_corpus/manifest.json` (28 ingested) with `TAU 0.6 / SHIPPED_TAU 0.5 / min_support 0.6` thresholds unchanged.
- Protected vector stores (`data/vector_store/chroma.sqlite3`, `data/vector_store/page_collection/chroma.sqlite3`) **do not exist in this sandbox and were not accessed**; all verification uses `data/page_corpus/manifest.json`, `chunks.json`, `master_data.json` and ephemeral `chromadb.EphemeralClient` fixtures. Retrieval weights `W_CARD 0.50 / W_PAGE 0.40 / W_COVERAGE 0.10 / W_TECH 0.10` preserved.
- M2C-18 status confirmed via `data/page_corpus/manifest.json`: `corpus_status: excluded_conflicting_identity`.

## 1. Code changes preserved (working-tree diff at HEAD c02e908)
9 files changed, 230 insertions / 52 deletions — no destructive git, no protected DB access, no commit/push:
- `scripts/rag_elaborate.py` — head-weight fallback requires `own ∩ focus` or `new_terms`; elaboration `standalone_novel` + `has_shown_single` + min-2 novel enforces genuine new evidence.
- `scripts/rag_evidence.py` + `scripts/rag_generate.py` — `verify_support_chain`/`verify_grounding` allow duplicate `[S#]` only same `chunk_id` (split-chunk fixtures); `cited_text` joins all texts for marker; thresholds unchanged.
- `scripts/rag_evidence.py` `_append_comparison_section` — renders `list_items` for comparison intents (fixes `technical vs business master data` truncated to headers).
- Other preserved: `scripts/rag_pipeline.py` card-first + concept-pairing + secondary-topic budget (≤4 for comparisons), `scripts/phase13_reranker.py` weights + coverage/code channels + overview penalty, `scripts/rag_api.py` readiness/liveness/CORS/auth.
- `benchmarks/run_quality.py` + `tests/*` — synthetic guide/page fallback + ephemeral fixtures.

## 2. Production configuration, readiness vs liveness, and API security — audited (no persistent-store access)
- `scripts/rag_api.validate_configuration()` — `SURA_PROFILE` local/production, `SURA_API_TOKEN` 32-256 ASCII no whitespace, `SURA_ALLOWED_HOSTS` required non-wildcard in production, `SURA_RATE_LIMIT_PER_MINUTE` ≥0, `SURA_MAX_CONCURRENT_REQUESTS` ≥1, `RAG_CORS_ORIGINS` wildcard forbidden in production, `RAG_CSP_FRAME_ANCESTORS` wildcard forbidden, `SURA_LOG_QUERIES`/`RAG_ENABLE_DEBUG` and experimental flags (`SURA_INTENT_AWARE`/`SURA_SECTION_SELECTION`/`SURA_ADDITIONAL_EVIDENCE`) forbidden in production. Invalid production config → startup `503` fail-closed, no listening socket.
- `/health` = liveness (always 200 when process live, even if stores missing). `/ready` = readiness (checks service non-None, retriever non-empty, corpus non-empty, `health_check()` pass, Ollama probe via guard chain → `503` with `retriever_unavailable|index_unavailable|model_unavailable|service_not_ready` otherwise). `/api/health` = UI-facing status (mirrors `/ready` with `svc.info()` and `debug_enabled`). Gate traffic on `/ready`, not `/health` — see `docs/DEPLOYMENT.md` §§2-3.
- `create_app()` — `CORSMiddleware` `allow_credentials False`, `allow_methods GET,POST,OPTIONS`, explicit `allow_headers`, production CORS defaults to `[]` (no implicit `localhost:5173`), `TrustedHostMiddleware` only in production. Auth: `Authorization: Bearer <token>` via `secrets.compare_digest`, 401 + `WWW-Authenticate: Bearer`, no credential logging. Body limit `MAX_BODY_BYTES 16384` enforced via both `Content-Length` and streaming `consume_body` with 10s deadline (413/408), `X-Request-Id` validated or minted, security headers `X-Content-Type-Options/Cache-Control/Content-Security-Policy(frame-ancestors)`, per-IP rate limit + `MAX_IP_BUCKETS 4096` expiration, concurrent admission cap `SURA_MAX_CONCURRENT_REQUESTS` (429), shutdown drain 5s, structured logs hash query via HMAC in production (no raw query leak).
- No blocker prevents local development; public boundary requires external TLS-terminating reverse proxy + authentication — see tier table below.

## 3. User-visible RAG behaviors verified (EphemeralClient, fake_embed, 28 pages)
- Specific procedures outrank generic overview via reranker domain overlap + overview penalty.
- Comparison questions retrieve balanced evidence for both sides: Move-In vs Move-Out (4 sources), Billing vs Invoicing (3 sources) via secondary-topic + concept-pairing; explicit relationship disclosure when no explicit compare sentence; missing side disclosed (e.g., budget-billing hold → `unable_to_verify`).
- Multi-part answers use supported parts; missing part via `aspect_limitation`/`procedural_limitation`.
- Follow-up: `elaborate`/`why`/`second step`/`compare` resolve against active topic; bare `explain further` without context → clarification; industry mismatch rejected; conversation isolation via `conversation_id` + TTL + cache key (`norm_q, generator, corpus_sha, evidence_threshold, ood_min_coverage, k_chunks, ...`) without leak.
- Every factual claim supported by cited source: `verify_grounding` `LOW_SUPPORT <0.6`/`TOKEN_NOT_IN_CONTEXT`/`NO_CITATION`; duplicate markers only same-chunk allowed; missing evidence → `UNABLE_TO_VERIFY`/`NO_ADDITIONAL_VERIFIED_EVIDENCE`/`out_of_scope`/`documentation_unavailable` with fixed safe messages.

## 4. Tests actually executed (safe isolated, no protected DB)
Backend:
```
SURA_TEST_ISOLATED=1 python -m pytest tests/test_multi_document_retrieval.py tests/test_qa_defect_fixes.py tests/test_adversarial_rag.py tests/test_rag_generalization.py tests/test_rag_response.py tests/test_causal_evidence.py tests/test_followup_state.py tests/test_followup_elaboration.py tests/test_followup_resolution.py tests/test_ephemeral_rag_pipeline.py tests/test_rag_evidence_quality.py tests/test_response_quality_fixes.py tests/test_security_audit.py tests/test_source_corpus.py tests/test_source_manifest.py tests/test_phase11_service.py tests/test_phase11_api.py tests/test_predeployment_hardening.py tests/test_phase16_context.py tests/test_phase17a_evidence.py -q
→ 360 passed, 30 skipped, 1 warning, 169 subtests passed (30 skipped = live-store/ollama/model-unavailable; no protected store touched)

python -m pytest tests/test_release_runtime.py -v → 35 passed (production auth, stateless recovery, unsafe-prod fail-closed, body-limit without Content-Length, IP bucket cap, HMAC query hash, owned-client lifecycle, vector-contract dimension/model, factory-owned close, TLS/host checks)
```
Frontend:
```
npm --prefix web run build → 296 modules, 367kB JS gzip 114kB pass
npm --prefix web run test   → 124 passed, 1 skipped across 12 files (app.test.tsx 43, sura_ux 6 (1 skipped), abstention 4, messageView 9, markdown 9, structuredAnswer 8, api 12, followup 12, util 10, storage 6, typography 4, dependencySecurity 2)
```

Manual ephemeral checks (`scripts/ephemeral_service.py` `build_ephemeral_service()`):
- `Compare Move-In and Move-Out` → answered 4 cites grounded=True (S1 Move-in, S3 Move-Out)
- `Compare Billing and Invoicing` → answered 3 cites (S1 Billing, S2 Invoicing)
- `What is technical vs business master data?` → answered 1 cite with full bullet expansion
- `steps in clearing process` / `contract account` → answered 2 cites
- `budget billing hold` → unable_to_verify, `capital of France` → out_of_scope, injection → out_of_scope, `M2C-18` → documentation_unavailable

All with `chromadb.EphemeralClient`; `ls data/vector_store/*.sqlite3` → no such file.

## 5. Reproducible local run (loopback, no auth)
```bash
python -m venv .venv && source .venv/bin/activate  # 3.11 required for lock file; 3.10 uses ranged requirements.txt
python -m pip install --upgrade pip
python -m pip install -r requirements.lock.txt       # Linux 3.11 byte-identical closure (1338 pins) — or: pip install -r requirements.txt -r requirements-phase11.txt gt-all-minilm-l6-v2
cd web && npm ci && npm run build && cd ..
# Extractive (default, no Ollama): model via M2C_MODEL_DIR or gt-all-minilm-l6-v2 wheel; no HF download
SURA_PROFILE=local RAG_GENERATOR=extractive python -m uvicorn scripts.rag_api:create_app --factory --host 127.0.0.1 --port 8000 --log-level info
# dev UI: cd web && npm run dev  # Vite 0.0.0.0:5173 proxies /api → :8000
curl http://127.0.0.1:8000/health            # 200 liveness
curl http://127.0.0.1:8000/ready             # 200 readiness (or 503 with missing stores/model)
curl http://127.0.0.1:8000/api/health       # UI-facing, includes topics/pages_available
SURA_TEST_ISOLATED=1 python -m pytest tests/test_release_runtime.py tests/test_multi_document_retrieval.py -q
```
Corpus source: 29 PDFs → `data/page_corpus/manifest.json` + `chunks.json` (310 chunks, 28 ingested) — see `docs/DEPLOYMENT.md` §3 for provision-vs-rebuild; never rebuild into protected `data/vector_store/`.

## 6. Deployment tiers and remaining blockers
| Tier | Config | Verified here | Remaining (requires authorized staging) |
|---|---|---|---|
| **Local-only dev** | `SURA_PROFILE=local`, loopback `127.0.0.1:8000`, `RAG_GENERATOR=extractive`, `RAG_STATIC_DIR=web/dist`, no token/hosts | ✅ Synthetic retrieval, API/CORS/body-limit/auth-negative paths, frontend build/tests, liveness/ready logic (synthetic) | Live persistent-store recall not validated (stores absent) |
| **Private behind HTTPS reverse proxy** | `SURA_PROFILE=production`, `SURA_API_TOKEN` (32-256 ASCII, secret-manager), `SURA_ALLOWED_HOSTS` non-wildcard, explicit `RAG_CORS_ORIGINS`, `RAG_CSP_FRAME_ANCESTORS='none'`, `RAG_ENABLE_DEBUG=0`, `SURA_LOG_QUERIES=0`, experimental flags 0, TLS termination + auth boundary at proxy | ✅ Config validation fail-closed, stateless production chat, CORS/host/auth negative cases, 429/413/408 paths, HMAC log redaction, owned-client lifecycle | **Blocker 1:** Persistent vector-store recall — requires staging with provisioned `data/vector_store/*.sqlite3` (`tests/test_phase14_recall.py` + golden benchmark on Linux). **Blocker 2:** Deployed HTTPS/authentication boundary — requires operator-provisioned reverse proxy verification (not built by this repo). Both are external prerequisites; code itself is staged. |
| **Public internet** | Same as private + public WAF/IdP audit, rate-limit tuning, observability | ❌ Not claimed | Same as private + independent security review; do not expose `uvicorn` directly. |

Other documented limitations: M2C-18 conflicting LOIOs stay `excluded_conflicting_identity` (no guess/ingest); lexical grounding only (no semantic entailment NLI); Ollama `llama3.2:3b` not live-tested (extractive remains default and is never silently substituted — `502 generator_failed` / `503 model_unavailable`).

## 7. Explicit confirmations
- ✅ Protected `data/vector_store/chroma.sqlite3` and `data/vector_store/page_collection/chroma.sqlite3` not opened/queried/hashed/copied/repaired/rebuilt/migrated — verified `ls` no such file, tests `EphemeralClient` only.
- ✅ M2C-18 exclusion preserved with both LOIOs.
- ✅ `git stash list` empty (4 prior stashes already in base commit), no `reset --hard`/`clean`/destructive restore; working tree only 9 intended diffs; no commit/push/merge/deploy.
- ✅ Thresholds `TAU 0.6 / SHIPPED_TAU 0.5 / MIN_SENTENCE_SUPPORT 0.6` and weights `W_CARD 0.50 / W_PAGE 0.40 / W_COVERAGE 0.10` unchanged; no hard-coded Q/A or topic-ID exceptions.

## 8. Single next action
Provision protected stores in authorized staging and run persistent-store recall gate — the sole check that can move tier 2 from synthetic-verified to production-approved.
