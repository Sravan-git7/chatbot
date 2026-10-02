# Phase 16: Controlled Context & Grounding Ablation Report

* **Model**: `llama3.2:3b`
* **Evaluation Set**: Frozen Phase 12 113-question benchmark
* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards

## 1. Comparative Metrics Across Ablations

| Configuration | Guarded Ollama Correct / 65 | Oracle / 65 | Gap | Extractive / 65 | Absent-Detail / 16 | Wrong-Page | Grounding Failures | Median Route ms | Median Total ms |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **phase15_baseline** | **34 / 65** | 38 / 65 | 4 | 48 / 65 | 0 / 16 | 1 | 0 | 48.95 ms | 468.48 ms |
| **phase16_A_only** | **34 / 65** | 38 / 65 | 4 | 48 / 65 | 0 / 16 | 1 | 0 | 49.09 ms | 483.23 ms |
| **phase16_B_only** | **39 / 65** | 43 / 65 | 4 | 48 / 65 | 0 / 16 | 1 | 0 | 50.07 ms | 47.96 ms |
| **phase16_C_only** | **35 / 65** | 39 / 65 | 4 | 48 / 65 | 0 / 16 | 1 | 0 | 47.06 ms | 48.29 ms |
| **phase16_combined_ABC** | **40 / 65** | 44 / 65 | 4 | 48 / 65 | 0 / 16 | 1 | 0 | 47.02 ms | 47.69 ms |

## 2. Per-Ablation Recovery Breakdown

### phase16_A_only
* **Recovered (0)**:
* **Regressed (0)**:

### phase16_B_only
* **Recovered (5)**:
  * **P12-003**: *How do I navigate to the detailed display of an object in the monitoring lists?*
    *Answer*: To navigate to the detailed display of an object in the monitoring lists, you can choose Edit > Select or double-click on the field in question. [S1/S2]
  * **P12-004**: *How is a device number created in Device Management?*
    *Answer*: A device number is created in MM with the Goods Receipt function and transferred to the device. It can also be generated when you create a device in IS-U. [S3]
  * **P12-031**: *What does outsorting mean for a consumption bill?*
    *Answer*: Outsorting means that bill checks are run, which may result in the bill being outsorted. This means that postings do not take place in contract accounts receivable and payable until the bill is released using the Outsorting function. [S3]
  * **P12-051**: *What can be changed in an installment plan proposal before it is saved?*
    *Answer*: In an installment plan proposal, the following changes can be made before it is saved:

- Add installments
- Delete installments
- Calculate or delete interest
- Create or delete an installment plan surcharge and/or an inflation surcharge [S4].
  * **P12-058**: *What does Device Management say about advanced metering infrastructure?*
    *Answer*: Device Management manages technical data, installations, meter readings, and the inspection of devices. If you have activated the Advanced Metering Infrastructure business function (ISU_AMI_1) and you are in an advanced metering infrastructure, you can find more information under Advanced Metering Infrastructure [S1].
* **Regressed (0)**:

### phase16_C_only
* **Recovered (1)**:
  * **P12-022**: *What kind of change can happen to account master data without a user editing it?*
    *Answer*: Master data can be changed automatically by certain business transactions, such as a return, which can result in a processing lock being set [S2].
* **Regressed (0)**:

### phase16_combined_ABC
* **Recovered (6)**:
  * **P12-003**: *How do I navigate to the detailed display of an object in the monitoring lists?*
    *Answer*: To navigate to the detailed display of an object in the monitoring lists, you can choose Edit > Select or double-click on the field in question. [S1/S2]
  * **P12-004**: *How is a device number created in Device Management?*
    *Answer*: A device number is created in MM with the Goods Receipt function and transferred to the device. It can also be generated when you create a device in IS-U. [S3]
  * **P12-022**: *What kind of change can happen to account master data without a user editing it?*
    *Answer*: Master data can be changed automatically by certain business transactions, such as a return, which can result in a processing lock being set [S2].
  * **P12-031**: *What does outsorting mean for a consumption bill?*
    *Answer*: Outsorting means that bill checks are run, which may result in the bill being outsorted. This means that postings do not take place in contract accounts receivable and payable until the bill is released using the Outsorting function. [S3]
  * **P12-051**: *What can be changed in an installment plan proposal before it is saved?*
    *Answer*: In an installment plan proposal, the following changes can be made before it is saved:

- Add installments
- Delete installments
- Calculate or delete interest
- Create or delete an installment plan surcharge and/or an inflation surcharge [S4].
  * **P12-058**: *What does Device Management say about advanced metering infrastructure?*
    *Answer*: Device Management manages technical data, installations, meter readings, and the inspection of devices. If you have activated the Advanced Metering Infrastructure business function (ISU_AMI_1) and you are in an advanced metering infrastructure, you can find more information under Advanced Metering Infrastructure [S1].
* **Regressed (0)**:
