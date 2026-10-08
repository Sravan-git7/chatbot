# SURA Golden Evaluation Final Release Verification (Phase 6)

**Execution Date:** 2026-10-08T09:12:13Z
**Generator:** extractive
**Total Evaluated Cases:** 157

## 1. Corpus Architecture & System Inventory

As audited in Phase 0:
- **Topic Cards / Source Inventory:** 29 topics (`M2C-01` to `M2C-29`)
- **Ingested & Searchable Knowledge Base:** 25 pages
- **Un-ingested / Identity-Only Topics:** 4 topics (`M2C-01`, `M2C-13`, `M2C-16`, `M2C-18`)
- **Backend Architecture:** Stateless FastAPI service; deterministic extractive answer generation (`llama3.2:3b` is not on the default answer path).

---

## 2. Comparison: Phase 1 Baseline vs Final System

| Metric | Phase 1 Baseline | Final System | Delta / Status |
| :--- | :--- | :--- | :--- |
| **Route Accuracy** | 97.5% | **97.5%** | No change |
| **OOS Precision** | 93.8% | **93.8%** | No change |
| **OOS Recall** | 100.0% | **100.0%** | No change |
| **Unable-to-Verify Precision** | 90.0% | **90.0%** | No change |
| **Unable-to-Verify Recall** | 90.0% | **90.0%** | No change |
| **Top-1 Document Hit Rate** | 94.5% | **94.5%** | No change |
| **Any Selected Hit Rate** | 94.5% | **94.5%** | No change |
| **Citation Validity** | 100.0% | **100.0%** | **100% (STRICT PASS)** |
| **Key-Fact Coverage** | 71.8% | **71.8%** | No change (Preserved) |
| **Paraphrase Overlap** | 82.2% | **82.2%** | No change (Preserved) |
| **Latency p50** | 24.6 ms | **23.9 ms** | Baseline measured in optimized single-thread run |
| **Latency p95** | 30.4 ms | **29.9 ms** | Baseline measured in optimized single-thread run |
| **Single-Source Answers** | 59 | **59** | Preserved |
| **< 3 Sentence Answers** | 43 | **43** | Preserved |
| **Topic-Reference Precision** | 100.0% | **100.0%** | **100% (STRICT PASS)** |


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
