# Phase 19C Final Validation — Stop Optimizing, Verify and Close

**Validation Status:** **`VALIDATED`**
**Phase 19 Closure Status:** **`READY TO CLOSE`**

---

## 1. Final Architecture

1. **Bounded Service Request Concurrency (`RagService._request_sem`):**
   - `RagService` (`scripts/rag_service.py`) gates active in-flight pipeline execution via a fair FIFO bounded semaphore `_FIFOBoundedSemaphore(max_concurrency=4)` (`MAX_CONCURRENT_REQUESTS = 4`).
   - Waiting worker threads acquire permits in strict FIFO arrival order without thread starvation, while bounding simultaneous CPU embedding (`SentenceTransformer.encode`) and Chroma vector queries to 4 concurrent threads.
2. **Fine-Grained Generation Lock (`RagService._gen_sem` / `EvidenceGuard._gen_sem`):**
   - Request validation (`clean_question`, `resolve_conversation_id`), query embedding, card routing, candidate reranking, batched page retrieval (`PageRetriever.retrieve_many_pages`), identity resolution, Step 3 lexical gate, context construction (`ContextBuilder.build`), and `EvidenceGuard` pre-check (`analyze_question`, `build_units`, `assess`) all execute **outside** `_gen_sem`.
   - Across the 113 frozen benchmark queries in Guarded Ollama mode, **`38 / 113` (`33.6%`)** queries (`6` pre-routing exits + `32` `EvidenceGuard` pre-check refusals) exit before generation and never acquire `_gen_sem`.
   - Only actual LLM generation (`self.inner.generate(question, context)` -> `OllamaClient.generate_with_telemetry(prompt)`) acquires `_gen_sem` (`DEFAULT_GENERATION_CONCURRENCY = 1`), and immediately releases `_gen_sem` before `EvidenceGuard` post-check (`kind_satisfied`), `verify_grounding()`, citation normalization, and response construction.
3. **Dual Request-Local State Isolation:**
   - **Explicit Per-Invocation Return Objects:** `GenerationResult` (`scripts/rag_generate.py`) carries `evidence: Optional[Dict[str, Any]] = None` and `telemetry: Optional[Dict[str, Any]] = None`; `OllamaClient.generate_with_telemetry(prompt)` returns `(text, telemetry)` directly; `EvidenceRetriever.retrieve_in_page_with_promotion()` returns `(hits, promoted_chunk_id)` directly; `RagPipeline.answer()` and `RagService.ask()` pass `evidence` through the per-request return dictionary.
   - **Thread-Local Storage + Per-Request Reset:** `EvidenceGuard.last`, `EvidenceExtractiveGenerator.last`, `EvidenceRetriever.last_promoted`, and `OllamaClient.last_telemetry` are backed by `threading.local()` properties AND explicitly cleared at the start of every request via `reset_request_state()` in `RagService._run_pipeline_request()`, `RagPipeline.answer()`, `EvidenceGuard.generate()`, `EvidenceExtractiveGenerator.generate()`, `EvidenceRetriever.retrieve_in_page_with_promotion()`, and `OllamaClient.generate_with_telemetry()`.
4. **Reranker Batched Page Retrieval & Thread-Safe Bounded Caches:**
   - `PageRetriever.retrieve_many_pages()` (`scripts/page_retriever.py`) executes a single batched Chroma query per `rerank_candidates()` call (`card_q=128, page_q=113, total_chroma_q=241` across `n=113`), and `PageRetriever.page_chunks()` / `PageCorpusIndex.entry()` return defensive copies under `threading.Lock()`.

---

## 2. Final Concurrency Setting

- **`MAX_CONCURRENT_REQUESTS = 4`** (`RagService(pipeline, generator, max_concurrency=4, generation_concurrency=1, coarse_lock=False)`)
- **`DEFAULT_GENERATION_CONCURRENCY = 1`** (serializes only inner `OllamaClient` HTTP calls while allowing up to 4 concurrent routing/retrieval/pre-check/post-check threads).

### Controlled Semaphore Comparison (`max_concurrency = 2, 4, 6` across `n = 113` Queries)

| `max_concurrency` | Worker Pool (`w`) | Throughput (`req/s`) | `total_ms` `p50` | `total_ms` `p95` | `total_ms` `p99` | Errors | Determinism Mismatches |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`2`** | `10` | `38.02` | `262.56 ms` | `296.55 ms` | `304.85 ms` | `0` | `0` |
| **`2`** | `20` | `39.24` | `503.72 ms` | `549.60 ms` | `552.44 ms` | `0` | `0` |
| **`4` (Chosen)** | `10` | **`34.58–40.40`** | **`243.68–274.94 ms`** | **`300.63–356.12 ms`** | **`315.64–445.56 ms`** | **`0`** | **`0`** |
| **`4` (Chosen)** | `20` | **`40.43–40.65`** | **`478.75–487.77 ms`** | **`540.62–554.41 ms`** | **`558.20–563.76 ms`** | **`0`** | **`0`** |
| **`6`** | `10` | `39.20` | `247.06 ms` | `325.08 ms` | `334.82 ms` | `0` | `0` |
| **`6`** | `20` | `35.96` | `526.66 ms` | `638.86 ms` | `684.20 ms` | `0` | `0` |

**Decision:** `max_concurrency = 4` is chosen. It achieves peak 20-worker throughput (`40.43–40.65 req/s`) and `300.63 ms` 10-worker `p95` without the 20-worker CPU contention degradation seen at `max_concurrency = 6` (`35.96 req/s, p95 = 638.86 ms`).

---

## 3. Concurrency Results (`1, 2, 5, 10, 20` Workers, `max_concurrency = 4`, `n = 113`)

| Workers (`w`) | Wall Time (`s`) | Throughput (`req/s`) | `total_ms` `p50` | `total_ms` `p95` | `total_ms` `p99` | `route_ms` `p50 / p95` | Errors | Determinism Mismatches | Evidence Contamination | Citation Contamination | Grounding Regressions |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`1`** | `3.963` | **`28.51`** | `34.26 ms` | `43.64 ms` | `51.20 ms` | `28.54 / 37.36 ms` | `0` | `0` | `0` | `0` | `0` |
| **`2`** | `2.970` | **`38.05`** | `50.83 ms` | `69.16 ms` | `75.47 ms` | `43.83 / 59.35 ms` | `0` | `0` | `0` | `0` | `0` |
| **`5`** | `2.981` | **`37.91`** | `133.04 ms` | `178.25 ms` | `190.99 ms` | `93.36 / 127.83 ms` | `0` | `0` | `0` | `0` | `0` |
| **`10`** | `2.797` | **`40.40`** | `243.68 ms` | **`300.63 ms`** | **`315.64 ms`** | `90.26 / 123.51 ms` | `0` | `0` | `0` | `0` | `0` |
| **`20`** | `2.780` | **`40.65`** | `478.75 ms` | **`540.62 ms`** | **`558.20 ms`** | `89.31 / 127.09 ms` | `0` | `0` | `0` | `0` | `0` |

All acceptance criteria (`0` errors, `0` determinism mismatches, `0` cross-request evidence contamination, `0` citation contamination, `0` grounding regressions) are satisfied across all worker counts.

---

## 4. Isolation Verification (`Task 1` Audit)

| Component | State Field(s) | Isolation Mechanism | Per-Request Reset Hook | Sequential Same-Thread Early-Exit Leak Check | Cross-Thread Leak Check (`20` Workers) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **`EvidenceGuard`** | `.last` | `threading.local()` + `GenerationResult.evidence` deep copy | `reset_request_state()` at start of `RagService._run_pipeline_request()`, `RagPipeline.answer()`, and `EvidenceGuard.generate()` | **`0` leaks (`PASS`)** | **`0` leaks (`PASS`)** |
| **`EvidenceExtractiveGenerator`** | `.last` | `threading.local()` + `GenerationResult.evidence` deep copy | `reset_request_state()` at start of `RagService._run_pipeline_request()`, `RagPipeline.answer()`, and `EvidenceExtractiveGenerator.generate()` | **`0` leaks (`PASS`)** | **`0` leaks (`PASS`)** |
| **`EvidenceRetriever`** | `.last_promoted` | `threading.local()` + `retrieve_in_page_with_promotion()` tuple return | `reset_request_state()` at start of `RagService._run_pipeline_request()`, `RagPipeline.answer()`, `retrieve_in_page_with_promotion()`, and `retrieve_many_pages()` | **`0` leaks (`PASS`)** | **`0` leaks (`PASS`)** |
| **`OllamaClient`** | `.last_telemetry` | `threading.local()` + `generate_with_telemetry()` tuple return | `reset_request_state()` at start of `EvidenceGuard.reset_request_state()` and `OllamaClient.generate_with_telemetry()` | **`0` leaks (`PASS`)** | **`0` leaks (`PASS`)** |
| **`RagService`** | `evidence`, `timings_ms` | Local stack variables in `_run_pipeline_request()` | Calls `self._reset_request_state()` before `self.pipeline.answer(q, debug=True)` on every `ask()` invocation | **`0` leaks (`PASS`)** | **`0` leaks (`PASS`)** |

Specifically verified: when a single worker thread executes an answered query (`P12-001`, which populates `.last`, `.last_telemetry`, and `.last_promoted`) followed immediately on the **same worker thread** by an out-of-domain query (`P12-106`, which exits at Step 3 before reaching Step 5 retrieval or Step 7 generation), `r["debug"]["evidence"]`, `svc._evidence_gen.last`, `retriever.last_promoted`, and `client.last_telemetry` are all reset to `None` / `{}` with **zero sequential state leakage**.

---

## 5. Windows Ollama Validation Status (`Task 4`)

- **Local Ollama Probe (`http://127.0.0.1:11434/api/tags`):** `ollama_available() == False` (the Windows Ollama host is not accessible from this Linux sandbox).
- **Validation Status:** **`NOT VERIFIED`** in this environment. No live Windows Ollama timing numbers are fabricated or claimed.
- **Promotion Decision:** Per Task 4 rules, `ollama_num_predict=192` and `ollama_keep_alive=-1` are **NOT** promoted to production defaults without live Windows measurement. Production generation settings remain strictly unchanged (`ollama_num_predict=None`, `ollama_keep_alive=None`).
- **Ready-to-Run Windows Command:**
  ```powershell
  python scripts/evaluate_phase19b.py --live-ollama --out data/phase19/phase19b_metrics.json
  ```

---

## 6. Production Generation Configuration

`scripts/rag_service.py::production_pipeline_config()` remains unchanged:

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
- **Model & Sampling (`scripts/rag_core.py`):** `LLM_MODEL_NAME = "llama3.2:3b"`, `LLM_OPTIONS = {"temperature": 0, "seed": 42}`
- **Service Concurrency (`scripts/rag_service.py`):** `MAX_CONCURRENT_REQUESTS = 4`, `DEFAULT_GENERATION_CONCURRENCY = 1`

---

## 7. Complete Test Count (`Task 5`)

All **13 regression test suites (172 / 172 tests — 100% pass rate)** pass in `18.06s`:
- `tests/test_phase8_context_generation.py`
- `tests/test_phase11_1_evidence.py`
- `tests/test_phase13_reranker.py`
- `tests/test_phase14_recall.py`
- `tests/test_phase15_hybrid.py`
- `tests/test_phase16_context.py`
- `tests/test_phase17a_evidence.py`
- `tests/test_phase18_citation_repair.py`
- `tests/test_phase18_reranker.py`
- `tests/test_phase18_production_config.py`
- `tests/test_phase19a_latency.py` (`12/12` passed)
- `tests/test_phase19b_generation_latency.py` (`7/7` passed)
- `tests/test_phase19c_concurrency.py` (`12/12` passed)

---

## 8. Remaining Known Limitations

1. **Live Windows Ollama Generation Latency (`num_predict=192`, `keep_alive=-1`):**
   - Wired and unit-tested in `OllamaClient` and `scripts/evaluate_phase19b.py`, but remains `NOT VERIFIED` until executed against the live Windows Ollama daemon.
2. **Guarded Ollama (`43/65`) vs Extractive (`52/65`) Accuracy Gap:**
   - On `9` answerable queries (`P12-001, 010, 030, 035, 044, 050, 053, 057, 060`), `EvidenceGuard` pre-check passes but `llama3.2:3b` produces phrasing that fails `verify_grounding()`, even though `EvidenceExtractiveGenerator` answers `8/9` of those queries accurately.
3. **Single-Process CPU Embedding Throughput Ceiling (`~40.6 req/s`):**
   - `SentenceTransformer.encode` (`all-MiniLM-L6-v2` on CPU) accounts for `~15–18 ms` of the `~28 ms` single-request routing time, bounding single-process CPU throughput to `~40 req/s` at `max_concurrency = 4`.

---

## 9. Explicit Statement on Closing Phase 19

**Phase 19 (`19A` Routing/Retrieval Latency Optimization, `19B` Batched Reranker Page Retrieval & Generation Telemetry, and `19C` Fine-Grained Service Concurrency & Request Isolation) is VALIDATED and READY TO CLOSE.** No further Phase 19 optimization work is needed.
