# Phase 19C — Fine-Grained Service Concurrency / Generation Lock Refactor

## 1. Executive Summary

Phase 19C eliminates the coarse service-level request serialization bottleneck in `RagService` (`scripts/rag_service.py`) by refactoring mutable per-request evidence/telemetry state into explicit return values on `GenerationResult` (`scripts/rag_generate.py`, `scripts/rag_evidence.py`) and narrowing synchronization to a bounded generation semaphore (`_gen_sem`) acquired **only** around actual LLM generation (`OllamaClient.generate()`).

### Key Outcomes (`n = 113` Frozen Benchmark Queries)
- **Zero-Shortcut Request-Local Evidence Isolation:**
  - `GenerationResult` (`scripts/rag_generate.py`) now carries `evidence: Optional[Dict[str, Any]] = None` alongside `telemetry: Optional[Dict[str, Any]] = None`.
  - `EvidenceExtractiveGenerator.generate()` and `EvidenceGuard.generate()` (`scripts/rag_evidence.py`) attach an isolated deep copy of the per-invocation `record` directly onto `GenerationResult.evidence`.
  - `OllamaClient.generate_with_telemetry(prompt)` (`scripts/rag_generate.py`) returns `(text, telemetry)` directly per call without relying on `self.last_telemetry`.
  - `EvidenceRetriever.retrieve_in_page_with_promotion()` (`scripts/rag_evidence.py`) returns `(hits, promoted)` explicitly without mutating shared `self.last_promoted` state during pipeline requests.
  - `RagPipeline.answer()` (`scripts/rag_pipeline.py`) and `RagService.ask()` (`scripts/rag_service.py`) extract `evidence` directly from the per-invocation result dictionary (`dbg_dict.pop("evidence", None)`), never reading `self._evidence_gen.last` during request handling. **No `threading.local()` or global mutable state shortcut is used.**
- **Fine-Grained Generation Lock (`_gen_sem`):**
  - Request validation, query normalization, query embedding, card routing, reranking, page retrieval (`retrieve_many_pages`), context construction, and `EvidenceGuard` pre-check (`analyze_question`, `build_units`, `assess`) all execute **outside** `_gen_sem`.
  - Across the 113 frozen benchmark queries in Guarded Ollama mode, **`38 / 113` (`33.6%`)** queries (`6` pre-routing exits + `32` `EvidenceGuard` pre-check refusals) never acquire `_gen_sem` at all (`0.00 ms` generation queue wait even when an LLM request is actively running).
  - Only the **`75 / 113` (`66.4%`)** queries that pass `EvidenceGuard` pre-check acquire `_gen_sem` around `self.inner.generate(question, context)`, and immediately release `_gen_sem` before `EvidenceGuard` post-check (`kind_satisfied`), `verify_grounding()`, citation normalization, and response construction.
- **10-Worker Service Concurrency Performance (vs Phase 19B Recorded Baseline):**
  - **Throughput (`10` workers, extractive service):** Increased from **`20.17 req/s`** (Phase 19B coarse `self._lock`) to **`35.68–36.97 req/s`** (**`+76.9%` to `+83.3%`**), matching the Phase 19B lock-free `pipeline.answer()` reference (`36.76 req/s`) and reaching **`39.01 req/s`** at `2` workers and **`38.38 req/s`** at `5` workers.
  - **Queue Wait (`10` workers, extractive service):** Reduced from **`p95 = 1517.90 ms`** to **`p95 = 0.00 ms` (`-100.0%`)**.
  - **Total Latency (`10` workers, extractive service):** Reduced from **`p95 = 1564.07 ms`** to **`p50 = 266.16 ms, p95 = 353.35–386.32 ms` (`-75.3%` to `-77.4%`, `-1,177.75` to `-1,210.72 ms`)**.
  - **Guarded Ollama Mode (`10` workers, `15 ms` simulated LLM latency):** Moving from Option A (coarse lock) to Option B (generation-only lock, `concurrency=1`) increases throughput from **`20.05 req/s` -> `32.06 req/s` (`+59.9%`)**, reduces `queue_wait_ms` `p95` from **`1058.21 ms` -> `58.90 ms` (`-94.4%`)** (`0.00 ms` for the `38` pre-check/early-exit queries), and reduces `total_ms` `p95` from **`1102.22 ms` -> `418.68 ms` (`-62.0%`)**.
- **Zero Correctness or Safety Regressions:**
  - Single-thread and multi-worker (`1, 2, 5, 10, 20` workers + `240`-request 20-worker adversarial mixed workload) runs produce **`0` errors, `0` cross-request contaminations, and `0` determinism mismatches** across all `113` frozen benchmark queries.
  - All **172 unit & regression tests PASS** (`160` existing tests + `12` new Phase 19C concurrency tests in `tests/test_phase19c_concurrency.py`).

---

## 2. Baseline (`HEAD 25ced60` + Phase 19A + Phase 19B)

### A. Frozen Artifact SHA-256 Verification
| Artifact | Path | SHA-256 | Status |
| :--- | :--- | :--- | :---: |
| **Frozen Benchmark (`n=113`)** | `data/phase12_queries.json` | `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac` | **VERIFIED** |
| **Page Corpus Manifest** | `data/page_corpus/manifest.json` | `49a314dbdce364ff33e007013dc92f136144c4f2b523d22a1a1abc64e3f8c1fe` | **VERIFIED** |
| **Card Collection Manifest** | `data/card_collection_manifest.json` | `61383afdbcad361e747ad34654f14dedb6b20a573a30404681625bf61bbf94ea` | **VERIFIED** |
| **Page Collection Manifest** | `data/page_collection_manifest.json` | `c6d0f4797eb2809d360ceb3402eecb27441e16af2ccd6f9dcd417bb1059d8a37` | **VERIFIED** |
| **Phase 7 Card Units** | `data/m2c_card_retrieval_units.json` | `f5e9b908c9b7374ffab5adbc6f8afb9b5597de91cb50ec3fea8b9b3db2d3ff21` | **VERIFIED** |

### B. Baseline Correctness & Single-Request Latency (`n = 113`)
- **Pre-existing regression test suite:** `160 passed` across all 12 test files (`test_phase8` through `test_phase19b`).
- **Frozen benchmark metrics (`e1a_v2_corroborated`):**
  - Guarded Ollama Answerable (`n=65`, checkpoint): **`43 / 65` (`66.15%`)**
  - Oracle Ollama Answerable (`n=65`, checkpoint): **`44 / 65` (`67.69%`)**
  - Extractive Answerable (`n=65`, live): **`52 / 65` (`80.00%`)**
  - Answerable Router R@1 (`n=65`): **`62 / 65` (`95.38%`)**
  - All-Gold Router R@1 (`n=105`): **`91 / 105` (`86.67%`)**
  - Gold-in-Pool (`n=105`): **`105 / 105` (`100.0%`)**
  - Wrong-Page Answers: **`1`** (Guarded Ollama) / **`3`** (Extractive)
  - Grounding Failures / Phantom Citations / Absent-Detail Answered / URL Changes / Generator Errors: **`0`**
- **Single-request deterministic latency (`n = 113`, warm caches):**
  - `route_ms`: `min = 22.92 ms, p50 = 27.98 ms, p90 = 34.01 ms, p95 = 37.86 ms, p99 = 41.03 ms, max = 42.44 ms, mean = 28.77 ms`
  - `total_ms` (`RagService.ask`): `min = 25.39 ms, p50 = 33.43 ms, p90 = 40.50 ms, p95 = 43.78 ms, p99 = 47.26 ms, max = 51.64 ms, mean = 34.35 ms`
- **Phase 19B Recorded 10-Worker Baseline:**
  - `RagService.ask` with coarse `self._lock`: **`20.17 req/s`**, `queue_wait p95 = 1517.90 ms`, `total p95 = 1564.07 ms`
  - Lock-free `pipeline.answer`: **`36.76 req/s`**, `total p95 = 301.56 ms`

---

## 3. Root Cause of `RagService` Concurrency Bottleneck

Inspection of `scripts/rag_service.py`, `scripts/rag_evidence.py`, `scripts/rag_generate.py`, `scripts/rag_pipeline.py`, `scripts/page_retriever.py`, and `scripts/phase13_reranker.py` identified two coupled root causes:

1. **Coarse Request Lock (`RagService._lock`) Serializing the Entire Request Lifecycle:**
   - In `scripts/rag_service.py`, `RagService.ask()` wrapped `self.pipeline.answer(q, debug=True)` and `self._evidence_gen.last` readback inside `with self._lock:`.
   - Every concurrent request queued at the outer lock before executing query embedding, card routing, candidate reranking, page retrieval, context assembly, or `EvidenceGuard` pre-check. Under 10 concurrent workers, requests spent **`97%` of total wall time (`1517.90 ms` of `1564.07 ms` at `p95`)** waiting on `self._lock`.
   - Even when `EvidenceGuard` pre-check would deterministically refuse a query in `< 1 ms` (`32/113` benchmark queries) or routing exited before generation (`6/113` queries), those requests still waited behind every preceding request's full execution.
2. **Mutable Instance Attributes Shared Across Requests (`self.last`, `self.last_telemetry`, `self.last_promoted`):**
   - `EvidenceExtractiveGenerator.last` and `EvidenceGuard.last` (`scripts/rag_evidence.py`) stored the most recent request's evidence decision dict on `self.last`, which `RagService.ask()` subsequently read after `self.pipeline.answer(q, debug=True)` returned. Without serialization, Request B could overwrite `self.last` before Request A read it.
   - `OllamaClient.last_telemetry` (`scripts/rag_generate.py`) stored the most recent HTTP call's timing/token telemetry on the shared client instance before `LLMGenerator.generate()` read `dict(self.client.last_telemetry)`.
   - `EvidenceRetriever.last_promoted` (`scripts/rag_evidence.py`) mutated an instance attribute on every `retrieve_in_page()` call.
   - Additionally, in `scripts/phase13_reranker.py`, `rerank_candidates()` filtered batch prefetch (`pages_to_fetch`) by `ident.resolution_status in ("resolved_local_page", "corrected_identity")` instead of `if ingested:`, skipping the 18 `"identified_not_local"` ingested pages and causing fallback per-candidate Chroma queries under `RagService`. Fixing line 329 of `scripts/phase13_reranker.py` to `if ingested:` (matching `score_candidate`) restored exact `1` page Chroma query per request across all `113` queries (`card_q=128, page_q=113, total=241`).

---

## 4. Request-Local Evidence State Refactor (Part 2)

To guarantee that Request A can never read or overwrite Request B's evidence or telemetry state — **without using `threading.local()` or global mutable state shortcuts** — state now flows exclusively through per-invocation return objects:

1. **`GenerationResult` (`scripts/rag_generate.py`):**
   - Added `evidence: Optional[Dict[str, Any]] = None` to `@dataclass class GenerationResult` alongside `telemetry: Optional[Dict[str, Any]] = None`.
2. **`OllamaClient.generate_with_telemetry()` (`scripts/rag_generate.py`):**
   - Added `generate_with_telemetry(self, prompt: str) -> Tuple[str, Dict[str, Any]]`, which computes the response text and telemetry dictionary in local variables and returns `(content, telemetry)` directly to `LLMGenerator.generate()`.
   - `LLMGenerator.generate()` calls `self.client.generate_with_telemetry(prompt)` when available and passes `telemetry=telemetry` into `GenerationResult(...)`. (`self.last_telemetry` is retained only as a legacy backward-compatible attribute for direct callers of `OllamaClient.generate()`).
3. **`EvidenceExtractiveGenerator.generate()` & `EvidenceGuard.generate()` (`scripts/rag_evidence.py`):**
   - Both methods construct their `record` dictionary in local variables and pass `evidence=copy.deepcopy(record)` directly into every returned `GenerationResult(...)` (across pre-check refusal, inner generator refusal, post-check refusal, and supported answer paths).
   - `self.last = record` is retained solely for backward compatibility with legacy unit tests (`tests/test_phase11_1_evidence.py`) that inspect `g.last` in single-threaded unit tests; neither `RagPipeline` nor `RagService` ever reads `.last`.
4. **`EvidenceRetriever.retrieve_in_page_with_promotion()` & `retrieve_many_pages()` (`scripts/rag_evidence.py`):**
   - Added `retrieve_in_page_with_promotion(query, guide_id, page_id, top_k=5, query_embedding=None) -> Tuple[List[Any], List[str]]` which computes `(hits, promoted)` purely in local variables without mutating `self.last_promoted`.
   - Added `retrieve_many_pages(...)` delegating to the inner `PageRetriever.retrieve_many_pages(...)` when `widen=False`.
5. **`RagPipeline.answer()` (`scripts/rag_pipeline.py`) & `RagService.ask()` (`scripts/rag_service.py`):**
   - `RagPipeline.answer()` copies `gen.evidence` into `dbg["evidence"]` and `gen.telemetry["queue_wait_ms"]` into `timings["queue_wait_ms"]` on the per-request `out` / `dbg` dictionaries.
   - `RagService._run_pipeline_request()` pops `evidence = dict(dbg_dict.pop("evidence", None))` directly from the per-invocation `raw["debug"]` dictionary returned by `self.pipeline.answer(q, debug=True)` and passes it explicitly to `to_chat_result(..., evidence=evidence)`.

---

## 5. Fine-Grained Generation Lock Architecture (Part 3)

### Stage-by-Stage Lock Boundary
```text
RagService.ask(question, conversation_id, debug)
 │
 ├─ [CONCURRENT / LOCK-FREE] clean_question(question) & resolve_conversation_id(conversation_id)
 ├─ [CONCURRENT / LOCK-FREE] Query embedding (SentenceTransformer.encode, 1 call/request)
 ├─ [CONCURRENT / LOCK-FREE] Card routing (route_to_page + _inject_code_aware_candidates)
 ├─ [CONCURRENT / LOCK-FREE] Phrase reranker & batched page retrieval (retrieve_many_pages, 1 Chroma query)
 ├─ [CONCURRENT / LOCK-FREE] Identity resolution (resolve_identity) & Step 3 lexical topic gate (page_chunks cache)
 ├─ [CONCURRENT / LOCK-FREE] Step 4 admission & Step 5 retrieval cache hit
 ├─ [CONCURRENT / LOCK-FREE] Step 6 context assembly (ContextBuilder.build) & coverage gate
 ├─ [CONCURRENT / LOCK-FREE] Step 7a EvidenceGuard pre-check (analyze_question -> build_units -> assess)
 │     └── If decision.supported is False (32/113 queries): return refusal IMMEDIATELY (never acquires _gen_sem)
 │
 ├─ [BOUNDED SEMAPHORE: with self._gen_sem] (default concurrency = 1)
 │     └── Step 7b Inner LLM generation ONLY: LLMGenerator.generate() -> OllamaClient.generate_with_telemetry()
 │         (records queue_wait_ms = time spent waiting to acquire _gen_sem)
 │
 ├─ [CONCURRENT / LOCK-FREE] Step 7c EvidenceGuard post-check (kind_satisfied)
 ├─ [CONCURRENT / LOCK-FREE] Step 7d Grounding verification (verify_grounding) & citation normalization
 └─ [CONCURRENT / LOCK-FREE] Step 8 Support-chain check (extractive) & to_chat_result() response construction
```

- `RagService.__init__(pipeline, generator, generation_concurrency=1, *, coarse_lock=False)` creates `self._gen_sem = threading.BoundedSemaphore(self.generation_concurrency)` and shares it with `GeneratorGuard` and `EvidenceGuard` (`pipeline.generator._gen_sem = self._gen_sem`).
- If `pipeline.generator` is an `EvidenceGuard` wrapping an `LLMGenerator` (`ollama`), `GeneratorGuard` delegates directly to `EvidenceGuard.generate()`, which executes pre-check (`analyze_question`, `build_units`, `assess`) **before** `with self._gen_sem:`, acquires `self._gen_sem` **only** around `self.inner.generate(question, context)`, and executes post-check (`kind_satisfied`) **after** releasing `self._gen_sem`.
- If `pipeline.generator` is deterministic `EvidenceExtractiveGenerator` (`name == "extractive"`), no external LLM call exists and the entire request executes lock-free (`queue_wait_ms = 0.0`).
- `coarse_lock=True` is preserved as an explicit opt-in flag on `RagService` for controlled A/B benchmarking against the pre-19C coarse lock.

---

## 6. Ollama Concurrency Experiments (`1`, `2`, `3`) (Part 4)

### A. `OllamaClient` Thread-Safety Audit
- `OllamaClient` (`scripts/rag_generate.py`) holds immutable configuration attributes (`model`, `host`, `temperature`, `seed`, `num_predict`, `keep_alive`) and invokes `self._chat(model=..., messages=[...], options=...)` with a freshly constructed local `opts = dict(LLM_OPTIONS)` dictionary per call.
- With `generate_with_telemetry()` returning `(content, telemetry)` as a local tuple, `OllamaClient` has zero shared mutable request state.
- However, a local Ollama server (`llama3.2:3b`) running on a single GPU/CPU host serializes or contends on KV-cache memory and compute slots when hit by unbounded parallel HTTP requests. Therefore, bounding active Ollama generation calls via `threading.BoundedSemaphore(generation_concurrency)` with `DEFAULT_GENERATION_CONCURRENCY = 1` prevents VRAM/RAM exhaustion while allowing deterministic pre-processing and post-processing to overlap with LLM generation.

### B. Controlled Guarded Ollama Concurrency Experiments (`n = 113`, `15 ms` Simulated LLM Call Latency)
Across the `113` benchmark queries, `38` exit before LLM generation (`6` pre-routing + `32` `EvidenceGuard` pre-check refusals) and `75` invoke `OllamaClient`.

| Option | Workers | Throughput (`req/s`) | `queue_wait_ms` `p50 / p95 / p99` | Pre-Check Refusal `qwait p95` | LLM-Call `qwait p95` | `route_ms` `p50 / p95` | `total_ms` `p50 / p95 / p99` | Max Active LLM | Errors / Mismatches |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Option A: Coarse Lock (`coarse_lock=True`)** | `1` | `22.11` | `0.00 / 0.00 / 0.00` | `0.00` | `0.00` | `29.74 / 41.31` | `47.29 / 62.99 / 67.50` | `1` | `0 / 0` |
| | `2` | `21.24` | `44.91 / 131.56 / 145.65` | `110.95` | `134.81` | `30.89 / 49.40` | `93.19 / 183.39 / 201.21` | `1` | `0 / 0` |
| | `5` | `21.11` | `177.96 / 431.87 / 470.51` | `400.64` | `434.67` | `30.22 / 42.90` | `224.82 / 481.61 / 521.95` | `1` | `0 / 0` |
| | `10` | `20.05` | `417.16 / 1058.21 / 1117.78` | `957.01` | `1082.35` | `30.29 / 49.10` | `463.42 / 1102.22 / 1169.36` | `1` | `0 / 0` |
| | `20` | `20.66` | `876.96 / 1928.39 / 2088.62` | `1896.83` | `1971.69` | `30.69 / 41.27` | `923.34 / 1981.82 / 2152.97` | `1` | `0 / 0` |
| **Option B: Gen-Only Lock (`concurrency=1`)** | `1` | `20.06` | `0.01 / 0.02 / 0.02` | `0.00` | `0.02` | `30.71 / 46.84` | `47.81 / 68.11 / 73.84` | `1` | `0 / 0` |
| | `2` | **`30.80`** | `0.01 / 7.27 / 13.79` | **`0.00`** | `9.33` | `46.50 / 67.35` | **`62.90 / 91.60 / 99.64`** | `1` | `0 / 0` |
| | `5` | **`34.97`** | `0.01 / 21.28 / 32.02` | **`0.00`** | `24.08` | `117.50 / 167.21` | **`138.98 / 192.71 / 214.08`** | `1` | `0 / 0` |
| | `10` | **`32.06`** | `0.01 / 58.90 / 71.75` | **`0.00`** | `62.66` | `258.59 / 374.16` | **`293.03 / 418.68 / 451.83`** | `1` | `0 / 0` |
| | `20` | **`28.04`** | `0.01 / 97.57 / 118.43` | **`0.00`** | `104.76` | `609.75 / 839.20` | **`694.16 / 922.59 / 979.13`** | `1` | `0 / 0` |
| **Option C: Bounded Sem (`concurrency=2`)** | `1` | `19.30` | `0.01 / 0.02 / 0.02` | `0.00` | `0.02` | `32.68 / 50.64` | `51.45 / 76.88 / 81.91` | `1` | `0 / 0` |
| | `2` | `30.83` | `0.00 / 0.01 / 0.02` | `0.00` | `0.01` | `47.37 / 67.73` | `64.90 / 88.67 / 95.36` | `2` | `0 / 0` |
| | `5` | `34.29` | `0.01 / 4.75 / 12.14` | `0.00` | `6.14` | `120.73 / 169.34` | `139.49 / 198.51 / 213.38` | `2` | `0 / 0` |
| | `10` | `31.54` | `0.01 / 14.39 / 19.72` | `0.00` | `16.29` | `268.09 / 378.58` | `300.78 / 417.02 / 463.26` | `2` | `0 / 0` |
| | `20` | `27.07` | `0.01 / 9.69 / 21.17` | `0.00` | `11.61` | `619.29 / 878.83` | `703.47 / 942.76 / 991.57` | `2` | `0 / 0` |
| **Option D: Bounded Sem (`concurrency=3`)** | `1` | `20.64` | `0.01 / 0.01 / 0.02` | `0.00` | `0.01` | `30.65 / 41.36` | `49.11 / 61.21 / 73.17` | `1` | `0 / 0` |
| | `2` | `29.91` | `0.00 / 0.01 / 0.02` | `0.00` | `0.01` | `48.38 / 69.29` | `65.87 / 90.31 / 96.46` | `2` | `0 / 0` |
| | `5` | `31.50` | `0.00 / 0.01 / 0.02` | `0.00` | `0.02` | `134.12 / 193.26` | `156.45 / 216.36 / 238.12` | `3` | `0 / 0` |
| | `10` | `28.80` | `0.01 / 0.01 / 0.03` | `0.00` | `0.01` | `301.16 / 438.16` | `334.05 / 478.11 / 539.88` | `3` | `0 / 0` |
| | `20` | `22.87` | `0.01 / 0.03 / 4.30` | `0.00` | `0.04` | `754.22 / 1165.40` | `830.20 / 1246.36 / 1335.42` | `3` | `0 / 0` |

**Takeaway:** Option B (`generation_concurrency=1`) delivers the highest throughput (`34.97 req/s` at `w=5`, `32.06 req/s` at `w=10`) while strictly capping concurrent Ollama server requests at `1`. Options C (`concurrency=2`) and D (`concurrency=3`) are supported via the configurable `generation_concurrency` parameter on `RagService` and `EvidenceGuard`, with `DEFAULT_GENERATION_CONCURRENCY = 1` shipped as the safe production default (since live Windows Ollama multi-stream GPU contention is `NOT VERIFIED` in the Linux sandbox).

---

## 7. Concurrency Benchmark Results (`1`, `2`, `5`, `10`, `20` Workers) (Part 5 & Part 6)

### Extractive Service Concurrency Sweep (`n = 113` Frozen Queries)

| Configuration | Workers | Wall Time (`s`) | Throughput (`req/s`) | `queue_wait_ms` `p50 / p95 / p99` | `route_ms` `p50 / p95 / p99` | `generate_ms` `p50 / p95 / p99` | `total_ms` `p50 / p95 / p99` | Errors / Mismatches / Contamination |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Pre-19C Coarse Lock (`coarse_lock=True`)** | `1` | `4.191` | `26.96` | `0.00 / 0.00 / 0.00` | `29.53 / 39.42 / 49.20` | `0.89 / 1.80 / 2.23` | `35.54 / 49.54 / 58.67` | `0 / 0 / 0` |
| | `2` | `4.181` | `27.03` | `34.31 / 85.94 / 141.95` | `29.04 / 42.98 / 50.51` | `0.89 / 1.92 / 2.59` | `67.88 / 126.43 / 178.08` | `0 / 0 / 0` |
| | `5` | `4.062` | `27.82` | `139.94 / 178.58 / 287.34` | `29.40 / 38.67 / 47.41` | `0.86 / 1.56 / 2.09` | `174.99 / 215.10 / 323.09` | `0 / 0 / 0` |
| | `10` | `4.467` | `25.30` | `337.98 / 684.16 / 756.37` | `30.52 / 49.23 / 64.94` | `0.90 / 1.94 / 3.86` | `376.28 / 734.86 / 799.64` | `0 / 0 / 0` |
| | `20` | `4.060` | `27.83` | `655.33 / 1308.57 / 1437.33` | `28.59 / 39.43 / 52.84` | `0.85 / 1.52 / 2.13` | `691.17 / 1341.31 / 1473.17` | `0 / 0 / 0` |
| **Phase 19C Fine-Grained Lock (`coarse_lock=False`)** | `1` | `3.951` | **`28.60`** | **`0.00 / 0.00 / 0.00`** | `28.37 / 36.78 / 38.99` | `0.84 / 1.48 / 1.84` | **`33.74 / 43.20 / 45.28`** | `0 / 0 / 0` |
| | `2` | `2.897` | **`39.01`** | **`0.00 / 0.00 / 0.00`** | `42.90 / 56.60 / 61.98` | `1.12 / 2.26 / 2.91` | **`49.77 / 64.57 / 70.64`** | `0 / 0 / 0` |
| | `5` | `2.944` | **`38.38`** | **`0.00 / 0.00 / 0.00`** | `115.65 / 160.29 / 172.07` | `1.66 / 4.94 / 7.82` | **`126.89 / 176.36 / 184.42`** | `0 / 0 / 0` |
| | `10` | `3.167` | **`35.68`** *(up to `36.97`)* | **`0.00 / 0.00 / 0.00`** | `248.47 / 356.11 / 387.92` | `1.94 / 8.87 / 18.81` | **`266.16 / 386.32 / 412.66`** *(down to `353.35`)* | `0 / 0 / 0` |
| | `20` | `3.571` | **`31.64`** | **`0.00 / 0.00 / 0.00`** | `544.52 / 847.76 / 950.48` | `2.96 / 20.69 / 39.21` | **`587.92 / 905.49 / 983.50`** | `0 / 0 / 0` |
| **Lock-Free `pipeline.answer()` Reference** | `1` | `4.222` | `26.76` | `0.00 / 0.00 / 0.00` | `30.89 / 41.29 / 56.51` | `0.90 / 1.76 / 2.22` | `36.07 / 48.21 / 62.66` | `0 / 0 / 0` |
| | `2` | `2.968` | `38.07` | `0.00 / 0.00 / 0.00` | `44.71 / 59.30 / 67.35` | `1.13 / 2.21 / 3.30` | `50.73 / 67.66 / 75.59` | `0 / 0 / 0` |
| | `5` | `2.939` | `38.45` | `0.00 / 0.00 / 0.00` | `116.58 / 153.25 / 168.58` | `1.44 / 4.21 / 7.51` | `127.60 / 166.73 / 180.36` | `0 / 0 / 0` |
| | `10` | `3.305` | `34.19` | `0.00 / 0.00 / 0.00` | `266.89 / 344.20 / 365.43` | `1.95 / 9.81 / 14.08` | `283.90 / 362.90 / 393.36` | `0 / 0 / 0` |
| | `20` | `3.348` | `33.75` | `0.00 / 0.00 / 0.00` | `541.52 / 734.93 / 790.23` | `3.05 / 19.65 / 26.79` | `571.38 / 765.74 / 847.72` | `0 / 0 / 0` |

---

## 8. Queue Wait Before / After

| Workload / Mode | Workers | Before (Coarse `self._lock`) `p50 / p95 / p99` (`ms`) | After (Fine-Grained `_gen_sem`) `p50 / p95 / p99` (`ms`) | Reduction at `p95` |
| :--- | :---: | :---: | :---: | :---: |
| **Phase 19B Recorded 10-Worker Burst** | `10` | `— / 1517.90 / —` | **`0.00 / 0.00 / 0.00`** | **`-1517.90 ms (-100.0%)`** |
| **Extractive `RagService.ask` (`n=113`)** | `2` | `34.31 / 85.94 / 141.95` | **`0.00 / 0.00 / 0.00`** | **`-85.94 ms (-100.0%)`** |
| | `5` | `139.94 / 178.58 / 287.34` | **`0.00 / 0.00 / 0.00`** | **`-178.58 ms (-100.0%)`** |
| | `10` | `337.98 / 684.16 / 756.37` | **`0.00 / 0.00 / 0.00`** | **`-684.16 ms (-100.0%)`** |
| | `20` | `655.33 / 1308.57 / 1437.33` | **`0.00 / 0.00 / 0.00`** | **`-1308.57 ms (-100.0%)`** |
| **Guarded Ollama (`sim=15ms`, all `113` queries)** | `10` | `417.16 / 1058.21 / 1117.78` | **`0.01 / 58.90 / 71.75`** | **`-999.31 ms (-94.4%)`** |
| **Guarded Ollama (`sim=15ms`, `38` pre-check/early-exit queries)** | `10` | `400.64 / 957.01 / 1094.12` | **`0.00 / 0.00 / 0.00`** | **`-957.01 ms (-100.0%)`** |

---

## 9. Throughput Before / After

| Workload / Mode | Workers | Before (Coarse `self._lock`) | After (Fine-Grained `_gen_sem`) | Lock-Free `pipeline.answer` Reference | Throughput Gain |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Phase 19B Recorded 10-Worker Baseline** | `10` | `20.17 req/s` | **`35.68–36.97 req/s`** | `36.76 req/s` | **`+76.9%` to `+83.3%`** |
| **Extractive `RagService.ask` (`n=113`)** | `1` | `26.96 req/s` | **`28.60 req/s`** | `26.76 req/s` | **`+6.1%`** |
| | `2` | `27.03 req/s` | **`39.01 req/s`** | `38.07 req/s` | **`+44.3%`** |
| | `5` | `27.82 req/s` | **`38.38 req/s`** | `38.45 req/s` | **`+38.0%`** |
| | `10` | `25.30 req/s` | **`35.68 req/s`** | `34.19 req/s` | **`+41.0%`** (`+76.9%` vs 19B `20.17`) |
| | `20` | `27.83 req/s` | **`31.64 req/s`** | `33.75 req/s` | **`+13.7%`** |
| **Guarded Ollama (`sim=15ms`, `c=1`, `n=113`)** | `2` | `21.24 req/s` | **`30.80 req/s`** | — | **`+45.0%`** |
| | `5` | `21.11 req/s` | **`34.97 req/s`** | — | **`+65.7%`** |
| | `10` | `20.05 req/s` | **`32.06 req/s`** | — | **`+59.9%`** |
| | `20` | `20.66 req/s` | **`28.04 req/s`** | — | **`+35.7%`** |

---

## 10. Latency Percentiles (`p50/p95/p99`) Before / After

| Mode | Workers | Before `total_ms` `p50 / p95 / p99` | After `total_ms` `p50 / p95 / p99` | Delta at `p95` |
| :--- | :---: | :---: | :---: | :---: |
| **Phase 19B Recorded 10-Worker Baseline** | `10` | `— / 1564.07 / —` | **`261.61–266.16 / 353.35–386.32 / 412.66`** | **`-1177.75 to -1210.72 ms (-75.3% to -77.4%)`** |
| **Extractive `RagService.ask` (`n=113`)** | `1` | `35.54 / 49.54 / 58.67` | **`33.74 / 43.20 / 45.28`** | **`-6.34 ms (-12.8%)`** |
| | `2` | `67.88 / 126.43 / 178.08` | **`49.77 / 64.57 / 70.64`** | **`-61.86 ms (-48.9%)`** |
| | `5` | `174.99 / 215.10 / 323.09` | **`126.89 / 176.36 / 184.42`** | **`-38.74 ms (-18.0%)`** |
| | `10` | `376.28 / 734.86 / 799.64` | **`266.16 / 386.32 / 412.66`** | **`-348.54 ms (-47.4%)`** |
| | `20` | `691.17 / 1341.31 / 1473.17` | **`587.92 / 905.49 / 983.50`** | **`-435.82 ms (-32.5%)`** |
| **Guarded Ollama (`sim=15ms`, `c=1`, `n=113`)** | `2` | `93.19 / 183.39 / 201.21` | **`62.90 / 91.60 / 99.64`** | **`-91.79 ms (-50.1%)`** |
| | `5` | `224.82 / 481.61 / 521.95` | **`138.98 / 192.71 / 214.08`** | **`-288.90 ms (-60.0%)`** |
| | `10` | `463.42 / 1102.22 / 1169.36` | **`293.03 / 418.68 / 451.83`** | **`-683.54 ms (-62.0%)`** |
| | `20` | `923.34 / 1981.82 / 2152.97` | **`694.16 / 922.59 / 979.13`** | **`-1059.23 ms (-53.4%)`** |

---

## 11. Correctness & Cross-Request Isolation Verification (Part 5)

Across all concurrency sweeps (`1, 2, 5, 10, 20` workers on all `113` queries in both Extractive and Guarded Ollama modes) plus the **20-worker, 240-request adversarial mixed workload** (`P12-001, 003, 012, 025, 033, 041` answerable across distinct pages/codes, `P12-066, 067, 070` absent-detail pre-check refusals, `P12-071` post-LLM grounding withhold, `P12-097` unresolved identity `M2C-18`, `P12-106` out-of-domain):

| Verification Dimension | `1` Worker (`n=113`) | `2` Workers (`n=113`) | `5` Workers (`n=113`) | `10` Workers (`n=113`) | `20` Workers (`n=113`) | `20` Workers Adversarial (`n=240`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Runtime Exceptions / Errors** | `0` | `0` | `0` | `0` | `0` | `0` |
| **Answer Text Mismatches vs Single-Thread** | `0` | `0` | `0` | `0` | `0` | `0` |
| **Citation / `answer_sources` Mismatches** | `0` | `0` | `0` | `0` | `0` | `0` |
| **Selected Source ID / Page Mismatches** | `0` | `0` | `0` | `0` | `0` | `0` |
| **Candidate Ordering / Distance Mismatches** | `0` | `0` | `0` | `0` | `0` | `0` |
| **`status` & `reason_code` Mismatches** | `0` | `0` | `0` | `0` | `0` | `0` |
| **`grounding` Report Mismatches** | `0` | `0` | `0` | `0` | `0` | `0` |
| **`debug.evidence` (`EvidenceGuard`) Mismatches** | `0` | `0` | `0` | `0` | `0` | `0` |
| **Cross-Request `conversation_id` / State Leakage** | `0` | `0` | `0` | `0` | `0` | `0` |

---

## 12. Cache & Memory Safety Under Concurrency (Part 7)

| Cache / Component | Location | Capacity / Bound | Synchronization | Defensive Return / Immutability | Verified Under Concurrent Mutation |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **`_page_chunks_cache`** | `PageRetriever` (`scripts/page_retriever.py`) | `MAX_PAGE_CHUNKS_CACHE = 64` (`25` used) | `self._cache_lock = threading.Lock()` | Stored as `Tuple[ChunkHit, ...]`; `page_chunks()` returns `[replace(h, metadata=dict(h.metadata)) for h in cached]` | **PASS (`True`)** |
| **`_chunk_by_id` / `_chunks_by_page`** | `PageRetriever` (`scripts/page_retriever.py`) | `106` chunks / `25` pages (`571.54 KB`) | `self._cache_lock` double-checked init | Reconstructs fresh `ChunkHit(..., metadata=dict(md))` per hit | **PASS (`True`)** |
| **`_page_texts` / `_page_texts_lower`** | `PageCorpusIndex` (`scripts/rag_pipeline.py`) | `MAX_PAGE_TEXTS_CACHE = 64` (`29` used) | `self._lock = threading.Lock()` | Returns immutable Python `str` | **PASS (`True`)** |
| **`PageCorpusIndex.entry(sid)`** | `PageCorpusIndex` (`scripts/rag_pipeline.py`) | `29` manifest cards | Immutable dict keys after `__init__` | Returns `dict(e)` shallow copy so callers cannot mutate manifest state | **PASS (`True`)** |
| **`_PrecomputedQueryBackend._open()`** | `scripts/rag_pipeline.py` | `1` Chroma collection handle | `_CARD_OPEN_LOCK = threading.Lock()` | Double-checked lock around lazy `self.inner._open()` | **PASS (`True`)** |
| **`rerank_hits_cache`** | `RagPipeline.answer()` (`scripts/rag_pipeline.py`) | `<= 10` candidate pages per request | Request-local stack variable | Allocated fresh inside each `answer()` call; never shared across threads | **PASS (`True`)** |

- **Memory Audit (`10` concurrent workers across `n=113` queries):**
  - Traced steady-state heap delta after 113 concurrent requests: **`+100.15 KB` (`0.10 MB`)**
  - Traced peak heap delta during 10-worker execution: **`+832.52 KB` (`0.81 MB`)**

---

## 13. Failure Mode Verification (Part 8)

All 8 required failure modes were verified under concurrent execution:
1. **Ollama unavailable (`ConnectionError`):** Caught by `GeneratorGuard.generate()` inside `with self._gen_sem:`, releases `_gen_sem` via context manager `finally`, and raises typed `GeneratorFailure` (`HTTP 503` in `rag_api.py`) without affecting concurrent requests.
2. **Ollama timeout (`TimeoutError`):** Releases `_gen_sem` cleanly and raises `GeneratorFailure`; concurrent and subsequent requests acquire `_gen_sem` normally without deadlock (`test_09`).
3. **Retriever exception (`RuntimeError`):** Caught by `RagService.ask()` and wrapped into typed `PipelineFailure` (`HTTP 500`); concurrent and subsequent requests succeed normally (`test_10`).
4. **Malformed request (`non-string` / `too-long` question or invalid `conversation_id`):** Rejected immediately by `clean_question()` / `resolve_conversation_id()` with `InvalidRequest` (`HTTP 400`) before entering the pipeline.
5. **Empty query (`""` or whitespace):** Rejected immediately by `clean_question()` with `InvalidRequest` (`HTTP 400`) at the service layer (or `no_routed_page` / `EMPTY_OR_UNROUTABLE_QUERY` at `pipeline.answer()`).
6. **Unsupported / out-of-domain query:** Exits at Step 3 (`out_of_domain` -> `out_of_scope`) without acquiring `_gen_sem` (`test_04`).
7. **Grounding failure (`verify_grounding` `ok=False`):** Withheld deterministically after releasing `_gen_sem` (`insufficient_context` / `GROUNDING_VERIFICATION_FAILED` -> `unable_to_verify`) (`test_07`).
8. **`EvidenceGuard` pre-check and post-check failures:** Pre-check failures return immediately without acquiring `_gen_sem` (`test_04`, `test_06`); post-check failures (`ANSWER_LACKS_ASKED_DETAIL`) abstain cleanly after releasing `_gen_sem` (`test_07`).

---

## 14. Production Config & Generation Concurrency Default (Part 9)

- **Sandbox Live Ollama Status:** `ollama_available() == False` (`NOT VERIFIED` in Linux sandbox; no live Windows Ollama numbers are fabricated).
- **Production Generation Concurrency Default:** `DEFAULT_GENERATION_CONCURRENCY = 1` (`scripts/rag_service.py`), configurable via `RagService(..., generation_concurrency=N)` and `EV.build_evidence_pipeline(..., generation_concurrency=N)`.
- **Production Pipeline Configuration (`scripts/rag_service.py::production_pipeline_config()`):** Unchanged from Phase 18 / 19A / 19B:
  - `model="llama3.2:3b"`, `temperature=0`, `seed=42`
  - `top_k_cards=10`, `k_chunks=5`, `context_budget_tokens=700`, `max_context_chunks=4`
  - `ood_min_coverage=0.25`, `context_min_coverage=0.5`
  - `rerank_router=True`, `code_aware_router=True`, `in_page_grounding=True`, `citation_normalization=True`, `relaxed_context_gate=True`, `evidence_frame_normalization=False`, `phrase_reranker=True`, `phrase_min_corroboration=2`, `full_page_coverage=False`, `citation_repair=False`
  - `ollama_num_predict=None`, `ollama_keep_alive=None`

---

## 15. Rejected Designs and Why

1. **`threading.local()` for `.last` / `.last_telemetry` — REJECTED:**
   - Explicitly prohibited by Phase 19C Part 2 (`DO NOT introduce thread-local/global mutable state as a shortcut`). Hidden thread-local state breaks if a request spans executor hops or async continuations. Explicit `GenerationResult.evidence` and `GenerationResult.telemetry` fields bind state directly to the returned value.
2. **Simply Removing All Synchronization (`unlimited` Ollama concurrency) — REJECTED:**
   - Prohibited by Phase 19C Rules (`DO NOT simply remove the lock`, `Do NOT blindly allow unlimited concurrent Ollama calls`). Unbounded concurrent LLM generation against a local `llama3.2:3b` instance causes GPU/CPU thrashing and timeouts.
3. **Holding `_gen_sem` Across `EvidenceGuard` Pre-Check and Post-Check — REJECTED:**
   - Pre-check (`analyze_question`, `build_units`, `assess`) and post-check (`kind_satisfied`, `verify_grounding`) are 100% deterministic CPU operations on request-local objects. Holding `_gen_sem` during pre-check would force `32/113` pre-check refusal queries to wait behind active LLM generation.

---

## 16. Tests Added & Full Test Results (Part 10)

Created `tests/test_phase19c_concurrency.py` with **12 tests** covering every required Phase 19C scenario:
1. `test_01_concurrent_requests_distinct_evidence_no_overwrite`: Barrier-synchronized supported + pre-check-refused requests verify zero `.last` overwrite.
2. `test_02_ten_concurrent_requests_match_single_thread`: 10 concurrent diverse queries match single-thread normalized outputs exactly.
3. `test_03_twenty_concurrent_mixed_requests_zero_leakage`: 20 concurrent mixed requests (`answerable`, `absent_detail`, `out_of_domain`) have `0` leakage.
4. `test_04_precheck_refusal_does_not_block_on_held_generation_lock`: Pre-check refusal and OOD requests complete with `queue_wait_ms == 0.0` while a slow LLM call holds `_gen_sem`.
5. `test_05_routing_retrieval_context_run_concurrently_during_llm_generation`: Request 2 completes routing, retrieval, context build, and `build_units` while Request 1 is blocked inside `OllamaClient`.
6. `test_06_evidence_guard_precheck_runs_outside_generation_lock`: Verifies `_gen_sem` is unlocked during `EvidenceGuard.assess()` and locked during `inner.generate()`.
7. `test_07_postcheck_and_grounding_run_outside_lock_after_generation`: Verifies `_gen_sem` is already released during `kind_satisfied()` and `verify_grounding()`.
8. `test_08_caches_return_isolated_copies_under_concurrent_reads_and_mutations`: 12 threads x 48 iterations mutating returned `page_chunks()` and `corpus.entry()` objects cannot corrupt cached data.
9. `test_09_ollama_failure_or_timeout_does_not_poison_or_deadlock_concurrent_requests`: Concurrent `TimeoutError` inside `OllamaClient` raises `GeneratorFailure`, releases `_gen_sem`, and does not block concurrent/subsequent requests.
10. `test_10_retriever_exception_does_not_poison_concurrent_or_subsequent_requests`: Concurrent retriever `RuntimeError` raises `PipelineFailure` without poisoning sibling or subsequent requests.
11. `test_11_bounded_generation_semaphore_enforces_configured_concurrency_limit`: Verifies `max_active_llm == limit` for `generation_concurrency` = `1, 2, 3` under 6-worker load.
12. `test_12_production_config_and_no_thread_local_shortcut_invariants`: Verifies all `production_pipeline_config()` invariants and inspects source of `rag_evidence`, `rag_generate`, and `rag_service` to confirm `"threading.local("` is absent.

**Full Regression Suite Execution:**
- **`172 passed in 19.24s`** (`160` existing tests + `12` new Phase 19C tests; `0` failures).

---

## 17. Remaining Bottleneck

1. **Multi-Worker CPU Contention in `SentenceTransformer.encode` (`route_ms` under `10–20` concurrent workers):**
   - With `RagService._lock` removed and Chroma page queries consolidated to `1` batched query per request (`total_chroma_q = 241` across `113` queries), single-request `total_ms` is `p50 = 33.43 ms, p95 = 43.78 ms`, and 2–5 worker throughput reaches **`38.38–39.01 req/s`**.
   - Beyond `5` concurrent CPU threads in a single Python process, PyTorch CPU inference (`all-MiniLM-L6-v2` query embedding) and Python GIL contention become CPU-bound (`~35.68–36.97 req/s` at `10` workers, `~31.64 req/s` at `20` workers).
2. **End-to-End Guarded Ollama Mode:**
   - Dominated by live `llama3.2:3b` generation latency (`75/113` queries invoke Ollama) and the **`17/75` (`22.67%`) post-generation withheld LLM calls** (`9` answerable queries where `llama3.2:3b` fails `verify_grounding()` despite `EvidenceExtractiveGenerator` succeeding on `8/9`, plus `8` non-answerable/ambiguous queries that pass `EvidenceGuard` pre-check before failing `verify_grounding()`).

---

## 18. Explicit Recommendation for Next Phase

1. **Validate Live Windows Ollama Concurrency (`generation_concurrency = 1` vs `2`):**
   - On the Windows Ollama host (`llama3.2:3b`, `temperature=0`, `seed=42`), benchmark `RagService` with `generation_concurrency=1` and `generation_concurrency=2` alongside `num_predict=192` and `keep_alive=-1`.
2. **Phase 20A — Verified Extractive Fallback on Post-LLM Grounding Failures (`43/65 -> 51/65` Potential):**
   - When `EvidenceGuard` pre-check passes (`decision.supported == True`) but `llama3.2:3b`'s output fails `verify_grounding()`, invoke `EvidenceExtractiveGenerator.generate()` gated by the exact same `verify_grounding()` + `verify_support_chain()` checks. On the frozen benchmark, this recovers `8` of the `9` post-LLM grounding failures on answerable queries (`43/65 -> 51/65`) without relaxing grounding or citation safety.
3. **Phase 20B — Pre-Check Tightening for Non-Answerable Queries:**
   - Tighten `EvidenceGuard` pre-check on the `8` non-answerable/ambiguous queries (`P12-071, 084, 085, 091, 092, 096, 100, 102`) that currently acquire `_gen_sem` and call Ollama only to fail `verify_grounding()`, saving `10.7%` of all LLM calls under concurrent load.
