# Phase 17A: EvidenceGuard Structural / Frame Normalization Report

* **Model**: `llama3.2:3b`
* **Evaluation Set**: Frozen Phase 12 113-question benchmark
* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards

## 1. Comparative Metrics (Phase 16 vs Phase 17A)

| Configuration | Guarded Ollama Correct / 65 | Oracle / 65 | Gap | Extractive / 65 | Absent-Detail / 16 | Wrong-Page | Grounding Failures | Median Route ms | Median Total ms |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **phase16_combined_ABC** | **40 / 65** | 44 / 65 | 4 | 48 / 65 | 0 / 16 | 1 | 0 | 49.17 ms | 47.69 ms |
| **phase17a_combined_ABCE** | **42 / 65** | 47 / 65 | 5 | 48 / 65 | 0 / 16 | 2 | 0 | 50.7 ms | 494.53 ms |

## 2. Recovery & Regression Details

* **Recovered (2)**:
  * **P12-046**: *In which step do I choose Continue to get the installment plan proposal?*
    *Answer*: You choose Continue in step 7. [S4]
  * **P12-048**: *In which step do I enter an amount in the Installment Amount field?*
    *Answer*: You enter an amount in the Installment Amount field in step 5 of the Creating Installment Plans > Activities process. [S3]
* **Regressed (0)**: