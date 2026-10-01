# Phase 7B report - the real card collection and the real model through the Phase 7A router

Scope: validation only. No production integration: `rag_chat.py`, the legacy retriever and every protected artefact are untouched; no SAP page was ingested; no answer was generated; no LLM, hybrid retrieval, threshold, re-ranking or CLI mode was introduced; nothing was committed or pushed.

**Headline answers**

* **The real router reproduced the Phase 4 rankings: yes.** 50 of 50 questions: identical top-1, identical top-5 ordering, identical first-expected-rank, identical 4-decimal similarities.
* **The real router reproduced the Phase 5 rankings: yes.** 54 of 54 queries: the same four identities.
* Full test suite: **330 passed, 0 skipped, 0 failed** (the seven store-dependent tests that were skipped in 7A ran and passed).

All figures below come from `data/phase7B_validation.json` (deterministic output of `scripts/phase7b_validate.py`) or from the test run.

## 1. Collection rebuild result

1. **Preflight (before any rebuild): 23 of 23 checks OK**, so nothing had to stop the rebuild. The checks tie together: the units file sha256 (`f5e9b908...`), the token statistics, the source corpus sha256 (`0ee5cb8b...`) and content fingerprint, the recorded manifest (whose sha256 `5b3a5c30...` is the one stored in the Phase 4 results), the Phase 4 questions file, the builder's constants (collection, space, model, batch size), the 17-key metadata schema, the token statistics PASS, the local model files and the `chromadb` version (1.5.9, equal to the manifest).
2. **Rebuild:** `python scripts/build_card_collection.py --manifest /tmp/p7b_built_manifest.json` (no flags that change parameters, default units, default `data/vector_store/`, collection `sap_m2c_card_v1`). The builder was pointed at a temporary manifest path **so that the protected `data/card_collection_manifest.json` was not overwritten**; its sha256 is unchanged (`5b3a5c30...`). Result: 29 vectors, 384 dimensions, model `all-MiniLM-L6-v2`.
3. **Rebuilt manifest vs recorded manifest:** identical in every field except `created_utc` (the rebuild is later). This includes the configuration, model file hashes, corpus/units/token-stats hashes and `embeddings_float32_sha256` (`0d80d10b...` equal to the recorded value). A copy of the rebuilt manifest is kept at `data/phase7B_rebuilt_manifest.json`.
4. **Second, independent rebuild** into `/tmp/p7b_store2` produced the same float32 hash and, run through the validator, the same results as the first store (the single difference is the `vector_store_dir` path field of the manifest comparison, which names the temporary directory).

## 2. Collection configuration (verified on the rebuilt store, 16 of 16 checks)

| Item | Value |
| --- | --- |
| Collections in the store | exactly one: `sap_m2c_card_v1` (`sap_docs` not present; `chroma_db/` does not exist) |
| Vectors / dimension | 29 / 384 (matrix shape (29, 384), unit-normalised) |
| Distance space | `hnsw:space = cosine` |
| Collection config vs manifest | `config_json` equals `manifest.configuration` exactly |
| Hashes in collection metadata | units file and source corpus sha256 equal to the recorded manifest |
| Ids | 29 distinct ids equal to the 29 retrieval units, each exactly once |
| Metadata | every record equals `build_card_collection.metadata_for(unit)`: complete and unmodified |
| URL field | every record has `source_url`; **no record has a `url` key** |
| Documents | every stored document equals the unit's `embedding_text` |

## 3. Model verification

* The model files are resolved locally (no download): pip package `gt-all-minilm-l6-v2` 0.1.0, a **third-party re-packaging** of `sentence-transformers/all-MiniLM-L6-v2` (the existing provenance disclosure stands).
* `model.safetensors`, `tokenizer.json`, `vocab.txt`, `config.json`, `sentence_bert_config.json`, `modules.json`: SHA-256 equal to the recorded manifest provenance (6 of 6). `max_seq_length` 256 and dimension 384 equal the manifest.
* Environment (recreated because `/tmp/av` does not persist; PyPI downloads only, versions pinned to the recorded ones): `chromadb 1.5.9`, `sentence-transformers 6.1.0`, `torch 2.14.0`, `transformers 5.17.0`, `numpy 2.4.6`, `gt-all-minilm-l6-v2 0.1.0`.

## 4. Vector count / dimension and vector values

* Stored vectors vs vectors freshly recomputed from `embedding_text` with the model: **max absolute difference 7.45e-09** (criterion from Phase 5: < 1e-6).
* The freshly recomputed float32 matrix hashes to the recorded `0d80d10b...` (equal). The hash of the vectors read back from Chroma differs from it (`cc4c68ef...`); this is the known ~1e-7 read-back effect and is why the tolerance test, not a hash, is the criterion. Raw store-directory hashes were not used anywhere.

## 5. Router validation on the real store

The router under test is the Phase 7A default `ChromaCardBackend` (real `data/vector_store/`, real model via `m2c_common.resolve_model`), unchanged from 7A. A separate reference (stored vectors, batch-encoded queries, plain NumPy) was computed only for comparison.

* Every query was routed with `top_k = 29`; 29 candidates were returned for each of the 104 queries.
* Distances are ascending for all 104 queries; rank 1 always has the minimum distance; 0 violations.
* **Distance semantics:** the router's `distance` equals the independent `1 - q.d` cosine distance (max abs diff 5.96e-07 over all 104 x 29 values), and the complete 29-card ordering equals the independent ordering for every query (0 mismatches).
* Observed distances range from 0.2751 to 1.1405 (cosine-distance range is [0, 2]).
* **No gate:** 2921 returned candidates have a cosine distance above 0.5 (that is, below the legacy-equivalent cosine 0.5 similarity) and they are all returned; the legacy `MAX_DISTANCE` is not referenced in the code (AST test) and no other cut-off exists.
* Similarity is shown only when comparing with recorded Phase 4/5 values (`1 - distance`, 4 decimals). The stored and returned quantity is the cosine **distance**; no confidence score was invented.

## 6. Phase 4 regression (50 questions, `data/evaluation/card_retrieval_results.json`)

| Comparison | Result |
| --- | --- |
| Rank-1 source identical to recorded | 50 / 50 |
| Top-5 ordering identical to recorded | 50 / 50 |
| First-expected-rank identical to recorded | 50 / 50 |
| Recorded 4-decimal similarities reproduced (`round(1 - distance, 4)`) | 250 / 250 (0 mismatches; max abs diff 4.999e-05, i.e. rounding) |
| Metrics recomputed from the router output | R@1 0.92, R@3 0.96, R@5 1.00, MRR 0.95 (equal to the recorded values) |

The four recorded misses are unchanged (Q07, Q39, Q42, Q49). No evaluation result was edited.

## 7. Phase 5 regression (54 independent queries, dense rows of `data/evaluation/phase5_results.json`)

| Comparison | Result |
| --- | --- |
| Rank-1 identical to recorded | 54 / 54 |
| Top-5 ordering identical to recorded | 54 / 54 |
| First-expected-rank identical to recorded | 54 / 54 |
| Recorded similarities reproduced | 270 / 270 (0 mismatches; max abs diff 4.932e-05, rounding) |
| Metrics recomputed from the router output | R@1 0.7222, R@3 0.7963, R@5 0.8704, MRR 0.7873 (equal to the recorded dense values) |

The router therefore did not change the underlying retrieval behaviour: 0 ranking differences in 104 queries, so no investigation or "fix" was needed. Retrieval quality was deliberately not touched (no tuning, no text or model change, no hybrid, no top-k change, no thresholds).

## 8. Metadata validation (all 29 cards)

The router preserved `source_id`, `title`, `category`, `source_url`, `source_status`, `source_url_status`, `has_source_correction`, `citation`, `rank` and `distance` for every card, plus the provenance fields (`retrieval_unit_id`, `source_number`, `filename`, `sha256`, `corpus_document`, `page_start`, `page_end`): 0 differences against the builder's metadata for all 29 cards; no `url` alias appears in any candidate.

Known source issues, as visible through the router (not resolved or altered):

| Card | `source_status` | `source_url_status` | `has_source_correction` | Note recorded in the unit |
| --- | --- | --- | --- | --- |
| M2C-05 | verified | ok | **true** | explicit correction record exists; card record unchanged |
| M2C-14 | needs_review | needs_review | false | URL product segment `sap_s4hana_on-premise` (lower case) kept as stored |
| M2C-18 | needs_review | needs_review | false | `?version=2025.001` query string kept as stored |
| M2C-23 | needs_review | needs_review | false | `?version=2025.001` query string kept as stored |

## 9. Page-join status for all 29 cards (real repository)

| State | Cards |
| --- | --- |
| `resolved_page` | **1**: M2C-17 (`data/sap_help/pages/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.json`, 2683 characters) |
| `url_only` | **28** (reason `NO_LOCAL_PAGE_RECORD`) |
| `unresolved` | 0 |

**The Phase 7A baseline (1 resolved, 28 URL-only) still holds.** The local page index has one page record. Files present but not counted as page content: 8 JSON files in `captured_responses/` (raw captured responses) and 5 saved TOC files in `data/toc/`; URLs alone are never content. The classification equals an independent derivation from the files on disk (a page record with status OK, matching guide and page id, and non-empty text).

## 10. Orchestrator validation (real collection -> real router -> real page join)

No answer, LLM, network or legacy retriever is involved (see section 11). Distances are the cosine distances of the selected card.

| # | Scenario | Query | Outcome |
| --- | --- | --- | --- |
| 1 | resolved local page | "Contract Accounts Overview" | `resolved_page`, M2C-17 at distance 0.4037, page content available; siblings M2C-18 (0.4176) and M2C-24 (0.6213) follow |
| 2 | URL only | "Move-In Process" | `url_only`, M2C-03 (0.5221), `NO_LOCAL_PAGE_RECORD`, `page_content_available = false`, source URL returned |
| 3a | source issue | "parent topic for devices and technical installations" | `url_only`, M2C-05 (0.7278), `has_source_correction = true` visible |
| 3b | source issue | "Which reference explains how billing results become invoices, print documents and postings in FI-CA?" | `url_only`, M2C-14 (0.2783), `needs_review` |
| 3c | source issue | "control role of the contract account for postings, payments and dunning" | `url_only`, M2C-18 (0.4530), `needs_review`; rank 2 is M2C-17 (0.5168), which has local page content |
| 3d | source issue | "How are source receivables redistributed into scheduled installment receivables?" | `url_only`, M2C-23 (0.4564), `needs_review`; rank 2 M2C-27 (0.4738) |
| 4a | sibling near-tie (recorded Q07) | "Installment Plan Overview" | `url_only`, M2C-24 (0.3677) vs M2C-23 (0.3701); gap 0.0024 |
| 4b | sibling near-tie (recorded Q49) | "What is needed for final billing when a customer moves out?" | M2C-02 (0.5585) vs M2C-04 (0.5665); gap 0.0080 |
| 4c | smallest gap in all 104 queries | "Which cards are in the Payments & Clearing category?" | M2C-21 (0.5075) vs M2C-20 (0.5077); **gap 0.000147** |
| 5a | short / rare term | "extrapolation" | `url_only`, M2C-09 (0.7621); the top distance is large |
| 5b | short / rare term | "subledger processing" | `url_only`, M2C-15 (0.7516); M2C-03 0.7586, M2C-04 0.7628 follow (recorded Q42: the expected card M2C-17 is not in the top 3) |
| 6a | no card | empty query | `no_card_candidate`, `EMPTY_QUERY` |
| 6b | no card (caller selector rejects all; an illustration of the hook, not a recommended policy) | "What is a contract account?" | `no_card_candidate`, `SELECTOR_REJECTED_ALL_CANDIDATES`; candidates stay visible |

**`unresolved` cannot be produced with the real cards**, because all 29 cards have a parseable SAP Help URL. It remains covered by the Phase 7A unit tests only.

**Near-ties are frequent and matter for any later use of "rank 1":** of the 104 queries, 15 have a rank-1 to rank-2 distance gap below 0.01, and in 10 of those 15 the rank-1 card is not the expected one; below 0.05 the figures are 16 of 45. Rank 1 is a statement of rank, not of confidence, and the gap is the only signal available.

## 11. Reproducibility and isolation

* **Validation run twice on the same store:** the complete output JSON is byte-identical (two runs, plus a third run after the final edit of the script): vector comparison, Phase 4 and 5 rankings, distances to 6 decimals, metadata, joins and scenarios.
* **Independent rebuild** (`/tmp/p7b_store2`): identical results; the only difference is the manifest `vector_store_dir` path (temporary directory).
* **Live reproducibility test** (`ReproducibilityTests`): runs the validator again in a fresh process and compares the router and preflight stages and the vector statistics with the recorded file.
* **Store unchanged by the router stage:** ids, metadata, documents and vectors (logical content, not file hashes) are identical before and after the 104-query run; the router never writes.
* **No network:** sockets were blocked for the whole validation and for a fresh-process orchestration test; 0 connection attempts were recorded.
* **No LLM / legacy retriever:** after a complete orchestration in a fresh process, `ollama`, `rag_core`, `rag_chat`, `retrieve`, `evaluate_retrieval`, `create_embeddings`, `requests` and `sap_resolver` are not in `sys.modules`.
* **Legacy stores:** `chroma_db/` does not exist; `sap_docs` is not in the card store; the card store is the only thing created.

## 12. Tests

`tests/test_phase7b.py`: **25 tests** (all require the rebuilt store and model except the join, safety and consistency tests; store-dependent classes skip with an explicit reason if the store is absent).

| Area | Tests |
| --- | --- |
| Collection | name and single-collection check; count, dimension, metric; configuration and hashes equal to the recorded manifest; model identity; every id once, metadata complete and unchanged, `source_url` present and no `url`, documents equal to `embedding_text`; stored vectors vs model < 1e-6; legacy stores absent |
| Router (real) | round trip, metadata normalisation and `source_url` preservation; rank ordering and cosine distance equal to an independent NumPy computation; no legacy threshold or cut-off; known source issues M2C-05/14/18/23 visible and unaltered |
| Regression | Phase 4: all 50 top-5 orderings, similarities and first ranks; Phase 5: all 54; recorded Phase 4 metrics recomputed |
| Join | all 29 cards classified by the join criteria only; URL-only is not content; captured responses and TOCs are not counted |
| Orchestrator | real collection -> router -> join chain (resolved, url-only, source issue, near-tie, empty, selector-rejected); fresh process: no LLM/legacy module, no network |
| Reproducibility | recorded validation OK; a fresh validator run reproduces router stage, preflight and vector statistics |
| Safety | the 222 checkpoint hashes (PDFs, corpus, units, token stats, manifest, chunk candidates, evaluation data, Phase 4/5 reports, legacy scripts) unchanged; Phase 4/5 input hashes consistent; the Phase 7A deliverables unchanged (hashes recorded at the start of 7B); validation script contains no collection-mutating call and no LLM/legacy import |

**Complete test result** (`PYTHONDONTWRITEBYTECODE=1 /tmp/av/bin/python -m pytest tests -q -p no:cacheprovider -rs`): **330 passed, 0 skipped, 0 failed** (298 + 25 new + the 7 previously skipped store tests, which now run and pass; the Phase 5 live reproduction test confirms the store is unchanged by the evaluation).

One of my own new tests failed on its first run: I had asserted that the maximum distance for the two weak-signal queries exceeds 1.0, but the observed maximum for them is 0.909 (the collection-wide maximum is 1.14). That was an over-claim in a new test, not a retrieval or evaluation expectation; I replaced it with the assertion that more than 20 cards with distance above 0.5 are returned (no gate). No existing test or recorded expectation was changed.

## 13. Files created

| File | Role |
| --- | --- |
| `scripts/phase7b_validate.py` | Read-only validator (stages preflight, collection, router, all) |
| `tests/test_phase7b.py` | 25 tests |
| `data/phase7B_validation.json` | Deterministic validation output (69 checks) |
| `data/phase7B_rebuilt_manifest.json` | Manifest written by the rebuild (copy of the temporary file) |
| `data/phase7B_report.md` | This report |
| `data/vector_store/` | The rebuilt card store (gitignored; generated artefact) |

## 14. Files modified

**None** of the existing files. Git still shows the same 9 modified tracked files as at the checkpoint; all 222 checkpoint hashes match; the protected manifest `data/card_collection_manifest.json` was not rewritten (the rebuild wrote its manifest elsewhere); the Phase 7A deliverables are byte-identical to their recorded hashes.

## 15. Discrepancies and unresolved issues

1. **No discrepancy was found** in the preflight, the rebuild, the collection validation or the regressions. The embedding hash even reproduced the recorded one. The rebuilt store's `created_utc` (collection metadata and temporary manifest) is later than the one in the protected manifest (`2026-09-30T14:22:20+00:00` recorded; `15:32:45+00:00` rebuilt); the protected manifest was intentionally left as is.
2. **Model provenance** is still a third-party PyPI re-packaging of the `all-MiniLM-L6-v2` weights. The Hugging Face weights themselves are not reachable from the sandbox. On the user's machine the application loads the model by name from the Hugging Face cache; equality of the two weight sets was not proven here.
3. **Environment volatility:** `/tmp/av` and the store vanish between sessions. The tests skip (with a reason) when the store or model are missing; the store has to be rebuilt on each machine (`python scripts/build_card_collection.py`, then the suite).
4. **Near-ties (section 10)** are a property of the card collection, not of the adapter; they are unchanged from Phases 4/5. Any stage that uses "the selected card" will need to carry the distance and the gap, or consider several candidates.
5. **`unresolved` and the URL-only majority:** the page stage can be exercised end-to-end for one card only (M2C-17). Scenario 3c shows the practical consequence: a query whose rank-1 card is `url_only` (M2C-18) has a rank-2 card with local content (M2C-17).
6. **Not verified:** the user's own Windows machine and the user's Hugging Face-cached model; the legacy `chroma_db` pipeline (absent); answer generation (out of scope).
7. **Untracked state unchanged:** everything from Phases 1-7 is still untracked in git (Phase 6 audit, section 2); that decision remains with the user.

## 16. Stop point

Phase 7B is complete. Phase 7C was not started: no answer orchestration, no integration with `rag_chat.py`, no CLI mode, no page ingestion, no thresholds, no hybrid retrieval.
