# SURA Feature Flags Documentation

This document describes all feature flags available in SURA, their default settings, performance impacts, and gating rules.

---

## 1. Feature Flag Inventory

| Flag Name | Default | Module | Purpose | Production Status |
| :--- | :--- | :--- | :--- | :--- |
| `SURA_INTENT_AWARE` | `0` (OFF) | `scripts/rag_completeness.py` | Classifies query into Definition, Procedure, Configuration, or Overview and applies query normalization. | **OFF (Evaluated in Phase 3; rejected due to latency increase)** |
| `SURA_SECTION_SELECTION` | `0` (OFF) | `scripts/rag_completeness.py` | Tags chunks by section signature and prevents redundant same-section selections. | **OFF (Evaluated in Phase 3; rejected due to latency increase)** |
| `SURA_ADDITIONAL_EVIDENCE` | `0` (OFF) | `scripts/rag_completeness.py` | Pulls complementary evidence units for procedural/multi-step queries. | **OFF (Evaluated in Phase 3; rejected due to latency increase)** |
| `SURA_LOG_QUERIES` | `0` (OFF) | `scripts/rag_api.py` | Controls whether user query strings are logged raw (`1`) or as SHA-256 hashes (`0`). | **0 (Default for privacy & GDPR compliance)** |
| `SURA_LOG_JSON` | `1` (ON) | `scripts/rag_api.py` | Controls structured JSON logging to stdout. | **1 (Enabled for production observability)** |
| `SURA_RATE_LIMIT_PER_MINUTE` | `60` | `scripts/rag_api.py` | Configurable per-client IP sliding window rate limit. | **60 (Enabled for DoS defense)** |

---

## 2. Phase 3 Experimentation Findings & Decision

During Phase 3 evaluation across all 157 golden benchmark cases (`scripts/run_phase3_experiment.py`):

1. **Gate Requirements:**
   - Citation validity: 100% required. (Achieved 100%).
   - Zero OOS queries answered. (Achieved: 0 OOS answered).
   - Zero Near-Miss queries answered. (Achieved: 0 Near-miss answered).
   - Tail latency gate: p95 must not increase by >25%.

2. **Results:**
   - **Baseline (Flags OFF):** p50 = 32.1 ms, p95 = 40.1 ms, Key-fact coverage = 71.8%, Citation validity = 100%.
   - **Flags ON:** p50 = 98.4 ms, p95 = 153.7 ms, Key-fact coverage = 71.8%, Citation validity = 100%.
   - Key-fact coverage did not increase (exact sentence coverage in reference pages was already capped by document content).
   - Tail latency p95 increased from 40.1 ms to 153.7 ms (+283%), decisively failing the <= +25% tail latency gate.

3. **Governing Policy:**
   - **KEEP FLAGS OFF.**
   - All Phase 3 flags (`SURA_INTENT_AWARE`, `SURA_SECTION_SELECTION`, `SURA_ADDITIONAL_EVIDENCE`) must remain set to `0` in production.
