# Phase 19B: Controlled Reranker Page-Query Consolidation + Ollama Generation Optimization Report

## 1. Baseline & Reproducibility Verification (Part 1)

Before modifying any code, the working tree, commit state, frozen benchmark/corpus hashes, and Phase 19A baseline were verified:

- **Branch & Commit Base:** `arena/01a0fc57-chatbot` at `HEAD 25ced60` (*"Phase 18: discriminative phrase reranking and citation repair experiments"*), with Phase 19A unstaged in the working tree.
- **Frozen Benchmark & Corpus Integrity (SHA-256 Verified):**
  - `data/evaluation/phase12_queries.json` (`113` frozen queries): `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`
  - `data/page_corpus/manifest.json` (`corpus_sha256: a447f7b63390831f85811ee12a2f316b8d44437679b4e3d28f0293c3e23a624b`): `49a314dbdce364ff33e007013dc92f136144c4f2b523d22a1a1abc64e3f8c1fe`
  - `data/card_collection_manifest.json` (`29` card vectors, `384` dims, `all-MiniLM-L6-v2`): `61383afdbcad361e747ad34654f14dedb6b20a573a30404681625bf61bbf94ea`
  - `data/page_collection_manifest.json` (`106` chunk vectors across `25` pages, `384` dims, cosine): `c6d0f4797eb2809d360ceb3402eecb27441e16af2ccd6f9dcd417bb1059d8a37`
  - `data/phase7/m2c_card_retrieval_units.json`: `f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21`
- **Production Configuration (`scripts/rag_service.py::production_pipeline_config()`):**
  - `phrase_reranker = True`
  - `phrase_min_corroboration = 2`
  - `full_page_coverage = False`
  - `citation_repair = False`
  - `evidence_frame_normalization = False`
  - `top_k_cards = 10, k_chunks = 5, context_budget_tokens = 700, max_context_chunks = 4`
  - `rerank_router = True, code_aware_router = True, in_page_grounding = True, citation_normalization = True, relaxed_context_gate = True`
- **Phase 19A Baseline Metrics (`n = 113` Frozen Queries):**
  - Query embeddings (`embed`): `241 -> 113` (`1.00 / req`)
  - Step-5 winning-page Chroma queries: `107 -> 0`
  - Reranker in-page Chroma queries (`sap_pages_v1`): `981` (`8.68 / req`)
  - Total Chroma queries (`sap_m2c_card_v1` + `sap_pages_v1`): `1,216 -> 1,109`
  - Hot-path `collection.get` calls (`page_chunks()` in Step 3 lexical gate): `108` (`113` with warmup)
  - Correctness: Router R@1 `62/65`, All-gold R@1 `91/105`, Gold-in-pool `105/105`, Extractive `52/65`, Guarded Ollama `43/65`, Oracle `44/65`, Wrong-page `3` extractive / `1` guarded, Grounding failures `0`, Phantom citations `0`, URL changes `0`, Generator errors `0`.

---

## 2. Experiment Matrix (Part 2 & Part 4)

### Workstream A — Reranker Page-Query Consolidation (`sap_pages_v1`)

`sap_pages_v1` contains **106 chunks** across **25 unique `(guide_id, page_id)` pages** (`1` to `8` chunks per page, `384`-d cosine HNSW index, scalar metadata with `doc_id = f"{guide_id}/{page_id}"` and `chunk_id = f"{guide_id}/{page_id}/{chunk_index:03d}"`). In Phase 19A, `rerank_candidates()` called `retriever.retrieve_in_page(...)` sequentially for each unique ingested candidate page (`8.68` calls/request on average, `981` calls across 113 queries).

| Experiment ID | Mechanism | Page Chroma Queries (`n=113`) | Total Chroma Queries (`n=113`) | Hot-Path `collection.get` | `2,825` `(query, page)` Pair Equivalence | `113/113` Pipeline Equivalence | Decision |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Phase 18 (`25ced60`)** | 2–3 embeddings/req + 8–10 per-page reranker queries + duplicate Step-5 query | `1,088` (`981+107`) | `1,216` | `108` | Baseline | Baseline | Historical |
| **Phase 19A Baseline** | 1 embedding/req + Step-5 winning-page cache reuse + 8–10 sequential per-page reranker queries | `981` (`8.68/req`) | `1,109` | `108` | `2,825/2,825` | `113/113` | Baseline |
| **Cand R1 (`batched_where_full_include`)** | Single batched `collection.query(where={"doc_id": {"$in": doc_ids}}, include=["documents", "metadatas", "distances"])` per `rerank_candidates()` | **`113` (`1.00/req`)** | **`241`** | `108` | `2,825/2,825` (`0.0` float diff) | `113/113` | **PASS** (superseded by R4) |
| **Cand R2 (`bulk_unfiltered_full_include`)** | Single `collection.query(n_results=106, include=["documents", "metadatas", "distances"])` per request | `113` (`1.00/req`) | `241` | `108` | `2,825/2,825` (`0.0` float diff) | `113/113` | **SUPERSEDED** (SQLite deserializes all 106 rows every query; `~19 ms` vs `~2.5 ms` in R4) |
| **Cand R3 (`in_memory_numpy_cosine`)** | Pre-indexed `float32` embeddings in NumPy (`1.0 - mat @ q_vec`) | `0` | `128` | `0` | `0` order diffs, **`343/2,825` `to_dict()` `round(distance, 6)` diffs** (`max_diff = 3.58e-7`) | Fails strict `distances` debug check | **REJECT** (float32 accumulation order differs from Chroma HNSW C++ SIMD) |
| **Cand R4 (`batched_where_distances_with_preindexed_chunks`)** | Single batched `collection.query(where={"doc_id": {"$in": doc_ids}}, include=["distances"])` + pre-indexed chunk `(doc, md, heading_path)` & `page_chunks` in `PageRetriever` (`571.5 KB`) | **`113` (`1.00/req`)** | **`241`** | **`0`** | **`2,825/2,825` (`0.0` float diff)** | **`113/113`** | **PASS & ADOPTED** |

### Workstream B — Controlled Ollama Generation Experiments (`llama3.2:3b`, `temperature=0`, `seed=42`)

| Experiment ID | Parameter Tested | Value(s) | Deterministic / Checkpoint Replay Findings (`n=113` / `75` LLM Calls) | Live Ollama Latency (`p50/p95/p99`) | Decision |
| :--- | :--- | :---: | :--- | :---: | :---: |
| **Exp G-A (Baseline)** | Default `OllamaClient` | `num_predict=None`, `keep_alive=None`, `budget=700`, `stream=False` | Guarded `43/65`, Oracle `44/65`, Wrong-page `1`, Absent-detail `0/16`, Grounding `0`, Phantom `0`; answered output tokens `p50=29.0, p95=113.05, max=146` (`43` correct: `p50=27.0, p95=54.9, max=63`) | `NOT_VERIFIED` in Linux sandbox | **KEEP (Production Default)** |
| **Exp G-B1..B3** | Bounded `num_predict` | `256`, `192`, `160` | `0/58` answered responses exceed `160`, `192`, or `256` tokens (`max=146` on `P12-105`); checkpoint replay preserves `43/65` guarded / `44/65` oracle | `NOT_VERIFIED` in Linux sandbox | **INCONCLUSIVE / NOT VERIFIED** (safe on token lengths; requires Windows live timing run) |
| **Exp G-B4** | Aggressive `num_predict` | `128` | Truncates answered query `P12-105` (`146` tokens) mid-sentence; backward citation inheritance in `split_cited_sentences()` masks truncation | `NOT_VERIFIED` in Linux sandbox | **REJECT** (silent mid-sentence truncation hazard) |
| **Exp G-C** | `keep_alive` | `-1` vs default (`5m`) | Optional `keep_alive` wired in `OllamaClient` & `PipelineConfig` (default `None`) | `NOT_VERIFIED` in Linux sandbox | **INCONCLUSIVE / NOT VERIFIED** (requires Windows daemon validation) |
| **Exp G-D** | `context_budget_tokens` | `700` vs `600` vs `500` | `600` drops cited `[S4]` on `6` answered LLM queries (`P12-002, 029, 036, 037, 038, 039`); `500` drops `[S4]` on `7` answered LLM queries (`+ P12-051`) and regresses Extractive `52/65 -> 51/65` | Deterministic (`0` ms gain; breaks context evidence) | **REJECT** (`700` required for `[S4]` evidence) |
| **Exp G-E** | Streaming vs Non-Streaming | `stream=True` vs `stream=False` | `17/75` (`22.67%`) LLM calls fail post-generation grounding (`16` `GROUNDING_VERIFICATION_FAILED` + `1` `GENERATOR_REFUSED`) and are withheld | Deterministic safety gate | **REJECT** (unbuffered streaming leaks unverified/ungrounded tokens on `22.7%` of LLM calls) |

---

## 3. Exact Operation-Count Changes (`n = 113` Frozen Queries)

| Operation Counter | Phase 18 (`HEAD 25ced60`) | Phase 19A Baseline | Phase 19B (Adopted `Cand R4`) | Delta vs Phase 19A | Delta vs Phase 18 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Query Embeddings (`retriever.embed`)** | `241` (`2.13/req`) | `113` (`1.00/req`) | **`113` (`1.00/req`)** | `0 (0.0%)` | **`-128 (-53.1%)`** |
| **Card Store Chroma Queries (`sap_m2c_card_v1`)** | `128` (`1.13/req`) | `128` (`1.13/req`) | **`128` (`1.13/req`)** | `0 (0.0%)` | `0 (0.0%)` |
| **Reranker Page Chroma Queries (`sap_pages_v1`)** | `981` (`8.68/req`) | `981` (`8.68/req`) | **`113` (`1.00/req`)** | **`-868 (-88.5%)`** | **`-868 (-88.5%)`** |
| **Step-5 Winning-Page Chroma Queries (`sap_pages_v1`)** | `107` (`0.95/req`) | `0` (`0.00/req`) | **`0` (`0.00/req`)** | `0` | **`-107 (-100.0%)`** |
| **Total Chroma `.query()` Calls (`card + page`)** | `1,216` (`10.76/req`) | `1,109` (`9.81/req`) | **`241` (`2.13/req`)** | **`-868 (-78.3%)`** | **`-975 (-80.2%)`** |
| **Hot-Path `collection.get()` Calls (`page_chunks`)** | `108` (`0.96/req`) | `108` (`0.96/req`) | **`0` (`0.00/req`)** | **`-108 (-100.0%)`** | **`-108 (-100.0%)`** |
| **Memory Impact (`PageRetriever` Pre-Index)** | `0 KB` | `0 KB` | **`571.54 KB` (`0.56 MB`)** | `+571.54 KB` | `+571.54 KB` |

---

## 4. Latency Before / After (`n = 113` Frozen Queries, Deterministic Pipeline)

### A. Same-Process Back-to-Back Benchmark (`scripts/evaluate_phase19b.py`, `n = 113`)

| Stage (`ms`) | Percentile | Phase 19A Baseline | Phase 19B (`Cand R4`) | Delta (`ms` / `%`) |
| :--- | :---: | :---: | :---: | :---: |
| **`route_ms`** (`n=113`) | `min` | `49.20` | **`27.88`** | **`-21.32 ms (-43.3%)`** |
| | `p50` | `66.49` | **`38.08`** | **`-28.41 ms (-42.7%)`** |
| | `p90` | `88.13` | **`61.06`** | **`-27.07 ms (-30.7%)`** |
| | `p95` | `93.43` | **`67.01`** | **`-26.42 ms (-28.3%)`** |
| | `p99` | `104.89` | **`83.83`** | **`-21.06 ms (-20.1%)`** |
| | `mean` | `68.89` | **`42.87`** | **`-26.02 ms (-37.8%)`** |
| **`retrieve_ms`** (Step 5, `n=107`) | `p50 / p95 / p99` | `0.00 / 0.00 / 0.01` | **`0.00 / 0.00 / 0.00`** | **`0.00 ms` (100% cache hit)** |
| **`total_ms`** (extractive E2E, `n=113`) | `min` | `53.25` | **`32.26`** | **`-20.99 ms (-39.4%)`** |
| | `p50` | `76.07` | **`48.14`** | **`-27.93 ms (-36.7%)`** |
| | `p90` | `101.76` | **`75.87`** | **`-25.89 ms (-25.4%)`** |
| | `p95` | `108.22` | **`82.88`** | **`-25.34 ms (-23.4%)`** |
| | `p99` | `120.76` | **`101.44`** | **`-19.32 ms (-16.0%)`** |
| | `mean` | `79.17` | **`52.56`** | **`-26.61 ms (-33.6%)`** |

*(Note: Under dedicated single-pass runs without multi-pass CPU throttling, Phase 19B `route_ms` reaches `p50 = 28.69–28.93 ms, p95 = 40.23–43.98 ms, p99 = 46.91–58.94 ms` and extractive `total_ms` reaches `p50 = 33.04–36.45 ms, p95 = 49.35–53.15 ms, p99 = 57.96–67.99 ms`, compared to Phase 19A's recorded `route_ms p50 = 47.53 ms, p95 = 54.07 ms` and `total_ms p50 = 53.55 ms, p95 = 61.60 ms`.)*

---

## 5. Correctness Before / After (`n = 113` Frozen Queries)

| Metric | Phase 18 (`e1a_v2`) | Phase 19A | Phase 19B (`Cand R4`) | Gate Requirement | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Router R@1 (Answerable, `n=65`)** | `62/65 (95.38%)` | `62/65 (95.38%)` | **`62/65 (95.38%)`** | Unchanged (`62/65`) | **PASS (`0` diffs)** |
| **Router R@1 (All-Gold, `n=105`)** | `91/105 (86.67%)` | `91/105 (86.67%)` | **`91/105 (86.67%)`** | Unchanged (`91/105`) | **PASS (`0` diffs)** |
| **Gold-in-Pool (`n=105`)** | `105/105 (100.0%)` | `105/105 (100.0%)` | **`105/105 (100.0%)`** | `= 105/105` | **PASS (`0` diffs)** |
| **Extractive Answerable Correct (`n=65`)** | `52/65 (80.00%)` | `52/65 (80.00%)` | **`52/65 (80.00%)`** | `= 52/65` | **PASS (`0` diffs)** |
| **Wrong-Page Answers (Extractive)** | `3` | `3` | **`3`** | `<= 3` | **PASS (`0` diffs)** |
| **Guarded Ollama Answerable (`n=65`, ckpt)** | `43/65 (66.15%)` | `43/65 (66.15%)` | **`43/65 (66.15%)`** | `>= 43/65` | **PASS (`0` diffs)** |
| **Oracle Ollama Answerable (`n=65`, ckpt)** | `44/65 (67.69%)` | `44/65 (67.69%)` | **`44/65 (67.69%)`** | `>= 44/65` | **PASS (`0` diffs)** |
| **Wrong-Page Answers (Guarded Ollama)** | `1` | `1` | **`1`** | `<= 1` | **PASS (`0` diffs)** |
| **Absent-Detail Answered (Guarded Ollama)** | `0/16` | `0/16` | **`0/16`** | `= 0/16` | **PASS (`0` diffs)** |
| **Grounding Failures** | `0` | `0` | **`0`** | `= 0` | **PASS** |
| **Phantom Citations** | `0` | `0` | **`0`** | `= 0` | **PASS** |
| **URL Changes** | `0` | `0` | **`0`** | `= 0` | **PASS** |
| **Generator Errors** | `0` | `0` | **`0`** | `= 0` | **PASS** |

---

## 6. Retrieval & Pipeline Exact Equivalence Gate (Part 3)

Comparing Phase 19A vs Phase 19B (`Cand R4`) across all **113 frozen benchmark queries** (`113/113`) and all **2,825 `(query, page)` pairs** (`113 queries x 25 pages`):

| Verification Dimension | Compared Count | Exact Matches | Mismatches | Max Float Diff |
| :--- | :---: | :---: | :---: | :---: |
| **`(query, page)` `retrieve_many_pages` vs `retrieve_in_page`** | `2,825` | **`2,825/2,825 (100%)`** | `0` | `0.0` |
| **`status`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`answer` (extractive)** | `113` | **`113/113 (100%)`** | `0` | — |
| **`reason_code`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`message`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`topic`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`citations`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`routing` & `candidate_ordering`** | `113` | **`113/113 (100%)`** | `0` | `0.0` |
| **`ui` fields** | `113` | **`113/113 (100%)`** | `0` | — |
| **`debug` fields (deterministic)** | `113` | **`113/113 (100%)`** | `0` | `0.0` |
| **`selected_page`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`selected_chunk_ids` & `chunk_indexes`** | `113` | **`113/113 (100%)`** | `0` | — |
| **`distances` (`round(distance, 6)`)** | `113` | **`113/113 (100%)`** | `0` | `0.0` |
| **`context_block` (`ContextBlock.to_dict(with_text=True)`)** | `113` | **`113/113 (100%)`** | `0` | — |
| **`grounding_result`** | `113` | **`113/113 (100%)`** | `0` | — |
| **Full `answer(debug=True)` dict (excluding `timings_ms`)** | `113` | **`113/113 (100%)`** | `0` | `0.0` |
| **Full `answer(debug=True)` with `EvidenceRetriever(widen=True)`** | `113` | **`113/113 (100%)`** | `0` | `0.0` |

---

## 7. Ollama Generation Results (Part 4)

### A. Generation Request & Token Profile (`n = 75` Queries Passing `EvidenceGuard` Pre-Check)
- Across the 113 frozen queries:
  - `6` stop before Step 7 (`5` `out_of_domain` + `1` `unresolved_identity`).
  - `32` are refused deterministically by `EvidenceGuard` pre-check (`decision.supported == False`) in `< 1 ms` without calling Ollama.
  - `75` reach `OllamaClient.generate()` (`model="llama3.2:3b"`, `stream=False`, `options={"temperature": 0, "seed": 42}`):
    - **Prompt instruction header:** `140` WordPiece tokens
    - **Context tokens (`n=75`):** `min = 32, p50 = 461.0, p90 = 606.0, p95 = 611.0, p99 = 628.08, max = 634, mean = 438.75`
    - **Total input prompt tokens (`n=75`):** `min = 199, p50 = 653.0, p90 = 810.6, p95 = 818.0, p99 = 824.04, max = 827, mean = 633.72`
    - **Output tokens (`n=58` answered in Windows checkpoint):** `min = 15, p50 = 29.0, p90 = 56.6, p95 = 113.05, p99 = 135.17, max = 146, mean = 35.83`
    - **Output tokens (`n=43` correct answerable in Windows checkpoint):** `min = 15, p50 = 27.0, p90 = 43.6, p95 = 54.9, p99 = 60.9, max = 63, mean = 30.14`

### B. Controlled Generation Experiments
1. **`num_predict` Sweep (`default`, `256`, `192`, `160`, `128`):**
   - `num_predict = 256`, `192`, and `160`: `0/58` answered responses in the Windows checkpoint exceed `146` tokens (`P12-105` is the longest answered output at `146` tokens; `63` tokens is the longest correct answerable output).
   - `num_predict = 128`: **REJECTED.** Truncates `P12-105` (`146` tokens) mid-sentence; because the final line still ends with `[S1]`, backward citation inheritance in `split_cited_sentences()` allows the truncated sentence to pass `verify_grounding()`.
2. **`keep_alive` (`-1` vs default `5m`):**
   - Optional `num_predict` and `keep_alive` parameters are wired into `OllamaClient` (`scripts/rag_generate.py`) and `PipelineConfig` (`scripts/rag_pipeline.py`) with production defaults `None` (preserving `rag_core.LLM_OPTIONS` unchanged).
3. **Prompt / Context Budget (`700` vs `600` vs `500`):**
   - **REJECTED (`600` and `500`).** Reducing `context_budget_tokens` from `700` to `600` changes the context hash on `15/75` LLM queries and drops `[S4]` on `6` answered queries (`P12-002, P12-029, P12-036, P12-037, P12-038, P12-039`) whose verified Windows Ollama answers explicitly cite `[S4]`. Reducing to `500` drops `[S4]` on `7` answered LLM queries (`+ P12-051`) and regresses Extractive correctness (`52/65 -> 51/65`).
4. **Streaming vs Non-Streaming (`stream=True` vs `stream=False`):**
   - **REJECTED (unbuffered streaming).** Out of `75` LLM calls, `17/75` (`22.67%`) fail post-generation checks (`16` `GROUNDING_VERIFICATION_FAILED` + `1` `GENERATOR_REFUSED`) and must be withheld. Streaming tokens before `verify_grounding()` completes would expose unverified text and phantom citations on `22.7%` of LLM calls.

---

## 8. Windows Validation Status (Part 5)

- **Sandbox Ollama Probe (`http://127.0.0.1:11434/api/tags`):** `ollama_available() == False` (no local Ollama daemon in the Linux sandbox).
- **Generation Latency Status:** **`NOT VERIFIED`** in the Linux sandbox. No live Ollama timing numbers are fabricated.
- **Deterministic Windows Validation Harness:** `scripts/evaluate_phase19b.py` is ready to run on the Windows Ollama machine (`llama3.2:3b`, `temperature=0`, `seed=42`):
  ```powershell
  python scripts/evaluate_phase19b.py --live-ollama --out data/phase19/phase19b_metrics.json
  ```
- **Production Policy:** Per Part 5 & Part 8, production generation settings (`ollama_num_predict=None`, `ollama_keep_alive=None`, `context_budget_tokens=700`) are **NOT modified**.

---

## 9. Rejected Experiments and Why

1. **Candidate R3 (`in_memory_numpy_cosine` for Reranker Page Retrieval) — REJECTED:**
   - Although chunk ordering matched (`0` order mismatches across `2,825` `(query, page)` checks), OpenBLAS/NumPy `float32` matrix multiplication (`1.0 - mat @ q_vec`) differs in floating-point accumulation order from Chroma's C++ `hnswlib` SIMD inner product by up to `3.58e-7`, causing `round(distance, 6)` in `ChunkHit.to_dict()` / `debug["retrieved"]` to differ by `1e-6` on **`343 / 2,825` (`12.1%`)** pairs. Rejected under Part 3's strict `distances` equivalence gate.
2. **Candidate R2 (`bulk_unfiltered_full_include`) — SUPERSEDED / REJECTED:**
   - Querying all `106` chunks with `include=["documents", "metadatas", "distances"]` deserializes all `106` document and 20-column metadata rows from SQLite on every request (`~19 ms`), whereas Candidate R4 filters to candidate `doc_id`s with `include=["distances"]` and resolves `(doc, md, heading_path)` from memory in `~2.5 ms`.
3. **Experiment G-B4 (`num_predict=128`) — REJECTED:**
   - Truncates `P12-105` (`146` tokens) mid-sentence while still passing `verify_grounding()` via backward citation inheritance.
4. **Experiment G-D (`context_budget_tokens = 600` or `500`) — REJECTED:**
   - Drops cited `[S4]` evidence chunks on `6` (`budget=600`) to `7` (`budget=500`) answered queries and regresses extractive accuracy (`52/65 -> 51/65`).
5. **Experiment G-E (Unbuffered Token Streaming) — REJECTED:**
   - Violates the grounding contract on the `17/75` (`22.67%`) LLM calls withheld post-generation by `verify_grounding()`.

---

## 10. Adopted Candidate (Part 8)

- **Workstream A (Reranker Page-Query Consolidation) — `PASS` (Adopted Candidate R4):**
  - `PageRetriever.retrieve_many_pages()` (`scripts/page_retriever.py`) executes **one** batched Chroma query (`where={"doc_id": {"$in": doc_ids}}, include=["distances"]`) per `rerank_candidates()` call and reconstructs `ChunkHit` objects from a count-validated in-memory index (`571.54 KB`), while `PageRetriever.page_chunks()` serves Step 3 lexical gate chunks from the same index.
  - `EvidenceRetriever.retrieve_many_pages()` (`scripts/rag_evidence.py`) and `rerank_candidates()` (`scripts/phase13_reranker.py`) use `retrieve_many_pages()` whenever `retrieve_in_page` / `_query` has not been monkeypatched on the retriever instance (preserving full backward compatibility with all existing spy/stub unit tests).
  - Additionally, `RagService` (`scripts/rag_service.py`) uses thread-local `.last` / `.last_telemetry` (`threading.local()`), post-precheck `EvidenceGuard._llm_lock`, and bounded concurrency (`MAX_CONCURRENT_REQUESTS = 4`).
- **Workstream B (Ollama Generation Parameters) — `INCONCLUSIVE / NOT VERIFIED` (Production Unchanged):**
  - Telemetry extraction (`_extract_ollama_telemetry`, `GenerationResult.telemetry`) and optional `num_predict`/`keep_alive` knobs are wired for controlled evaluation, with production defaults kept at `None`.

---

## 11. Production Config

`scripts/rag_service.py::production_pipeline_config()` remains:

```python
RP.PipelineConfig(
    top_k_cards=10,
    k_chunks=5,
    context_budget_tokens=700,
    max_context_chunks=4,
    ood_min_coverage=0.25,
    context_min_coverage=0.5,
    rerank_router=True,
    code_aware_router=True,
    in_page_grounding=True,
    citation_normalization=True,
    relaxed_context_gate=True,
    evidence_frame_normalization=False,
    phrase_reranker=True,
    phrase_min_corroboration=2,
    full_page_coverage=False,
    citation_repair=False,
    ollama_num_predict=None,
    ollama_keep_alive=None,
)
```

---

## 12. Tests (Part 7)

All **166 tests PASS** (`15.62s`), including:
- `tests/test_phase19b_generation_latency.py` (**13/13 PASSED**):
  - `test_01`..`test_09`: Default `OllamaClient` invariants, optional `num_predict`/`keep_alive` wiring, privacy-safe telemetry extraction, post-check telemetry preservation, `EvidenceRetriever` `query_embedding` forwarding, grounding safety gates, production config invariants, thread-local isolation under 8-worker concurrency, and non-blocking `EvidenceGuard` pre-check refusal (`< 50 ms`) while an LLM call is in flight.
  - `test_10_exact_old_new_retrieval_chunk_ordering_and_distance_equivalence`: Verifies `retrieve_many_pages` vs `retrieve_in_page` across all 25 pages (`chunk_id`, `chunk_index`, `distance`, `to_dict()`).
  - `test_11_candidate_ordering_context_citation_equivalence_and_chroma_query_count`: Verifies `1` page Chroma query and `0` `collection.get` calls per `answer()`, plus exact equivalence of candidate ordering, context, citations, and full `answer(debug=True)` output.
  - `test_12_unsupported_absent_detail_and_leakage_guards`: Verifies out-of-domain, unresolved identity, absent-detail refusal, `ValueError` on empty identity, and `LeakageError` on cross-page chunk leakage.
  - `test_13_concurrent_request_deterministic_repeat_and_cache_isolation`: Verifies deterministic repeated requests and 6-worker concurrent request isolation.
- `tests/test_phase19a_latency.py` (**12/12 PASSED**)
- `tests/test_phase18_production_config.py`, `tests/test_phase18_reranker.py`, `tests/test_phase18_citation_repair.py`, `tests/test_phase17a_evidence.py`, `tests/test_phase16_context.py`, `tests/test_phase15_hybrid.py`, `tests/test_phase14_recall.py`, `tests/test_phase13_reranker.py`, `tests/test_phase11_1_evidence.py`, `tests/test_phase8_context_generation.py` (**141/141 PASSED**).

---

## 13. Remaining Bottleneck

1. **Deterministic Routing & Retrieval (`route_ms` `p50 ~ 28.9–38.1 ms`):**
   - Now dominated by the **single CPU query embedding** (`SentenceTransformer.encode` on `all-MiniLM-L6-v2`, `~15–18 ms`), followed by `1` card Chroma query + `1` batched page Chroma query (`~5–6 ms` combined) and Python phrase/identity/tokenization overhead (`~5–8 ms`).
2. **End-to-End Guarded Ollama Mode:**
   - Dominated by `llama3.2:3b` generation latency and the **`17/75` (`22.67%`) post-generation withheld LLM calls** (`9` answerable queries where `llama3.2:3b` fails `verify_grounding` even though `EvidenceExtractiveGenerator` succeeds on `8/9`, plus `8` non-answerable/ambiguous queries that pass `EvidenceGuard` pre-check and invoke Ollama before failing `verify_grounding`).

---

## 14. Explicit Recommendation for Phase 20

1. **Execute Live Windows Ollama Validation (`scripts/evaluate_phase19b.py --live-ollama`):**
   - Run the Phase 19B harness on the Windows Ollama machine to record verified live `generate_ms` `p50/p95/p99` for `num_predict=192` and `keep_alive=-1`.
2. **Phase 20A — Close the Guarded (`43/65`) vs Extractive (`52/65`) Gap on Post-Generation Grounding Failures:**
   - On the `9` answerable queries where `EvidenceGuard` pre-check passes (`decision.supported == True`) but `llama3.2:3b`'s generated phrasing fails `verify_grounding()` (`P12-001, 010, 030, 035, 044, 050, 053, 057, 060`), evaluate a **verified extractive fallback** (`EvidenceExtractiveGenerator.generate()`) gated by the same `verify_grounding()` + `verify_support_chain()` checks. On the frozen benchmark, `8` of those `9` queries are answered accurately by `EvidenceExtractiveGenerator`, offering a potential **`43/65 -> 51/65` (`+8`)** guarded accuracy improvement with zero relaxation of grounding safety.
3. **Phase 20B — Pre-Check Tightening for Non-Answerable Procedural/Ambiguous Queries:**
   - Investigate pre-check rules for the `8` non-answerable/ambiguous queries (`P12-071, 084, 085, 091, 092, 096, 100, 102`) that currently pass `EvidenceGuard` pre-check and invoke Ollama only to be withheld by `verify_grounding()`, eliminating wasted LLM compute on unsupported queries.
