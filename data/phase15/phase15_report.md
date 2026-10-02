# Phase 15: Hybrid / Code-Aware Retrieval Experiment Report

## 1. Executive Summary

* **Model**: `llama3.2:3b` (temperature=0, seed=42)
* **Evaluation Set**: Frozen Phase 12 113-question benchmark
* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards
* **Baseline**: Phase 14 (`top_k_cards=10, rerank_router=True, code_aware_router=False`)
* **Experiment**: Phase 15 (`top_k_cards=10, rerank_router=True, code_aware_router=True`)

## 2. Core Comparative Metrics

| Metric | Baseline (Phase 14) | Phase 15 Hybrid | Delta |
|---|:---:|:---:|:---:|
| **Answerable Router R@1 (n=65)** | 0.8154 (53/65) | **0.8923 (58/65)** | **+5 (+7.7%)** |
| **Answerable Gold In-Pool Rate (n=65)** | 0.8769 (57/65) | **1.0000 (65/65)** | **+8** |
| **All Gold Router R@1 (n=105)** | 0.7619 (80/105) | **0.8286 (87/105)** | **+7** |
| **All Gold In-Pool Rate (n=105)** | 0.9048 (95/105) | **1.0000 (105/105)** | **+10** |
| **All Gold MRR** | 0.7548 | **0.8216** | **+0.0668** |
| **Guarded Ollama Correct / 65** | 31 / 65 (47.7%) | **34 / 65 (52.3%)** | **+3 (+4.6%)** |
| **Oracle Ceiling / Real-vs-Oracle Gap** | 38 (Gap: 7) | **38 (Gap: 4)** | **Gap reduced to 4** |
| **Wrong-Page Answers** | 1 | 1 | +0 |
| **Unsupported Answered / 40** | 6 / 40 | 6 / 40 | +0 |
| **Absent-Detail Answered / 16** | 0 / 16 | 0 / 16 | 0 |
| **Citation Evidence Failures** | 2 | 2 | +0 |
| **Grounding Failures** | 0 | 0 | 0 |
| **Phantom Citations** | 0 | 0 | 0 |
| **Generator Errors** | 0 | 0 | 0 |
| **Route Latency (Median / Mean)** | 47.58 ms / 50.72 ms | 48.66 ms / 51.47 ms | +1.1 ms |
| **Total Pipeline Latency (Median)** | 442.5 ms | 468.5 ms | +26.0 ms |

## 3. Detailed Tracking of Target Failure Questions

| ID | Query | Gold | Baseline Selected | Hybrid Selected | Baseline Correct? | Hybrid Correct? |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **P12-001** | *What is the purpose of transaction EL43?* | `M2C-07` | `M2C-22` | `M2C-07` | No | **No** |
| **P12-002** | *What does transaction ELDM display?* | `M2C-07` | `M2C-25` | `M2C-07` | No | **YES** |
| **P12-007** | *Which indicator sets the clearing priority of original items?* | `M2C-24` | `M2C-20` | `M2C-20` | No | **No** |
| **P12-013** | *Through which component are letters such as move-out confirmations generated?* | `M2C-02` | `M2C-04` | `M2C-02` | No | **YES** |
| **P12-026** | *What is ISU_QD_1 used for in the meter reading monitoring lists?* | `M2C-07` | `M2C-07` | `M2C-07` | No | **No** |
| **P12-027** | *What is the business function ISU_AMI_1 required for?* | `M2C-07` | `M2C-05` | `M2C-05` | No | **No** |
| **P12-030** | *What is event 3000 used for?* | `M2C-24` | `M2C-05` | `M2C-24` | No | **No** |
| **P12-034** | *Which component monitors the workflow processes of move-in and move-out?* | `M2C-02` | `M2C-03` | `M2C-03` | No | **No** |
| **P12-038** | *Which business function is required to carry out quantity determination from the results list?* | `M2C-07` | `M2C-07` | `M2C-07` | YES | **YES** |
| **P12-041** | *Where in Customizing is the clearing priority indicator made available?* | `M2C-24` | `M2C-21` | `M2C-21` | No | **No** |
| **P12-042** | *Which component abbreviation covers purchase requisitions and purchase orders?* | `M2C-05` | `M2C-17` | `M2C-05` | No | **YES** |
| **P12-066** | *What is the maximum number of meter reading orders that transaction EL31 can display?* | `M2C-07` | `M2C-07` | `M2C-07` | No | **No** |
| **P12-067** | *How often does transaction EL32 run automatically?* | `M2C-07` | `M2C-02` | `M2C-07` | No | **No** |
| **P12-068** | *Which authorization object protects transaction EL43?* | `M2C-07` | `M2C-17` | `M2C-07` | No | **No** |

## 4. Improvements & Regressions

* **Total Improvements**: 3
  * **P12-002**: *What does transaction ELDM display?* (`M2C-25` -> `M2C-07`)
  * **P12-013**: *Through which component are letters such as move-out confirmations generated?* (`M2C-04` -> `M2C-02`)
  * **P12-042**: *Which component abbreviation covers purchase requisitions and purchase orders?* (`M2C-17` -> `M2C-05`)
* **Total Regressions**: 0