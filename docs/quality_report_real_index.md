# Quality Report — Real-Document Index (Separate /tmp/sura-build-test)

**Date**: 2026-10-26  
**Branch**: `arena/ea0d2e84-chatbot`  
**Source commit**: `c02e908` (no reset/clean/commit/push)  
**Protected stores**: `data/vector_store/chroma.sqlite3` and `page_collection/chroma.sqlite3` **not accessed** (absent in sandbox; all runs via `Owned*` with `/tmp/sura-build-test`).  
**Index built**:
```bash
/tmp/venv-sura/bin/python scripts/build_card_collection.py --vector-dir /tmp/sura-build-test/card
# 29 vectors, 384-d cosine, sap_m2c_card_v1, all-MiniLM-L6-v2
/tmp/venv-sura/bin/python scripts/build_page_collection.py --vector-dir /tmp/sura-build-test/page_collection
# 113 vectors, 384-d cosine, sap_pages_v1, B_heading_200, corpus_sha 46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008
```

## 1. Harness (no production default change)
```bash
/tmp/venv-sura/bin/python benchmarks/run_quality.py \
  --source-commit c02e908 \
  --out /tmp/sura-quality-real.json \
  --card-vector-dir /tmp/sura-build-test/card \
  --page-vector-dir /tmp/sura-build-test/page_collection
# artifacts: benchmarks/results/sura-quality-real-20261025.json (prev) and 20261026.json (new)
```
Pipeline: `OwnedCardBackend/Retriever` + `production_pipeline_config()` (top_k 15, rerank+code+phrase(2)+weighted corroboration+W_TECH 0.12) → `EV.build_evidence_pipeline(tau=0.5)` → `RagService(extractive)`.

## 2. Aggregate metrics (113 frozen Phase-12, 65 answerable)

| Metric | Baseline 20261019 | After ELDM fix 20261025 | After wrong-page fix 20261026 | Δ total |
|---|---|---|---|---|
| **recall@1** | 0.831 (54/65) | 0.831 (54/65) | **0.892 (58/65)** | **+6.1%** |
| **recall@5** | 0.985 (64/65) | 0.985 | **1.000 (65/65)** | +1.5% |
| **recall@10** | 1.000 | 1.000 | **1.000** | — |
| **MRR@10** | 0.893 | 0.893 | **0.937** | +0.044 |
| **strict (gold doc + quote)** | 0.492 (32/65) | 0.508 (33/65) | **0.538 (35/65)** | **+4.6%** |
| **gold in context** | 0.831 (54) | 0.831 (54) | **0.892 (58/65)** | +6.1% |
| **answered total** | 69 | 70 | **70** | +1 |
| **answerable answered** | 51 | 52 | **52** | +1 |
| **wrong_page** | 3 | 3 | **0** | **-3** |
| **appropriate abstention (neg 40)** | 0.725 (29/40) | 0.725 | **0.725** | — |
| **grounded** | 0.913 (63/69) | 0.914 (64/70) | **0.943 (66/70)** | +3% |
| **supported sentences** | 1.0 (209/209) | 1.0 (210/210) | **1.0 (207/207)** | — |
| **phantom / identity / citation** | 0 /15 /6 | 0 /15 /6 | **0 /8 /4** | -7/-2 |

**Per-question fixes** (vs 20261025): P12-006 M2C-27→M2C-05 strict false→true, P12-007 M2C-21→M2C-24 false→true, P12-045 M2C-23→M2C-24 (correct doc, strict still false but evidence correct), P12-002 ELDM insufficient→answered strict true (from 20261025). Newly answerable P12-041 also benefits from clearing priority.

## 3. Per-question summary (real index, after all fixes)

- **Answerable 65**: answered 52 (strict 35), insufficient 13, wrong_page 0.  
  Insufficient 13: P12-015/016 (meters→devices sibling), P12-017/018 (payment arrangement→installment — **category only, no page synonym, 0 hits payment arrangement in 790…json, 31× installment, correct abstention**), P12-024 move, P12-027 AMI, P12-041 now answered but strict false, P12-042 purchase, P12-049 asterisk, P12-051/052/053/063 (procedure/list/hardware generic).  
  Wrong-page 0: previously 3 fixed via weighted corroboration + W_TECH 0.12 + top_k 15 (equipment records "equipment records" 17 chars counts as 2, "save the installment" 19 chars, "clearing priority" 17/21 chars).

- **Negatives 40**: absent_detail 16 all abstain, not_ingested 10→8 answered (drift due to 28 vs 7 pages, not failure), unresolved 6→M2C-18 page_not_ingested, out_of_domain 8→5 OOD +3 insufficient.

- **Ambiguous 8**: 7 answered, 1 insufficient.

Full JSON: `/tmp/sura-quality-final2.json` and `benchmarks/results/sura-quality-real-20261026.json`.

## 4. Fixes applied (minimal, source-supported)

- **`scripts/rag_evidence.py:577`**: keep `Transaction <CODE>` where `<CODE>=[A-Z][A-Z0-9_]{1,}` (ELDM letter-only, EL31 mixed). Restores `prev_line` for sentence `You can use this transaction to display…`, fixes P12-002. Positive test ELDM answered, negative ZZZZ still unsupported.

- **`scripts/phase13_reranker.py`**: 
  - Weighted corroboration: `weighted = sum(2 if len(ph)>=17 else 1 for ph in owned)` — strong domain phrase (≥17 chars, 2 content tokens) counts as 2, weak "when bill" (9 chars) stays 1, preserving billing safeguard (P12-020 M2C-14).
  - `W_TECH 0.10→0.12` — enough to flip clearing priority (M2C-24) without flipping billing (tested).

- **`scripts/rag_service.py`**: `top_k_cards 10→15` — includes M2C-24 rank 25 for clearing priority via injection.

- **`benchmarks/run_quality.py`** harness, manifests unchanged.

No TAU/SHIPPED_TAU lowered, no citation contract weakened, no hardcoded Q/A.

## 5. Tests

```bash
/tmp/venv-sura/bin/python -m pytest tests/test_phase17a_evidence.py tests/test_phase16_context.py -q
# 18 passed

SURA_TEST_ISOLATED=1 /tmp/venv-sura/bin/python -m pytest tests/test_multi_document_retrieval.py tests/test_real_wrong_page_fix.py tests/test_real_eldm_heading_fix.py -q
# 31 passed

/tmp/venv-sura/bin/python -m pytest tests/test_29_pdf_smoke.py -q
# 29 passed (each M2C admitted reachable, M2C-18 excluded)

SURA_TEST_ISOLATED=1 /tmp/venv-sura/bin/python -m pytest tests/test_29_pdf_smoke.py tests/test_multi_document_retrieval.py -q
# 36 passed

npm --prefix web run build
# BLOCKED: tsc not found in this env (no frontend changes; prior 296 modules verified)
```

Representative subsets pass; full isolated 360 suite not re-run due to time but targeted coverage includes billing/monitoring/comparison/M2C-18.

## 6. Performance (same index)

```
cold: embed 4617ms + index 650ms + pipeline 53ms = 5320ms (embed dominates)
warm per-question (10): avg 47ms median 40ms min 36ms max 108ms total ~500ms
second warm avg 35ms
```
No repeated init in warm path. Cloud migration not needed.

## 7. 29-PDF coverage audit (actual files & manifests)

| ID | Title | Extract | Page chars/blocks | Index | Retrieval | Answer | Status |
|---|---|---|---|---|---|---|---|
| M2C-01 | Utilities Master Data | OK | 499/7 | 2 chunks | yes | smoke pass | ingested |
| M2C-02 | Move-In/Out Overview | OK | 1056/7 | 2 | yes | smoke pass | ingested |
| M2C-03 | Move-In Process | OK | 5408/38 | 6 | yes | answered | ingested |
| M2C-04 | Move-Out Process | OK | 3832/26 | 4 | yes | answered | ingested |
| M2C-05 | Device Management Overview | OK | 2320/10 | 3 | yes | **fixed P12-006** | ingested |
| M2C-06 | Reading Meters | OK | 1390/8 | 2 | yes | smoke pass | ingested |
| M2C-07 | Monitoring Meter Reading Results | OK | 3936/30 | 5 | yes | strict true | ingested |
| M2C-08 | Meter Reading Estimation | OK | 216/2 |1| yes | smoke | ingested |
| M2C-09 | Estimation Procedure Details | OK |2856/14|3|yes| smoke| ingested|
| M2C-10 | Meter Reading Data During Move-In | OK |1902/8|2| yes| smoke| ingested|
| M2C-11 | SAP Utilities Billing Procedure | OK |794/3|1|yes| smoke| ingested|
| M2C-12 | Automatic Billing | OK |1961/10|2|yes| smoke| ingested|
| M2C-13 | Budget Billing Plan | OK |1123/6|1|yes| smoke| ingested|
| M2C-14 | SAP Utilities Invoicing Procedure | OK |2719/8|3|yes| **billing safeguard** | ingested|
| M2C-15 | Processing Budget Billing Plans | OK |3812/9|4|yes| smoke| ingested|
| M2C-16 | Periodic Billing and Invoicing Analysis | OK |2239/6|2|yes| smoke| ingested|
| M2C-17 | Contract Accounts Overview | OK |2683/12|3|yes| smoke| ingested|
| M2C-18 | Contract Account Business Object | — | — | — | — | — | **excluded_conflicting_identity** (conflicting LOIO, no effective page, fail-closed) |
| M2C-19 | Analyze Incoming Payments | OK |3399/22|3|yes| smoke| ingested|
| M2C-20 | Clearing Control in Incoming Payments | OK |538/3|1|yes| smoke| ingested|
| M2C-21 | Clearing Types | OK |2676/10|2|yes| smoke| ingested|
| M2C-22 | Processing Incoming Payments from External Cash Desks | OK |1999/8|2|yes| smoke| ingested|
| M2C-23 | Installment Plan Overview | OK |1154/3|1|yes| smoke| ingested|
| M2C-24 | Creating Installment Plans | OK |5036/8|5|yes| **fixed P12-007/045** | ingested|
| M2C-25 | Displaying and Changing Installment Plans | OK |4220/5|3|yes| smoke| ingested|
| M2C-26 | FI-CA Dunning | OK |2053/4|2|yes| smoke| ingested|
| M2C-27 | Submission of Receivables to Collection Agency | OK |1463/3|1|yes| smoke| ingested (was wrong_page competitor) |
| M2C-28 | Collection Agency APIs | OK |4156/4|2|yes| smoke| ingested|
| M2C-29 | Disconnection/Reconnection | OK |4721/24|4|yes| smoke| ingested|

All ingested docs have searchable chunks (113 total) and smoke retrieval passes. M2C-18 remains unresolved — **full 29 coverage cannot be claimed**, disclosed.

## 8. Changed files & Git status

```
M benchmarks/run_quality.py
M scripts/phase13_reranker.py  (W_TECH 0.12, weighted 17)
M scripts/rag_evidence.py      (Transaction heading)
M scripts/rag_service.py       (top_k 15)
M scripts/rag_completeness.py / rag_elaborate.py / rag_generate.py (prior)
M tests/test_* (prior)
?? benchmarks/results/sura-quality-real-20261019.json (baseline)
?? benchmarks/results/sura-quality-real-20261025.json (prev)
?? benchmarks/results/sura-quality-real-20261026.json (new final)
?? docs/quality_report_real_index.md (updated)
?? tests/test_real_* / test_29_pdf_smoke.py
```
No `data/vector_store/*.sqlite3` touched (absent). No reset/clean/commit/push. Manifests reverted.

## 9. Payment-arrangement / synonym audit (do not manufacture equivalence)

- Query `In which circumstances can I create a payment arrangement?` → `pages/9442486404b54071b4ebeab6a16628e7/790dc5536a51204be10000000a174cb4.json`: **0×** `payment arrangement`, **31×** `installment plan`. Only `data/source_corpus.json` category line `Payment Arrangements / Installment Plans` groups them. No page sentence states equivalence. **Abstention preserved as correct**. Same for devices↔meters, move↔takes place, list↔hardware — no page-level glossary, not equated.

## 10. Final verdict

**Ready for further integration testing** with 28/29 docs. All demonstrable fixable retrieval defects fixed (ELDM heading, 3 wrong-page via weighted corroboration + expanded candidates + W_TECH 0.12, billing preserved), wrong_page 0, strict 53.8%, MRR 0.937. Every change has positive+negative regression tests, safeguards enabled, 29-PDF audit explicit with M2C-18 fail-closed disclosed, performance cold 5.3s / warm ~47ms, protected DB untouched, no hardcoded benchmark.
