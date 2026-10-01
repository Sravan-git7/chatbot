# Phase 7 specification (plan only; NOT executed in Phase 6)

Inputs: `data/phase6_repository_audit.md`, `data/phase6_retrieval_integration_map.md`. This plan is derived from them. Where a decision belongs to the user it is marked **DECISION**.

## 1. Goal and boundary

Introduce `sap_m2c_card_v1` into the application **as a separate, opt-in routing stage placed in front of the existing SAP-page retriever**, never as a replacement for it:

```
question -> [legacy]  rag_core.search over sap_docs (unchanged) ............ default, always available
         -> [stage 1] card router: sap_m2c_card_v1 -> topic(s) + card provenance
         -> [join]    card -> guide id + page id -> page chunks that exist locally (if any)
         -> [stage 2] page chunks (legacy sap_docs / data/sap_help) annotated or boosted by the routed pages
         -> answer (Ollama, unchanged prompt) -> citations (page URL + card provenance)
```

Reason (see integration map, section E): a card contains a two-sentence description and a URL, not SAP page text; page text exists locally for topic 17 only (recorded), and for at most five more topics as un-ingested single-page captures.

**Consequence for scope.** The page stage cannot be end-to-end for 23 to 28 of the 29 topics until the page corpus exists. That corpus is the upstream step of the handoff chain ("correct 29-topic corpus") and is **not** part of Phase 7. Phase 7 therefore delivers the router, the join and the orchestrator so that they work correctly today (stage 1 everywhere; stage 2 where page text exists; an honest route-only response elsewhere) and will pick up new page text automatically when it is added later.

## 2. Step 0 - preconditions (no behaviour change; each item needs a decision or a check)

| # | Item | Why | Owner |
| - | ---- | --- | ----- |
| 0.1 | **DECISION:** how the current working-tree changes (9 modified, plus untracked `rag_core.py`, `evaluate_answers.py`, `README.md`, `requirements.txt`, `data/answer_quality_questions.json`, `data/retrieval_results_improved.json`) are recorded in git before Phase 7 starts (one commit on the working branch, containing `rag_core.py` together with its four importers). **The Phase 1-5 artefacts, tests and scripts are untracked too (`git ls-files` lists none of them), so the same decision covers them.** Until they are committed, `git revert` cannot restore any of them | Without that, a Phase 7 revert point does not include the legacy refactor, and the tracked importers break without the untracked module | user |
| 0.2 | **DECISION:** name for the Phase 0 PDF audit now overwritten at `scripts/audit_corpus.py` (recoverable from `HEAD`) | Remove the naming ambiguity with `scripts/corpus_audit.py`; the new `audit_corpus.py` stays | user |
| 0.3 | Rebuild `data/vector_store/` with the existing `scripts/build_card_collection.py --rebuild` on the machine that runs the application, then run the full test suite and expect **260 passed, 0 skipped** | Phase 6 measured 253 passed, 7 skipped (all seven need the store). Recorded results are the reference | agent (Phase 7) |
| 0.4 | Confirm the legacy `chroma_db/` exists on the user's machine and record the legacy baseline there: `python scripts/evaluate_retrieval.py` must reproduce the committed `data/retrieval_results.json` (titles and ranks identical, distances within 1e-6) | The legacy baseline cannot be run in the sandbox; Phase 7's "legacy unchanged" criterion needs it | user, PowerShell |
| 0.5 | Recompute and record the md5 of each protected artefact (section 4) in the Phase 7 report | Proves they were not touched | agent |
| 0.6 | Re-derive the card-to-page availability table (section 5, step 7B) from the data at Phase 7 start. Do not rely on the Phase 6 statement: the recorded manifests (1 of 29) and the files on disk (five TOCs, seven captured pages) disagree | The page corpus may have changed between phases | agent |

## 3. Design decisions, stated up front

1. **M2C stays a separate retrieval stage.** Yes. Separate module, separate collection, separate accessor, separate tests.
2. **Adapter needed?** Yes: `CardRouter` (section 5, 7A). Required because keys (`source_url` vs `url`), distance space (cosine vs squared L2), thresholds, output shape and failure behaviour all differ (integration map, sections B and C).
3. **No threshold is shipped for cards.** The legacy `MAX_DISTANCE = 1.0` (cos >= 0.5) would drop 72% of the correct independent queries' top-1 cards (15 of 54 survive) and there are no out-of-domain card queries to calibrate a refusal gate. A threshold is allowed only after an out-of-domain card query set exists (7F, acceptance criterion A9).
4. **Hard gate vs soft boost is decided by measurement, not now.** Default design is **soft**: stage 1 annotates and boosts; it never removes a legacy result and never blocks the legacy fallback. A hard gate caps recall at the card retriever's top-k recall (0.8704 at k = 5 on independent queries).
5. **No embedding or collection changes.** Phase 7 reads the card collection; it does not re-embed, re-chunk or change `embedding_text`, the model, dimensions or distance space.
6. **Default behaviour of the application does not change.** Every new capability is behind an explicit mode flag with default `legacy`.

## 4. Files

### 4.1 New files (Phase 7 creates; nothing else is added to production)

| File | Purpose |
| ---- | ------- |
| `scripts/card_router.py` | Adapter (7A): opens `sap_m2c_card_v1` through its own client; returns `CardRoute` records |
| `scripts/card_page_join.py` | Join and availability (7B): card -> guide id and page id -> page chunks that exist locally; read-only |
| `scripts/rag_two_stage.py` | Orchestrator (7C): modes `legacy` (default), `shadow`, `routed`, `route_only`; calls `rag_core` functions unchanged |
| `scripts/evaluate_two_stage.py` | Evaluation (7E/7F): router recall through the adapter, legacy regression, two-stage vs legacy on the answerable subset |
| `data/evaluation/card_out_of_domain_queries.json` | Out-of-domain / unanswerable queries for the card set (7F); human-written or explicitly disclosed as agent-written, labelled; never LLM-generated |
| `data/phase7_topic_availability.json` | Output of 7B: per topic, which page text exists and where |
| `tests/test_card_router.py`, `tests/test_card_page_join.py`, `tests/test_two_stage.py`, `tests/test_phase7_protection.py` | Tests (section 7) |
| `data/phase7_report.md` | Report, written last (builders follow the Phase 4/5 pattern: deterministic, tested) |

### 4.2 Existing files that Phase 7 may modify

**None in the first pass.** The orchestrator uses `rag_core` by import only. One optional, separately reversible follow-up (7G, **DECISION**, only after all acceptance criteria pass): a CLI switch in `scripts/rag_chat.py` (`--mode`, default `legacy`) that delegates to `rag_two_stage`. That is the only production file edit, it is a single small commit, and reverting it restores the pre-Phase-7 CLI exactly.

### 4.3 Protected (must stay byte-identical; enforced by `tests/test_phase7_protection.py`)

* The 29 PDFs, `data/source_manifest.json`, `data/source_corpus.json`, `data/chunk_candidates/*`, `data/retrieval_units.json`, `data/retrieval_token_stats.json`, `data/card_collection_manifest.json`, `data/evaluation/*` (Phase 4/5 files), `data/retrieval_phase4_report.md`, `data/retrieval_phase5_report.md`.
* The Phase 1-5 scripts and tests, `scripts/m2c_common.py`.
* `data/vector_store/` content (vector-level check, not a file hash: opening a Chroma store changes bookkeeping files).
* Legacy pipeline: `scripts/rag_core.py`, `rag_chat.py` (except 7G), `retrieve.py`, `evaluate_retrieval.py`, `create_embeddings.py`, `chunk_pages.py`, `clean_sap_pages.py`, `fetch_sap_pages.py`, `chunks.json`, `cleaned_pages.json`, `sap_pages/`, `chroma_db/`, `data/retrieval_results*.json`, `data/evaluation_questions.json`, `data/answer_quality_questions.json`.
* The page-ingestion chain: `sap_resolver/`, `scripts/build_corpus.py`, `data/sap_help/`, `data/topic_*.json`, `data/guide_registry.json`, `captured_responses/`. Phase 7 reads them and does not ingest, resolve, capture or fetch.
* `sap_docs` must not receive card or topic data; `sap_m2c_card_v1` must not be written.

## 5. Steps (each is independently testable and reversible; later steps depend only on earlier ones being present, never the reverse)

### 7A - `CardRouter` adapter (`scripts/card_router.py`)

Interface (proposed, names are a spec, not code):

* `CardRouter(vector_dir=data/vector_store, collection="sap_m2c_card_v1", embedder=None)`; `embedder` is injectable (default: the same model `rag_core` uses, resolved with `m2c_common.resolve_model`).
* `route(question: str, top_k: int = 5, min_cosine: float | None = None) -> RouteResult`.
* `RouteResult`: `status` (`ok`, `empty_query`, `store_missing`, `collection_missing`, `below_threshold`), `routes` (ordered list), `n_candidates`.
* `CardRoute`: `rank`, `source_id`, `source_number`, `title`, `category`, `cosine` (= `1 - distance`; no other distance exposed), `source_url`, `url` (alias of `source_url`), `guide_id`, `page_id` (32-hex ids parsed from `source_url`; `None` if the URL does not have that form), `citation`, `sha256`, `source_status`, `source_url_status`, `has_source_correction`, `review_flag` (true for `needs_review`: #14, #18, #23).
* Never writes to the store, never touches `sap_docs` or `rag_core.get_collection`. Fails closed (status, not an exception) on a missing store; never returns a result without a URL silently (a card with no URL is returned with `url = None` and `review_flag` true).
* Model check: refuses to run if the collection's recorded model or dimension (384) does not match the embedder.

Independent test: stubbed embedder and collection (no model, no network), plus store-gated tests that compare the rankings with the stored Phase 4/5 results. Reversal: delete the file.

### 7B - Card-to-page join and availability (`scripts/card_page_join.py`)

* Input: the card's `source_number`, `guide_id`, `page_id`. Sources, read-only: `chunks.json` (legacy page chunks; page id parsed from each chunk `url`), `data/sap_help/chunks/chunks.jsonl` (`topic_id`, `guide_id`, `page_id`, `numeric_deliverable_id`), `data/guide_registry.json`.
* Rules: the join key is the **page id** (plus guide loio where present). A numeric deliverable id is never turned into a guide loio by inference; only recorded pairs (`numeric_deliverable_id` together with `guide_id` in a chunk record) are used. No title matching.
* Output per topic: `availability` in {`page_corpus` (chunks in `data/sap_help`), `legacy_only` (chunks in `sap_docs`/`chunks.json`), `both`, `none`} and the list of page chunk identifiers. Written to `data/phase7_topic_availability.json`.
* Expected from Phase 6 data (to be re-derived, step 0.6): topic 17 = `both`; the other 28 = `none`, with a separate note (not a status) for topics 2, 7, 11, 14, 24 that a captured page exists but is not ingested.

Independent test: fixture data plus a test against the real files that asserts the derived table equals the recorded evidence. Reversal: delete the file and its output.

### 7C - Orchestrator (`scripts/rag_two_stage.py`)

Modes (selected per call, default `legacy`):

| Mode | Behaviour |
| ---- | --------- |
| `legacy` | Calls `rag_core.generate_answer` with its defaults. **Output must equal the un-wrapped call.** |
| `shadow` | Runs `legacy` exactly; in addition runs the router and the join. Returns the legacy answer and sources unchanged, plus a `routing` diagnostics block. Never alters the answer. No LLM call beyond the legacy one |
| `routed` | Soft boost: take `rag_core.search(question, top_k=10, strategy=DEFAULT_STRATEGY)`, mark candidates whose page id is among the routed pages, reorder routed candidates first (stable, legacy order otherwise), keep `TOP_K = 3`, build the prompt with `rag_core.build_prompt`, call Ollama with `rag_core.LLM_OPTIONS`. If the routed topic has no page text, answer exactly as `legacy`. Never removes the legacy fallback |
| `route_only` | No LLM call. If the best card's topic has no page text, return "This topic is covered by `<title>` (source: `<source_url>`); the page content is not available locally", with the card's citation and review flag. No generated SAP content |

Known limit of the soft boost: `rag_core` fixes the candidate pool at `CANDIDATE_K = 10` and drops candidates beyond `MAX_DISTANCE`, so the boost can only reorder what the legacy query already returned. A routed page that is not among those candidates is unreachable without a separate, page-restricted query (a Chroma `where` filter on the exact recorded page URLs, run by the orchestrator through `rag_core.get_collection()`, without editing `rag_core`). Whether that is needed is decided by the 7E measurement, not assumed.

Failure handling: missing card store returns the legacy answer with `routing.status = "store_missing"`; a router exception is caught and recorded, never raised into the answer path; the legacy refusal (`NO_ANSWER_MESSAGE`) is preserved in every mode.

Independent test: stub `rag_core` functions and the LLM (no Ollama in the tests). Reversal: delete the file (nothing imports it).

### 7D - Citation flow

* Every answer carries a `sources` list; each entry has `title`, `url` (the SAP page), `origin` in {`page_chunk`, `card_route`}, and for routed items the card's `citation`, `source_id`, `source_status` and `review_flag`.
* URLs are never rewritten: the page URL of a chunk is reported as stored; the card URL is reported as stored. Where they differ in shape (numeric deliverable vs loio), both are shown and the join is recorded by page id, never by string conversion.
* A `needs_review` card (#14, #18, #23) is shown with the flag and the recorded review reason; it is not silently dropped and not silently corrected (the Phase 2 rule: manifest values stay the record).
* `print_sources` semantics are unchanged in `legacy` mode. In the new modes the list is labelled "sources provided to the model" (retrieved), not "sources used", because the legacy code does not verify usage.
* No fabricated citation: a `card_route` entry is never presented as if its text had been used for the answer.

### 7E - Router and regression evaluation (`scripts/evaluate_two_stage.py`)

1. Router recall through the adapter on the Phase 4 (50) and Phase 5 (54) sets; must equal the stored results (section 8, A2).
2. Legacy regression: 30 legacy retrieval questions in `legacy` mode and in `routed` mode; report both.
3. Answerable-subset comparison: for topics with page text, compare `legacy` with `routed` on page-level hits. Report counts only; no subjective score. If the subset is too small to conclude (today: one topic), say so and stop: the `routed` mode stays off.

### 7F - Out-of-domain card queries and (optional) threshold

Create a labelled set of unrelated and adjacent-but-unanswerable queries for the card collection, disclosed with its authorship. Report the score distribution of in-domain top-1 against out-of-domain top-1. A threshold is proposed only if the distributions separate; otherwise the report records that no threshold is justified and `min_cosine` stays `None`.

### 7G - CLI switch (optional, **DECISION**)

One commit adding `--mode` to `rag_chat.py`, default `legacy`. Skipped unless A1-A10 pass and the user approves.

## 6. Tests required before integration

| Area | Cases |
| ---- | ----- |
| Adapter | empty and whitespace query returns `empty_query`; missing store returns `store_missing`; wrong collection name returns `collection_missing`; `cosine = 1 - distance` for stub distances; results sorted by descending cosine, stable tie-break by `source_id`; `url` alias equals `source_url`; `guide_id`/`page_id` parsed correctly for all 29 real URLs and `None` for a malformed one; `needs_review` cards flagged (#14, #18, #23); `min_cosine = None` returns `top_k` items; `min_cosine = 0.9` returns none with `below_threshold`; embedder dimension mismatch is refused; the router never writes (store files read back identically by vector content) |
| Join | topic 17 resolves to page `0bfcc5536a51204be10000000a174cb4` in both corpora; a card whose page is absent gives `none`, never a guess; no title-based match (a fixture with equal titles and different page ids must not join); numeric deliverable is never converted to a loio without a recorded pair; availability table is deterministic (byte-identical on two runs) |
| Orchestrator | `legacy` output equals the direct `rag_core.generate_answer` call (stubbed LLM); `shadow` returns the same answer as `legacy`; `routed` with an unavailable topic equals `legacy`; `route_only` makes no LLM call; router failure does not change the answer; legacy refusal preserved in every mode; no mode calls `collection.add/upsert/delete` |
| Citations | every source has a non-empty URL or an explicit flag; `origin` set correctly; a review-flag card carries its flag; no URL is rewritten; `card_route` entries are not reported as used text |
| Boundary / protection | AST test: `rag_core`, `rag_chat`, `retrieve`, `evaluate_retrieval`, `create_embeddings`, `build_card_collection` and the Phase 4/5 scripts do not import `card_router`, `card_page_join` or `rag_two_stage` (the reverse import direction is allowed); protected artefact md5s equal the recorded values; `sap_docs` is never named in the new modules' write paths; new modules contain no `urllib.request`, `urllib.error`, `http.client`, `requests` or `socket`; no `temperature`/`seed`/prompt text is redefined (imported from `rag_core`) |
| Existing suite | all 260 existing tests pass with the store present (0 skipped); no existing test edited |
| Store-gated integration | the stored Phase 4 and Phase 5 dense rankings are reproduced by the adapter over the rebuilt store (same top-5 ids for every query) |
| Legacy regression (user's machine) | `evaluate_retrieval.py` default output equals the committed results (titles, ranks; distances within 1e-6), before and after Phase 7 |

## 7. Rollback strategy

* Each step (7A to 7G) is one commit. Reverting the commit removes only files that step created (7A to 7F), or one CLI option (7G). No step edits a protected file; therefore `git revert` of any subset leaves the legacy pipeline in its pre-Phase-7 state.
* Runtime rollback without any revert: mode `legacy` (the default); do not pass the flag. Removing `data/vector_store/` (gitignored, rebuildable) disables stage 1 with `store_missing`; the application then behaves as the legacy one.
* No Phase 7 step writes to `chroma_db/`, `sap_docs`, `chunks.json`, `sap_pages/` or the card store; there is no data migration to undo.
* Verification after rollback: rerun the protection tests; `evaluate_retrieval.py` reproduces the committed `data/retrieval_results.json`; `git diff <pre-phase-7-commit> --stat` lists no protected file.

## 8. Acceptance criteria (all must hold; report counts, not a subjective score)

| # | Criterion |
| - | --------- |
| A1 | The existing suite passes unchanged: **260 passed, 0 skipped** with the store rebuilt, and zero existing tests modified |
| A2 | Through the adapter, dense router recall equals the recorded values: Phase 4 R@1/3/5 = 0.92/0.96/1.00 and MRR 0.95 (50 q); Phase 5 R@1/3/5 = 0.7222/0.7963/0.8704 and MRR 0.7873 (54 q); the per-query top-5 ids are identical to `card_retrieval_results.json` and `phase5_results.json` |
| A3 | `legacy` mode returns results equal to `rag_core.generate_answer` / `search`; `evaluate_retrieval.py` output on the user's machine is unchanged (loose 22/24/25 of 25; same titles and ranks) |
| A4 | No protected file changed (md5 equal) and no write to `chroma_db`, `sap_docs` or the card store (vector-content check) |
| A5 | Every returned source carries a URL (or an explicit no-URL flag) and its origin; card provenance (`citation`, `source_status`, `review_flag`) reaches the output; URLs are byte-identical to the stored values |
| A6 | `route_only` never calls the LLM and never presents card text as SAP page content; topics without page text are reported as such |
| A7 | The availability table is deterministic and matches the recorded evidence; its counts are reported as they are (today: 1 of 29 with processed page text), not raised by inference |
| A8 | Failure paths return defined statuses (missing store, missing collection, empty query, router exception) and never change the legacy answer |
| A9 | No card refusal threshold is enabled unless the out-of-domain set (7F) shows separation, with the counts reported; otherwise the report states that none is justified |
| A10 | `routed` mode is enabled in any shipped path only if, on the legacy questions, it produces zero regressions in document hit (loose) relative to `legacy`, and the answerable-subset comparison is large enough to support the claim (otherwise it stays available but off, with the limit stated) |
| A11 | The Phase 7 report states what was and was not verified, names the remaining blocker (the missing page corpus for most topics), and makes no improvement claim without a measurement |

## 9. Out of scope for Phase 7 (by design)

Fetching or ingesting SAP pages, resolving guides, changing embeddings or the model, re-chunking, tuning `CANDIDATE_K`/`TOP_K`/`MAX_DISTANCE`/rerank weights, changing the prompt, changing the 30 legacy questions, hybrid retrieval at the card stage (not supported by Phase 5), and answer-quality evaluation of routed answers (that follows the corpus, per the handoff chain: corpus, embeddings, retrieval evaluation, answer-quality evaluation, RAG optimisation).
