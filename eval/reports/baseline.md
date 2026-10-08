# SURA Golden Evaluation Baseline (Phase 1)

**Execution Date:** 2026-10-08T08:23:36Z
**Generator:** extractive
**Total Evaluated Cases:** 157

## 1. Corpus Architecture & System Inventory

As audited in Phase 0:
- **Topic Cards / Source Inventory:** 29 topics (`M2C-01` to `M2C-29`)
- **Ingested & Searchable Knowledge Base:** 25 pages
- **Un-ingested / Identity-Only Topics:** 4 topics (`M2C-01`, `M2C-13`, `M2C-16`, `M2C-18`)
- **Backend Architecture:** Stateless FastAPI service; deterministic extractive answer generation (`llama3.2:3b` is not on the default answer path).

---

## 2. Baseline Metrics Summary

| Metric | Baseline Value | Target / Requirement | Status |
| :--- | :--- | :--- | :--- |
| **Route Accuracy** | **97.5%** | High route consistency | PASS |
| **OOS Precision** | **93.8%** | 100% | PASS |
| **OOS Recall** | **100.0%** | High | PASS |
| **Unable-to-Verify Precision** | **90.0%** | 100% | PASS |
| **Unable-to-Verify Recall** | **90.0%** | High | PASS |
| **Top-1 Document Hit Rate** | **94.5%** | High retrieval precision | PASS |
| **Any Selected Document Hit Rate** | **94.5%** | High recall | PASS |
| **Citation Validity** | **100.0%** | 100% (Hard Gate) | **PASS** |
| **Key-Fact Coverage** | **71.8%** | Verbatim representation | PASS |
| **Paraphrase Document Overlap** | **82.2%** | Consistency across phrasing | PASS |
| **Latency p50** | **24.6 ms** | Fast extractive retrieval | PASS |
| **Latency p95** | **30.4 ms** | Bounded tail latency | PASS |
| **Single-Source Answer Count** | **59** | Focus on primary page | INFO |
| **< 3 Sentence Answer Count** | **43** | Concise answers | INFO |
| **Topic-Reference Precision** | **100.0%** | 100% (no OOS topic refs) | **PASS** |

---

## 3. Hard Gates Verification

- **Citation Validity = 100%:** PASSED
- **No Existing Answerable Query Abstained:** PASSED
- **No Out-of-Scope (OOS) Query Answered:** PASSED
- **No Near-Miss Query Answered:** PASSED

**Hard Gate Failures:** 0

---

## 4. Evaluation Dataset Composition

- **Answerable Questions:** 40 (spanning all 25 ingested documents)
- **Paraphrase Groups:** 15 groups x 3 phrasings = 45 queries
- **Out-of-Scope (OOS):** 15 queries
- **Near-Miss (Unable-to-Verify):** 10 queries
- **Landing Page Suggestions:** 6 queries (from `Welcome.tsx` `EXAMPLE_PROMPTS`)
- **Explore Topic Chips:** 29 queries (25 searchable + 4 un-ingested)
- **Related Question Outputs:** 6 queries (from `util.ts` follow-up pools)
- **Multi-Turn Topic Switches:** 6 queries (2 sequences x 3 turns)
- **Total Test Cases:** 157
