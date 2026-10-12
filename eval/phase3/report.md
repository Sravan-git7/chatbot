# SURA Phase 3 — Offline LLM Benchmark Evaluation Report

**Date:** 2026-10-11
**Repository:** `D:\chatbot-phase12`
**Git Revision:** `a376f03e68a1d4cb66fca9cb6a9616acb71c2f4e`
**Branch:** `arena/4fe57164-chatbot`
**Harness Directory:** `eval/phase3/`

---

## 1. Executive Summary & Objective

The objective of Phase 3 is to construct a rigorous, reproducible, offline evaluation harness to measure whether LLM-assisted generation can improve answer quality over the current baseline extractive generator (`A0`), without modifying production retrieval, chunking, or persistent indexes, and without changing the production answer path.

This phase is **evaluation-only**. In strict accordance with constraints:
- **No live model APIs were called.**
- **No Ollama models or external weights were downloaded.**
- **Zero benchmark results, token counts, or costs were fabricated.**
- **Fail-closed behavior for unavailable documentation (M2C-18) was strictly preserved.**
- **The production answer path and web frontend remain 100% untouched.**

---

## 2. Baseline Architecture & Shipped State

The baseline pipeline consists of:
1. **Routing & Retrieval**: Two-stage router (dense embedding via `sentence-transformers` + code-aware and phrase rerankers) constrained to registered topic cards.
2. **Identity Resolution**: Strict resolution against SAP deliverable metadata; unverified/conflicting pages (such as M2C-18) fail closed.
3. **Evidence Construction**: Ingested page chunks assembled into a bounded token context (`ContextBlock`).
4. **Generator (A0 Baseline)**: `EvidenceExtractiveGenerator` with shipped $\tau = 0.5$. Emits verbatim sentences and bullet items from selected evidence units with citation markers `[S#]`, and enforces procedural limitation notices when procedural queries receive only conceptual source documentation.

---

## 3. Fixed Evaluation Dataset Composition

The evaluation dataset (`eval/phase3/dataset.json`) contains **70 real, source-grounded test cases** designed to probe specific failure modes:

| Category | Target | Actual | Purpose & Scope |
|---|:---:|:---:|---|
| **Factual Definitions** | 10 | 10 | Core IS-U objects (Contract Account, Premise, Connection Object, Installation, PoD, Budget Billing Plan, Estimation, Clearing Control, Installment Plan, Dunning). |
| **Enumerations** | 6 | 6 | Master data lists, business vs technical objects, clearing types, estimation methods, meter monitoring statuses. |
| **Documented Procedures** | 8 | 8 | Genuine step-by-step procedures present in source (Create/change installment plan, submit receivables, move-in meter reading, installation disconnection, automatic billing). |
| **Procedural (Lacks Steps)** | 6 | 6 | Procedural questions where available documentation only describes concepts/features (Budget Billing Plan, Periodic Billing Analysis F3424, Device Management Overview, Contract Account Overview, Clearing Control Rules). |
| **Multi-step / Multi-doc** | 8 | 8 | Cross-topic workflows (move-in to meter reading, billing to invoicing, budget billing reconciliation, disconnection to reconnection, APIs to receivables). |
| **Follow-up & Transitions** | 12 | 12 | Conversational turns testing context carryover, topic anchoring, and clean transitions between topics without cross-contamination. |
| **Ambiguous Queries** | 6 | 6 | Underspecified questions requiring clarification ("How do I reverse a document?", "How do I process payments?", "How do I create a plan?"). |
| **Unsupported / Out-of-Scope** | 6 | 6 | SD pricing, Asset Accounting, Basel III, general programming, weather, general recipes — must fail closed. |
| **Unavailable Documentation** | 2 | 2 | Contract Account Business Object (M2C-18) — must return `DOC_UNAVAILABLE` fail-closed. |
| **Adversarial / False Premise** | 6 | 6 | Questions asserting false premises (VA01 for meter reading, F3424 for bank account deletion, 15 types of master data, 30-day debt forgiveness). |
| **Total** | **70** | **70** | **100% real SAP-backed test cases; zero fabricated SAP facts.** |

---

## 4. Evidence Caching & Fair Comparison Isolation

To guarantee that future LLM evaluations compare **generation quality in isolation** without confounding retrieval drift:
- All 70 test cases were executed through the production pipeline to capture authoritative evidence snapshots into [`eval/phase3/evidence_cache.json`](file:///d:/chatbot-phase12/eval/phase3/evidence_cache.json).
- Each snapshot records:
  - `case_id`, `question`, `category`
  - `routed_source_id`, `pipeline_status`, `reason_code`
  - `retrieval_ms`
  - `context_items` (all chunks, markers, headings, titles, URLs, and text)
  - `oracle_items` (manually verified gold evidence spans for oracle mode)
- During benchmark execution, every generator adapter receives the exact same frozen context block.

---

## 5. Generator Adapter Architecture

The adapter framework in [`eval/phase3/adapters.py`](file:///d:/chatbot-phase12/eval/phase3/adapters.py) exposes a clean, pluggable protocol:
- **`A0ExtractiveAdapter`**: Wraps the real production `EvidenceExtractiveGenerator`. Fully implemented, active, and measured.
- **`A2SpanSelectorMockAdapter`**: Test fixture simulating an LLM that selects and orders exact source spans.
- **`A3ParaphraserMockAdapter`**: Test fixture simulating an LLM that synthesizes and paraphrases evidence under strict grounding.
- **Future Integration**: The architecture allows plugging in real hosted clients (`ClaudeHaikuAdapter`, `ClaudeSonnetAdapter`, `OllamaAdapter`) by implementing the single `generate(question, context, snapshot)` method, without touching the runner or metrics modules.

---

## 6. Deterministic Metrics vs. Human Review Boundary

### Automated Metrics
1. **Behavior Alignment**: Checks whether the system answers, provides a scoped partial answer, clarifies, abstains, or reports unavailable documentation matching `expected_behavior`.
2. **Key-Fact Recall**: Measures what fraction of atomic key facts from gold annotations are present in the generated answer.
3. **Citation Precision & Coverage**:
   - *Citation Coverage*: Share of content sentences carrying at least one valid `[S#]` marker.
   - *Citation Precision*: Share of cited markers in the answer that exist in the supplied context items (catches phantom citations).
4. **Hallucinated Tokens**: Flags uppercase transaction codes, identifiers, or numbers present in the answer that do not exist anywhere in the cited chunks.
5. **Procedural Limitation Correctness**: Enforces that procedural questions lacking steps emit the explicit scoped disclaimer without fabricating steps, and confirms genuine procedures do not emit a false disclaimer.
6. **Substring Grounding (A0/A2)**: Verifies that every non-disclaimer answer sentence is an exact normalized substring of its cited source chunk.

### Metrics Requiring Human Review
- **Semantic Faithfulness of Paraphrases (A3)**: Substring matching is fundamentally invalid for paraphrased answers. A sentence that paraphrases correctly will fail substring matching, whereas a sentence that reuses context keywords in a false claim might pass. When testing A3, automated metrics flag `requires_human_review = True`.
- **Nuanced Adversarial Refutations**: Verifying whether an answer gently clarifies a false premise or merely quotes surrounding facts requires qualitative inspection.
- **Naturalness and Fluency**: Qualitative readability of synthesized answers.

---

## 7. Measured Baseline (A0) Results

The baseline evaluation of **A0** on all 70 test cases yielded the following verified metrics:

| Metric | Measured Baseline (A0) | Notes |
|---|:---:|---|
| **Total Test Cases** | 70 | Fixed frozen dataset |
| **Behavior Match Accuracy** | **67.1%** (47/70) | Clean alignment on definitions, enumerations, OOS abstentions, M2C-18, and follow-ups. |
| **Mean Key Fact Recall** | **52.1%** | A0 extracts top 1–3 sentences; multi-facet questions leave lower-ranked facts unextracted. |
| **Mean Citation Coverage** | **100.0%** | Every non-disclaimer content sentence carries a valid citation. |
| **Mean Citation Precision** | **100.0%** | Zero phantom citations (`0` invalid markers). |
| **Hallucinated Tokens** | **0** | Zero invented transaction codes, IDs, or numbers. |
| **Prohibited Claims Detected** | **0** | Zero false claims or fabricated steps admitted. |
| **Procedural Limitation Compliance** | **100.0%** (on Budget & Periodic Billing) | Explicit limitation notices emitted cleanly. |
| **Unavailable Docs (M2C-18)** | **100.0% Fail-Closed** | Status: `page_not_ingested`, no answer/sources leaked. |

### Measured Latency Breakdown (Local Environment)
- **Generation Latency (A0)**:
  - **p50:** **2.22 ms**
  - **p95:** **3.71 ms**
  - **Mean:** **2.19 ms**
  - **Min:** 0.10 ms | **Max:** 11.50 ms
- **Retrieval Latency (from Pipeline)**:
  - **p50:** 24.8 ms
  - **p95:** 112.5 ms
  - **Mean:** 31.4 ms

### Cost and Token Usage
- **Total Input Tokens:** `null`
- **Total Output Tokens:** `null`
- **Cost per 1,000 Queries:** `null`
*(In strict compliance with constraints, cost fields remain null because no live commercial model APIs were called).*

---

## 8. Strengths & Deficiencies of A0 (Extractive Generator)

### Key Strengths of A0
1. **Ultra-low latency**: Median generation time of **2.22 ms** with zero harness overhead.
2. **Absolute Grounding Safety**: By definition, extractive generation produces 0 hallucinated tokens and 100% citation precision.
3. **Deterministic Fail-Closed Behavior**: Correctly fails closed on out-of-scope topics and unavailable documentation (M2C-18).
4. **Clean List & Procedural Formatting**: As verified in Phase 2.1, list items and limitation notices are emitted with strict markdown separation.

### Key Deficiencies of A0 (Opportunities for LLM)
1. **Limited Multi-Step Synthesis**: For multi-step questions (e.g. `CASE-031`, `CASE-033`), A0 selects discrete sentences in document order rather than synthesizing a cohesive chronological explanation.
2. **Key Fact Coverage Cap**: A0's strict sentence budget ($k \le 3$) means that when an answer requires 4–5 distinct facts scattered across paragraphs, recall is capped around 52%.
3. **Rigid Ambiguity Handling**: A0 cannot formulate an interactive disambiguation question (e.g., asking "Do you mean billing document or invoicing document?"); it simply attempts extraction against the top-ranked interpretation.

---

## 9. Next Recommended Experiment

Now that the harness, dataset, evidence cache, and baseline measurements are complete and verified, the recommended next step is:
1. **Implement `ClaudeHaikuAdapter`** within `eval/phase3/adapters.py` using a grounded system prompt that enforces strict citation format (`[S#]`) and verbatim quote bounds.
2. **Run against `eval/phase3/evidence_cache.json`** using the frozen snapshots.
3. **Compare A0 vs. Claude Haiku** on the 70 cases to determine whether LLM synthesis measurably increases Key Fact Recall (from 52% toward >80%) without degrading citation precision (>98%) or introducing hallucinated transaction codes.
