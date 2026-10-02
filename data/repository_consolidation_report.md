# Repository consolidation report (checkpoint before Phase 7D)

Task: a Git recovery point only. No feature work, no Phase 7D, no network, no embedding or vector-store rebuild, no push. Nothing protected was edited; no test or implementation file was changed to get a green result.

## 1. Git state before consolidation

* Branch `arena/01a0ed60-chatbot`; HEAD `d85c31e0594b472e852ea9e06e32e6eba7138747` (grafted single commit "Baseline SAP RAG pipeline and retrieval evaluation", identical to `origin/main`). `git log --all` shows no other commit.
* 9 tracked files modified, 215 untracked files (none ignored except `data/vector_store/` and `chroma_db/`, which do not exist here).
* Remote `origin` = `https://github.com/Sravan-git7/chatbot.git` (unchanged; not contacted).

## 2. What was inspected

`git status --short`, `git diff --stat`, `git diff` (all nine), `git ls-files --others --exclude-standard`, `git log --oneline --decorate --all`, `git diff --check` (clean), `git show HEAD:<path>` for the replaced scripts; `data/phase6_repository_audit.md`, `data/phase7_checkpoint.md` (222 pinned hashes), `data/phase7A_report.md`, `data/phase7B_report.md`, `data/phase7C_report.md`; the imports of every modified script; a scan of all untracked files for secrets and machine paths; which untracked files are pinned by the checkpoint; and a scratch-copy experiment (section 5).

## 3. Classification

Classes: **A** = Phase work to preserve; **B** = required supporting files; **C** = pre-existing / ambiguous changes; **D** = generated / runtime artefacts (not committed).

### A. Page-ingestion / topic-resolution pipeline and its data (listed as such in the Phase 7 checkpoint) (78 files)

`captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json`, `captured_responses/1_40374657_8990d0533f8e4308e10000000a174cb4.json`, `captured_responses/2_40374682_8082ce53118d4308e10000000a174cb4.json`, `captured_responses/3_40374657_4d76765c1e012b8ae10000000a42189b.json`, `captured_responses/4_40404052_147bce53118d4308e10000000a174cb4.json`, `captured_responses/5_40374633_cc7bce53118d4308e10000000a174cb4.json`, `captured_responses/6_40374790_790dc5536a51204be10000000a174cb4.json`, `captured_responses/_malformed_originals/1_40374657_8990d0533f8e4308e10000000a174cb4.json`, `captured_responses/_malformed_originals/1_40374657_8990d0533f8e4308e10000000a174cb4.json.repair.json`, `captured_responses/summary.json`, `data/captured_pagecontent_urls.txt`, `data/captured_url_mapping.json`, `data/captured_url_mapping.md`, `data/corpus_audit.json`, `data/corpus_audit.md`, `data/corpus_manifest.json`, `data/corpus_manifest.md`, `data/final_corpus_manifest.json`, `data/final_corpus_manifest.md`, `data/forensics/card_mapping_investigation_18_5.md`, `data/forensics/findings.md`, `data/forensics/local_forensics.json`, `data/forensics/pdf_deep_inspection.json`, `data/guide_registrations.json`, `data/guide_registry.json`, `data/ingest_config.json`, `data/ingest_plan.json`, `data/ingest_plan_page_and_descendants.json`, `data/ingest_plan_page_only.json`, `data/sap_help/CORPUS.json`, `data/sap_help/audit.json`, `data/sap_help/audit.md`, `data/sap_help/chunks/chunks.jsonl`, `data/sap_help/chunks/embedding_input.jsonl`, `data/sap_help/comparison_with_legacy.json`, `data/sap_help/comparison_with_legacy.md`, `data/sap_help/corpus_stats.json`, `data/sap_help/logs/build.jsonl`, `data/sap_help/pages/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.json`, `data/sap_help/raw/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.json`, `data/toc/2ac7fe29a0c94cdd88fb80c2cb9f7758.json`, `data/toc/9442486404b54071b4ebeab6a16628e7.json`, `data/toc/a003b275c98148ee8a4c3fafe9588fe3.json`, `data/toc/ed84b70c199d4470ae2e5ccb93b2e45b.json`, `data/toc/f4a255a5de524e3992155767996fb1fd.json`, `data/topic_manifest.json`, `data/topic_resolution.json`, `sap_resolver/__init__.py`, `sap_resolver/chunk.py`, `sap_resolver/clean.py`, `sap_resolver/corrections.py`, `sap_resolver/dedupe.py`, `sap_resolver/events.py`, `sap_resolver/fetch.py`, `sap_resolver/intake.py`, `sap_resolver/pdf_cards.py`, `sap_resolver/pipeline.py`, `sap_resolver/plan.py`, `sap_resolver/registry.py`, `sap_resolver/repair.py`, `sap_resolver/resolver.py`, `sap_resolver/schema.py`, `sap_resolver/toc.py`, `sap_resolver/urls.py`, `scripts/build_corpus.py`, `scripts/capture_responses.py`, `scripts/compare_with_legacy.py`, `scripts/corpus_audit.py`, `scripts/forensic_search.py`, `scripts/guide_intake.py`, `scripts/inspect_pdf_cards.py`, `scripts/repair_captured_response.py`, `scripts/resolve_topics.py`, `tests/__init__.py`, `tests/test_corpus_pipeline.py`, `tests/test_corrections.py`, `tests/test_repair_response.py`, `tests/test_sap_resolver.py`

### A. Phase 4 - retrieval units, card collection, evaluation (19 files)

`data/card_collection_manifest.json`, `data/evaluation/card_retrieval_failure_analysis.md`, `data/evaluation/card_retrieval_questions.json`, `data/evaluation/card_retrieval_results.json`, `data/evaluation/independent_queries.json`, `data/evaluation/phase5_failure_analysis.md`, `data/evaluation/phase5_results.json`, `data/retrieval_phase4_report.md`, `data/retrieval_token_stats.json`, `data/retrieval_units.json`, `scripts/build_card_collection.py`, `scripts/build_card_eval_questions.py`, `scripts/build_phase4_report.py`, `scripts/build_retrieval_units.py`, `scripts/evaluate_card_retrieval.py`, `scripts/m2c_common.py`, `scripts/validate_token_lengths.py`, `tests/test_card_retrieval_eval.py`, `tests/test_retrieval_units.py`

### A. Phase 3 - chunk candidates (6 files)

`data/chunk_candidates/bounded_sections.json`, `data/chunk_candidates/chunk_candidate_report.md`, `data/chunk_candidates/section_based.json`, `data/chunk_candidates/whole_document.json`, `scripts/build_chunk_candidates.py`, `tests/test_chunk_candidates.py`

### A. Phase 7C - card -> page identity (6 files)

`data/m2c_page_identity.json`, `data/m2c_page_identity_report.md`, `data/m2c_page_identity_rules.md`, `data/phase7C_report.md`, `scripts/m2c_page_identity.py`, `tests/test_phase7c.py`

### A. Phase 6 - audit / integration map / spec (3 files)

`data/phase6_next_phase_spec.md`, `data/phase6_repository_audit.md`, `data/phase6_retrieval_integration_map.md`

### A. Phase 7A - router, join, orchestrator (5 files)

`data/phase7A_report.md`, `scripts/m2c_orchestrator.py`, `scripts/m2c_page_join.py`, `scripts/m2c_router.py`, `tests/test_phase7a.py`

### A. Phase 7B - real-store validation (5 files)

`data/phase7B_rebuilt_manifest.json`, `data/phase7B_report.md`, `data/phase7B_validation.json`, `scripts/phase7b_validate.py`, `tests/test_phase7b.py`

### A. Phase 7 checkpoint (1 files)

`data/phase7_checkpoint.md`

### A. Phase 5 - independent evaluation (6 files)

`data/retrieval_phase5_report.md`, `scripts/build_independent_queries.py`, `scripts/build_phase5_report.py`, `scripts/evaluate_phase5.py`, `scripts/phase5_retrievers.py`, `tests/test_phase5.py`

### A. Phase 2 - source corpus and corrections (6 files)

`data/source_corpus.json`, `data/source_corpus.md`, `data/source_corpus_validation_report.md`, `data/topic_corrections.json`, `scripts/build_source_corpus.py`, `tests/test_source_corpus.py`

### A. Phase 1 - source manifest (6 files)

`data/source_inventory.md`, `data/source_manifest.csv`, `data/source_manifest.json`, `data/source_validation_report.md`, `scripts/build_source_manifest.py`, `tests/test_source_manifest.py`

### B. Required supporting files (legacy-app refactor companions) (6 files)

`README.md`, `data/answer_quality_questions.json`, `data/retrieval_results_improved.json`, `requirements.txt`, `scripts/evaluate_answers.py`, `scripts/rag_core.py`

### D. Generated runtime logs / offline e2e outputs (excluded) (68 files)

Not staged. They stay untracked on disk, untouched.

* `data/logs/corpus_audit.jsonl`, `data/logs/resolution.jsonl`: timestamped event logs of earlier pipeline runs (the resolution log still records the pre-TOC state `GUIDE_UNRESOLVED`); not pinned by the checkpoint; no test reads them.
* `data/sap_help_e2e/**` (66 files, 681 KB): outputs of the offline end-to-end runs documented in `README.md` (`python scripts/build_corpus.py --offline --scope ... --out-dir data/sap_help_e2e/...`); regenerable; not pinned; no test reads them (the tests use temporary directories).

### C. Pre-existing / ambiguous changes (9 tracked files)

See section 4. Their *content* and purpose are fully established; their *author* is not (single grafted commit, no reflog, no phase report claims them as its own work).

### Runtime / environment artefacts outside the tree (never staged)

`/tmp/av` (test virtual environment, recreated by `pip install` of pytest, pypdf, beautifulsoup4, requests, numpy, chromadb 1.5.9, sentence-transformers 6.1.0, gt-all-minilm-l6-v2 0.1.0 from PyPI; test tooling only), `/tmp/pip*.log`, `/tmp/p7b_*`, `/tmp/cons/*`, `/tmp/exp` (deleted). No `__pycache__`, `.venv`, `.env`, `chroma_db/`, `data/vector_store/` or model cache exists inside the repository.

## 4. The nine modified tracked files

Each row: current diff vs HEAD; whether a phase report says the change is intentional; test dependence; required for the current working state; recommendation.

| File | Diff vs HEAD | Phase report says | Tests depend on it | Required | Recommendation |
| --- | --- | --- | --- | --- | --- |
| `scripts/rag_chat.py` | 462 -> 86 lines: import-time chat script replaced by a CLI over `rag_core` (same prompt text; default strategy `improved`; Ollama `temperature 0, seed 42`) | Phase 6 audit: intentional refactor (docstring states why) | Hash pinned in the Phase 7 checkpoint (tests `test_phase7a::ProtectedArtifactTests::test_checkpoint_hashes_still_match`, `test_phase7b::SafetyTests::test_checkpoint_protected_set_is_unchanged`); 7A/7B also assert it is not imported by the M2C modules | Needs `rag_core.py` (class B) | Preserve (commit with `rag_core.py`) |
| `scripts/retrieve.py` | 162 -> 49 lines: CLI over `rag_core.search`; corrects the distance wording (squared L2) | Phase 6: intentional refactor | Checkpoint hash pin | Needs `rag_core.py` | Preserve |
| `scripts/evaluate_retrieval.py` | 243 -> 278 lines: uses `rag_core` strategies; original loose metric kept; adds strict match, MRR, repeated-document count, URLs | Phase 6: intentional; default strategy `baseline` reproduces the original numbers | Checkpoint hash pin | Needs `rag_core.py` | Preserve |
| `scripts/create_embeddings.py` | +23/-6 lines: imports constants from `rag_core`; paths anchored to the repo root; input-exists check; docstring on squared-L2 | Phase 6: intentional (path robustness, single config source) | Checkpoint hash pin | Needs `rag_core.py` | Preserve |
| `scripts/chunk_pages.py` | two path constants anchored to `REPO_ROOT` (logic unchanged) | Phase 6: intentional, unrelated to the card work | Checkpoint hash pin | No | Preserve |
| `scripts/clean_sap_pages.py` | two path constants anchored to `REPO_ROOT` (logic unchanged) | Phase 6: intentional, unrelated to the card work | Checkpoint hash pin | No | Preserve |
| `scripts/audit_corpus.py` | 667 -> 150 lines: the Phase 0 PDF audit was replaced in place by the post-build audit of `data/sap_help` (the old one is recoverable with `git show d85c31e:scripts/audit_corpus.py`) | Phase 6 / checkpoint / 7A: documented as potentially conflicting; "do not revert" | **Yes, functionally**: `tests/test_corpus_pipeline.py::RealTopic17EndToEnd::test_audit_script_reports_incomplete_corpus_and_clean_pages` executes the working-tree version; also checkpoint hash pin | Yes (tests) | Preserve; the naming conflict stays open (see section 13) |
| `.gitignore` | removes two pasted PowerShell lines (`@"` ... `"@ | Out-File ...`) that corrupted HEAD's file; adds `data/vector_store/` | Phase 4: the `vector_store` block is intentional; the cleanup's origin is not attributable | Checkpoint hash pin; it keeps the Phase 4/7B store out of Git | Yes (prevents committing a Chroma store) | Preserve |
| `data/retrieval_results.json` | regenerated legacy baseline output: identical `retrieved_titles` and `match_ranks` for all 30 questions; adds `retrieved_urls`, `strict_match_ranks`, `distinct_documents` | Phase 6: generated by the modified `evaluate_retrieval.py` against the user's live `chroma_db`; cannot be regenerated here | Checkpoint hash pin | No (legacy baseline record) | Preserve |

**Decision.** All nine are committed, none is reverted, edited or left behind, because (1) the content of every diff was read in full and is non-destructive and recoverable from the parent commit `d85c31e`; (2) all nine are pinned by the committed Phase 7 checkpoint tests; (3) `audit_corpus.py` is functionally required. Evidence: in a scratch copy of the working tree with these nine files reset to HEAD, the suite gave `3 failed, 351 passed, 24 skipped` (the audit test and the two checkpoint-hash tests); the real tree gives 0 failures. Leaving them out would therefore make the committed tree fail its own tests. **Their authorship remains unknown**; committing them records their current content, not a claim about who wrote them. If you decide any of them should not be kept, `git checkout d85c31e -- <file>` restores the original, but the checkpoint pins must then be revised knowingly.

## 5. Protected artefacts

The 29 PDFs (tracked, unmodified), `data/source_manifest.json`, `data/source_corpus.json`, `data/chunk_candidates/*`, `data/retrieval_units.json`, `data/retrieval_token_stats.json`, `data/card_collection_manifest.json`, `data/evaluation/*`, the Phase 4/5 reports, `data/topic_manifest.json`, `data/topic_corrections.json`, the 5 saved TOCs, the existing captured responses and the local page JSON were not touched. The 222 checkpoint hashes all match (enforced by two tests that pass). The checkpoint was not regenerated. No embedding or vector-store rebuild, no network operation.

Review findings on content being committed (not changed): no credentials, tokens, `.env` or virtual environments. Machine-specific path: `data/card_collection_manifest.json` (line 11), `data/retrieval_token_stats.json` (line 322) and `data/phase7B_rebuilt_manifest.json` (line 11) record the sandbox model directory `/tmp/av/lib/python3.11/site-packages/gt_all_minilm_l6_v2/model` as build provenance. It is not a secret; the first two are protected, hash-pinned Phase 4 artefacts and were left as they are. Treat that `directory` value as sandbox-specific.

## 6. Staging boundary

Explicit staging only (no `git add .`): every class A and B file, the nine class C files, and this report. Excluded: class D (68 files). The exact staged list is in `git show --stat HEAD`.

## 7. Test result before commit

`/tmp/av/bin/python -m pytest tests -q`: **354 passed, 24 skipped, 0 failed** (verified in this task, not assumed). The 24 skips are the tests that need the card vector store or model (17 in `test_phase7b.py`, 5 in `test_card_retrieval_eval.py`, 2 in `test_phase5.py`); `data/vector_store/` does not exist and rebuilding it is forbidden here. `git diff --check`: clean.

## 8-12. Commit, post-commit result, final status, push, Phase 7D

Filled in after the commit (this text is the only change made to the report after it was committed, so the working-tree copy of this file differs from the committed copy by this addendum; it is deliberately left uncommitted to keep a single consolidation commit).

1. **Git HEAD before consolidation:** `d85c31e0594b472e852ea9e06e32e6eba7138747`.
2. **Commit:** `a4182ffa4f3bd9d7d3fc5846a187b258ccf11444` ("Consolidate RAG pipeline through Phase 7C"), parent `d85c31e`, branch `arena/01a0ed60-chatbot`. 157 files changed: 148 added, 9 modified (156,716 insertions, 1,609 deletions).
3. **Files classified as Phase work (A):** 141 untracked files plus this report, in the groups of section 3.
4. **Required supporting files (B):** 6 (`scripts/rag_core.py`, `scripts/evaluate_answers.py`, `data/answer_quality_questions.json`, `data/retrieval_results_improved.json`, `README.md`, `requirements.txt`).
5. **Ambiguous (C):** the nine modified tracked files of section 4, committed unchanged because they are checkpoint-pinned and `audit_corpus.py` is functionally required; authorship unknown.
6. **Excluded (D):** `data/logs/` (2 files) and `data/sap_help_e2e/` (66 files), still untracked on disk; plus the environment artefacts under `/tmp`.
7. **Test result before commit:** 354 passed, 24 skipped, 0 failed.
8. **Test result after commit:** working tree 354 passed, 24 skipped, 0 failed; and, to prove the committed tree alone is sufficient, `git archive HEAD` extracted to a clean directory (so without the excluded files and without any store): 354 passed, 24 skipped, 0 failed.
9. **Final `git status --short`** (before this addendum was written): `?? data/logs/` and `?? data/sap_help_e2e/` only. With this addendum: additionally ` M data/repository_consolidation_report.md`.
10. **Not pushed.** No `git push`, no PR, no remote change, no GitHub operation; `origin/main` is still `d85c31e`.
11. **Phase 7D was not started.** No feature work, network access, embedding or vector-store rebuild was done.
12. `git diff --cached --check` reported only "new blank line at EOF" on four generated markdown files (`data/m2c_page_identity_report.md`, `data/source_corpus.md`, `data/source_inventory.md`, `data/source_validation_report.md`). They were committed byte-for-byte because three of them are checkpoint-pinned and the fourth is compared by a test against regenerated output.


## 13. Open points carried forward (not acted on)

* The authorship of the nine class C changes is unknown; they are committed as found.
* `scripts/audit_corpus.py` replaced the Phase 0 PDF audit in place; `audit_out/*` can no longer be regenerated under that name. Decide later whether to restore the old tool under another name.
* `data/guide_registry.json` and `data/final_corpus_manifest.*` are stale relative to the registrations and saved TOCs (documented in the 7C report).
* Class D files remain untracked on disk and are regenerable; no `.gitignore` entry was added because `.gitignore` is checkpoint-pinned.
* The card vector store is absent; 24 tests skip until it is rebuilt with `scripts/build_card_collection.py`.
