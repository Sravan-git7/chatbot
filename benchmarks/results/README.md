# Result provenance and run adjudication

All files here were created during this mission; historical artifacts under `data/` and `eval/` remain untouched.

## Authoritative final evidence

- `v2_baseline_stages.json`, `v2_baseline_e2e.json`: real measurements against an immutable Git archive of baseline **6eb9d9d**, workload v2. The harness runs from the working checkout, so its own git metadata can differ; `source_commit`/`source_tree` identify the code actually measured.
- `release_05ef5e7_stages.json`, `release_05ef5e7_e2e.json`: final committed runtime **05ef5e7**, same v2 workload, n=100 warm measured requests/item (1300 total), concurrency n=200 offered requests/level at 1/4/5/10/20. Expected statuses, card identity and accepted-response correctness checked.
- `release_05ef5e7_queued20_e2e.json`: separately labelled opt-in admission cap 20, same v2 questions. Sequential n=10/item is a smoke, **not** a robust per-item p99 sample. Concurrency n=200/level is the experiment of interest; all admitted work queues through the same four service slots.
- `v1_baseline_quality.json`, `release_05ef5e7_quality.json`: paired independent 113-case reference evaluation, unchanged frozen labels and corpus; final metric definition is the same as baseline. Baseline is an actual new run, not historical data copied as new.
- `v2_phase3_baseline_a0.json`, `v2_phase3_a0.json`, `v2_phase3_a0_oracle.json`: new deterministic-generation runs against the sealed cache. Cached retrieval latency is historical input, **not a new retrieval measurement**. The baseline manifest metadata in those files is historical; `run_manifest_v2.json` identifies execution code/provenance.
- `v2_phase3_a2_mock.json`: fixture/plumbing only, never actual LLM performance.
- `v2_live_smoke.json`: actual private local extractive API/UI-serving smoke, nine workflow checks.
- `v2_ollama_smoke.json`, `v2_ollama_blocked.json`: real runtime/model unavailable; failure contract verified, inference and performance **BLOCKED**.
- `v2_browser_e2e.json`: Chromium binary absence verified, real-browser E2E **BLOCKED**. Separately, the live HTTP/jsdom component suite passes all 120 tests; that is not Chromium coverage.
- `v1_npm_audit.json`: initial advisory findings. `v2_npm_audit.json`: post-patch npm audit, zero findings.
- `v1_pip_audit.json`: PyPI advisory audit of the pinned Linux closure (127 dependency rows). Five finding rows represent four unique Chroma server advisories (one duplicate). No patched version supplied by the advisory service; scoped limitations are in the release report.
- `run_manifest_v2.json`: source/artifact hashes, commands, test counts and scope/limitations. Runtime commit is distinct from the later report/artifact commit; no runtime code changes are made by that later commit.

## Exploratory and superseded evidence (retain, do not blend)

- `20261013T144541Z_6eb9d9d_extractive_stages.json`: early v1 stage run; follow-up wall latency included both turns. Not the final workload-v2 comparison.
- `20261013T144554Z_6eb9d9d_extractive_e2e.json`: **invalid for RAG latency/throughput**, despite the old harness writing status OK: sequential requests and all concurrency levels were contaminated by the 60/min limiter. Retained as evidence of the harness defect, never presented as fast RAG performance.
- `20261013T151050Z_6eb9d9d_extractive_stages.json`: instrumentation-only baseline exposing embed/card-query/rerank/verify timing. Per-stage observations are usable; the old follow-up combined-wall statistic is not a final single-turn comparison.
- `20261013T151120Z_6eb9d9d_extractive_e2e.json`: old harness marked it INVALID due to 429s. Sequential samples were clean; concurrency primarily measured the admission cap. Superseded by the harness that separates accepted and rejection latency explicitly.
- Other `v1_*` and `v2_final_*` files: intermediate hardening/quality iterations. They preserve the actual intermediate results, including negative findings; use the explicit `release_05ef5e7_*` set for final-source claims.

A JSON filename or status alone is not a performance claim. Always check mode, source commit/dirty state, workload hash, sample count, response mix, rejection/error counts and this adjudication before comparing numbers. No Ollama latency is combined with extractive latency.
