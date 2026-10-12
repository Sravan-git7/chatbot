# Phase 8 report - end-to-end SAP Utilities RAG (card router -> page identity -> page chunks -> grounded answer -> citations)

**Revision 2026-10-12.** The original Phase 8 snapshot was measured on a 7-page corpus; the corpus has since grown to 28 of 29 pages (every card with an established page identity is ingested; only M2C-18 stays fail-closed with `excluded_conflicting_identity`), the M2C-01 Topic 1 map-root correction and the M2C-05 correction are machine-checked, and guide 021b182b is machine-verified (M2C-13/16 resolve under their own guide). All figures below come from the re-evaluation of 2026-10-12 in `data/evaluation/phase8_results.json` and `phase8_performance.json`; numbers that used to describe the 7-page state are marked as historical. The pipeline is still NOT validated with a real local LLM (no Ollama server or weights are reachable in this environment); nothing below was fabricated to hide that gap.

Status: **the pipeline runs end to end on the 28 ingested SAP Help pages; the remaining card (M2C-18, conflicting identity) is fail-closed by design.**

## 1. Executive summary

| Question | Answer |
|---|---|
| Does the chain run? | Yes: card router -> 7C identity -> constrained page-chunk retrieval -> context -> generator -> verifier -> citations, via `scripts/rag_answer.py`. |
| On real SAP documentation? | Yes, for 28 of 29 cards. M2C-18 (conflicting identity, unverified) returns `unresolved_identity` / `page_not_ingested` fail-closed and is never used as an answer source. |
| Real local LLM tested? | **No.** No Ollama server, no weights, no reachable download host. The `ollama` path is implemented and unit-tested with stubs only. The measured answers come from a deterministic *extractive* generator. |
| Biggest weakness measured | Abstention on absent details: only 5/11 absent-detail queries are refused in router mode (6/11 oracle). With oracle routing the page stage answers 55/59 answerable queries; real routing answers the same 55/59 and matches the expected status on 0.9322 of answerable queries. |
| Router quality | top-1 0.7500 (54/72 queries with a gold card), MRR 0.834 (historical 7-page snapshot: top-1 0.4625, MRR 0.623). |
| Hallucination guard | Six scripted fabrication types are withheld 59/59 each (verifier only; says nothing about llama3.2:3b). |
| Completion | The chain is validated on the 28 ingested pages with the extractive generator; an LLM-validated run is still outstanding (section 19). |

## 2. Scope and constraints respected

* `rag_chat.py`, `rag_core.py`, `rag_modes.py`, the card collection `sap_m2c_card_v1`, all 7A-7G modules and pinned evaluation inputs are hash-pinned in `tests/test_phase8_e2e.py::ProtectionTests`; the 2026-10-12 corpus/identity work re-baselined those pins with every change recorded in this report.
* No `chroma_db`, no `sap_docs`, no `scripts/rag_two_stage.py`; `routed` is still rejected by `rag_modes.py`. Phase 8 ships its own entry point `scripts/rag_answer.py`.
* No external LLM API; no network at runtime (AST test bans `urllib.request`, `http.client` etc. in the pipeline modules).
* The only network-touching tool is `scripts/page_fetch.py` (official `help.sap.com` pages only). The 21 pages added after the original Phase 8 snapshot came from verified official responses stored under `data/page_corpus/fetched/` and `data/captured_responses/`, ingested through the same `page_corpus.py` pipeline; the M2C-18 probe capture stays excluded (conflicting identity).

## 3. Architecture

```
query -> M2C card router (rank 1, no threshold, Phase 7F) -> 7C page identity (resolve_identity)
      -> lexical topic gate (OOD) -> page-corpus lookup (guide_id,page_id) -> constrained chunk retrieval (page_retriever)
      -> context builder (dedup / order / token budget / provenance) -> context-coverage gate
      -> generator (LLMGenerator over OllamaClient | ExtractiveGenerator) -> grounding verifier -> citations (page_citations over 7D)
      -> structured answer contract (+ debug block, ui block)
```

Modules (all in `scripts/`): `page_extract`, `page_corpus`, `page_fetch`, `page_chunker`, `build_page_collection`, `page_retriever`, `rag_text`, `rag_context`, `rag_generate`, `page_citations`, `rag_pipeline`, `rag_answer`, `build_phase8_queries`, `evaluate_phase8`.
The card is a **pointer**: the card router decides which page; the card text is never given to the generator as evidence and never cited as an answer source.

## 4. Page corpus pipeline

* Inputs: 22 verified official responses in `data/page_corpus/fetched/`, 7 captures in `captured_responses/` (HTML, status 200) and M2C-17's local flat-text record. Output: `data/page_corpus/` (`manifest.json`, `pages/<guide>/<page>.json`, `fetch_plan.json`, `fetch_log.json`) - deterministic, corpus sha256 `46e7c63a` (`46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008`).
* Each page records URL, guide id, page id, source ids, timestamp, HTTP status, title, breadcrumb, content hash and text hash.
* `validate_extraction` rejects empty pages, error pages, TOC-like pages and failed fetches. A URL, raw HTML or a failed fetch is never treated as a resolved page. The probe capture for M2C-18 is excluded (conflicting identity).
* Corpus status (2026-10-12): 28 pages `ingested`, 1 card `excluded_conflicting_identity` (M2C-18). The historical 7-page state listed M2C-01/13/16 as `excluded_card_identity_only`; that category no longer exists because guide 021b182b became machine-verified and the Topic 1 map-root correction became machine-checked.

## 5. Structure-preserving extraction

`page_extract.py` keeps headings (h1-h4 hierarchy -> `heading_path`), paragraphs, lists, tables (row-wise), notes and code-like terms, drops navigation/script/style, and keeps breadcrumb and title separately. Tested for ordering, table linearisation, whitespace and error rejection (`test_phase8_corpus.py`).

## 6. Chunking and chunk statistics

Strategies (all measured with the exact all-MiniLM-L6-v2 tokenizer; model limit 256 tokens), on the 28-page corpus:

| | A_legacy_1000c | B_heading_200 (default) | C_heading_128 |
|---|---|---|---|
| chunks | 90 | 113 | 145 |
| chunks per page (mean) | 3.21 | 4.04 | 5.18 |
| chunks over 256 tokens | 0 | 0 | 0 |
| tiny chunks under 24 tokens | 1 | 1 | 1 |

B was declared the default **before** the original evaluation, so the choice is not tuned on the results. Chunk metadata: `chunk_id, guide_id, page_id, source_url, title, heading_path, section_title, chunk_index, text, content_hash` (+ source ids, offsets, page text hash). Tested in `test_phase8_chunking.py`.

## 7. Page-chunk vector collection

Collection `sap_pages_v1` in `data/vector_store/page_collection/` (a separate Chroma persistent client directory; the card store is never opened by the builder). 113 vectors, 384 dims, cosine, all-MiniLM-L6-v2 (third-party PyPI re-packaging of the weights; file hashes in the manifest), normalised embeddings, chunk config and corpus sha recorded in `data/page_collection_manifest.json`. Rebuild is reproducible (tested: fresh build in a temp dir gives identical chunk fingerprint, vector count and float32 embedding hash). `data/vector_store/` is git-ignored, so a fresh clone must run `python scripts/build_page_collection.py --rebuild`.

## 8. Page retriever and identity-constrained second stage

`PageRetriever.retrieve_in_page(query, guide_id, page_id)` filters on both ids in Chroma and then re-checks every hit; any hit outside the requested identity raises `LeakageError` (tested with a deliberately leaking subclass). A right page id with the wrong guide id returns nothing. Hits keep URL, title, heading path, hashes, rank, distance and similarity. A separate `retrieve_corpus` exists only for evaluation (corpus-wide, no card stage) and is not used by the pipeline. The retrieval stage does **not** re-rank across cards; the router's rank 1 decides.

## 9. Evaluation set (AI-authored - disclosed)

`data/evaluation/phase8_queries.json`: 80 queries - 59 answerable (per page n = 6-10, authored for the seven originally ingested pages, all still ingested), 11 absent-detail, 0 not-ingested, 2 unresolved-identity (M2C-18 only), 8 out-of-domain (every 7th of the 7F OOD file). The not-ingested and unresolved-identity categories are derived by `build_phase8_queries.py` from the current identity state and corpus; the builder fails if a hand-written query contradicts the derived category. Since every card with an established identity now has its page text ingested, the not-ingested category is empty; the six queries formerly in it were removed when those pages (M2C-19/21/25/26/27/29) were ingested, and the two M2C-01/M2C-13 unresolved queries were removed when their identities became machine-checked. **Authored by the AI coding assistant with the page text in view**, before any retrieval; labels never changed after retrieval runs. Answerable queries carry verbatim evidence quotes (tested against page text); absent-detail terms are verified absent from the page. Not blind, not a domain expert, small: every metric is a point estimate with a wide Wilson interval.

## 10. Routing (stage 1) - measured separately

Card router rank-1, n = 72 queries with a gold card: **top-1 0.7500** (Wilson 0.639-0.836), MRR 0.834; answerable only: top-1 0.8305 (49/59). (Historical 7-page snapshot: top-1 0.4625, MRR 0.623 - the improvement comes from the reranked-top-10 router path and the larger, cleaner corpus, not from tuning on this set.) No threshold was added (7F verdict stands).

## 11. Identity (stage 2) - measured separately

When the router picks an ingested card, the effective page equals the gold page 49/49. M2C-05's correction metadata is preserved 9/9; M2C-01's correction is machine-checked (effective guide e52c8ee6, page e369ce53). M2C-18 (conflicting identity) was never answered (`m2c18_never_answered: true`): a query focusing it uniquely returns `page_not_ingested` via the focused-unavailable-topic gate, and the pre-registered invariant that the conflicting card is never presented as an answer source holds.

## 12. Retrieval (stage 3) - chunking comparison

Within the gold page (n = 59):

| | R@1 | R@3 | R@5 | MRR | corpus-wide R@1 |
|---|---|---|---|---|---|
| A | 0.864 | 0.949 | 0.983 | 0.910 | 0.678 |
| B | 0.831 | 0.949 | 1.000 | 0.897 | 0.644 |
| C | 0.847 | 0.949 | 0.983 | 0.896 | 0.678 |

B remains the pre-declared default; the paired differences to A stay insignificant. Corpus-wide R@1 dropped relative to the 7-page snapshot (0.81/0.75/0.80) because the corpus now contains 21 more pages of same-domain text, which makes corpus-wide (no card stage) retrieval intrinsically harder; the card stage is what production uses.

## 13. Context assembly

Dedup (identical content hash, or text contained in an already selected chunk), document order within a page, token budget 700 (max 4 chunks), provenance (`marker`, chunk id, heading path, URL) per item, drops are recorded with a reason. Tested in `test_phase8_context_generation.py`.

## 14. Grounded generation and the answer contract

* `LLMGenerator` + `OllamaClient` (model name from `rag_core.LLM_MODEL_NAME`, local server only). The prompt contains only the numbered excerpts; instructions forbid outside knowledge, inventing URLs/ids and require `[S#]` markers. **Never executed against a real model.**
* `ExtractiveGenerator`: deterministic non-LLM baseline that selects supported sentences. All measured generation results are from this generator.
* Contract (`schema_version` 1): `status` in `answered | insufficient_context | out_of_domain | page_not_ingested | unresolved_identity | no_relevant_page`, `answer`, `reason_code`, `message`, `topic` (card id, card URL, identity status, correction/review flags), `citations` (`answer_sources` vs `topic_pointer`), `routing`, `ui` (headline, badges, sources), `timings_ms`, optional `debug` (routing, identity, gates, retrieved, context, prompt, generation, grounding). JSON-serialisable.
* Pre-declared lexical constants (not tuned): `OOD_MIN_COVERAGE 0.25`, `CONTEXT_MIN_COVERAGE 0.5`, `MIN_SENTENCE_SUPPORT 0.6`, `EXTRACTIVE_MIN_SCORE 0.34`. They are uncalibrated heuristics.

## 15. Citations

Extends 7D: only chunks the answer cites **and** the verifier confirms are listed as `answer_sources` (`verified_used`); the card is a separate `topic_pointer` with `used_as_answer_text = false`; URLs come from the card/page record and are never rewritten (measured: 0 URL differences); markers not in the supplied context are rejected (0 phantom citations). M2C-01/05 corrections and the M2C-14/18/23 review flags travel with the citation notes.
Measured (router mode): 104 answer sources over 63 answered, of which 43/86 (0.5) on answerable queries contain gold evidence - the extractive baseline cites some supporting-but-not-evidence chunks; citation correctness at source level is therefore 0.5, not 1.0.

## 16. End-to-end results, stage by stage

Oracle routing (card stage bypassed to isolate the page stack; marked `mode: oracle` in outputs; n = 72):

* answered when answerable 55/59 (0.932); answered **and** citing a gold evidence chunk on the gold page 51/59 (0.864); page matches gold 59/59.
* grounding verifier passed on all answered; 4 refusals by the extractive generator.
* absent-detail abstention only **6/11** (0.545): the baseline answers 5 questions about details the page does not contain. This is a real weakness; the lexical gates are too weak to catch it, and it is unknown whether llama3.2:3b with the prompt would do better.
* unresolved identity 2/2 correct statuses (M2C-18).

Real routing (router rank-1 with reranked top-10, n = 80):

* status matches expectation on answerable queries 55/59 (0.9322). Of 8 OOD queries, 6 flagged (0.75), 1 answered, 1 insufficient; false-OOD rate on in-domain queries 0/72.
* answered-and-cites-evidence 43/59 (0.7288). Verifier clean on all answered. Phantom citations 0, topic pointer counted as evidence 0.
* M2C-18 queries: one returns `page_not_ingested` through the focused-unavailable-topic gate; the other ("Which attributes does the contract account business object expose?") is answered from M2C-17's genuinely ingested contract-account page after ambiguous focus falls through to the router. The pre-registered invariant `m2c18_never_answered` (the conflicting card is never the answer source) holds in both cases.

Different pipeline configurations are never blended into one number.

## 17. Hallucination and grounding tests

Scripted stub generators that fabricate one way each - invented number, transaction code, URL, off-context claim, phantom `[S9]` citation, uncited claim - were run over all 59 answerable queries: **0 fabricated answers shown, 59/59 withheld each**, with a faithful control passing 59/59 (so the guard is not just refusing everything). Unit tests also cover generator refusal, absent topic words (no LLM call), generator exceptions propagating (no silent fallback), and a regression for the sentence splitter that once separated `[S#]` markers from their sentences. Limitation: this tests the verifier, not an LLM's tendency to hallucinate.

## 18. Performance (CPU, extractive generator; `phase8_performance.json`)

Per query (router mode, n = 73 answered-path runs): context median 2.33 ms (p95 4.89), retrieve median 0.00 ms (p95 0.01), generate median 0.31 ms (p95 0.41). Embedder load 4.7 s; pipeline build 0.23 s; chunk+embed per strategy about 4.1-4.6 s; peak RSS 1218 MB. **LLM generation latency is not measured** and will dominate in practice.

## 19. What works / what is validated / what is not

* **Works (runs):** full chain on the 28 ingested pages; all status paths; CLI (`--json`, `--debug`, `--generator`); rebuildable page collection.
* **Validated (tested, measured):** corpus validation, extraction, chunking, retrieval constraints (no leakage), context builder, verifier, citation rules, protected-artifact immutability, determinism.
* **Implemented but not validated:** the Ollama LLM generator (stub-tested only); behaviour of the hand-written eval set on the 21 pages ingested after the original Phase 8 snapshot (they are covered by the corpus-consistency suites, not by hand-written questions).
* **Uncertain:** whether chunking B beats A (not significant); LLM answer quality; the lexical gate thresholds on a larger/other query set; the 0.5 citation-evidence rate with an LLM.
* **Not met:** a real local LLM run. Phase 8 must not be called LLM-complete until that exists.

## 20. Phase 9 recommendations and how to reproduce

1. Resolve or permanently retire M2C-18 with user-verified evidence; until then it stays fail-closed (`excluded_conflicting_identity`).
2. Install Ollama + the llama3.2:3b model; run `rag_answer.py --generator ollama`, re-run `evaluate_phase8.py` with an LLM generator class, and compare against the extractive baseline; add a human-labelled answer-quality set.
3. Extend the hand-written eval set to the 21 pages ingested after the original snapshot (evidence quotes must be verbatim from the page text; `build_phase8_queries.py` fails otherwise).
4. Improve absent-detail abstention (6/11 oracle, 5/11 router); replace the lexical OOD/abstention gates with a calibrated approach on a larger set.

Reproduce:
```
pip install pytest pypdf beautifulsoup4 lxml requests numpy chromadb==1.5.9 sentence-transformers==6.1.0 gt-all-minilm-l6-v2==0.1.0
python scripts/build_card_collection.py --rebuild          # rewrites data/vector_store and the card manifest
python scripts/page_corpus.py && python scripts/build_page_collection.py --rebuild
python scripts/evaluate_phase8.py
python scripts/rag_answer.py --generator extractive --question "Which transaction monitors meter reading results?" --json --debug
python -m pytest tests -q
```
Store-dependent tests skip with an explicit reason when the stores or model are missing.
