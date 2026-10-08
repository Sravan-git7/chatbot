# SURA Phase 0 Audit Findings

## 0. Executive Summary
This document records the comprehensive, read-only Phase 0 audit of the SURA (SAP Utilities Documentation Assistant) repository (`D:\chatbot-phase12`). All findings are backed by specific file and line citations.

---

## 0.1 End-to-End Answer Path

### Execution Flow
```
User Query
  │
  ▼ [POST /api/chat]
scripts/rag_api.py:chat (L215-L226)
  │
  ▼ [current().ask(req.message, ...)]
scripts/rag_service.py:RagService.ask (L372-L417)
  │
  ├── clean_question (L82-L91)
  ├── resolve_conversation_id (L94-L101)
  ├── Concurrency Gate: _FIFOBoundedSemaphore (L399-L410, limit=4)
  └── _run_pipeline_request (L340-L370)
        │
        ▼ [active_pipeline.answer(q, debug=True)]
scripts/rag_pipeline.py:RagPipeline.answer (L385-L660)
  │
  ├── 1. Card Router & Reranker (L395-L448):
  │      - Chroma card retrieval (top_k_cards=10)
  │      - Phase 13 / 18 reranker: phase13_reranker.py (L283-L365)
  │        * phrase_reranker=True (L441)
  │        * phrase_min_corroboration=2 (L442)
  │        * full_page_coverage=False (L443)
  ├── 2. Identity Resolution (L450-L467):
  │      - m2c_page_identity.resolve_identity (pid.py)
  ├── 3. Lexical Topic Gate (L469-L481):
  │      - T.coverage(qterms, topic_text) vs ood_min_coverage (0.10)
  ├── 4. Identity / Corpus Admission (L483-L525):
  │      - Page ingested check (25 active ingested pages in Phase 12)
  ├── 5. Identity-Constrained Chunk Retrieval (L527-L553):
  │      - retriever.retrieve(guide_id, page_id, query)
  ├── 6. Context Assembly (L556-L568):
  │      - rag_context.build_context (L100-L134)
  │        * context_budget_tokens=700 (enforced in rag_context.py:L114-L116)
  │        * max_context_chunks=4 (enforced in rag_context.py:L110-L112)
  │      - Lexical context gate: ccov vs 0.25 (relaxed_context_gate=True)
  └── 7. Generation & Grounding Verification (L569-L630):
        - generator.generate(query, context)
        - verify_grounding (rag_generate.py:L240-L360)
  │
  ▼ [Return to RagService._run_pipeline_request]
scripts/rag_service.py:L365-L370
  - Support Chain Verification: support_chain (L214-L220) via rag_evidence.verify_support_chain
  │
  ▼ [Return to RagService.ask -> to_chat_result]
scripts/rag_service.py:to_chat_result (L222-L283)
  - Topic reference gating (L240-L251)
  - Deterministic response composer: scripts/rag_response.py:compose_response (L264)
  │
  ▼ [Return to rag_api.py -> ChatResponse JSON]
Frontend Rendering
  ├── web/src/components/MessageView.tsx:L173-L270
  ├── web/src/components/StructuredAnswer.tsx:L27-L88
  ├── web/src/components/Markdown.tsx:L71-L108
  └── web/src/components/Sources.tsx:L32-L138
```

### Key Parameter & Architectural Invariants
1. **Is `llama3.2:3b` on the production answer path?**
   - **NO.** By default, `rag_api.py` sets `--generator extractive` (`scripts/rag_api.py:L244`).
   - In `scripts/rag_service.py:build_service` (L448-L457), generator `"extractive"` configures `EvidenceExtractiveGenerator` (`scripts/rag_evidence.py:L188-L221`).
   - `llama3.2:3b` via `OllamaClient` is only wired if explicitly requested via `--generator ollama` or `RAG_GENERATOR=ollama`.
2. **Are final displayed sentences generated or deterministic/extractive?**
   - **100% Deterministic and Extractive.** Sentences are extracted verbatim from retrieved context chunks by `EvidenceExtractiveGenerator`, validated by `support_chain`, and grouped into sections deterministically by `rag_response.py`.
3. **Where is `context_budget` enforced?**
   - In `scripts/rag_context.py:build_context` (L114-L116): `used + t > budget_tokens` drops chunks exceeding the budget (default 700 tokens).
4. **Where is `max_chunks` enforced?**
   - In `scripts/rag_context.py:build_context` (L110-L112): `len(selected) >= max_chunks` drops chunks beyond the limit (default 4 chunks).
5. **Where is `phrase_min_corroboration` enforced?**
   - In `scripts/phase13_reranker.py:unique_phrase_page_map` (L306) and passed from `scripts/rag_pipeline.py:L428` (`phrase_min_corroboration=2`).
6. **Where is `full_page_coverage` enforced?**
   - In `scripts/phase13_reranker.py` (L169, L365) and passed from `scripts/rag_pipeline.py:L429` (`full_page_coverage=False`).
7. **Where does grounding validation happen?**
   - Primary: `scripts/rag_generate.py:verify_grounding` (L240-L364), called in `scripts/rag_pipeline.py:L577`.
   - Secondary (extractive support chain): `scripts/rag_evidence.py:verify_support_chain` (L580-L640), called in `scripts/rag_service.py:L366`.

---

## 0.2 Legacy Architecture Audit

| Keyword / Symbol | File(s) | Classification | Description & Reachability |
|---|---|---|---|
| `elaborat` (`rag_elaborate.py`) | `scripts/rag_elaborate.py`, `data/phase_elaboration/*` | **Dead Code / Experimental Artifact** | Unreachable from production runtime (`rag_service.py`, `rag_api.py`, and `rag_pipeline.py` do NOT import `rag_elaborate`). Referenced only in historical evaluations (`evaluate_elaboration_llm.py`). |
| `follow_up` / `followup` (`rag_followup.py`) | `scripts/rag_followup.py` | **Dead Code / Experimental Artifact** | Only imported by `rag_elaborate.py` and `evaluate_elaboration_llm.py`. Completely unreachable from `rag_api.py` and `rag_service.py`. |
| `followup.ts` (`web/src/followup.ts`) | `web/src/followup.ts` | **Test Only** | `turnContext` is only imported in `web/src/__tests__/followup.test.ts`. `App.tsx` and `api.ts` do NOT import or invoke `turnContext`. |
| `getFollowUpQuestions` | `web/src/util.ts` (L105-L132) | **Production Reachable (Frontend-Only UI)** | Generates static client-side suggestions ("You might also want to know") displayed below answered messages. |
| `active_topic` | `scripts/rag_service.py` (L337), `scripts/rag_pipeline.py` (L235, L458) | **Dead Code in Production** | `_canonical_active_topic` in `rag_service.py:L337` unconditionally returns `None`. `expected_topic` is never passed to `_run_pipeline_request`. Frontend does not transmit context. |
| `two_stage` | `scripts/evaluate_two_stage.py`, `scripts/evaluate_two_stage_llm.py`, `data/phase_elaboration/two_stage_*` | **Experimental Artifact** | Standalone benchmark scripts and experimental output reports. Not reachable from runtime. |
| `rewrite` | `scripts/rag_citation_repair.py` | **Disabled Feature (Flag OFF)** | `citation_repair=False` in `production_pipeline_config()`. Only performs deterministic marker normalization when flag is enabled. No LLM query rewriting exists. |
| `synthes` | `scripts/evaluate_phase18.py` | **Historical Benchmark Reference** | Only appears in evaluation descriptions. Zero generative synthesis on production path. |

---

## 0.3 State & Storage Audit

### Backend State
- **Stateless by Design**: `scripts/rag_api.py` (L11-L12) and `scripts/rag_service.py` (L94-L101).
- `conversation_id` is echoed back or generated if missing.
- No session memory, no conversational history cache, no database, no in-memory turn accumulation.
- Every request is answered strictly independently.

### Frontend Storage
- **Mechanism**: `localStorage` (`web/src/storage.ts`: L8, L28, L37, L46).
- **Storage Keys**:
  - `CONV_KEY = 'sapchat.v1.conversations'`
  - `SET_KEY = 'sapchat.v1.settings'`
- **Storage Version Key**:
  - Currently embedded as a string prefix (`v1` in `sapchat.v1.conversations`).
  - **No explicit schema version key** (e.g., `sapchat.storage_version`) and no migration harness exist.
- **Payload Persisted**:
  - Conversation list: `id`, `title`, `createdAt`, `updatedAt`, `messages`.
  - Debug blocks are stripped before persistence (`web/src/storage.ts`: L26).

---

## 0.4 Trust Badge Audit

### What "Checked against the documentation" Currently Means
- **Frontend**: In `web/src/components/MessageView.tsx` (L199-L207):
  ```tsx
  {r.metadata.grounded && (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-stone-500"
      title="Every sentence was checked against the cited documentation text"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
      Checked against the documentation
    </span>
  )}
  ```
- **Backend Grounding Source**:
  - In `scripts/rag_service.py` (L254):
    `"grounded": status == ANSWERED and _grounding(dbg, pstatus)["ok"] is True`
  - In `_grounding(dbg, pstatus)` (L206-L211):
    Checks that `verify_grounding` returned `ok: True`, violations count is 0, and status is `answered`.
  - For extractive generator: also verifies `support_chain["ok"] is True` (`rag_service.py`: L366-L370).
- **Current Limitation**:
  - It is currently a static non-interactive text pill.
  - It does not display the count of documentation sources cited (e.g. "Quoted from 2 documentation sources").
  - It does not provide an interactive drawer or modal ("How this was checked") explaining the verification criteria.

---

## 0.5 Validator / Display Relationship Audit

### Do validators validate exactly the text displayed to the user?
- **YES.**
  - `verify_grounding` validates `gen.text` directly from the generator (`scripts/rag_pipeline.py`: L577).
  - `support_chain` validates that each sentence of `raw["answer"]` is a verbatim substring of the cited chunk (`scripts/rag_service.py`: L366).
  - `rag_response.py:compose_response` splits `answer` by `\n` into structured section lines without altering a single character of the text.
  - The frontend `Markdown.tsx` component parses the exact verbatim sentence text:
    - Normalizes presentation whitespace before commas (`\s+,` -> `,`).
    - Collapses consecutive duplicate marker tokens (`[S1] [S1]` -> `[S1]`).
    - Transforms `[S#]` markers into interactive clickable buttons with contiguous display numbers mapped from first appearance.
  - **Conclusion**: Canonical evidence text is 100% verbatim and validated prior to display.

---

## 0.6 Out-of-Scope (OOS) vs. Unable-to-Verify Decision Logic

### Decision Points in `scripts/rag_pipeline.py`
1. **Out of Scope (`out_of_domain` / `no_relevant_page`)**:
   - Empty or unroutable query -> `no_relevant_page` (L445).
   - Lexical topic gate (L479-L481): `cov = T.coverage(qterms, topic_text)`. If `cov < self.cfg.ood_min_coverage` (0.10), pipeline aborts with `out_of_domain` (`LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC`).
   - In `rag_service.py`: `STATUS_MAP["out_of_domain"] = "out_of_scope"`.
   - `routed = status != OUT_OF_SCOPE` -> `metadata.card_id = None`, `topic_reference = None`.
2. **Unable to Verify (`insufficient_context` / `unresolved_identity`)**:
   - `unresolved_identity` (L483-L488): Conflicting guide or unverified identity (e.g. M2C-18).
   - `insufficient_context` (L565-L567): Lexical context gate coverage `< 0.25` (`LOW_QUERY_TERM_COVERAGE_IN_CONTEXT`).
   - `insufficient_context` (L588): `GENERATOR_REFUSED` (no evidence sentence meets threshold `tau`).
   - `insufficient_context` (L592): `GROUNDING_VERIFICATION_FAILED`.
   - `insufficient_context` (rag_service.py: L369): `SUPPORT_CHAIN_FAILED`.
3. **Topic Reference Gating (`scripts/rag_service.py`: L238-L251)**:
   - For `UNABLE_TO_VERIFY`, `topic_reference` is shown **ONLY IF** routing evidence exists:
     `cand.get("coverage", 0.0) > 0.0 or cand.get("phrase_match", 0.0) > 0.0 or cand.get("code_match", 0.0) > 0.0`.
   - For ungrounded off-topic queries like `"today's news updates"`, candidate evidence is `0.0`, resulting in `topic_reference = None`.
   - For genuine SAP Utilities queries with insufficient context (e.g. penalty fee question), candidate evidence is `> 0.0`, preserving the reference card.

---

## 0.7 Related Questions Audit

### Source & Generation
- **Type**: **Static / Hardcoded in Frontend Client (`web/src/util.ts`)**.
- **Mechanics**:
  - `web/src/util.ts:getFollowUpQuestions(question, result)` (L105-L132).
  - Evaluates regex patterns in `FOLLOW_UP_POOLS` against `question + answer + source_titles`.
  - Categories:
    - `/installment|payment|clear|receivable|dunning/i`
    - `/invoic/i`
    - `/contract account|business partner|move-in|move-out/i`
    - `/billing|budget|meter|device|rate/i`
  - Fallback: `DEFAULT_FOLLOW_UPS` (4 general questions).
  - Max questions returned: 3.
  - **They are NOT generated by an LLM, NOT retrieval-derived, and NOT produced by the backend.**

---

## 0.8 Baseline Test Results & Metrics

### 1. Frontend Test Suite (`npm --prefix web test`)
- **Total Test Files**: 9 passed (9 total)
- **Total Tests**: 79 passed, 1 skipped (live backend e2e test skipped by default without `LIVE_BACKEND=1`)
- **Duration**: ~9.3s
- **Status**: 100% PASS

### 2. Frontend Production Build (`npm --prefix web run build`)
- **Result**: `tsc --noEmit && vite build` completed in 1.49s with exit code 0.
- **Bundle size**:
  - `dist/index.html`: 0.72 kB
  - `dist/assets/index-DyI2wEFe.css`: 39.22 kB (gzip: 8.32 kB)
  - `dist/assets/index-C103DfIi.js`: 351.77 kB (gzip: 109.44 kB)

### 3. Whitespace / Git Hygiene (`git diff --check`)
- **Result**: Exit code 0 (clean).

### 4. Core Active Python Tests
- `python -m pytest tests/test_rag_response.py tests/test_golden_eval.py -v`:
  - 8 passed in 16.12s.
  - Status matches: 12 / 12 (100%).
  - Citation validity: 6 / 6 (100%).
  - Irrelevant topic suppression: 4 / 4 (100%).

### 5. Legacy Phase 11 Test Suite Audit (`tests/test_phase11_api.py`, `tests/test_phase11_service.py`)
- **Observation**:
  - `tests/test_phase11_service.py`: 3 failures out of 37 tests.
  - `tests/test_phase11_api.py`: 5 failures out of 38 tests.
- **Root Cause**:
  - These tests were written for **Phase 11**, when only 7 pages were ingested and Dunning (`M2C-26`) was absent (`corpus_status == "page_not_ingested"`).
  - In **Phase 12**, Dunning (`M2C-26`) was officially ingested into the corpus (expanding the ingested corpus to 25 pages).
  - The Phase 11 tests assert that `Q_DUNNING` ("How are dunning notices created?") returns `documentation_unavailable`. However, on the active Phase 12 corpus, `Q_DUNNING` now correctly finds the ingested Dunning page and returns a grounded `answered` result.
  - This is not a code regression; it is a known artifact of historical test expectations written before the Phase 12 corpus expansion.

### 6. End-to-End Latency Profile (Local Windows Sandbox)
- Extractive answer generation latency:
  - Routing + Retrieval: ~35–55 ms
  - Context + Extractive Generation + Grounding Verification: ~25–40 ms
  - End-to-end request latency: **~80–120 ms**
- Throughput / Concurrency:
  - Server concurrency capped at 4 (`MAX_CONCURRENT_REQUESTS = 4`).
