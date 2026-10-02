# Phase 8 report - end-to-end SAP Utilities RAG (card router -> page identity -> page chunks -> grounded answer -> citations)

Status: **the pipeline is implemented and runs end to end on the 7 SAP Help pages that exist locally. It is NOT validated on the full 29-topic corpus and NOT validated with a real local LLM.**
Both gaps come from the sandbox (help.sap.com and every model host are unreachable), not from a design choice. Nothing below was fabricated to hide them.
All figures come from `data/evaluation/phase8_results.json` (deterministic: two consecutive runs gave an identical file hash, `735f7061...`) and `phase8_performance.json`.

## 1. Executive summary

| Question | Answer |
|---|---|
| Does the chain run? | Yes: card router -> 7C identity -> constrained page-chunk retrieval -> context -> generator -> verifier -> citations, via `scripts/rag_answer.py`. |
| On real SAP documentation? | Only for 7 of 29 cards (M2C-02, 05, 07, 11, 14, 17, 24). The other 22 return `page_not_ingested` (18) or `unresolved_identity` (4). |
| Real local LLM tested? | **No.** No Ollama server, no weights, no reachable download host. The `ollama` path is implemented and unit-tested with stubs only. The measured answers come from a deterministic *extractive* generator. |
| Biggest weakness measured | The card router is the bottleneck: top-1 on the page eval set 0.46 (answerable 0.39). With oracle routing the page stage answers 55/59 answerable queries. |
| Hallucination guard | Six scripted fabrication types are withheld 59/59 each (verifier only; says nothing about llama3.2:3b). |
| Completion | **Not complete** per the task's own rule (full chain on real SAP docs). See section 19. |

## 2. Scope and constraints respected

* `rag_chat.py`, `rag_core.py`, `rag_modes.py`, `.gitignore`, the card collection `sap_m2c_card_v1`, the card manifest, all 7A-7G modules, reports and pinned evaluation inputs are unchanged (hash-pinned in `tests/test_phase8_e2e.py::ProtectionTests`; the pre-existing 9 modified tracked files are untouched since the Phase 8 baseline).
* No `chroma_db`, no `sap_docs`, no `scripts/rag_two_stage.py`; `routed` is still rejected by `rag_modes.py`. Phase 8 therefore ships its own entry point `scripts/rag_answer.py`.
* No commit, push, reset, clean or checkout was run. No external LLM API; no network at runtime (AST test bans `urllib.request`, `http.client` etc. in the pipeline modules).
* The only network code is `scripts/page_fetch.py` (official `help.sap.com` pages only). It was tried once live and failed (section 4); it is not part of the pipeline or tests.

## 3. Architecture

```
query -> M2C card router (rank 1, no threshold, Phase 7F) -> 7C page identity (resolve_identity)
      -> lexical topic gate (OOD) -> page-corpus lookup (guide_id,page_id) -> constrained chunk retrieval (page_retriever)
      -> context builder (dedup / order / token budget / provenance) -> context-coverage gate
      -> generator (LLMGenerator over OllamaClient | ExtractiveGenerator) -> grounding verifier -> citations (page_citations over 7D)
      -> structured answer contract (+ debug block, ui block)
```

Modules (all new, `scripts/`): `page_extract`, `page_corpus`, `page_fetch`, `page_chunker`, `build_page_collection`, `page_retriever`, `rag_text`, `rag_context`, `rag_generate`, `page_citations`, `rag_pipeline`, `rag_answer`, `build_phase8_queries`, `evaluate_phase8`.
The card is a **pointer**: the card router decides which page; the card text is never given to the generator as evidence and never cited as an answer source.

## 4. Page corpus pipeline

* Inputs: the 7 verified local captures in `captured_responses/` (HTML, status 200) plus M2C-17's local flat-text record. Output: `data/page_corpus/` (`manifest.json`, `pages/<guide>/<page>.json`, `fetch_plan.json`, `fetch_log.json`) - deterministic, corpus sha256 `fd55d20f...2e8d`.
* Each page records URL, guide id, page id, source ids, timestamp, HTTP status, title, breadcrumb, content hash and text hash.
* `validate_extraction` rejects empty pages, error pages (title patterns tightened after a false positive on the legitimate title "Error Handling in Billing"), TOC-like pages and failed fetches. A URL, raw HTML or a failed fetch is never treated as a resolved page. The probe capture for M2C-18 is excluded (conflicting identity).
* Why `data/page_corpus/` and not `data/sap_help/`: files added there change `PageContentIndex` and break the checkpoint-pinned 7A/7C tests. This is a deviation from an earlier folder convention; the legacy corpus is untouched.
* **Live fetch:** one attempt through `page_fetch.py` failed (host unreachable, `curl` exit 35). Failure recorded in `fetch_log.json`; nothing saved; not re-run. The registry holds no numeric id/build pair for 6 of 7 guides, so a fetch plan for the remaining 22 pages cannot be built without guessing; none was guessed.

| Card | Page text | Source |
|---|---|---|
| M2C-02, 05, 07, 11, 14, 24 | ingested | captures |
| M2C-17 | ingested | local flat-text record |
| 18 other cards | `not_ingested_no_local_content` | - |
| M2C-01, 13, 16 | `excluded_card_identity_only` | - |
| M2C-18 | `excluded_conflicting_identity` | - |

## 5. Structure-preserving extraction

`page_extract.py` keeps headings (h1-h4 hierarchy -> `heading_path`), paragraphs, lists, tables (row-wise), notes and code-like terms, drops navigation/script/style, and keeps breadcrumb and title separately. Tested for ordering, table linearisation, whitespace and error rejection (`test_phase8_corpus.py`, 35 tests).

## 6. Chunking and chunk statistics

Strategies (all measured with the exact all-MiniLM-L6-v2 tokenizer; model limit 256 tokens):

* **A_legacy_1000c** - reproduces the legacy `chunk_pages` algorithm (check: 310 == 310 legacy chunks on the legacy corpus).
* **B_heading_200** - heading-aware, target 200 tokens, 1-sentence overlap, "Title > Heading" prefix embedded, tiny sections merged.
* **C_heading_128** - same with target 128 tokens.

| | A | B (default) | C |
|---|---|---|---|
| chunks | 23 | 32 | 38 |
| tokens mean / max | 158.9 / 231 | 118.8 / 226 | 101.4 / 226 |
| chars mean / max | 805 / 998 | 566 / 1092 | 477 / 1063 |
| chunks over 256 tokens | 0 | 0 | 0 |
| chunks under 24 tokens | 1 | 0 | 0 |
| split mid-section | 0 | 16 | 24 |

B was declared the default **before** evaluation, so the choice is not tuned on the results. Chunk metadata: `chunk_id, guide_id, page_id, source_url, title, heading_path, section_title, chunk_index, text, content_hash` (+ source ids, offsets, page text hash). Tested in `test_phase8_chunking.py` (16 tests).

## 7. Page-chunk vector collection

Collection `sap_pages_v1` in `data/vector_store/page_collection/` (a separate Chroma persistent client directory; the card store is never opened by the builder). 32 vectors, 384 dims, cosine, all-MiniLM-L6-v2 (third-party PyPI re-packaging of the weights; file hashes in the manifest), normalised embeddings, chunk config and corpus sha recorded in `data/page_collection_manifest.json`. Chunks fingerprint `c50e951f...`. Rebuild is reproducible (tested: fresh build in a temp dir gives identical chunk fingerprint, vector count and float32 embedding hash). `data/vector_store/` is git-ignored, so a fresh clone must run `python scripts/build_page_collection.py --rebuild`.

## 8. Page retriever and identity-constrained second stage

`PageRetriever.retrieve_in_page(query, guide_id, page_id)` filters on both ids in Chroma and then re-checks every hit; any hit outside the requested identity raises `LeakageError` (tested with a deliberately leaking subclass). A right page id with the wrong guide id returns nothing. Hits keep URL, title, heading path, hashes, rank, distance and similarity. A separate `retrieve_corpus` exists only for evaluation (corpus-wide, no card stage) and is not used by the pipeline. The retrieval stage does **not** re-rank across cards; the router's rank 1 decides.

## 9. Evaluation set (AI-authored - disclosed)

`data/evaluation/phase8_queries.json`: 88 queries - 59 answerable (per page n = 6-10), 11 absent-detail, 6 not-ingested, 4 unresolved-identity, 8 out-of-domain (every 7th of the 7F OOD file). **Authored by the AI coding assistant with the page text in view**, before any retrieval; labels never changed afterwards. Answerable queries carry verbatim evidence quotes (tested against page text); absent-detail terms are verified absent from the page. Not blind, not a domain expert, small: every metric is a point estimate with a wide Wilson interval.

## 10. Routing (stage 1) - measured separately

Card router rank-1, n = 80 queries with a gold card: **top-1 0.4625** (Wilson 0.357-0.571), top-3 0.775, top-5 0.875, MRR 0.623. Answerable only: top-1 0.390 (23/59). This is a harder, paraphrase-heavy set than the Phase 4/5 card sets (Phase 5: R@1 0.72), and the card router was not changed. No threshold was added (7F verdict stands).

## 11. Identity (stage 2) - measured separately

When the router picks an ingested card, the effective page equals the gold page 23/23. M2C-05's correction metadata is preserved 9/9. Cards with conflicting (M2C-18) or identity-only identity were routed 19 times and **answered 0 times**. Unresolved-identity queries: 4/4 correct status.
Note: the 7C status (`identified_not_local`, e.g. for M2C-07) is computed against `data/sap_help` only; the pointer in the citation now carries a `page_corpus` field and an adjusted statement saying page text is held in `data/page_corpus` (the 7D entry itself is copied, not modified).

## 12. Retrieval (stage 3) - chunking comparison

Within the gold page (n = 59): 

| | R@1 | R@3 | R@5 | MRR | evidence in assembled context |
|---|---|---|---|---|---|
| A | 0.864 | 0.949 | 0.983 | 0.910 | 56/59 |
| B | 0.831 | 0.949 | 1.000 | 0.897 | 59/59 |
| C | 0.847 | 0.949 | 0.983 | 0.896 | 58/59 |

Paired sign test B vs A on R@1: 3 vs 5, p = 0.73 - **no significant difference**. B's advantage is evidence-in-context (the property that matters for answers) but the paired end-to-end difference B vs A (6 vs 1) is also not significant (p = 0.125). I therefore claim B is a reasonable default, not a proven winner. Corpus-wide (no card stage) R@1 is 0.81 / 0.75 / 0.80, page-hit@1 0.95 / 0.92 / 0.95.

## 13. Context assembly

Dedup (identical content hash, or text contained in an already selected chunk), document order within a page, token budget 700 (max 4 chunks), provenance (`marker`, chunk id, heading path, URL) per item, drops are recorded with a reason. Mean context 416 tokens, redundancy 0.53 (overlap sentences inflate it by design), context precision 0.34 (most retrieved chunks do not contain the evidence quote, which is expected with 4-5 chunks per page). 32 tests in `test_phase8_context_generation.py`.

## 14. Grounded generation and the answer contract

* `LLMGenerator` + `OllamaClient` (model name from `rag_core.LLM_MODEL_NAME`, local server only). The prompt contains only the numbered excerpts; instructions forbid outside knowledge, inventing URLs/ids and require `[S#]` markers. **Never executed against a real model.**
* `ExtractiveGenerator`: deterministic non-LLM baseline that selects supported sentences. All measured generation results are from this generator.
* Contract (`schema_version` 1): `status` in `answered | insufficient_context | out_of_domain | page_not_ingested | unresolved_identity | no_relevant_page`, `answer`, `reason_code`, `message`, `topic` (card id, card URL, identity status, correction/review flags), `citations` (`answer_sources` vs `topic_pointer`), `routing`, `ui` (headline, badges, sources), `timings_ms`, optional `debug` (routing, identity, gates, retrieved, context, prompt, generation, grounding). JSON-serialisable.
* Pre-declared lexical constants (not tuned): `OOD_MIN_COVERAGE 0.25`, `CONTEXT_MIN_COVERAGE 0.5`, `MIN_SENTENCE_SUPPORT 0.6`, `EXTRACTIVE_MIN_SCORE 0.34`. They are uncalibrated heuristics.

## 15. Citations

Extends 7D: only chunks the answer cites **and** the verifier confirms are listed as `answer_sources` (`verified_used`); the card is a separate `topic_pointer` with `used_as_answer_text = false`; URLs come from the card/page record and are never rewritten (measured: 0 URL differences); markers not in the supplied context are rejected (0 phantom citations). M2C-05 corrected identity and M2C-14/18/23 review flags travel with the citation notes.
Measured (oracle routing): 96 answer sources over 60 answered, of which 51/83 (0.61) on answerable queries contain gold evidence - i.e. the extractive baseline cites some supporting-but-not-evidence chunks; citation correctness at source level is therefore 0.61, not 1.0.

## 16. End-to-end results, stage by stage

Oracle routing (card stage bypassed to isolate the page stack; marked `mode: oracle` in outputs; n = 80):

* answered when answerable 55/59 (0.932); answered **and** citing a gold evidence chunk on the gold page 51/59 (0.864); page matches gold 59/59.
* grounding verifier passed 55/55 answered; 4 refusals by the extractive generator.
* absent-detail abstention only **6/11** (0.545): the baseline answers 5 questions about details the page does not contain. This is a real weakness; the lexical gates are too weak to catch it, and I do not know whether llama3.2:3b with the prompt would do better.
* not-ingested 6/6, unresolved identity 4/4 correct statuses.

Real routing (router rank-1, n = 88):

* status matches expectation on answerable queries only 22/59 (0.373): 12 go to unresolved cards, 12 to not-ingested pages, and **11 are wrongly flagged out-of-domain** (11/80 = 0.1375 false OOD) because the router picked a card whose text does not overlap the query. Of 8 OOD queries, 7 flagged (0.875); 1 answered.
* answered-and-cites-evidence 19/59 (0.322). Verifier clean 22/22 on answered. Phantom citations 0, topic pointer counted as evidence 0.

Different pipeline configurations are never blended into one number.

## 17. Hallucination and grounding tests

Scripted stub generators that fabricate one way each - invented number, transaction code, URL, off-context claim, phantom `[S9]` citation, uncited claim - were run over all 59 answerable queries: **0 fabricated answers shown, 59/59 withheld each**, with a faithful control passing 59/59 (so the guard is not just refusing everything). Unit tests also cover generator refusal, absent topic words (no LLM call), generator exceptions propagating (no silent fallback), and a regression for the sentence splitter that once separated `[S#]` markers from their sentences. Limitation: this tests the verifier, not an LLM's tendency to hallucinate.

## 18. Performance (CPU, extractive generator; `phase8_performance.json`)

Per query (router mode, n = 88): total median 13.6 ms, p95 32.8 ms; route median 12.5 ms; retrieve 12.3 ms; context 2.2 ms; generate 0.3 ms. Embedder load 4.1 s; pipeline build 0.17 s; chunk+embed per strategy about 1 s; peak RSS 1146 MB. **LLM generation latency is not measured** and will dominate in practice.

## 19. What works / what is validated / what is not

* **Works (runs):** full chain on 7 ingested pages; all status paths; CLI (`--json`, `--debug`, `--generator`); rebuildable page collection.
* **Validated (tested, measured):** corpus validation, extraction, chunking, retrieval constraints (no leakage), context builder, verifier, citation rules, protected-artifact immutability, determinism.
* **Implemented but not validated:** the Ollama LLM generator (stub-tested only); live SAP fetch (one failed attempt); behaviour on the other 22 pages.
* **Uncertain:** whether chunking B beats A (not significant); LLM answer quality; the lexical gate thresholds on a larger/other query set; the 0.61 citation-evidence rate with an LLM.
* **Not met:** "full chain on real SAP documentation" for all 29 topics, and a real local LLM run. Phase 8 must not be called complete until both exist.

## 20. Phase 9 recommendations and how to reproduce

1. On a machine with network access: fetch the remaining 22 official pages (record numeric guide/build ids from user-verified loio values, do not guess), re-run `page_corpus.py` and `build_page_collection.py --rebuild`.
2. Install Ollama + the llama3.2:3b model; run `rag_answer.py --generator ollama`, re-run `evaluate_phase8.py` with an LLM generator class, and compare against the extractive baseline; add a human-labelled answer-quality set.
3. Router quality: the router, not the page stack, limits end-to-end accuracy (top-1 0.46 here). Candidate fixes (hybrid retrieval, page-level re-ranking across the router's top-k, abstention) must be evaluated on a fresh set - do not tune on `phase8_queries.json`.
4. Replace the lexical OOD/abstention gates with a calibrated approach on a larger set; improve absent-detail abstention (6/11).

Reproduce:
```
pip install pytest pypdf beautifulsoup4 lxml requests numpy chromadb==1.5.9 sentence-transformers==6.1.0 gt-all-minilm-l6-v2==0.1.0
python scripts/build_card_collection.py --manifest /tmp/card_manifest.json   # never overwrite data/card_collection_manifest.json
python scripts/page_corpus.py && python scripts/build_page_collection.py --rebuild
python scripts/evaluate_phase8.py
python scripts/rag_answer.py --generator extractive --question "Which transaction monitors meter reading results?" --json --debug
python -m pytest tests -q
```
Tests: 671 passed in the full suite (540 pre-existing + 131 Phase 8: corpus 35, chunking 16, context/generation 32, pipeline 27, e2e/protection/report 21) with all stores present. Store-dependent tests skip with an explicit reason when the stores or model are missing.
