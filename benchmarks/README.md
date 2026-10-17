# SURA benchmark and independent quality verification

## Fixed workloads and results

- `workload_v1.json`: preserved exploratory workload. Its billing-due-date follow-up routes to Budget Billing Plan, so it does not prove same-page elaboration. Historical v1 runs remain identifiable and are not used as the final latency comparison.
- `workload_v2.json`: frozen release workload (13 items, seven categories, SHA-256 in every result). It checks the expected **card identity**, not only status. It includes anchored elaboration, explicit topic switching, supported simple/complex questions, out-of-scope and insufficient-evidence queries, M2C-18, and varying page/context lengths. These are verified-corpus smoke expectations, not blind human gold. Future changes require v3, never editing v2.
- `run_benchmark.py`: actual in-process and HTTP measurements, separate generator modes, nearest-rank p50/p95/p99, mean/stddev, cold samples and warm measurements, concurrency throughput, accepted/rejected/error/timeout counts, resource/environment/configuration metadata. Defaults to v2.
- `run_quality.py`: independent frozen 113-case reference-evidence evaluator of the production pipeline. Expected guide/page, cited context identity and evidence in the answer must agree; a plausible wrong-source answer cannot score as correct.
- `results/`: machine-readable runs. `results/README.md` identifies authoritative and exploratory/invalid runs. Sealed historical results under `data/` and `eval/` are never overwritten.

## Evaluation families are not interchangeable

- **Operational Phase D** is the 24-scenario operational harness recorded in `release/corrected_audit_v2/case_results.json`. Its historical result is not a canonical frozen gold set and was **not re-executed** by the store-free tests in this patch. The new isolated operational regression module covers only the two targeted P2.1/P5.1 source-grounding cases; it is not a 24-case Phase D run.
- **Frozen quality labels** are evaluated separately by `run_quality.py` against `data/evaluation/phase12_queries.json` (113 AI-authored reference-evidence cases). The runner validates its case-ID and expectation contract before service construction, and its metrics are lexical/provenance—not SAP semantic correctness.
- **Historical frozen datasets** such as `eval/golden/golden_v1.jsonl` (157 cases) and `eval/phase3/dataset.json` (70 cases) keep their own versioned labels and protocols. Never merge their counts or treat an Operational Phase D result, a latency workload, or a case-ID reconciliation as semantic gold.

## Commands (repository root, chosen Python venv)

```bash
python benchmarks/run_benchmark.py --mode stages --workload benchmarks/workload_v2.json --repeat 100 --strict
python benchmarks/run_benchmark.py --mode e2e --spawn 8300 --workload benchmarks/workload_v2.json --repeat 100 --concurrency-levels 1,4,5,10,20 --concurrency-requests 200 --strict
python benchmarks/run_quality.py --source-commit "$(git rev-parse HEAD)" --out /tmp/current-quality.json
```

The HTTP harness starts/stops a **private local** server and lifts its per-IP rate limiter only for measurement. The production admission cap is still four: 429 saturation above it is visible, not silently dropped. Requests admitted above the service's internal four-slot FIFO queue wait in a bounded queue; actual LLM generation is serialized. For the separately labelled extractive queue experiment:

```bash
python benchmarks/run_benchmark.py --mode e2e --spawn 8300 --workload benchmarks/workload_v2.json --repeat 100 --concurrency-levels 1,5,10,20 --concurrency-requests 200 --admission-cap 20 --strict
```

Do not promote that setting to an unmeasured Ollama host. To measure real Ollama use `--generator ollama`; missing runtime/model yields **BLOCKED**, never substituted extractive numbers. No model is downloaded.

## Statistics and honesty rules

100 warm measured requests per item after warmup; sequential aggregate n=1300. Follow-up warm latency measures the designated final turn, not both turns combined. HTTP concurrency uses 200 offered mixed single-turn requests per level. Single-turn cases are round-robin; follow-ups are independently measured in sequential multi-turn sessions.

Nearest-rank percentile index is `ceil(q/100*n)` (one-based). Every statistic retains n. Cold first-request samples and service construction/model-loading cost are separate from warm latency. Mean/stddev describe the measured distribution, not a confidence interval. Per-item p99 has only 100 observations and is exploratory; small accepted samples at saturation are especially uncertain. Mixed-workload percentiles are not guarantees for every question: per-item distributions are retained too.

**Accepted RAG latency/completed throughput are separate from 429 rejection latency/counts.** All-response latency is also retained; rejected requests are not counted as completed RAG work. A sequential run contaminated by 429s is INVALID. Saturation rejections in the concurrency sweep are legitimate operating-limit evidence and remain reported. `--strict` fails sequential status/source/model mismatches or incorrect/erroring accepted concurrent responses.

Machine metadata includes CPU, RAM, Python/package versions, generator, commit/dirty state, corpus hashes and workload hash. Baseline source can be an immutable `git archive` using `--source-root` and `--source-commit`; no branch switching/history rewrite is needed. Final execution/source hashes are indexed by `results/run_manifest_v2.json`.

## Stage boundaries

- `validation_ms`: clean-question/id validation in the service (not all ASGI/Pydantic overhead).
- `embed_ms`: query embedding.
- `card_query_ms`: card vector query and code-aware injection.
- `rerank_ms`: deterministic reranking, including candidate-page retrieval.
- `route_ms`: parent window containing the three preceding stages; **do not add it to them**.
- `retrieve_ms`: winning-page retrieval; often near zero because request-local rerank results are reused, but elaboration may perform new retrieval.
- `context_ms`: evidence/context construction.
- `generate_ms`: extractive generation or the real model call, including generator-side evidence work.
- `verify_ms`: grounding/citation-marker verification.
- `support_chain_ms`: extractive support-chain verification in the service.
- `queue_wait_ms`: service/generation queue wait.
- `total_ms`: whole pipeline; full service wall time and HTTP wall time are measured separately.

Citation assembly and response serialization are inside total/wall windows, not independently claimed as separately instrumented pure costs. Nor is generator-side evidence filtering completely separable from generation in existing wrappers. The unmodified baseline lacks the new sub-stage timers; native route/context/generate/total windows and full wall latency remain measured. The earlier instrumentation-only baseline exposes some sub-stages. No missing stage is replaced with an invented zero.

Regressions: `tests/test_benchmark_instrumentation.py` (stage boundaries, parent windows, behavior, workload schema, percentiles, wrong-source evaluator rejection), plus the full follow-up/evidence/concurrency suites. Quality labels are AI-authored reference labels tied to an older corpus; lexical grounding is not semantic truth and negative-label drift is never quietly relabelled.
