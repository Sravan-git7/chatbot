# Phase 13-A Evaluation: Multi-Candidate Router Reranking

## 1. Executive Summary

* **Evaluation Set**: Frozen Phase 12 113-question set (SHA-256 `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`)
* **Architecture**: Top-5 candidate retention + in-page chunk retrieval relevance + deterministic scoring formula
* **Scoring Formula**: `score = 0.50 * card_sim + 0.40 * page_sim + 0.10 * coverage` (with -0.20 penalty for unresolved identity cards like M2C-18)

## 2. Router Metrics Comparison

| Metric | Baseline (Dense Top-1) | Phase 13-A (Reranked Top-5) | Absolute Delta | Relative Gain |
|---|---|---|---|---|
| **R@1 (All Gold, n=105)** | 0.5048 (53/105) | **0.7333** (77/105) | **+0.2285** | **+45.3%** |
| **R@1 (Answerable, n=65)** | 0.4615 (30/65) | **0.7692** (50/65) | **+0.3077** | **+66.7%** |
| **R@3 (All Gold)** | 0.7524 | 0.8000 | +0.0476 | - |
| **R@5 (All Gold)** | 0.8571 | 0.8571 | 0.0000 | - |
| **MRR (All Gold)** | 0.6504 | **0.7861** | **+0.1357** | **+20.9%** |

## 3. End-to-End Answer Quality (Evidence Pipeline)

| Metric | Baseline | Phase 13-A Reranker | Delta |
|---|---|---|---|
| **Answerable Correct (Cited Evidence)** | 21 / 65 | **41 / 65** | **+20 (+30.8%)** |
| **Wrong-Page Answers** | 5 | **2** | **-3** |
| **Unsupported Answered (False Positives)** | 9 / 40 | 12 / 40 | +3 |
| **Oracle Answerable Correct** | 52 / 65 | 52 / 65 | 0 |
| **Real-vs-Oracle Gap** | 31 | **11** | **--20 (reduced by 64.5%)** |

## 4. Latency Impact

* **Baseline Real Route Time (Median)**: 21.1 ms
* **Phase 13-A Real Route Time (Median)**: 113.6 ms
* **Total Pipeline Median Latency**: 143.4 ms (vs Baseline 45.2 ms)

## 5. Selection Changes & Transitions

* **Total questions where card selection changed**: 54 / 113
* **Questions improved from Incorrect/Abstained to Correct**: +20
* **Questions regressed from Correct to Incorrect/Abstained**: -0
* **Net Correctness Gain**: **+20**

