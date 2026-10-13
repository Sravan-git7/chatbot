# SURA latency and RAG quality comparison

Date: 2026-10-13 · Baseline runtime: `6eb9d9d` · Final measured runtime: `05ef5e7c99aca8a03ee05b61ba16128093c2e1b9`.
No public deployment. New actual runs, not historical measurements repackaged as new. Later report/artifact commits do not change this runtime.

## Method and environment

Workload v2: 13 fixed cases, source/status assertions, seven categories. SHA-256 `d54ecbf2e223e7efad16b0b54aef47d2172c2a741228d75f75f448c791660d22`. Baseline uses an immutable Git archive; final measurements run committed code. Same stores/weights/configuration: 29 cards, 28 pages, 113 page vectors, corpus `46e7c63a…`, MiniLM CPU, deterministic extractive, top-k card candidates 10 and page retrieval cap 5. The corpus and gold labels are not rewritten.
Linux x86-64; Intel Xeon @2.60 GHz, two logical/affinity CPUs, ~3.85 GiB RAM; Python 3.11.2, Node 22.22.3. Chroma 1.5.9, sentence-transformers 6.1.0, Torch 2.14.1, NumPy 2.4.6. This is not Windows/local-user hardware.
10 warmups for stages and 5 for HTTP excluded; 100 measured final-turn requests per item (1300 aggregate). Concurrency: 200 offered mixed single-turn requests at each level. Cold first requests and service construction are separate. Nearest-rank percentiles, mean/stddev and n stored per item. Shared VM variability and finite samples preclude a causal speedup claim; per-item p99 and small saturation samples are exploratory.
No answer cache, evidence reduction, source remapping or concurrency-based request dropping was added to improve a score. 429s are explicitly counted, never counted as completed RAG work.

## Extractive warm latency — aggregate

| Mode | Baseline p50 / p95 / p99 ms | Final p50 / p95 / p99 ms | n each |
| --- | --- | --- | --- |
| Full in-process ask | 40.61 / 64.78 / 78.78 | 34.82 / 53.83 / 62.59 | 1300 |
| HTTP end-to-end | 45.01 / 68.65 / 82.23 | 37.59 / 54.57 / 65.51 | 1300 |

HTTP mean/stddev: baseline 45.84/16.24 ms; final 38.30/13.02 ms.
All sequential final responses match status/card assertions; zero HTTP errors/timeouts. The expected abstention mix is 400/1300 (four cases), not counted as failures.

### HTTP per-item distributions (100 measured requests each)

| Workload item | Baseline p50 / p95 / p99 ms | Final p50 / p95 / p99 ms |
| --- | --- | --- |
| simple-01-billing | 40.93 / 59.40 / 63.50 | 35.43 / 46.12 / 52.18 |
| simple-02-movein | 56.89 / 79.70 / 98.49 | 48.93 / 58.28 / 68.96 |
| simple-03-dunning | 44.81 / 55.80 / 75.16 | 37.95 / 44.74 / 50.58 |
| complex-01-cash-desk | 47.56 / 67.94 / 83.59 | 39.38 / 42.58 / 44.48 |
| complex-02-installment-lifecycle | 42.33 / 51.30 / 58.11 | 36.71 / 41.63 / 45.88 |
| followup-01-billing-elaborate | 64.76 / 80.89 / 97.09 | 53.81 / 58.60 / 67.70 |
| followup-02-topic-switch | 43.40 / 61.76 / 71.61 | 35.88 / 39.08 / 47.54 |
| scope-01-weather | 35.08 / 41.07 / 50.19 | 29.99 / 32.51 / 34.32 |
| evidence-01-el31-price | 56.11 / 72.08 / 82.10 | 48.49 / 67.91 / 75.76 |
| evidence-02-validation-transfer | 42.38 / 54.32 / 58.92 | 35.21 / 40.21 / 44.86 |
| identity-01-m2c18 | 3.63 / 4.37 / 4.62 | 2.13 / 2.67 / 2.94 |
| length-01-installment | 55.21 / 71.73 / 78.39 | 46.95 / 54.46 / 66.55 |
| length-02-collection-agency | 37.79 / 44.53 / 48.18 | 35.17 / 39.28 / 44.15 |

## Stage breakdown (final warm measurements)

Parent routing contains embed/card-query/rerank: do not double-count. Generator wrappers include some evidence work inside generation; citation assembly/response serialization are in total/wall windows, not separately claimed as pure isolated costs. Request validation excludes ASGI/Pydantic overhead. Baseline unmodified code lacks the new sub-stage timers; native route/context/generate/total windows remain measured.

| Stage | p50 / p95 / p99 ms | Mean / stddev ms | Executed samples |
| --- | --- | --- | --- |
| validation_ms | 0.01 / 0.01 / 0.03 | 0.01 / 0.0 | 1300 |
| support_chain_ms | 0.14 / 0.27 / 0.35 | 0.15 / 0.07 | 900 |
| route_ms | 27.10 / 38.52 / 48.30 | 26.64 / 9.1 | 1300 |
| embed_ms | 16.27 / 20.73 / 24.90 | 16.49 / 2.34 | 1200 |
| card_query_ms | 4.91 / 12.63 / 16.72 | 6.23 / 3.08 | 1200 |
| rerank_ms | 5.86 / 7.85 / 9.55 | 6.07 / 0.96 | 1200 |
| retrieve_ms | 0.00 / 19.11 / 20.93 | 1.79 / 5.68 | 1100 |
| context_ms | 3.94 / 8.24 / 10.69 | 3.71 / 2.52 | 1100 |
| generate_ms | 2.06 / 4.28 / 5.63 | 2.32 / 1.04 | 1100 |
| verify_ms | 0.35 / 0.73 / 0.89 | 0.35 / 0.23 | 1100 |
| queue_wait_ms | 0.00 / 0.00 / 0.00 | 0.00 / 0.0 | 1300 |
| total_ms | 34.29 / 52.93 / 61.83 | 35.12 / 13.06 | 1300 |

Missing stages on early abstention paths are absent, not fabricated zeros. Winning-page retrieval often reuses request-local reranking results; elaboration can retrieve anew. Per-item page characters/context chunk counts are retained in stage JSON, so the workload includes genuinely different admitted document/evidence lengths.

## Cold start and memory

Service construction (includes local model/store loading): baseline 6.881 s; final 5.404 s. First in-process ask: 85.77 → 61.30 ms. First HTTP chat: 105.82 → 79.88 ms.
Peak process RSS: baseline stages 926.9 MiB; final stages 925.8 MiB; final API server 956.3 MiB. Resource counters are Linux-specific; CPU utilization and a separate server-spawn-to-readiness timer were not collected, so no such numbers are asserted.

## Concurrency — production admission cap 4

The per-IP limiter is lifted only in the private benchmark process. Default admission cap remains four. Above it, 429 is expected saturation; accepted/rejection distributions and all-response distributions are separately retained. Completed RPS counts only HTTP 200 RAG responses. Correctness is checked on every accepted response.

| Concurrent clients | Baseline accepted / 429 | Final accepted / 429 | Baseline completed RPS | Final completed RPS | Final accepted p50 / p95 / p99 ms |
| --- | --- | --- | --- | --- | --- |
| 1 | 200 / 0 | 200 / 0 | 23.70 | 27.15 | 37.29 / 51.16 / 58.33 |
| 4 | 200 / 0 | 200 / 0 | 27.88 | 33.58 | 122.52 / 172.03 / 190.95 |
| 5 | 53 / 147 | 53 / 147 | 22.45 | 27.17 | 157.26 / 222.81 / 284.80 |
| 10 | 35 / 165 | 34 / 166 | 22.31 | 26.53 | 178.59 / 241.93 / 247.11 |
| 20 | 32 / 168 | 24 / 176 | 18.39 | 19.99 | 260.21 / 480.53 / 528.64 |

Every level offers 200 requests; error and timeout counts are zero. Accepted correctness equals accepted count. The small accepted samples at high concurrency must not be interpreted as strong p99 guarantees. Rejection and abstention rates are in the machine-readable sweep; rejected requests are visible, not silently dropped.

### Opt-in admission cap 20 (extractive only, same internal four service slots)

| Concurrent clients | Accepted / 429 | Completed RPS | Accepted p50 / p95 / p99 ms |
| --- | --- | --- | --- |
| 1 | 200 / 0 | 25.96 | 38.20 / 57.35 / 65.56 |
| 5 | 200 / 0 | 33.27 | 151.38 / 237.77 / 276.30 |
| 10 | 200 / 0 | 29.94 | 326.70 / 462.05 / 509.08 |
| 20 | 200 / 0 | 31.92 | 592.95 / 825.94 / 873.71 |

200 offered per level; all accepted responses correct; zero errors/timeouts. This deliberately queues more work rather than promising more compute capacity. The sequential part of this auxiliary run has only 10 samples/item and is not used for robust p99 claims.

## Goals and optimization decision

- Initial engineering goals on the **measured sandbox**, not the unmeasured Windows PC: extractive warm HTTP p95 <1500 ms; retrieval/evidence selection p95 <300 ms; non-model API overhead p95 <200 ms.
- Full sequential HTTP p95 is below both 1500 and 200 ms, even including deterministic generation. This is a conservative upper bound on overhead; no unpaired stage-percentile subtraction is represented as a measured overhead distribution.
- Entire sequential pipeline latency bounds its nonnegative retrieval/evidence subset below 300 ms here; individual stage statistics above expose the actual cost. Percentiles of different stages are not summed into a fabricated composite percentile.
- Declared default target concurrency is **four**, not twenty: all 200 requests at four complete correctly. Above four the default system visibly rejects saturation. The cap-20 experiment documents a supported opt-in queue tradeoff on this CPU, not a universal production setting.
- Query embedding/routing dominates extractive cost. Existing single embedding and request-local retrieval reuse are already regression-protected; no new model initialization or answer cache is introduced. Baseline already met the latency budget. No measured evidence justifies risking grounding/source quality for further micro-optimization.
- Small timing differences are observations, not a claimed algorithmic optimization or statistically established speedup. Re-run on Windows hardware before setting local SLOs. There is no fabricated per-case sustained throughput: throughput was measured on the mixed concurrency workload.
- Finite network (Ollama 60 s), queue (30 s), body reception (10 s) and client (60 s) bounds prevent the demonstrated waits. Arbitrary stuck Python/native computation still lacks a hard server execution deadline; this is an explicit reliability limitation.

## Ollama — separate result

**BLOCKED** on both baseline and final sandbox: no reachable daemon/model. No generation p50/p95/p99, throughput or positive inference quality is claimed. The real missing-model contract is measured: health 200, readiness 503/model_unavailable, chat 502/generator_failed, no fabricated answer or extractive substitution. Local instructions run the same workload with the already available model and record model/hardware separately.

## Independent RAG quality — same frozen 113-case labels

AI-authored reference-evidence labels, not blind domain-expert gold. Current 28-page corpus is larger than the labels' original corpus. Correct evidence answers require the gold guide/page in BOTH citation and context and the expected quote in the answer. Lexical support is not semantic truth. Precision beyond top-1 is not claimed without complete relevance judgments.

| Metric | Baseline | Final |
| --- | --- | --- |
| recall_at_1 | 0.9538 | 0.9538 |
| recall_at_5 | 1.0000 | 1.0000 |
| precision_at_1_known_gold | 0.9538 | 0.9538 |
| mrr_truncated_10 | 0.9744 | 0.9744 |
| gold_evidence_context_coverage | 0.9538 | 0.9538 |
| strict_evidence_answer_accuracy | 0.5692 | 0.5692 |
| appropriate_abstention_frozen_negative_labels | 0.7250 | 0.7500 |
| unsupported_answer_rate_frozen_negative_labels | 0.2750 | 0.2500 |
| grounded_answer_rate_lexical | 1.0000 | 1.0000 |
| supported_sentence_rate_lexical | 1.0000 | 1.0000 |
| answerable_strict_correct (count) | 37 | 37 |
| answerable_answered (count) | 53 | 52 |
| wrong_page_answered (count) | 1 | 0 |
| negative_answered (count) | 11 | 10 |
| phantom_citations (count) | 0 | 0 |
| source_identity_violations (count) | 0 | 0 |

The wrong-page navigation-pointer answer is now withheld, not magically routed to an invented source. The missing preselected-interval answer now abstains. No correct reference-evidence answer is lost (37/65 remains 37/65). Ten frozen negative-label cases still answer: eight formerly not-ingested pages and two formerly unresolved identities now have admitted valid content. Labels remain sealed; those are corpus-drift candidates, not automatically relabelled successes. Their semantic correctness, especially the saved-installment-plan source alternative, needs independent adjudication.
Coverage of reference evidence is high, but strict evidence answer accuracy remains 56.9%; this is not enough to certify broad semantic correctness. The verifier/evaluator remains lexical and no human truth-score is invented.

## Phase 3 cached evaluation (not live retrieval or real LLM)

| Run | Behavior matches | Mean key-fact recall | Citation coverage / precision | Prohibited-claim flags |
| --- | --- | --- | --- | --- |
| v2_phase3_baseline_a0 | 47/70 | 0.521 | 1.000 / 1.000 | 10 |
| v2_phase3_a0 | 47/70 | 0.521 | 1.000 / 1.000 | 10 |
| v2_phase3_a0_oracle | 46/70 | 0.507 | 1.000 / 1.000 | 10 |
| v2_phase3_a2_mock | 53/70 | 0.282 | 1.000 / 1.000 | 2 |

A2_mock is a fixture, never real LLM evidence. A0/oracle are deterministic current generation over the unchanged cache; cache retrieval latency remains historical. The 10 A0 prohibited-claim flags and 47/70 behavior match rate remain unresolved evaluation-quality concerns, not hidden by 100% lexical citations. New outputs do not rewrite the sealed cache/gold/baseline files.

## Reproduction

See `LOCAL_PRODUCTION_VERIFICATION.md` for the compact Windows command sequence and `benchmarks/README.md` for exact measurement boundaries. Machine-readable authoritative files are indexed in `benchmarks/results/README.md` and `run_manifest_v2.json`. No public deployment is authorized by these results.
