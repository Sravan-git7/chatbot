# Phase 7E report: Router and regression evaluation

Scope: Phase 7E only (`data/phase6_next_phase_spec.md`, section 5, step 7E; section 6 supplies the test areas it names). 7F and 7G were not started. No retrieval change, no hybrid retrieval, no threshold, no change to the Phase 4/5 labels, no SAP page ingested or fetched, no answer generation, no `rag_chat.py` edit, no change to 7A–7D code. Nothing was committed or pushed.

**Headline**

- The real Phase 7 router reproduced every recorded Phase 4 and Phase 5 ranking. There are **0 changed rankings** in 104 queries: top-1, top-5 ordering, expected-card rank and R@1/3/5, MRR, coverage and hits are all equal to the recorded values, overall and per question type.
- Rank, routing decision, identity status, local page availability and citation are reported as separate layers. Of the 85 rank-1 hits (46 + 39), **1** has a local page (M2C-17, Phase 4 only). The other **84** are hits on cards with no local page text.
- **The `legacy` mode was not run live** and **the `routed` mode does not exist.** Both are stated below, not simulated. The answerable subset is one topic out of 29, so per the spec nothing is concluded and `routed` stays off.
- Full suite: **448 passed, 0 skipped, 0 failed** with the card store present. With the store absent: **422 passed, 26 skipped, 0 failed**.

## 1. What 7E defines, and what was done

The spec's 7E has three items. The table maps each to what was done.

| Spec item | Done |
|---|---|
| 1. Router recall through the adapter on Phase 4 (50) and Phase 5 (54); must equal the stored results | Done with the real `ChromaCardBackend` and the real model, over a store rebuilt this phase (section 2). |
| 2. Legacy regression: 30 legacy questions in `legacy` and in `routed` mode | **Partly.** The recorded legacy results are re-scored and the card route is overlaid on the 30 questions. `legacy` is not run live and `routed` does not exist (section 6). |
| 3. Answerable-subset comparison; if too small (today one topic), say so and stop; `routed` stays off | Done. One topic with page text (M2C-17); stated, not compared (section 7). |

`scripts/evaluate_two_stage.py` is the spec's file name. It runs read-only, blocks sockets and counts attempts (0), and writes a deterministic `data/phase7E_evaluation.json`. Two runs are byte-identical, and a store-gated test re-runs it in a fresh process and requires an identical document.

## 2. The card store was rebuilt (disclosure)

`data/vector_store/` does not persist between sessions, and 7E item 1 cannot run without it. The spec's step 0.3 prescribes rebuilding it with the existing builder. I rebuilt it exactly as in 7B:

`python scripts/build_card_collection.py --manifest /tmp/p7e_built_manifest.json`

- The builder wrote its manifest to a temporary path. The protected `data/card_collection_manifest.json` was not rewritten (sha256 `5b3a5c30…` is unchanged).
- The rebuilt manifest equals the protected one in every field except `created_utc`.
- The store is gitignored. No `sap_docs` and no `chroma_db/` were created. The legacy store does not exist.
- The test venv `/tmp/av` was recreated from PyPI with the pinned versions (`chromadb 1.5.9`, `sentence-transformers 6.1.0`, `gt-all-minilm-l6-v2 0.1.0`). The weights are the third-party PyPI re-packaging, as disclosed since Phase 4.
- Store content (ids, documents, metadata, vectors) is identical before and after the evaluation: 1 collection, 29 vectors.

## 3. Phase 4 regression (50 questions, recorded `card_retrieval_results.json`)

| Comparison | Result |
|---|---|
| Top-1 identical to recorded | 50 / 50 |
| Top-5 ordering identical | 50 / 50 |
| Expected-card rank identical (every expected id) | 50 / 50 |
| First-expected-rank identical | 50 / 50 |
| Recorded similarities reproduced (4 dp) | 250 / 250 (max abs diff 4.999e-05, rounding) |
| Default path (`route_to_identity`, `top_k` 5) equals the prefix of the 29-card ranking | 50 / 50 |

Metrics recomputed from the router output, equal to recorded, including the per-type breakdown:

| R@1 | R@3 | R@5 | MRR | coverage@1 / @3 / @5 | hits@1 |
|---|---|---|---|---|---|
| 0.92 | 0.96 | 1.00 | 0.95 | 0.8583 / 0.955 / 1.0 | 46 |

The four recorded misses are unchanged: Q07, Q39, Q42, Q49.

## 4. Phase 5 regression (54 independent queries, dense rows of `phase5_results.json`)

| Comparison | Result |
|---|---|
| Top-1 identical | 54 / 54 |
| Top-5 ordering identical | 54 / 54 |
| Expected-card rank identical | 54 / 54 |
| First-expected-rank identical | 54 / 54 |
| Recorded similarities reproduced | 270 / 270 (max abs diff 4.932e-05) |
| Default path equals the prefix of the full ranking | 54 / 54 |

| R@1 | R@3 | R@5 | MRR | coverage@1 / @3 / @5 | hits@1 |
|---|---|---|---|---|---|
| 0.7222 | 0.7963 | 0.8704 | 0.7873 | 0.6728 / 0.7963 / 0.8704 | 39 |

## 5. Router-specific metrics (routing layers above the rank)

The layers stay separate. A card at rank 1 is a rank. The routing decision is "rank 1 is selected", which is not a confidence claim. The identity status comes from 7C, local page availability from the 7A/7C join, and citation availability from 7D.

| | Phase 4 (50) | Phase 5 (54) |
|---|---|---|
| Rank-1 is an expected card | 46 | 39 |
| …and a local page exists | **1** (M2C-17) | **0** |
| …and no local page exists | **45** | **39** |
| …and the card is `needs_review` | 5 | 6 |
| Queries routed to a local page | 1 | 0 |
| Queries routed to a `needs_review` card | 5 | 7 |
| Selected card has a URL; URL byte-identical to the card | 50 / 50 | 54 / 54 |
| `card_route` never reported as used text (`used_as_answer_text` false, `verified_used` false) | all | all |
| Review flag equals card `needs_review` | all | all |

Routing by 7C state, `queries (rank-1 expected)`:

| State | Phase 4 | Phase 5 |
|---|---|---|
| `identified_not_local` | 43 (39) | 43 (32) |
| `card_identity_only` | 4 (4) | 5 (3) |
| `corrected_identity` | 1 (1) | 3 (2) |
| `conflicting_identity` | 1 (1) | 3 (2) |
| `resolved_local_page` | 1 (1) | 0 |

The 7A join reports `url_only` for every card without a local page, with the fallback reason carried. It never reports `resolved_page` for an identified-but-not-local card. A high rank is not evidence that the SAP page is available.

**Near-ties are visible and common.** They match the 7B figures, which were cross-checked by a test against the independent 7B validation file.

| | Phase 4 | Phase 5 | Both |
|---|---|---|---|
| Queries with a rank-1 to rank-2 gap < 0.01 | 7 | 8 | **15** |
| …of which rank 1 is not an expected card | 4 | 6 | **10** |
| Queries with a gap < 0.05 | 15 | 30 | **45** |
| …of which rank 1 is not an expected card | 4 | 12 | **16** |
| Smallest gap | 0.000147 (Q35: M2C-21 vs M2C-20) | 0.001266 (P5-06) | |

In six of the 15 near-ties below 0.01, the rank-1 and rank-2 cards differ in routing status or review flag: Q07, Q34, Q39, P5-01, P5-06 and P5-50. In these cases a one-position swap changes the identity status or the `needs_review` flag shown to the user, which is a reason not to treat rank 1 as a decision. The 0.01 and 0.05 bins are descriptive (the ones 7B used). They are not thresholds and were not tuned.

## 6. Legacy regression (item 2)

**`legacy` mode was not run live.** The legacy `chroma_db` does not exist here. The legacy retriever loads the embedding model by its Hugging Face name, which is unreachable from the sandbox, and `rag_core.py` is protected. The spec already assigns this run to the user's machine (step 0.4). What is verified instead:

- The recorded `data/retrieval_results.json` (sha256 pinned) is re-scored with the legacy rules. The loose hits are **22 / 24 / 25 of 25** at top-1/3/5, and the strict hits are 18 / 22 / 23. The re-scored match ranks equal the stored ones for all 25 scored questions. The other 5 questions are out of domain.
- By construction and by test, no legacy file (`rag_core`, `rag_chat`, `retrieve`, `evaluate_retrieval`, `create_embeddings`) references any Phase 7 module. No Phase 7 module imports them, and none of the legacy modules is loaded after an evaluation.

**`routed` mode does not exist.** The plan's orchestrator (soft boost over legacy candidates) was realised as the 7C identity layer, which carries no page chunks. Building a boost now would be a new feature outside 7E. Under the spec's own rule (item 3), the `routed` mode stays off, and acceptance criterion A10 is not satisfiable today.

**What was measured instead:** the card route overlaid on the same 30 questions, with the recorded legacy top-5 URLs joined to the routed card by page id under the 7D rule. These are descriptive counts. The legacy labels are page titles, not cards or page ids, so no correctness is claimed.

- **Rank-1 card for the 30 questions:** M2C-18 ×15, M2C-01 ×8, M2C-17 ×2, and M2C-03, M2C-08, M2C-11, M2C-14, M2C-24 once each.
- **Route state:** 15 `conflicting_identity`, 8 `card_identity_only`, 5 `identified_not_local`, 2 `resolved_local_page`. 16 of the 30 route to a `needs_review` card.
- **Near-ties:** 6 questions have a gap < 0.01 and 10 have a gap < 0.05.
- **Agreement with the recorded legacy retrieval:** the recorded legacy top-5 contains the routed card's page for **1** question (q16 → M2C-17; the chunk URL uses the numeric deliverable 40374631 and the card URL uses the loio `e52c8ee6…`, joined by page id through the recorded pair). All legacy chunk URLs are reported unmodified.
- **No card refusal.** The five out-of-domain legacy questions (q26–q30) each still return a rank-1 card (distances 0.5987–0.9584) and are routed. No threshold exists or is proposed, because that is 7F. Their distances are listed in the JSON and no in-domain versus out-of-domain comparison was made here.

A practical consequence: most legacy questions (23 of 30) land on a card whose identity is unconfirmed (M2C-01) or in conflict (M2C-18), and cannot be turned into a verified page.

## 7. Answerable subset (item 3)

Topics with local page text, counted from the repository (not inferred): **M2C-17 only, 1 of 29.** The subset is far too small to compare `legacy` with `routed`, and there are no page-id labels for the legacy questions. Titles are never used to join (7B rule), so a page-level hit rate would require inventing labels. Per the spec: stated, nothing concluded, and **`routed` stays off.** The router counts on the Phase 4/5 sets that touch this topic are 1 and 0 for rank-1, and 2 and 1 for "expected card is M2C-17".

## 8. Edge cases tested

All use the real router, real 7C identity and real 7D citation. For each card, "natural" is the number of Phase 4/5 queries in which it is rank 1. "Forced" means the caller-side `selector` hook picks that card on a recorded query that expects it. The real rank and distance are reported, and the forcing is labelled, not presented as a rank decision.

| Case | Natural rank-1 | Result |
|---|---|---|
| M2C-05 correction metadata | 4 | `corrected_identity`; the correction block is present, `has_source_correction` is true, the card URL is unchanged, and not review-flagged |
| M2C-14 `needs_review` | 4 | `identified_not_local`, `review_flag` true, reasons carried, URL unchanged |
| M2C-18 conflicting | 4 | `conflicting_identity`; `effective_guide_id` is null; the conflict and probe evidence are shown with `used_as_effective_guide` false; `review_flag` true |
| M2C-23 `needs_review` | 4 | `identified_not_local`, `review_flag` true (forced from rank 2 on Q07, which is visible) |
| M2C-01, 13, 16 | 1, 4, 4 | `card_identity_only`; no effective ids; no local page |
| M2C-17 | 1 | `resolved_local_page`; the page is available; the content is a legacy local copy and `fresh_network_fetch_claimed` is false |
| `identified_not_local` / `url_only` (M2C-07) | 3 | 7C `identified_not_local`; 7A join `url_only`; page not available |
| `no_card_candidate` | | an empty query gives `EMPTY_QUERY`; a rejecting selector gives `SELECTOR_REJECTED_ALL_CANDIDATES`; both return 0 sources |
| Near-tied candidates | | the 15 queries with a gap < 0.01; 6 of them differ in routing status between rank 1 and rank 2 (section 5) |
| 7D citation metadata | | URL byte-identical, `origin=card_route`, flags, `used_as_answer_text=false` for every routed query (104 of 104) and every edge card |

`unresolved` cannot occur with the 29 real cards, because all of them have parseable SAP Help URLs. It stays covered only by the 7A/7C unit tests.

## 9. Tests

- `tests/test_phase7e.py`: **37 tests**, all passing. 35 need no store: the committed evaluation document is checked against the recorded Phase 4/5 data independently, the evaluator is exercised with a deterministic stub that must detect differences, and the scope rules are enforced. 2 are store-gated (a fresh-process byte-identical re-run of the evaluation, and a real-router sample).
- The scope tests check: no network, LLM or legacy imports; no collection-mutating call; no threshold or retrieval parameter in the evaluator; 7A–7D implementation, Phase 4/5 data, legacy results and the collection manifest pinned by hash; no legacy or production file referencing the new modules; no `chroma_db/`.
- No existing test or recorded expectation was edited. Two assertions in my own new tests were wrong on first run (double rounding of a 6-dp distance against a 4-dp similarity; a hashlib `.update()` flagged as a collection update). I fixed the tests, not the evaluator or any data.

**Full suite** (`PYTHONDONTWRITEBYTECODE=1 /tmp/av/bin/python -m pytest tests -q -p no:cacheprovider`):

| Condition | Passed | Skipped | Failed |
|---|---|---|---|
| Store present | **448** | **0** | **0** |
| Store absent (measured by moving it aside and back) | 422 | 26 (24 earlier + 2 new store-gated) | 0 |

Baseline before 7E: 387 passed / 24 skipped.

## 10. Files

**Created**

- `scripts/evaluate_two_stage.py`
- `tests/test_phase7e.py`
- `data/phase7E_evaluation.json`
- `data/phase7E_report.md`

**Generated, not part of the repository:** `data/vector_store/` (gitignored, rebuilt as in section 2), `/tmp/p7e_built_manifest.json`, `/tmp/av`.

**Modified:** none. The same 9 tracked files remain modified as before 7A (`.gitignore`, `data/retrieval_results.json`, `scripts/audit_corpus.py`, `chunk_pages.py`, `clean_sap_pages.py`, `create_embeddings.py`, `evaluate_retrieval.py`, `rag_chat.py`, `retrieve.py`). Their content is untouched in this phase. `git diff --check` is clean. No `__pycache__` was left.

## 11. Remaining limitations

1. `legacy` mode is not run live, and `routed` mode does not exist, so spec item 2 and acceptance criteria A3 and A10 are only partly covered. The live legacy regression is the user's PowerShell run: `python scripts/evaluate_retrieval.py`, compared with the committed `data/retrieval_results.json`.
2. Page-level evaluation is not possible: one topic has page text, and there are no page-id labels.
3. The Phase 5 queries are the project's own labelled set. Recall values are measurements on 29 cards, not a confidence claim, and rank 1 is not confidence.
4. Out-of-domain card queries do not exist yet (7F). Every query returns a card, and no refusal is possible.
5. Of the 29 cards, 3 are `card_identity_only`, 1 conflicting (#18), 1 corrected (#05), and 23 are identified but have no local page. This is unchanged. Real page text needs the corpus work, not Phase 7.
6. The model weights are the third-party PyPI re-packaging. Equality with the weights on the user's machine was not proven here.
7. The store and the venv vanish between sessions. The 26 store-gated tests skip then, with a reason.
8. Everything from Phase 1 to 7E is still untracked, HEAD is still `d85c31e`, and the earlier consolidation commit `a4182ff…` is still lost. Please commit and push this work soon.

## 12. Next phase per the specification

**7F: out-of-domain card queries and (optional) threshold.** Create a labelled set of unrelated and adjacent-but-unanswerable queries for the card collection, disclosed with its authorship (human-written or explicitly agent-written, never LLM-generated). Report the score distribution of in-domain top-1 against out-of-domain top-1. Propose a threshold only if the distributions separate; otherwise record that none is justified and `min_cosine` stays `None` (acceptance criterion A9).

7G (the optional `--mode` CLI switch) follows only if A1–A10 pass and the user approves. Neither was started.
