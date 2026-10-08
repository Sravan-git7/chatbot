# Phase 18: Reranker Page-Evidence Deepening (E1) + Deterministic Citation Repair (E2) Report

* **Frozen set**: Phase 12 113-question benchmark (SHA256 3c5a9ddd2d62e9cb...)
* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards
* **Guarded part**: BLOCKED in this environment (Ollama unreachable) - Windows runbook below

## 1. Comparative Metrics

| Configuration | Answerable R@1 /65 | All-gold R@1 /105 | Gold-in-pool | Extractive /65 | Guarded /65 (Oracle) | Absent /16 | Wrong-page | Route median ms |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **phase16_baseline** | 58 / 65 | 87 / 105 | 105/105 | 48 / 65 | BLOCKED | 12 / 16 | 5 | 60.86 ms |
| **e1a_phrase_reranker** | 62 / 65 | 90 / 105 | 105/105 | 50 / 65 | BLOCKED | 12 / 16 | 3 | 64.38 ms |
| **e1a_v2_corroborated** | 62 / 65 | 91 / 105 | 105/105 | 52 / 65 | BLOCKED | 12 / 16 | 3 | 61.78 ms |
| **e1b_full_page_coverage** | 59 / 65 | 88 / 105 | 105/105 | 48 / 65 | BLOCKED | 12 / 16 | 3 | 63.82 ms |
| **e1ab_phrase_and_page** | 61 / 65 | 90 / 105 | 105/105 | 50 / 65 | BLOCKED | 12 / 16 | 2 | 64.55 ms |
| **e1ab_v2_corroborated** | 63 / 65 | 92 / 105 | 105/105 | 52 / 65 | BLOCKED | 12 / 16 | 1 | 64.18 ms |
| **e2_citation_repair** | 58 / 65 | 87 / 105 | 105/105 | 48 / 65 | BLOCKED | 12 / 16 | 5 | 62.11 ms |
| **e1e2_combined** | 61 / 65 | 90 / 105 | 105/105 | 50 / 65 | BLOCKED | 12 / 16 | 2 | 63.23 ms |
| **e1e2_v2_combined** | 63 / 65 | 92 / 105 | 105/105 | 52 / 65 | BLOCKED | 12 / 16 | 1 | 63.85 ms |

## 2. Adoption Decisions (pre-declared rules)

* **R1** router: answerable R@1 >= 58/65 AND all-gold R@1 >= 87/105 AND gold-in-pool 100%
* **R2** extractive: zero per-question extractive regressions vs phase16_baseline
* **R3** guarded: guarded: wrong-page <= 1, unsupported answered <= 6 (no new non-stale), absent-detail = 0, grounding = 0, phantom = 0, URL changes = 0, cite-evidence <= 2, generator errors = 0 (only when Ollama ran)
* **R4** latency: median route latency <= baseline median + 15 ms

* **phase16_baseline**: baseline (reference)
* **e1a_phrase_reranker**: **FAIL**
    * R1_router: PASS
    * R2_extractive: FAIL
    * R3_guarded: BLOCKED
    * R4_latency: PASS
    * extractive recovered: P12-007, P12-034, P12-041, P12-047
    * extractive regressed: P12-020, P12-023
* **e1a_v2_corroborated**: **PASS**
    * R1_router: PASS
    * R2_extractive: PASS
    * R3_guarded: BLOCKED
    * R4_latency: PASS
    * extractive recovered: P12-007, P12-034, P12-041, P12-047
* **e1b_full_page_coverage**: **PASS**
    * R1_router: PASS
    * R2_extractive: PASS
    * R3_guarded: BLOCKED
    * R4_latency: PASS
* **e1ab_phrase_and_page**: **FAIL**
    * R1_router: PASS
    * R2_extractive: FAIL
    * R3_guarded: BLOCKED
    * R4_latency: PASS
    * extractive recovered: P12-007, P12-034, P12-041, P12-047
    * extractive regressed: P12-020, P12-023
* **e1ab_v2_corroborated**: **PASS**
    * R1_router: PASS
    * R2_extractive: PASS
    * R3_guarded: BLOCKED
    * R4_latency: PASS
    * extractive recovered: P12-007, P12-034, P12-041, P12-047
* **e2_citation_repair**: **PASS**
    * R1_router: PASS
    * R2_extractive: PASS
    * R3_guarded: BLOCKED
    * R4_latency: PASS
* **e1e2_combined**: **FAIL**
    * R1_router: PASS
    * R2_extractive: FAIL
    * R3_guarded: BLOCKED
    * R4_latency: PASS
    * extractive recovered: P12-007, P12-034, P12-041, P12-047
    * extractive regressed: P12-020, P12-023
* **e1e2_v2_combined**: **PASS**
    * R1_router: PASS
    * R2_extractive: PASS
    * R3_guarded: BLOCKED
    * R4_latency: PASS
    * extractive recovered: P12-007, P12-034, P12-041, P12-047

* **Passing configurations**: e1a_v2_corroborated, e1b_full_page_coverage, e1ab_v2_corroborated, e2_citation_repair, e1e2_v2_combined
* **Best passing configuration**: e1ab_v2_corroborated

## 3. BLOCKED: Guarded Ollama Metrics (Windows runbook)

1. Start Ollama on the Windows machine and pull the model:  ollama pull llama3.2:3b
2. Keep the ORIGINAL (Windows) vector stores - do not use the sandbox-rebuilt stores.
3. Run:  python scripts/evaluate_phase18.py
4. Baseline guarded rows are pre-populated from data/phase16/phase16_ollama_ckpt.jsonl; only the new-flag configurations need fresh LLM calls.
5. Compare data/phase18/phase18_comparison.json adoption section against the sealed Phase 16 numbers.
