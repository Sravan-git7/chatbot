# Phase 14: Retrieval Recall Experiment Report

## 1. Executive Summary

* **Model**: `llama3.2:3b` (temperature=0, seed=42)
* **Evaluation Set**: Frozen Phase 12 113-question benchmark (SHA-256 `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`)
* **Corpus & Cards**: 25 ingested SAP Help pages, 6 guides, 29 M2C cards (all frozen)
* **Configurations Tested**: Candidate pool depths $k \in \{5, 10, 15\}$ using the exact same Phase 13 reranker (weights: card 0.50, page 0.40, lexical 0.10, unresolved penalty -0.25).
* **Production Status**: **FROZEN AT TOP-5**. Neither top-10 nor top-15 is made production default.

---

## 2. Core Comparison Table across Candidate Depths

| Metric | Top-5 (Current Prod) | Top-10 (Candidate Depth 10) | Top-15 (Candidate Depth 15) | Delta (Top-15 vs Top-5) |
|---|:---:|:---:|:---:|:---:|
| **Router R@1 (Answerable, n=65)** | 0.7692 (50/65) | 0.8154 (53/65) | **0.8462 (55/65)** | **+5 (+7.7%)** |
| **Answerable Gold In-Pool Rate** | 0.8154 (53/65) | 0.8769 (57/65) | **0.9077 (59/65)** | **+6 (+9.2%)** |
| **All Gold Cards R@1 (n=105)** | 0.7333 (77/105) | 0.7619 (80/105) | **0.7714 (81/105)** | **+4 (+3.8%)** |
| **All Gold In-Pool Rate (n=105)** | 0.8571 (90/105) | 0.9048 (95/105) | **0.9238 (97/105)** | **+7 (+6.7%)** |
| **All Gold Cards R@3 / R@5** | 0.8000 / 0.8571 | 0.8476 / 0.8476 | **0.8667 / 0.8667** | +0.0667 / +0.0095 |
| **Guarded Ollama Correct / 65** | 30 / 65 (46.2%) | 31 / 65 (47.7%) | **33 / 65 (50.8%)** | **+3 (+4.6%)** |
| **Oracle Correct / 65** | 38 / 65 (58.5%) | 38 / 65 (58.5%) | 38 / 65 (58.5%) | 0 |
| **Real-vs-Oracle Gap** | **8** | **7** | **5** | **Reduced from 8 to 5 (-37.5%)** |
| **Wrong-Page Answers** | 1 | 1 | 2 | +1 (P12-103) |
| **Unsupported Answered / 40** | 6 / 40 | 6 / 40 | 6 / 40 | **0 (No false positives)** |
| **Absent-Detail Answered / 16** | 0 / 16 | 0 / 16 | 0 / 16 | **0 (No false positives)** |
| **Citation Evidence Failures** | 2 | 2 | 2 | 0 |
| **Grounding Failures** | 0 | 0 | 0 | 0 |
| **Phantom Citations** | 0 | 0 | 0 | 0 |
| **Generator Errors** | 0 | 0 | 0 | 0 |
| **Extractive Real Correct / 65** | 41 / 65 (63.1%) | 43 / 65 (66.2%) | **45 / 65 (69.2%)** | **+4 (+6.2%)** |
| **Route Latency Median (steady-state)** | **48.73 ms** | **53.17 ms** | **61.70 ms** | **+13.0 ms** |
| **Rerank Latency Median (steady-state)** | **18.96 ms** | **22.86 ms** | **30.13 ms** | **+11.2 ms** |
| **Total Pipeline Latency Median** | 414.2 ms | 442.5 ms | 463.6 ms | +49.4 ms |

---

## 3. Analysis of the 8 Phase 13 Real-vs-Oracle Failure Questions

| ID | Query | Gold Card | Dense Rank | Top-5 Rerank / Outcome | Top-10 Rerank / Outcome | Top-15 Rerank / Outcome | Recovered? |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **P12-002** | *What does transaction ELDM display?* | `M2C-07` | #21 | Missed (`M2C-25` abstained) | Missed (`M2C-25` abstained) | Missed (`M2C-25` abstained) | **No** (Dense rank 21 > 15) |
| **P12-007** | *Which indicator sets the clearing priority of original items?* | `M2C-24` | #25 | Missed (`M2C-20` abstained) | Missed (`M2C-20` abstained) | Missed (`M2C-20` abstained) | **No** (Dense rank 25 > 15) |
| **P12-013** | *Through which component are letters such as move-out confirmations generated?* | `M2C-02` | #12 | Missed (`M2C-04` abstained) | Missed (`M2C-04` abstained) | **In Pool! Won reranking** (`M2C-02`, answered) | **YES (at k=15)** |
| **P12-027** | *What is the business function ISU_AMI_1 required for?* | `M2C-07` | #25 | Missed (`M2C-05` answered wrong) | Missed (`M2C-05` answered wrong) | Missed (`M2C-05` answered wrong) | **No** (Dense rank 25 > 15) |
| **P12-034** | *Which component monitors the workflow processes of move-in and move-out?* | `M2C-02` | #4 | In pool; Sibling `M2C-03` won reranking (score 0.5155 vs 0.4793) | In pool; Sibling `M2C-03` won reranking | In pool; Sibling `M2C-03` won reranking | **No** (Sibling confusion at reranker) |
| **P12-038** | *Which business function is required to carry out quantity determination from the results list?* | `M2C-07` | #6 | Missed (`M2C-09` abstained) | **In Pool! Won reranking** (`M2C-07`, answered) | **In Pool! Won reranking** (`M2C-07`, answered) | **YES (at k=10 & k=15)** |
| **P12-041** | *Where in Customizing is the clearing priority indicator made available?* | `M2C-24` | #26 | Missed (`M2C-21` abstained) | Missed (`M2C-21` abstained) | Missed (`M2C-21` abstained) | **No** (Dense rank 26 > 15) |
| **P12-042** | *Which component abbreviation covers purchase requisitions and purchase orders?* | `M2C-05` | #14 | Missed (`M2C-17` abstained) | Missed (`M2C-17` abstained) | **In Pool! Won reranking** (`M2C-05`, answered) | **YES (at k=15)** |

### Recovery Summary:
* At **top-10**: 1 of the 8 failures is recovered (`P12-038`).
* At **top-15**: 3 of the 8 failures are recovered (`P12-038`, `P12-013`, `P12-042`).
* Of the remaining 5 failures:
  - 4 queries (`P12-002`, `P12-007`, `P12-027`, `P12-041`) have dense rank $\ge 21$. They require candidate pool $\ge 25$ or lexical router enhancement.
  - 1 query (`P12-034`) was already in the candidate pool (#4), but lost reranking to its sibling card `M2C-03`.

---

## 4. Inspection of Side Effects and Regressions

1. **Total Questions Changed Across All 113**: Exactly **10 questions** change selected card between $k=5$ and $k=15$. The other 103 questions maintain identical routing.
2. **Sibling-Card Confusion**:
   - Zero new sibling-card misroutings are introduced.
   - For all 3 recovered questions (`P12-013`, `P12-038`, `P12-042`), once the gold card entered the candidate pool, the Phase 13 page-evidence score cleanly elevated the gold card over any non-gold competitors.
3. **Unresolved Identity Invocations**:
   - No unresolved identity regressions. The unresolved card penalty (-0.25) reliably prevented non-resolving cards from winning even when admitted into larger candidate pools.
4. **Unsupported False Positives**:
   - 6 / 40 across all depths (0 increase).
5. **Absent-Detail False Positives**:
   - 0 / 16 across all depths (0 increase).
6. **Wrong-Page Answers**:
   - Top-5: 1 wrong-page answer (`P12-027`).
   - Top-10: 1 wrong-page answer (`P12-027`).
   - Top-15: 2 wrong-page answers (`P12-027` and `P12-103`).
   - *Investigation of P12-103*: `P12-103` is an ambiguous question ("How are meter readings validated?"). At $k=15$, card `M2C-28` (dense rank #15) entered the candidate pool, achieved a high page-level similarity score, and won reranking. The generator produced an answer citing `M2C-28`, which is outside the acceptable gold set for `P12-103`.

---

## 5. Latency & Complexity Evaluation

* **Steady-State Route Latency**:
  - $k=5$: 48.73 ms median
  - $k=10$: 53.17 ms median (+4.44 ms)
  - $k=15$: 61.70 ms median (+12.97 ms)
* Thanks to the Phase 13-C single query-embedding optimization, evaluating 15 candidates instead of 5 only adds ~13 ms of route latency.

---

## 6. Conclusion & Recommendation

### Measured Answer to the Primary Question:
* **Does increasing candidate depth materially improve retrieval recall?**
  - **Yes**: Answerable R@1 increases from **76.9%** ($k=5$) to **81.5%** ($k=10$) and **84.6%** ($k=15$).
  - Answerable gold in-pool rate increases from **81.5%** to **90.8%**.
* **Does it improve final answer accuracy?**
  - **Yes**: Guarded Ollama correct answers increase from **30/65** to **31/65** ($k=10$) and **33/65** ($k=15$), reducing the real-vs-oracle gap from 8 to 5.
* **Is there a side effect?**
  - At $k=15$, one ambiguous question (`P12-103`) selects an unaccepted card resulting in +1 wrong-page answer (wrong-page answers: 1 $\rightarrow$ 2).
  - At $k=10$, there are **zero negative side effects**: +1 correct answer (`P12-038`), 0 new wrong-page answers, 0 new false positives, and +4.4 ms latency.

**Production Default Status**: Production default remains **top-5** (`PipelineConfig(top_k_cards=5)`), per strict Phase 14 constraints.
