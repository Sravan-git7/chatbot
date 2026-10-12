# SURA Phase 3 — Offline LLM Benchmark Harness

This directory contains the reproducible, offline evaluation harness built to evaluate whether LLM-assisted generation can improve answer quality over the baseline extractive generator.

> [!IMPORTANT]
> This is an **evaluation-only** harness. It does **not** call any live model APIs, download models, or modify the production answer path. Fake/mock adapters (`A2_mock`, `A3_mock`) are test fixtures and are never reported as actual LLM performance.

---

## Directory Contents

| File | Purpose |
|---|---|
| `dataset.json` | 70-case frozen evaluation set across 10 categories with key facts, prohibited claims, and expected behaviors. |
| `evidence_cache.json` | Serialized evidence snapshots (chunks, titles, URLs, routing statuses) captured from the production pipeline. |
| `baseline_manifest.json` | Generator identity, git commit hash, configuration, and question inventory. |
| `adapters.py` | Adapter interfaces for A0 (extractive baseline), A2 (span-selection mock), and A3 (paraphrasing mock). |
| `metrics.py` | Deterministic evaluation checks (behavior, fact recall, citations, hallucinations, procedural limits). |
| `runner.py` | CLI benchmark runner with latency instrumentation, oracle mode, and JSON reporting. |
| `a0_baseline_results.json` | Baseline results from running A0 across all 70 test cases. |
| `a0_oracle_results.json` | Baseline results from running A0 with gold oracle evidence. |
| `report.md` | Comprehensive analysis separating measured findings, automated vs human metrics, and next steps. |

---

## How to Run

All commands should be executed from the repository root (`D:\chatbot-phase12`):

### 1. Run the Baseline Extractive Generator (A0)
```powershell
python eval/phase3/runner.py --adapter A0 --out eval/phase3/a0_baseline_results.json
```

### 2. Run with Oracle Evidence Subset
```powershell
python eval/phase3/runner.py --adapter A0 --oracle --out eval/phase3/a0_oracle_results.json
```

### 3. Run Test Fixture Adapters (Plumbing Validation Only)
```powershell
python eval/phase3/runner.py --adapter A2_mock --out eval/phase3/a2_mock_results.json
python eval/phase3/runner.py --adapter A3_mock --out eval/phase3/a3_mock_results.json
```

### 4. Run the Phase 3 Unit Test Suite
```powershell
python -m unittest tests/test_phase3_eval.py
```

### 5. Run the Full Backend Regression Suite
```powershell
python -m unittest tests/test_phase2_fixes.py tests/test_causal_evidence.py tests/test_source_manifest.py tests/test_phase3_eval.py
```
