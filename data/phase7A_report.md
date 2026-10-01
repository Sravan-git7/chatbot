# Phase 7A report - pure M2C routing foundation

Scope: Phase 7A only. The architecture decision from Phase 6 is applied: **M2C card retrieval is a routing / topic-identification stage; it does not replace the SAP-page retriever.** Nothing in 7B-7G was implemented; there is no page ingestion, no answer generation, no LLM call, no `rag_chat.py` integration, no CLI mode, no commit and no push.

## 1. Checkpoint

Full record: `data/phase7_checkpoint.md` (taken before any 7A file was written).

* HEAD `d85c31e0594b472e852ea9e06e32e6eba7138747` on `arena/01a0ed60-chatbot`; no commits since.
* 9 tracked files modified vs HEAD (`.gitignore`, `data/retrieval_results.json`, `scripts/audit_corpus.py`, `chunk_pages.py`, `clean_sap_pages.py`, `create_embeddings.py`, `evaluate_retrieval.py`, `rag_chat.py`, `retrieve.py`); 72 untracked entries, which include everything from Phases 1-6.
* `scripts/rag_core.py` is untracked but required by four of the modified scripts. `scripts/audit_corpus.py` differs completely from HEAD (Phase 0 PDF audit replaced by a page-corpus audit) and is potentially conflicting. No ownership of any change is asserted.
* Baseline test result at checkpoint: **253 passed, 7 skipped, 0 failed.** The 7 skips are the store-dependent tests (`tests/test_card_retrieval_eval.py` lines 148, 158, 172, 186, 238 and `tests/test_phase5.py` lines 376, 387); `data/vector_store/` is absent and was not rebuilt.
* The checkpoint records the SHA-256 of 222 protected files (29 PDFs, Phase 1-5 data, scripts and tests, legacy app files, the local page corpus, Phase 6 documents). `tests/test_phase7a.py::ProtectedArtifactTests` verifies them.

**Environment disclosure.** The test virtual environment (`/tmp/av`) did not survive between sessions, so it was recreated from PyPI (`pytest pypdf beautifulsoup4 requests numpy chromadb sentence-transformers gt-all-minilm-l6-v2`). That is the only network access of this phase: package downloads for test tooling. No SAP request, no model/embedding run, no store build. The new modules themselves use no network (tests enforce it).

## 2. Files

### Created

| File | Role |
| --- | --- |
| `scripts/m2c_router.py` | Query -> ranked M2C card candidates, normalised metadata |
| `scripts/m2c_page_join.py` | Card -> local SAP page content resolution (read-only) |
| `scripts/m2c_orchestrator.py` | Pure flow: query -> router -> page join -> routing outcome |
| `tests/test_phase7a.py` | 45 tests |
| `data/phase7_checkpoint.md` | Checkpoint and protected-file hashes |
| `data/phase7A_report.md` | This report |

### Modified

None. No existing file was edited (`git status` shows the same 9 modified tracked files as at the checkpoint; all 222 recorded hashes still match).

## 3. Routing interface (`scripts/m2c_router.py`)

```python
route(query: str, backend: CardBackend, top_k: int = 5) -> RouterResult
RouterResult(query, top_k, distance_metric, candidates: tuple[CardCandidate, ...])
CardCandidate(rank, source_id, title, category, source_url, source_status, source_url_status,
              has_source_correction, citation, distance, distance_metric,
              retrieval_unit_id, source_number, filename, sha256, corpus_document, page_start, page_end)
```

* **`source_url` is canonical.** There is no `url` attribute or key. A record that has only the legacy `url` key is rejected with `CardMetadataError`; it is never aliased. (No alias is exposed, so there is no second field to document.)
* **Strict normalisation.** The eight contract keys (`source_id`, `title`, `category`, `source_url`, `source_status`, `source_url_status`, `has_source_correction`, `citation`) must be present. Missing keys, a non-boolean correction flag, a non-finite/non-numeric distance, a Chroma id different from `source_id`, or a wrongly shaped result raise `CardMetadataError`. Provenance keys (`filename`, `sha256`, ...) pass through and are `None` when absent.
* **Order is the backend's order.** Nothing is re-sorted or filtered; `rank` is the 1-based position. `top_k` must be an integer >= 1.
* **No threshold.** The legacy `MAX_DISTANCE = 1.0` is not used and not referenced in code (an AST test checks this). Far candidates are returned with their distance. A cut-off is a caller-side `selector` passed to the orchestrator.
* **Distance.** `distance` is the collection's cosine distance (`1 - cosine`), carried with `distance_metric = "cosine"`. A backend that does not declare `cosine` is refused, so a squared-L2 (legacy) store cannot be used by mistake.
* **Empty / whitespace query** returns no candidates and does not query the backend.
* **Default backend `ChromaCardBackend`** (lazy imports; nothing heavy at import): opens `data/vector_store/` collection `sap_m2c_card_v1` read-only in use (no add/upsert/delete), refuses `sap_docs` and any `chroma_db` directory, never creates a store (missing directory/database -> `CardStoreUnavailable`), checks the collection reports `hnsw:space = cosine`, and embeds with an injectable embedder (default: local `all-MiniLM-L6-v2` via `m2c_common.resolve_model`, normalised). Failures raise typed exceptions (`CardStoreUnavailable`, `RouterConfigError`, `CardMetadataError`); nothing is swallowed.

## 4. Page-join states (`scripts/m2c_page_join.py`)

Evidence for "local page content": a processed page record `data/sap_help/pages/<guide_id>/<page_id>.json` with `status == "OK"`, matching guide id and page id (both parsed from the card's `source_url`), and non-empty text. Not treated as content: the URL itself, `captured_responses/` (raw captures), the legacy `chunks.json`/`sap_docs`. A guide id is never inferred from a numeric deliverable id, and no title matching is done.

| State | Meaning | `card_exists` / `url_exists` / `local_page_content` |
| --- | --- | --- |
| `resolved_page` | valid local page record exists for the card's guide + page | true / true / true |
| `url_only` | card and parseable SAP Help URL, but no usable local record (`NO_LOCAL_PAGE_RECORD`, or `LOCAL_PAGE_RECORD_NOT_USABLE` when a record exists but is failed/empty) | true / true / false |
| `unresolved` | no card (`CARD_MISSING`), no URL (`NO_SOURCE_URL`), or a string that is not a recognised SAP Help page URL (`URL_NOT_A_SAP_HELP_PAGE_URL`, e.g. a numeric-deliverable URL) | see reason |

Applied to the 29 real cards against the repository as it is today (read-only): **1 `resolved_page` (M2C-17, 2683 characters, `data/sap_help/pages/e52c8ee6.../0bfcc5536a51204be10000000a174cb4.json`) and 28 `url_only` (`NO_LOCAL_PAGE_RECORD`); 0 `unresolved`.** All 29 card URLs parse, including the two with a `?version=2025.001` suffix (M2C-18, M2C-23), which is kept on `source_url` unmodified. A test recomputes this from the files on disk instead of hard-coding it.

## 5. Orchestrator (`scripts/m2c_orchestrator.py`)

`route_to_page(query, backend, page_index, top_k=5, selector=select_top_ranked) -> RoutingOutcome` with `query`, `state`, `candidates`, `selected_card`, `resolution`, `source_url`, `page_content_available`, `fallback_reason`, `distance_metric`. States: `resolved_page`, `url_only`, `unresolved`, `no_card_candidate` (no additional states). `no_card_candidate` carries `fallback_reason` `EMPTY_QUERY`, `NO_CARD_CANDIDATES_RETURNED` or `SELECTOR_REJECTED_ALL_CANDIDATES`. The default selector takes rank 1; that is a statement of rank, not of confidence. A backend failure (for example a missing store) raises; it is not reported as `no_card_candidate`. The module imports no LLM, network, legacy-pipeline or third-party package, and produces no answer.

## 6. Tests added (`tests/test_phase7a.py`, 45 tests)

| Requested area | Tests |
| --- | --- |
| 1 Router returns normalised metadata | `test_returns_normalised_metadata`, `test_real_card_metadata_shape_from_units_is_accepted` (all 29 real cards, metadata built by `build_card_collection.metadata_for`), `test_malformed_records_fail_loudly` |
| 2 `source_url` preserved | `test_source_url_is_preserved_unmodified` (includes `?version=` and lower-case product URLs) |
| 3 Legacy `url` not assumed | `test_legacy_url_key_is_not_assumed` (legacy-only record rejected; no `url` attribute or key) |
| 4 No legacy `MAX_DISTANCE` | `test_no_legacy_max_distance_is_applied` (distances up to 1.99 returned; AST check) |
| 5 Ranking preserved | `test_ranking_order_is_preserved`, `test_top_k_limits_and_is_validated` |
| 6 URL-only vs local content | `test_url_only_is_not_local_content`, `test_resolved_page_when_valid_local_record_exists`, `test_real_repository_state_is_reported_as_it_is` |
| 7 Missing content not resolved | `test_missing_content_is_never_resolved` (wrong guide, failed record, empty text), `test_unresolved_states` |
| 8 No LLM | `test_no_llm_network_or_legacy_imports_anywhere_in_the_new_modules`, subprocess test asserting `ollama`, `chromadb`, `sentence_transformers`, `torch`, `numpy` and the legacy modules are not loaded after a full orchestration |
| 9 Legacy retrieval unmodified | `test_orchestrator_does_not_modify_legacy_retrieval` (hashes before/after; legacy files do not mention the new modules) |
| 10 No network | subprocess and in-process tests that make `socket.connect`/`getaddrinfo` raise, and an import ban (`requests`, `urllib.request`, `http.client`, `socket`, ...) |
| 11 Deterministic | `test_deterministic_with_mocked_data` |
| 12 Protected artefacts | `ProtectedArtifactTests` (222 checkpoint hashes; required set present; no card store created) |
| Also | ChromaDB round trip on a throw-away collection in a temp directory (real Chroma result shape, cosine distance values, clamping, refusal of a squared-L2 collection, missing collection, read-only check); default backend refusals and "never creates a store"; selector-only cut-off; four-state coverage |

The throw-away collection uses hand-made 3-d vectors; it is not the card collection and does not replace the skipped store tests.

## 7. Complete test result

`PYTHONDONTWRITEBYTECODE=1 /tmp/av/bin/python -m pytest tests -q -p no:cacheprovider -rs`

**298 passed, 7 skipped, 0 failed** (253 + 45 new; the seven skips are the same store-dependent tests as at the checkpoint and were not rebuilt). After the run: `data/vector_store/` and `chroma_db/` are still absent, no `__pycache__` was left, and all checkpoint hashes still match.

## 8. Not verified / unresolved ambiguity

1. **The default backend has not been run against the real `sap_m2c_card_v1` store or the real embedding model** (the store is absent and must not be rebuilt in this phase). Verified instead: the Chroma result shape and cosine distances on a throw-away collection; the build script's source (it creates the collection with `hnsw:space = cosine`); injectable embedder paths. The store-gated check that the router reproduces the stored Phase 4/5 rankings belongs to a later step after the store is rebuilt.
2. **Which page content counts.** The join counts only `data/sap_help/pages/`. Two other local sources were deliberately not counted: `captured_responses/` (seven raw captures; `data/captured_url_mapping.md` accepts five as page bodies for topics 2, 7, 11, 14, 24 but they are unprocessed HTML) and the legacy `chunks.json` (one guide; its only card-linked page is M2C-17, which is also the one `resolved_page`). If a later phase ingests the captures, the join will pick them up only via the same page-record format.
3. **Recorded corpus state vs disk.** `data/final_corpus_manifest.json` records 1 of 29 topics resolved and six guides without a TOC, but `data/toc/` holds five saved TOCs. The join does not use that manifest; it reports what page records exist. Reconciling the manifest is part of the corpus work, not of 7A.
4. **`unresolved` does not occur in today's data** (every card has a parseable URL); it is covered by tests only.
5. **`selected_card` is rank-1 by default.** That is not a relevance claim. There is no calibrated confidence threshold for cards (Phase 6, section C.4), and out-of-domain card queries still do not exist.
6. **Opening a Chroma store in place** may update its bookkeeping files (seen earlier); the router never writes vectors, but file hashes of a store are not a valid identity check.
7. **Checkpoint hashes describe the working tree**, not a commit. They are a change detector: a legitimate later edit of a protected file will make `ProtectedArtifactTests` fail until the checkpoint is regenerated deliberately. The untracked state (Phase 6 audit, section 2) is still unrecorded in git; that decision remains with the user (Phase 7 step 0.1).
8. **`audit_corpus.py` naming conflict** remains as documented; untouched.

## 9. Stop point

Phase 7A is complete and stopped here. Not started: 7B (availability table and any wider join), 7C (answer orchestrator/modes), 7D-7G, the `--mode` CLI switch, SAP page ingestion, answer generation, commits and pushes.
