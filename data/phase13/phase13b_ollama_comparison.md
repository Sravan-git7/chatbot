# Phase 13-B Evaluation Report: Real Ollama Generator with Router Reranking

## 1. Executive Summary

* **Model**: `llama3.2:3b` (temperature=0, seed=42)
* **Evaluation Set**: Frozen Phase 12 113-question set (SHA-256 `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`)
* **Corpus**: 25 ingested SAP Help pages, 6 guides, 29 M2C cards
* **Router Configuration**: Phase 13-A Top-5 candidate page evidence reranker (`rerank_router=True`)

## 2. Core Metrics: Baseline vs Phase 13-B

| Metric | Phase 12 Baseline Real Ollama (Dense Top-1) | Phase 13-B Real Ollama (Reranked Top-5) | Delta | Phase 12 Oracle Ollama |
|---|:---:|:---:|:---:|:---:|
| **Router R@1 (Answerable, n=65)** | 0.4615 (30/65) | **0.7692 (50/65)** | **+0.3077 (+66.7% rel)** | 1.0000 (Oracle) |
| **Router R@1 (All Gold, n=105)** | 0.5048 (53/105) | **0.7333 (77/105)** | **+0.2285 (+45.3% rel)** | 1.0000 (Oracle) |
| **Router R@3 (All Gold)** | 0.7524 | 0.8000 | +0.0476 | - |
| **Router R@5 (All Gold)** | 0.8571 | 0.8571 | 0.0000 | - |
| **Router MRR (All Gold)** | 0.6504 | **0.7861** | **+0.1357 (+20.9% rel)** | 1.0000 |

### Generator Results: Guarded Ollama (`ollama + EvidenceGuard`)

| Metric | Phase 12 Real (Baseline) | Phase 13-B Real (Reranked) | Delta | Phase 12 Oracle | Phase 13-B Oracle |
|---|:---:|:---:|:---:|:---:|:---:|
| **Answerable Correct / 65** | 16 / 65 (24.6%) | **30 / 65 (46.2%)** | **+14 (+21.5% abs)** | 38 / 65 | 38 / 65 |
| **Wrong-Page Answers** | 3 | **1** | **-2** | 0 | 0 |
| **Unsupported Answered / 40** | 4 / 40 | 6 / 40 | +2 | 0 | 0 |
| **Absent-Detail Answered / 16** | 0 / 16 | 0 / 16 | 0 | 0 | 0 |
| **Citation Evidence Failures** | 0 | 2 | +2 | 2 | 2 |
| **Grounding Failures** | 0 | 0 | 0 | 0 | 0 |
| **Phantom Citations** | 0 | 0 | 0 | 0 | 0 |
| **URL Alterations** | 0 | 0 | 0 | 0 | 0 |
| **Generator Errors** | 0 | 0 | 0 | 0 | 0 |
| **Real-vs-Oracle Gap** | 22 questions | **8 questions** | **-14** | - | - |

### Generator Results: Raw Ollama (`ollama_raw`)

| Metric | Phase 12 Real (Baseline) | Phase 13-B Real (Reranked) | Delta | Phase 12 Oracle | Phase 13-B Oracle |
|---|:---:|:---:|:---:|:---:|:---:|
| **Answerable Correct / 65** | 19 / 65 (29.2%) | **33 / 65 (50.8%)** | **+14 (+21.5% abs)** | 41 / 65 | 42 / 65 |
| **Wrong-Page Answers** | 7 | **7** | **+0** | 0 | 0 |
| **Unsupported Answered / 40** | 5 / 40 | 9 / 40 | +4 | 0 | 0 |
| **Absent-Detail Answered / 16** | 0 / 16 | 0 / 16 | 0 | 0 | 0 |
| **Citation Evidence Failures** | 1 | 3 | +2 | 3 | 3 |
| **Grounding Failures** | 0 | 0 | 0 | 0 | 0 |
| **Phantom Citations** | 0 | 0 | 0 | 0 | 0 |
| **URL Alterations** | 0 | 0 | 0 | 0 | 0 |
| **Generator Errors** | 0 | 0 | 0 | 0 | 0 |
| **Real-vs-Oracle Gap** | 22 questions | **9 questions** | **-13** | - | - |

## 3. Comparison across Generators (Reranked vs Baseline)

| Architecture | Real Answerable Correct (Baseline) | Real Answerable Correct (Phase 13 Reranked) | Delta (Rerank Gain) | Oracle Ceiling | Real-to-Oracle Recovery % |
|---|:---:|:---:|:---:|:---:|:---:|
| **Extractive (Evidence)** | 21 / 65 | 41 / 65 | **+20** | 52 / 65 | **64.5%** gap recovered |
| **Ollama (Guarded)** | 16 / 65 | 30 / 65 | **+14** | 38 / 65 | **63.6%** gap recovered |
| **Ollama (Raw)** | 19 / 65 | 33 / 65 | **+14** | 42 / 65 | **60.9%** gap recovered |

## 4. Latency Analysis (Median / p95)

* **Route Latency (Median)**: 151.1 ms (Baseline: 13.2 ms)
* **Retrieve Latency (Median)**: 21.6 ms
* **Generate Latency (Median)**: 409.8 ms (p95: 1361.9 ms)
* **Total Pipeline Latency (Median)**: 538.6 ms (p95: 1391.3 ms)

## 5. Selection Changes & Transitions (Guarded Ollama)

* **Total questions with card selection changed**: 54 / 113
* **Transitions from Incorrect/Abstained -> Correct**: +14
* **Transitions from Correct -> Incorrect/Abstained**: -0
* **Net Correctness Gain**: **+14**

