# SURA — SAP Utilities Documentation Assistant — Release Readiness Report

Date: 2026-10-13 · Branch: `arena/b450cda2-chatbot` · Final commit: `a6b1b53` · Prepared by: release engineering (Agent Mode)

## Release status

**READY WITH EXPLICIT LIMITATIONS**

The backend RAG pipeline, API security posture, frontend, and evaluation harness are verified green end-to-end on
the current 28-page corpus. A final blocker-resolution pass (commit `a6b1b53`, on top of the `9be6553` release)
found and fixed two production-honesty defects that the green test suite did not catch — an Ollama `/ready`
false-success and a structured-logging handler that silently dropped records under the documented production start
(Section B items 13–15) — each now covered by regression tests and live-verified. Every limitation listed in
Section C is known, documented, fail-safe (never fabricates an answer), and does not block deployment of the
shipped `extractive` configuration.

---

## A. Executive summary

| Area | Result |
| --- | --- |
| Backend test suite (`tests/`) | **1338 passed, 225 subtests passed, 0 failed** (1 warning) |
| Frontend unit tests (`web/`, vitest) | **115 passed, 1 skipped** across 11 files |
| Frontend typecheck (`tsc --noEmit`) | clean (exit 0) |
| Frontend production build (`vite build`) | clean — `web/dist/` produced (296 modules; JS 366 kB / gzip 114 kB, CSS 41 kB) |
| Live API smoke (extractive generator) | `/health`, `/ready`, `/api/health`, chat, follow-up, fail-closed, CORS, rate-limit, body-size, SPA paths all correct |
| Ollama readiness (generator `ollama`, model absent) | `/health` 200 · `/ready` **503 model_unavailable** (fail-closed) · `/api/chat` **502 generator_failed** — no false success, no fabricated answer, no silent extractive fallback |
| Structured request logging (production start) | one-line JSON records emitted on stdout; query text hashed by default (`SURA_LOG_QUERIES=0`) |
| Debug endpoint security | off by default; debug requests rejected with **403** |
| Corpus | 29 registered topic cards, **28 admitted pages**, 113 page chunks |
| Identity | 25 identified_not_local · 2 corrected (M2C-01, M2C-05) · 1 resolved_local_page (M2C-17) · **1 conflicting (M2C-18, fail-closed)** |

---

## B. Issues resolved this engagement (root cause → fix → regression test)

1. **M2C-01 (Topic 1) wrong source identity.** Root cause: card #1's map-root URL under guide `021b182b` actually
   resolves to the "Master Data" guide `e52c8ee6` (SAP redirect; verified against saved capture evidence).
   Fix: machine-checked correction recorded in `data/topic_corrections.json`; identity now `corrected_identity` in
   `data/m2c_page_identity.json` (`3a832d40…`); page admitted to the corpus under its true guide. The card's
   authoritative source URL is deliberately kept as the source of record (metadata-only correction).
   Regression: `tests/test_corrections.py`, `tests/test_source_corpus.py` (asserts corrections == [1, 5], both keep
   their original `authoritative_source`), `tests/test_phase7g.py` `EXPECTED_IDENTITY` (M2C-01 → corrected_identity).
2. **M2C-13 / M2C-16 unverifiable identities → verified.** Machine verification under guide `021b182b`
   (`identified_not_local`), pages admitted via verified captures; corpus grew 7 → 28 pages. Regression:
   `tests/test_elaboration_followup.py::test_N…` now asserts all three topics are answered **strictly from their own
   page** (`source_id == card_id` for every cited source).
3. **M2C-18 conflicting identity.** Two different guides claim the card page; no mapping is invented. The topic stays
   **fail-closed**: `documentation_unavailable` with an honest topic reference, never an assembled answer.
   Regression: `tests/test_phase11_guards.py`, `tests/test_elaboration_followup.py::test_N…`, phase 8/12 invariant
   `m2c18_never_answered`.
4. **Follow-up hijack.** Root cause: the focused unavailable-topic gate ran before follow-up resolution and rerouted
   relational follow-ups onto sibling topics. Fix: `expected_topic` guard in `scripts/rag_pipeline.py` (~:473–495)
   plus session `active_topic` merge in `scripts/rag_service.py` (~:499–540). Explicit caller context must not wipe a
   conversation-established topic. Regression: follow-up suites (95 passed / 146 subtests at introduction; now part
   of the 1338-green run).
5. **Bare elaboration with explicitly empty context must fail closed.** Root cause: the session-topic merge from
   fix #4 also fired for an explicitly empty caller context (`{"questions": []}`). Fix: merge only when the caller
   context carries substantive history (non-empty `questions` or an `answer`); otherwise the request keeps failing
   closed with `ELABORATION_CONTEXT_MISSING` (`scripts/rag_service.py`). Regression:
   `tests/test_followup_state.py::APIElaborationRequestContract…`.
6. **Debug-config mismatch / debug security.** Root cause: debug payloads were reachable unless explicitly denied.
   Fix: `RAG_ENABLE_DEBUG` defaults to `0` (`scripts/rag_api.py:244`); debug requests return **403** while it is off
   (`:379`); tests enable debug per-app via `create_app(enable_debug=True)`, never globally — the production default
   stays locked. Docs corrected: `docs/DEPLOYMENT.md` now states default `0` and the 403 behavior. Regression:
   `tests/test_phase11_api.py` (42 passed), `tests/test_phase12_questions_and_env.py`.
7. **Evidence-quality filter regression (config-fragment lead-ins).** Root cause:
   `rag_evidence.is_incomplete_list_leadin` kept a colon-ended lead-in whenever any list items were attached, even
   when every attached item was a bare `Label : Value` configuration fragment; the lead-in then leaked a useless
   block into answers. Fix: reject such lead-ins together with their list (`scripts/rag_evidence.py`, new
   `_QUALITY_CONFIG_LIST_ITEM`). Noun-phrase lists (e.g. master-data objects) are unaffected — they remain
   legitimate evidence with their lead-in. Regression: `tests/test_rag_evidence_quality.py` (18 passed),
   `tests/test_phase2_fixes.py` (master-data lists preserved), `tests/test_elaboration_followup.py::test_Q…`.
8. **Evaluator/verifier desync (procedural-limitation answers).** Root cause:
   `scripts/evaluate_phase11_1.py::chain_ok` did not exempt procedural-limitation notices while the shipped verifier
   `rag_evidence.verify_support_chain` does; six phase-12 composer answers were misreported as support-chain
   failures. Fix: `chain_ok` now skips procedural-limitation sentences exactly like the shipped verifier (content
   sentences still must match verbatim). Regression: `tests/test_phase12_eval_audit.py` (31 passed) and live
   `verify_support_chain` parity.
9. **Stale Phase-12 evaluation artifacts.** Root cause: sealed results were recorded on the old 7-page corpus.
   Fix: `data/evaluation/phase12_results.json` + `phase12_performance.json` regenerated on the 28-page corpus with
   the sealed query set unchanged (freeze `3c5a9ddd…`, 113 queries); ollama configs recorded honestly as BLOCKED
   (`NO_OLLAMA_EXECUTABLE` / `OLLAMA_SERVER_NOT_RESPONDING`); failure audit regenerated
   (`data/evaluation/phase12_failure_audit.json`). Regression: `tests/test_phase12_eval_audit.py`,
   `tests/test_phase12_questions_and_env.py` (18 passed).
10. **Stale legacy tests (corpus-count / topic-correction assumptions)** — fixed without weakening assertions:
    - `tests/test_source_corpus.py`: asserts **both** corrections [1, 5] with exact guide prefixes and unchanged
      authoritative sources (was [5]-only). Required rebaselining the Phase-7 integrity chain — see item 12.
    - `tests/test_elaboration_followup.py::test_N`: replaced the stale "four missing pages" assumption (25/29 era)
      with the verified truth — M2C-18 fail-closed assertions kept verbatim; the three now-verified topics assert
      answered-from-own-page with per-source card checks (stronger than before).
    - `tests/test_elaboration_followup.py::test_Q`: enforces the stated contract — noun-phrase list items are
      forbidden **isolated, without their list introduction** (matching the phase-2 master-data contract); bare
      configuration items and heading fragments remain absolutely forbidden.
    - `tests/test_phase10.py` + `tests/test_phase11_guards.py`: pins re-baselined for the regenerated corpus-coupled
      artifacts; Phase 10 re-selection re-run honestly (Section E).
    - `tests/test_phase19a_latency.py::test_08_context_equivalence`: the direct-reproduction now applies the exact
      same deterministic `ordered_workflow_evidence` selection the pipeline applies, and asserts the
      `context_selection` debug block both ways (12 passed).
    - Follow-up suites no longer require `RAG_ENABLE_DEBUG` globally — they pass `enable_debug=True` per app, so the
      production default stays `0` (root-cause fix, not a workaround).
11. **Health/readiness honesty.** `/ready` and `/api/health` report `pages_available` = pages actually admitted and
    searchable (28), not the 29 registered cards; readiness fails closed on missing/empty stores. Verified live
    (Section D). Stale "25/29" comment in `scripts/rag_api.py` corrected.
12. **Phase-7 protected-artifact chain rebaselined (documented).** The legitimate stale-test fix in
    `tests/test_source_corpus.py` changed a file pinned by the Phase-7 checkpoint. The integrity chain was
    rebaselined honestly, in order: `data/phase7_checkpoint.md` (entry `4552cd5f…`), then
    `tests/test_phase7b.py` (checkpoint pin `348d5bd1…`), then `tests/test_phase7g.py` (checkpoint + test_phase7b
    pins `348d5bd1…` / `c73c38fb…`). All 222 checkpoint entries verified; protected-set tests pass
    (`tests/test_phase7a.py`, `test_phase7b.py`, `test_phase7g.py` — 129 passed combined). No protected data
    artifact was altered; `data/source_corpus.json` stays sealed at `0ee5cb8b…` because Phase 4/5 provenance
    (`card_collection_manifest.source_corpus_file_sha256`, retrieval units, Phase 4/5 reports) is bound to it.

### Final blocker-resolution pass (commit `a6b1b53`, on top of the `9be6553` release)

The following were found by inspecting the shipped code paths against the live server — not from the report — and
each slipped past a green suite because the tests exercised object shapes or logging setups that never occur in the
shipped configuration. All are fixed at the root cause, live-verified, and now carry regression tests.

13. **Ollama `/ready` false-success (fail-open readiness).** Root cause: the readiness probe used a single-level
    `gen.client or gen.inner.client` lookup and an `hasattr(client, "check_available")` gate. The shipped chain is
    `GeneratorGuard → EvidenceGuard → LLMGenerator → OllamaClient` (and `RagService` re-wraps the generator, so the
    real depth is 4), which the one-level lookup could not traverse; and the shipped `OllamaClient` had no
    `check_available`, so the `hasattr` gate skipped the check entirely. `/ready` therefore reported
    `ready:true, generator:"ollama"` while the model was unreachable, and the next `/api/chat` failed with a 502 —
    a false success. Fix: (a) `rag_generate.OllamaClient.check_available(timeout=5.0)` — a bounded probe that lists
    local models and matches the configured model strictly (exact, or implicit `:latest` for an untagged name),
    never raises, and treats an injected `chat` stub as available without touching the network; (b) `rag_api`
    `/ready` walks the guard chain (bounded ≤8 `.client`/`.inner` hops) and **fails closed** — no probe found →
    `503 model_unavailable` ("cannot be verified"), probe False → `503 model_unavailable` ("not reachable"). Also
    added an opt-in `SURA_OLLAMA_TIMEOUT_SECONDS` so a hung local server cannot hold a request and a concurrency
    slot indefinitely (unset = ollama default; invalid/non-positive ignored; the readiness probe is always bounded).
    Live-verified with `--generator ollama` and no Ollama installed: `/health` 200, `/ready` **503
    model_unavailable**, `/api/chat` **502 generator_failed** ("No answer was produced") — never a fabricated answer,
    never a silent extractive fallback. Regression: `tests/test_health_ready.py` (shipped-chain traversal via
    `build_service`, probeless fail-closed, `check_available` units with a fake `ollama` module, timeout wiring) —
    15 passed.
14. **Structured request logs silently dropped under the production start.** Root cause: `sura.structured` had no
    handler, so `structured_logger.info(json.dumps(record))` propagated to the root logger, whose last-resort handler
    emits WARNING and above only — every INFO record was dropped under the documented `python scripts/rag_api.py`
    start, even though `docs/DEPLOYMENT.md` states the records are emitted. The observability tests passed only
    because they attach their own handler. Fix: `_configure_structured_logging()` in `rag_api`, called from `main()`
    (the CLI production start) rather than at import, so embedding tests keep full control of the logger. It is
    idempotent, defers to any pre-existing operator handler, attaches exactly one stdout handler with a raw
    `%(message)s` formatter (one JSON object per line), sets INFO, and disables propagation. Live-verified: a chat
    request now emits a single-line JSON record (request_id, route, selected/retrieved chunk ids, validator results,
    latency, config/corpus hash, status, http_status) with the query **hashed** by default. Regression:
    `tests/test_observability.py::test_production_start_configures_structured_stdout_logging` (attaches one stdout
    handler, idempotent, emits raw JSON, defers to an operator handler) — 5 passed.
15. **M2C-18 disposition made machine-checked (still fail-closed, still unresolved).** The M2C-18 identity remains
    `conflicting_identity` and fail-closed — no authoritative guide/page mapping could be established from verified
    evidence, and none was invented. `tests/test_map_root_identity.py` was strengthened from a one-line assertion
    into a machine check against the repository's own saved evidence: the card's claimed identity is preserved
    verbatim (guide `94424864…`, page `b1a202c9…`), the card guide's verified TOC does **not** contain the page
    (`page_is_toc_node` False), the conflict records both reasons
    (`PAGE_NOT_A_NODE_OF_CARD_GUIDE_TOC`, `PAGE_SEEN_IN_OTHER_DELIVERABLE`), and the existence-only probe capture
    (deliverable `40374490` / loio `e4375c1c…`, unregistered, not the card guide) is never used as an effective
    guide. The precise missing evidence is documented in Section C item 1.

---

## C. Explicit limitations (the reason status is not unconditional)

1. **M2C-18 (Contract Account Business Object) remains unresolved and fail-closed.** The card names guide
   `9442486404b54071b4ebeab6a16628e7` (registered + verified, 1481-node TOC) and page
   `b1a202c9bb3011da2b24000f20dac9ef`, but that page is **not** a node of the card guide's verified TOC. The only
   evidence the page exists is a captured `http.svc/pagecontent` API response for deliverable `40374490` whose loio is
   `e4375c1cad104b2eb7d027369bd76638` ("Enterprise Services in Financials") — a guide that is **not** registered and
   **not** verified, and the capture proves only that the page exists inside that deliverable, not that SAP serves the
   card's original public URL from it. Identity is therefore `conflicting_identity`
   (`PAGE_NOT_IN_CARD_GUIDE_TOC_PAGE_SEEN_ELSEWHERE`); no mapping is invented and the topic answers
   `documentation_unavailable` with an honest topic reference. **Missing evidence to resolve it (either one):**
   (a) a capture of the card's exact public URL showing it resolves/redirects to a *registered+verified* guide whose
   TOC contains `b1a202c9…`; or (b) a verified TOC + guide registration for `e4375c1c…` (deliverable 40374490) that
   lists `b1a202c9…` as a node, plus authority that the card should point there instead of `94424864…`.
   `help.sap.com` is unreachable in this sandbox, so neither can be produced here; resolution requires SAP-side
   source confirmation. Regression: `tests/test_map_root_identity.py` (machine-checked, Section B item 15).
2. **Real Ollama/model inference is not verified in this sandbox** (`NO_OLLAMA_EXECUTABLE`, server not responding);
   the phase-12 ollama configurations are recorded honestly as BLOCKED in `data/evaluation/phase12_results.json` — no
   fake LLM numbers. The shipped and evaluated default is the deterministic `extractive` generator. **The readiness
   and error-handling contract for the `ollama` path is, however, now fixed and live-verified** (Section B item 13):
   a missing/unreachable model makes `/ready` fail closed with `503 model_unavailable` and `/api/chat` fail closed
   with `502 generator_failed` — never a startup crash, never a false `ready:true`, never a fabricated answer, never
   a silent fallback to extractive. What remains unverified here is only the positive path (an actual generated answer
   from a real local model), which requires an Ollama runtime and pulled model that this environment does not have.
3. **`data/source_corpus.json` is a sealed Phase-2 snapshot** (`0ee5cb8b…`) built before the Topic 1/5 correction
   set reached its current form; its `corrections_sha256` therefore records the older corrections file by design.
   Phase 4/5 provenance is bound to this exact artifact, so it is intentionally not regenerated. The live correction
   record is `data/topic_corrections.json` (`dec2dbe4…`), and `tests/test_source_corpus.py` proves regeneration from
   it yields both corrections.
4. **Legacy resolver page index** (`data/sap_help/pages`) covers only the M2C-17 page; the canonical page source is
   `data/page_corpus/` (28 pages). The legacy index is retained for the resolver's `resolved_local_page` path and is
   documented as such.
5. **Evaluation gaps, honestly recorded** (phase 12, 28-page corpus, sealed queries): evidence-real answers correct
   38/65 with 2 wrong-page; unsupported-answered 11/40 — the 11 are queries whose gold type (`not_ingested` /
   `absent_detail`) predates the corpus growth and are now legitimately answerable; they are recorded, not hidden.
   Router recall@1 on gold-card questions is 0.5048 (recall@5 0.8571); the failure audit
   (`data/evaluation/phase12_failure_audit.json`) attributes gaps to vocabulary mismatch (42), sibling ambiguity
   (85), identity-hub routing (44), near-tie embeddings (35), other ranking (82), underspecified queries (2).
   Grounding violations, phantom citations, and fabricated URLs: **0**.
6. **Phase 10 fusion/rerank experiments not adopted.** On the 28-page corpus selection picks λ\*=2.0 on DEV, but the
   declared TEST rules reject adoption of both G (cue gain +3 < 4) and R (unresolved-identity routing regression
   4/4 → 2/4). The default pipeline therefore stays λ = 0 — conservative, by design
   (`data/phase10_report.md`, revision 2026-10-12).
7. **Frontend browser E2E (Playwright, `web/e2e/`) not executed** in this sandbox (no browser binaries available and
   no approved download source). Frontend verification covers unit tests, typecheck, and the production build.
8. **Environment reproduction:** the repository pins tested versions but not a complete transitive lock; use a
   deployment-specific lock/wheelhouse for byte-for-byte reproduction (`docs/DEPLOYMENT.md` §2).

---

## D. Verification results (exact commands)

All commands from the repository root, Python venv `.venv`. Release suite 2026-10-12; final blocker-resolution
pass re-run 2026-10-13 at commit `a6b1b53`.

| # | Command | Result |
| -- | --- | --- |
| 1 | `.venv/bin/python -m pytest tests/ -q` | **1338 passed, 225 subtests passed, 0 failed**, 1 warning, 134 s |
| 2 | `.venv/bin/python -m pytest tests/test_phase7a.py tests/test_phase7b.py tests/test_phase7g.py tests/test_source_corpus.py -q` | 129 passed |
| 3 | `.venv/bin/python -m pytest tests/test_rag_evidence_quality.py tests/test_phase2_fixes.py tests/test_followup_state.py tests/test_phase11_1_service.py tests/test_phase11_service.py tests/test_followup_elaboration.py -q` | 157 passed, 126 subtests |
| 4 | `.venv/bin/python -m pytest tests/test_followup_state.py tests/test_followup_resolution.py tests/test_followup_elaboration.py tests/test_phase11_service.py tests/test_phase11_1_service.py tests/test_phase11_api.py -q` | 198 passed, 151 subtests |
| 5 | `cd web && npm ci && npx tsc --noEmit` | exit 0 (clean typecheck) |
| 6 | `cd web && npx vitest run` | **115 passed, 1 skipped** (11 files) |
| 7 | `cd web && npm run build` | vite build OK — `dist/index.html`, JS 366 kB (gzip 114 kB), CSS 41 kB |
| 8 | `.venv/bin/python scripts/rag_api.py --host 0.0.0.0 --port 8000 --generator extractive` then `curl` probes | see live smoke below |
| 9 | `.venv/bin/python scripts/evaluate_phase12.py` (after conscious deletion of stale sealed results) | regenerated on 28-page corpus; sealed queries sha unchanged (`3c5a9ddd…`) |
| 10 | `.venv/bin/python scripts/phase12_failure_audit.py` | audit regenerated; ground/phantom/url violations = 0 |

**Live API smoke (extractive, debug off):**

| Probe | Result |
| --- | --- |
| `GET /health` | `{"status":"ok","process":"live"}` |
| `GET /ready` | `{"status":"ok","ready":true,"topics":29,"pages_available":28,"generator":"extractive"}` |
| `GET /api/health` | `{"status":"ok","ready":true,"debug_enabled":false,...,"topics":29,"pages_available":28}` |
| `POST /api/chat` "How does billing work?" | `answered`, grounded, citations `[S1]/[S2]` |
| `POST /api/chat` with `"debug": true` | **403** (debug disabled by default) |
| `POST /api/chat` "Tell me about Contract Account Business Object." (M2C-18) | `documentation_unavailable`, card_id M2C-18, honest message + topic reference |
| `POST /api/chat` "What is the weather in Tokyo?" | `out_of_scope` |
| `POST /api/chat` "elaborate" (same conversation) | `answered`, `grounded: true` |
| `POST /api/chat` malformed / empty `message` | **422** `invalid_request` envelope with `fields:["message"]` |
| `POST /api/chat` body > 16 KB | **413** `payload_too_large` |
| `GET /api/nonexistent` | **404** JSON envelope (not the SPA) |
| `GET /some/spa/route` | **200** `text/html` (SPA deep link) |
| CORS preflight from an allowed origin | **200** with `access-control-allow-origin` |
| CORS preflight from a disallowed origin | **400**, no `access-control-allow-origin` |
| 3rd request/min with `SURA_RATE_LIMIT_PER_MINUTE=2` | **429** `rate_limited` + `Retry-After: 60` |

**Live API smoke (generator `ollama`, no Ollama runtime installed — final pass, port 8023):**

| Probe | Result |
| --- | --- |
| `GET /health` | **200** `{"status":"ok","process":"live"}` (startup does not crash on a missing model) |
| `GET /ready` | **503** `model_unavailable` "Ollama model is not reachable." (fail-closed — was a false `ready:true` before item 13) |
| `POST /api/chat` | **502** `generator_failed` "The answer generator failed (ConnectionError). No answer was produced." |

**Production start structured logging (final pass):** `python scripts/rag_api.py … --generator extractive` emits one
JSON line per request on stdout, e.g. `{"request_id":…,"route":"M2C-12","validator_results":{"grounding":{"violations":0,…},"grounded":true,…},"latency_ms":62.4,"config_hash":…,"corpus_hash":…,"query":"1637695ab84cc32b","status":"answered","http_status":200}` — `query` is a hash because `SURA_LOG_QUERIES` defaults to `0`.

---

## E. Source / corpus status

**Corpus:** 29 registered M2C topic cards · 28 admitted pages (`data/page_corpus/manifest.json`,
corpus_sha256 `46e7c63a…`) · 113 page chunks (`B_heading_200`, page manifest `621cea32…`, vector_count 113) ·
card manifest `aa859ea2…` (29 card vectors) · embedding model local `all-MiniLM-L6-v2` only (no runtime downloads).

**Identity (`data/m2c_page_identity.json` `3a832d40…`):** 25 `identified_not_local` · 2 `corrected_identity`
(M2C-01 → `e52c8ee6`, M2C-05 → `2ac7fe29`) · 1 `resolved_local_page` (M2C-17) · 1 `conflicting_identity` (M2C-18,
fail-closed). Corrections recorded in `data/topic_corrections.json` (`dec2dbe4…`); both corrections are
metadata-only (`applied_to_content: false`), authoritative sources preserved.

**Sealed evaluation artifacts (current hashes):** phase8 queries `150cba14…` / results `22571efb…` · phase9 query
set `101a5edb…` (101 queries) · phase12 query set `3c5a9ddd…` (113 queries: 65 answerable, 16 absent_detail,
10 not_ingested, 6 unresolved_identity, 8 ambiguous, 8 out_of_domain) · phase12 results re-evaluated 2026-10-12 ·
phase10 selection `08d259e6…` (λ\*=2.0 DEV; G/R not adopted on TEST).

**Phase headline numbers:** Phase 4 card retrieval R@1 0.92 / R@5 1.0 / MRR 0.95 · Phase 8 top-1 0.75, MRR 0.8336,
`m2c18_never_answered` true · Phase 9 all-gold R@1 0.3412 (29/85), oracle 58/69 · Phase 12 evidence-real correct
38/65, unsupported-answered 11/40 (honest, corpus-coupled gold labels), router R@1 0.5048 / R@5 0.8571 / MRR 0.6504
(n=105) · baseline support-chain failures 0 · grounding/phantom/URL violations 0.

**Frontend:** React 18 + Vite 6 + TypeScript, served by FastAPI from `web/dist` (same-origin `/api`), CSP
`frame-ancestors 'none'` by default (`RAG_CSP_FRAME_ANCESTORS`).

---

## F. Deployment instructions (summary — full guide: `docs/DEPLOYMENT.md`)

1. **Python 3.11 runtime**, from the repository root:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt -r requirements-phase11.txt \
     "chromadb==1.5.9" "sentence-transformers==6.1.0" "ollama==0.6.3" "gt-all-minilm-l6-v2==0.1.0"
   ```
   (or set `M2C_MODEL_DIR` to an approved local model directory containing `model.safetensors` + `tokenizer.json`).
2. **Build the UI:** `cd web && npm ci && npm run build && cd ..` (served from `web/dist`; override with
   `RAG_STATIC_DIR` if deployed elsewhere).
3. **Provision the vector stores** at `data/vector_store/` (cards, `sap_m2c_card_v1`) and
   `data/vector_store/page_collection/` (pages, `sap_pages_v1`) — supply prebuilt stores, or rebuild:
   ```bash
   python scripts/build_retrieval_units.py && python scripts/validate_token_lengths.py
   python scripts/build_card_collection.py --rebuild
   python scripts/page_corpus.py
   python scripts/build_page_collection.py --rebuild
   ```
   Readiness fails closed on missing/empty stores or count mismatches.
4. **Environment (all optional, safe defaults):** `RAG_GENERATOR=extractive` (default) · `RAG_ENABLE_DEBUG=0`
   (default — debug requests get 403 while off) · `RAG_CORS_ORIGINS` (default localhost dev origins; same-origin
   deployment needs none) · `RAG_STATIC_DIR` · `RAG_CSP_FRAME_ANCESTORS='none'` · `HOST` / `PORT`. `.env.example`
   is a template only — nothing auto-loads `.env`.
5. **Start:** `python scripts/rag_api.py --host 0.0.0.0 --port 8000 --generator extractive`
6. **Verify:** `GET /health` (liveness), `GET /ready` (must report `ready:true`, `topics:29`,
   `pages_available:28`), `GET /api/health` (must report `debug_enabled:false` in production).

No absolute host paths are required at runtime; no absolute Windows paths exist in runtime code. Secrets: none
required — the stack is fully local/offline (no external LLM calls in the shipped configuration).

---

## G. GitHub status

- Repository: `Sravan-git7/chatbot` · working/release branch: `arena/b450cda2-chatbot` (session-fixed) at final
  commit **`a6b1b53`**, descended from `9be6553` (prior release) ← `c7527ed` (tip of `arena/4fe57164-chatbot`).
  Both `c7527ed` and `9be6553` are ancestors of `a6b1b53`, so the intended release branch contains all prior work.
- **Both existing branches are preserved** on the remote and neither was merged, deleted, reset, or force-pushed:
  `arena/4fe57164-chatbot` → `c7527ed` and `arena/b450cda2-chatbot` → `a6b1b53` (verified with
  `git ls-remote --heads origin`). Other sessions' `arena/*` branches, `captured-responses-data`, and `main`
  (`d85c31e`) were left untouched. No protected backups (`av/`, `local_backup2/`, `scratch/`) were modified.
- All changes committed on `arena/b450cda2-chatbot` and pushed with a **normal (non-force) push**
  (`9be6553..a6b1b53`, a clean fast-forward — the remote was a strict ancestor, no divergence); local HEAD and
  `origin/arena/b450cda2-chatbot` are in sync at `a6b1b53`; working tree clean. No history was rewritten.
- Secrets/env files: none committed (`git ls-files` secret scan is part of the green suite, `tests/test_phase9.py`);
  the final diff was additionally scanned for key/token patterns and hardcoded absolute local paths — none
  introduced. `.env.example` holds placeholders only.
- Generated heavy artifacts (`data/vector_store/`, `.venv/`, `web/node_modules/`, `web/dist/`) stay git-ignored per
  repository convention; all evaluation artifacts recorded above are checked in and hash-verified. Sealed historical
  baselines (`data/source_corpus.json` `0ee5cb8b…`, `data/phase12/ollama_environment.json`, frozen phase 8/9/10/12
  query/result sets, pinned `data/m2c_page_identity.json` `3a832d40…`) were **not** regenerated; the runtime uses the
  live inputs (`data/topic_corrections.json` `dec2dbe4…`, card/page corpora, vector stores) — see Section C item 3.

*End of report.*
