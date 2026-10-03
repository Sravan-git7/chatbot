# Phase 19A: Hot-Path Performance Optimization Report

## 1. Root Cause
In `HEAD 25ced60`, the deterministic routing and retrieval hot path (`RagPipeline.answer()`) performed two sources of redundant per-request work:

1. **Duplicate Query Embeddings (`2` to `3` times per `answer()` call; `241` embeddings across 113 queries):**
   - **Call #1:** `route_to_page(query, self.backend, ...)` called `ChromaCardBackend.query(query, top_k=10)`, which executed `self._embed(query.strip())` (`SentenceTransformer.encode`) and discarded the vector after querying `sap_m2c_card_v1`.
   - **Call #2 (`15/113` queries):** When `_inject_code_aware_candidates()` injected code/phrase-matched cards (`to_inject` non-empty), `self.backend.query(query.strip(), len(self.cards))` computed the exact same query embedding a second time and discarded it.
   - **Call #3 (`113/113` queries):** `RagPipeline.answer()` then called `q_emb = self.retriever.embed([query])` before calling `PR13.rerank_candidates()`.
2. **Duplicate Winning-Page Chroma Retrieval (`107` extra Chroma queries across 113 requests):**
   - During Step 1 reranking, `PR13.score_candidate()` already called `retriever.retrieve_in_page(query, eff_g, eff_p, top_k=3, query_embedding=query_embedding)` for every unique ingested candidate page (including the winning page) and cached the result in a local `hits_cache`, which was discarded when `rerank_candidates()` returned.
   - In Step 5 (`identity-constrained retrieval`), `RagPipeline.answer()` called `self.retriever.retrieve_in_page(query, identity.effective_guide_id, identity.effective_page_id, top_k=self.cfg.k_chunks, query_embedding=q_emb)` (`k_chunks=5`) for the winning page a second time.

---

## 2. Old Execution Path
```text
answer(query)
  |
  +--> 1a. route_to_page(query, self.backend, ...)
  |         +--> ChromaCardBackend.query(query, top_k=10)
  |                +--> self._embed(query.strip())         # EMBEDDING #1 (discarded)
  |                +--> card_collection.query(...)         # Card Chroma query #1
  |
  +--> 1b. _inject_code_aware_candidates(query, candidates)   [15/113 queries]
  |         +--> ChromaCardBackend.query(query, 29)
  |                +--> self._embed(query.strip())         # EMBEDDING #2 (discarded)
  |                +--> card_collection.query(...)         # Card Chroma query #2
  |
  +--> 1c. q_emb = self.retriever.embed([query])           # EMBEDDING #2 (or #3)
  |
  +--> 1d. PR13.rerank_candidates(..., query_embedding=q_emb)
  |         +--> up to 10 unique candidate pages:
  |                +--> retriever.retrieve_in_page(..., top_k=3, query_embedding=q_emb)
  |                +--> local hits_cache discarded on return
  |
  +--> 2-4. resolve_identity() -> lexical topic gate -> corpus admission
  |
  +--> 5. self.retriever.retrieve_in_page(query, win_g, win_p, top_k=5, query_embedding=q_emb)
  |         +--> REDUNDANT winning-page Chroma query (107/113 queries)
  |
  +--> 6-7. build_context() -> EvidenceGuard / generator -> verify_grounding() -> build_citations()
```

---

## 3. New Execution Path
```text
answer(query)
  |
  +--> 1a. q_emb = self.retriever.embed([query.strip()])   # EMBEDDING #1 (EXACTLY ONCE per request)
  |
  +--> 1b. route_to_page(query, self.backend, ..., query_embedding=q_emb)
  |         +--> _PrecomputedQueryBackend(self.backend, q_emb).query(query, top_k=10)
  |                +--> card_collection.query(query_embeddings=q_emb)   # 0 extra embeddings
  |
  +--> 1c. _inject_code_aware_candidates(query, candidates, query_embedding=q_emb)
  |         +--> _PrecomputedQueryBackend(self.backend, q_emb).query(query, 29) [if to_inject]
  |                +--> card_collection.query(query_embeddings=q_emb)   # 0 extra embeddings
  |
  +--> 1d. PR13.rerank_candidates(..., query_embedding=q_emb, k_chunks=self.cfg.k_chunks, hits_out=rerank_hits_cache)
  |         +--> up to 10 unique candidate pages:
  |                +--> retriever.retrieve_in_page(..., top_k=max(3, k_chunks), query_embedding=q_emb)
  |                +--> stores raw_hits in request-local rerank_hits_cache[(guide_id, page_id, fetch_k)]
  |                +--> scores candidate on hits = raw_hits[:3] (100% identical reranker score & note)
  |
  +--> 2-4. resolve_identity() -> lexical topic gate -> corpus admission
  |
  +--> 5. win_page_key_k = (win_g, win_p, self.cfg.k_chunks)
  |       if win_page_key_k in rerank_hits_cache:
  |           hits = list(rerank_hits_cache[win_page_key_k][:self.cfg.k_chunks])
  |         +--> REUSES winning page's k_chunks=5 hits (0 duplicate Chroma queries; retrieve_ms = 0.00 ms)
  |
  +--> 6-7. build_context() -> EvidenceGuard / generator -> verify_grounding() -> build_citations()
```

---

## 4. Exact Implementation
1. **`scripts/rag_pipeline.py`**:
   - Added `_PrecomputedQueryBackend(inner, query_embedding)`, a request-local adapter that forwards `query_embeddings=[[float(x) for x in vec]]` directly to Chroma's card collection without calling `self.backend._embed()`, mutating shared backend state, or touching SHA-pinned Phase 7 files (`scripts/m2c_router.py`, `scripts/m2c_orchestrator.py`).
   - Added optional `query_embedding: Optional[Any] = None` to `route_to_page(...)` and `_inject_code_aware_candidates(...)`.
   - In `RagPipeline.answer()`, computed `q_emb = self.retriever.embed([query.strip()])` once per request, passed `query_embedding=q_emb` through `route_to_page()`, `_inject_code_aware_candidates()`, and `PR13.rerank_candidates(..., query_embedding=q_emb, k_chunks=self.cfg.k_chunks, hits_out=rerank_hits_cache)`, and reused `rerank_hits_cache[(identity.effective_guide_id, identity.effective_page_id, self.cfg.k_chunks)]` in Step 5.
2. **`scripts/phase13_reranker.py`**:
   - Added optional `k_chunks: int = 3` and `hits_out: Optional[Dict[Tuple[Any, ...], Any]] = None` parameters to `rerank_candidates()` (and `k_chunks: int = 3` to `score_candidate()`).
   - Inside `score_candidate()`, queried `retriever.retrieve_in_page(..., top_k=max(3, int(k_chunks)), query_embedding=query_embedding)`, cached `raw_hits` under both `(guide_id, page_id)` and `(guide_id, page_id, fetch_k)`, and sliced `hits = list(raw_hits)[:3]` for `page_sim`, `note = f"page_hits={len(hits)}_top_chunk_sim={page_sim}"`, `hits[:2]` coverage, and fallback `page_txt`.
3. **`scripts/rag_service.py` & `tests/test_phase18_production_config.py`**:
   - Updated `production_pipeline_config()` to set `phrase_reranker=True, phrase_min_corroboration=2, full_page_coverage=False, citation_repair=False, evidence_frame_normalization=False`.

---

## 5. Evidence-Equivalence Proof
- **Why `top_k=3` vs `k_chunks=5` normalization was required:** `score_candidate()` originally requested `top_k=3` chunks per candidate page, whereas Step 5 requested `top_k=self.cfg.k_chunks` (`5` chunks, from which `build_context` selects up to `max_context_chunks=4` within `context_budget_tokens=700`). Reusing a 3-chunk result in Step 5 would truncate the 4th/5th chunks; conversely, scoring candidates on all 5 chunks without slicing would alter `note = f"page_hits={len(hits)}..."`.
- **How exact equivalence is guaranteed:**
  1. `score_candidate()` fetches `fetch_k = max(3, int(k_chunks))` (`5` chunks when called from `RagPipeline.answer()`) using the exact same `query_embedding=q_emb` and `(guide_id, page_id)` filter as Step 5.
  2. Because `PageRetriever.retrieve_in_page()` orders chunks deterministically by `(distance, chunk_index, chunk_id)`, `raw_hits[:3]` is identical to a `top_k=3` query and `raw_hits[:5]` is identical to Step 5's `top_k=5` query.
  3. Step 5 keys the request-local cache by `(guide_id, page_id, self.cfg.k_chunks)` (`k=5`), so a `k=3` cache entry is never mistaken for `k=5`.
- **113-query empirical proof:** Comparing full `pipe.answer(q, debug=True)` dicts (with `timings_ms` removed) before and after Phase 19A across all 113 frozen benchmark queries yielded **`113/113` (`100%`) bit-for-bit identical outputs** (`diffs=[]`).

---

## 6. Operation Counts Before/After (`n = 113` Frozen Queries)

| Operation Counter | BEFORE (`HEAD 25ced60`, E1a-v2) | AFTER (Phase 19A) | Delta |
| :--- | :---: | :---: | :---: |
| **Query Embeddings (`embed`) — Total (113 queries)** | `241` | **`113`** | **`-128 (-53.1%)`** |
| **Query Embeddings / Request (`min / median / max / mean`)** | `2 / 2 / 3 / 2.13` | **`1 / 1 / 1 / 1.00`** | **`-1.13 / req`** |
| **Card Chroma Queries (`sap_m2c_card_v1`) — Total** | `128` (`1.13 / req`) | `128` (`1.13 / req`) | `0` |
| **Reranker In-Page Chroma Queries (`sap_pages_v1`) — Total** | `981` (`8.68 / req`) | `981` (`8.68 / req`) | `0` |
| **Step-5 Winning-Page Chroma Queries — Total** | `107` (`0.95 / req`) | **`0` (`0.00 / req`)** | **`-107 (-100.0%)`** |
| **Total Chroma Queries Across All 113 Requests** | `1216` (`10.76 / req`) | **`1109` (`9.81 / req`)** | **`-107 (-8.8%)`** |

---

## 7. `p50 / p90 / p95 / p99` Before/After (`n = 113` Frozen Queries, `ms`)

| Stage (`ms`) | Percentile | BEFORE (`HEAD 25ced60`) | AFTER (Phase 19A) | Delta (`ms` / `%`) |
| :--- | :---: | :---: | :---: | :---: |
| **`route_ms`** (`n=113`) | `p50` | `65.66` | **`47.53`** | **`-18.13 ms (-27.6%)`** |
| | `p90` | `82.81` | **`53.19`** | **`-29.62 ms (-35.8%)`** |
| | `p95` | `88.57` | **`54.07`** | **`-34.50 ms (-39.0%)`** |
| | `p99` | `106.26` | **`60.65`** | **`-45.61 ms (-42.9%)`** |
| | `mean` | `68.19` | **`47.88`** | **`-20.31 ms (-29.8%)`** |
| **`retrieve_ms`** (Step 5, `n=107`) | `p50` | `2.59` | **`0.00`** | **`-2.59 ms (-100.0%)`** |
| | `p90` | `3.45` | **`0.00`** | **`-3.45 ms (-100.0%)`** |
| | `p95` | `4.15` | **`0.00`** | **`-4.15 ms (-100.0%)`** |
| | `p99` | `4.69` | **`0.00`** | **`-4.69 ms (-100.0%)`** |
| | `mean` | `2.75` | **`0.00`** | **`-2.75 ms (-100.0%)`** |
| **`context_ms`** (`n=107`) | `p50` | `2.99` | **`2.78`** | `-0.21 ms (-7.0%)` |
| | `p90` | `4.71` | **`3.96`** | `-0.75 ms (-15.9%)` |
| | `p95` | `5.02` | **`4.05`** | `-0.97 ms (-19.3%)` |
| | `p99` | `6.44` | **`5.02`** | `-1.42 ms (-22.0%)` |
| **`generate_ms`** (extractive, `n=107`) | `p50` | `0.38` | **`0.34`** | `-0.04 ms (-10.5%)` |
| | `p95` | `0.73` | **`0.49`** | `-0.24 ms (-32.9%)` |
| **`total_ms`** (deterministic pipeline, `n=113`) | `p50` | `74.19` | **`53.55`** | **`-20.64 ms (-27.8%)`** |
| | `p90` | `92.42` | **`59.98`** | **`-32.44 ms (-35.1%)`** |
| | `p95` | `100.17` | **`61.60`** | **`-38.57 ms (-38.5%)`** |
| | `p99` | `117.36` | **`67.56`** | **`-49.80 ms (-42.4%)`** |
| | `mean` | `77.40` | **`54.04`** | **`-23.36 ms (-30.2%)`** |

---

## 8. Routing Correctness Before/After (`n = 113` Frozen Queries)

| Routing Metric | BEFORE (Phase 18 `e1a_v2_corroborated`) | AFTER (Phase 19A) | Status |
| :--- | :---: | :---: | :---: |
| **Router R@1 (Answerable, `n=65`)** | `62/65 (95.38%)` | **`62/65 (95.38%)`** | **IDENTICAL (`0` diffs)** |
| **Router R@1 (All-Gold, `n=105`)** | `91/105 (86.67%)` | **`91/105 (86.67%)`** | **IDENTICAL (`0` diffs)** |
| **Gold in Candidate Pool (`n=105`)** | `105/105 (100.0%)` | **`105/105 (100.0%)`** | **IDENTICAL (`0` diffs)** |
| **Per-Query Candidate Order & Scores (`n=113`)** | Baseline | **`113/113` identical** | **IDENTICAL (`0` diffs)** |

---

## 9. Extractive Correctness Before/After (`n = 113` Frozen Queries)

| Extractive / Safety Metric | BEFORE (Phase 18 `e1a_v2_corroborated`) | AFTER (Phase 19A) | Status |
| :--- | :---: | :---: | :---: |
| **Extractive Answerable Correct (`n=65`)** | `52/65 (80.00%)` | **`52/65 (80.00%)`** | **IDENTICAL (`0` regressions)** |
| **Wrong-Page Answers (Extractive)** | `3` | **`3`** | **IDENTICAL** |
| **Absent-Detail Answered (Extractive)** | `12/16` (`0/16` in guarded Ollama) | **`12/16`** | **IDENTICAL** |
| **Grounding Failures** | `0` | **`0`** | **IDENTICAL** |
| **Phantom Citations / URL Changes** | `0 / 0` | **`0 / 0`** | **IDENTICAL** |
| **Full `answer(debug=True)` Dict Equivalence** | Baseline | **`113/113 (100.0%)`** | **IDENTICAL** |

---

## 10. Tests
`tests/test_phase19a_latency.py` (**12/12 PASSED**) + Phase 13/18 regression suite (**53/53 PASSED**):
1. `test_01_single_embedding_per_answer` — **PASSED**
2. `test_02_q_emb_propagation_to_route_to_page` — **PASSED**
3. `test_03_reranker_receives_same_q_emb` — **PASSED**
4. `test_04_request_local_cache_eliminates_winning_page_duplicate` — **PASSED**
5. `test_05_correct_k_handling_in_request_cache` — **PASSED**
6. `test_06_final_evidence_equivalence` — **PASSED**
7. `test_07_candidate_ranking_and_score_equivalence` — **PASSED**
8. `test_08_context_equivalence` — **PASSED**
9. `test_09_citation_and_grounding_equivalence` — **PASSED**
10. `test_10_concurrent_request_isolation` — **PASSED**
11. `test_11_empty_query_and_no_global_cache` — **PASSED**
12. `test_12_unsupported_behavior_and_production_config_guard` — **PASSED**

---

## 11. Files Changed
- `scripts/rag_pipeline.py` (modified)
- `scripts/phase13_reranker.py` (modified)
- `scripts/rag_service.py` (modified)
- `tests/test_phase18_production_config.py` (modified)
- `tests/test_phase19a_latency.py` (added)
- `data/phase19/phase19a_latency_optimization.md` (added)
- `data/phase19/phase19a_latency.json` (added)

---

## 12. Remaining Bottleneck
1. **End-to-end guarded LLM mode:** Uncached Ollama (`llama3.2:3b`) generation (`generate_ms`, ~88% of uncached E2E latency).
2. **Deterministic routing hot path (`route_ms` `p50 = 47.53 ms`):** The **8–10 sequential per-page Chroma queries** (`retriever.retrieve_in_page` called `981` times across 113 queries, `8.68` mean/request, costing `~22–25 ms` per request) inside `rerank_candidates()`, followed by single query embedding (`~15–18 ms`) and repeated per-query phrase/identity/chunk scanning (`~5–8 ms`).

---

## 13. Phase 19B Recommendation
1. **Keep & Adopt Phase 19A (`PASS`).**
2. **Phase 19B Next Step:**
   - **Deterministic retrieval side:** Batch the 8–10 candidate-page Chroma queries in `rerank_candidates()` into a single retrieval call (or pre-indexed page-chunk lookup) while preserving exact `(distance, chunk_index, chunk_id)` ordering.
   - **LLM generation side (Windows Ollama):** Evaluate bounded `num_predict` and `keep_alive` in a separate controlled experiment on the Windows Ollama environment.
