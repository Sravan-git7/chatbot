# Phase 6 - retrieval integration map

Read-only analysis. Sources: `scripts/rag_core.py`, `rag_chat.py`, `retrieve.py`, `evaluate_retrieval.py`, `create_embeddings.py`, `fetch_sap_pages.py`, `scripts/build_card_collection.py`, `scripts/evaluate_card_retrieval.py`, `data/retrieval_units.json`, `data/card_collection_manifest.json`, the Phase 4 and 5 result files, `data/final_corpus_manifest.json`, `data/guide_registry.json`, `data/toc/`, `captured_responses/`, `chunks.json`. Line numbers refer to the current working tree and are approximate for ranges. Nothing was executed against either collection (both stores are absent from this checkout), so statements about runtime behaviour are derived from the code and from recorded results, and are labelled as such.

## A. The existing (legacy) RAG pipeline as implemented

```
user question (rag_chat.py: input("You: "))                               rag_chat.py:~48
 -> generate_answer(question, strategy="improved")                         rag_core.py:402
 -> search(question, top_k=TOP_K=3, strategy)                              rag_core.py:327
      query processing: strip(); empty -> []  (no other rewriting)         rag_core.py:_search_pipeline
      embedding: SentenceTransformer("all-MiniLM-L6-v2").encode([q], normalize_embeddings=True)   rag_core.py:183-205
      retrieval: collection.query(n_results=CANDIDATE_K=10)                rag_core.py:183-205
      filter: keep candidates with distance <= MAX_DISTANCE=1.0            rag_core.py:252-265
      rerank: final = 0.60*semantic + 0.30*title-term overlap + 0.10*body-term overlap    rag_core.py:207-237
      dedup: one chunk per page content (strategy "improved"), keep TOP_K=3                rag_core.py:165,265-297
 -> no results: fixed refusal text, LLM not called                         rag_core.py:411
 -> context: "SOURCE i / Title / URL / Content" blocks                     rag_core.py:378-393
 -> prompt: 10 strict grounding rules + context + question                 rag_core.py:341-375
 -> ollama.chat(model="llama3.2:3b", options={"temperature":0,"seed":42})  rag_core.py:419
 -> answer text + list of the retrieved chunks
 -> sources: rag_chat.print_sources prints title, squared-L2 distance, cosine, final_score, URL   rag_chat.py:12-28
```

| Question | Answer (from the code) |
| --- | --- |
| Where is the collection accessed? | `rag_core.get_collection()` (line 80), a cached `chromadb.PersistentClient(path=DB_DIR).get_collection("sap_docs")`. Also `_document_fingerprints()` reads the whole collection for dedup (line 140). |
| Which store? | `chroma_db/` at the repository root, collection `sap_docs`. `sap_docs` is the only collection the application code knows. `chroma_db/` is gitignored and absent here. It is created by `create_embeddings.py` (recreates the collection every run). |
| Where are embeddings generated? | Indexing: `create_embeddings.py` (`model.encode(texts, normalize_embeddings=True)`). Query time: `rag_core.get_embedding_model()` (cached `SentenceTransformer("all-MiniLM-L6-v2")`, resolved by name through the Hugging Face cache). |
| Where does retrieval happen? | `rag_core._query_candidates` -> `collection.query`, then `_search_pipeline`. Three strategies: `baseline` (raw dense top-k), `current` (filter, rerank, URL dedup), `improved` (`current` plus content dedup; the default). |
| `TOP_K` | `rag_core.TOP_K = 3` (chunks sent to the LLM). `CANDIDATE_K = 10`. The `retrieve.py` CLI defaults to 5, and the evaluators use up to 5. |
| Distance semantics | Collection has no `hnsw:space`, so ChromaDB's default **squared L2** on unit vectors: `distance = 2 - 2*cosine`. `MAX_DISTANCE = 1.0` means cosine >= 0.5. `rag_core.distance_to_cosine` converts. |
| Metadata expected | Exactly two keys, `title` and `url` (set in `create_embeddings.py`). Ids are `chunk_<n>`. The code reads `metadata["title"]`, `metadata["url"]` (context, dedup, printout) and parses the chunk index from the id (`_chunk_index`). |
| How citations are produced | There is no structured citation object. The context block tells the model the title and URL of each source, and rule 10 of the prompt asks the model to "mention only the source title(s) actually used". The CLI separately prints **all retrieved chunks** ("sources provided to the model"), which is not proof of what the answer used. The URL shown is the SAP Help page of the chunk. |
| Where does SAP page content enter? | `fetch_sap_pages.py` (network; hard-wired to deliverable 40374631, build 1779, reads `master_data.json` for the table of contents) -> `sap_pages/*.json` (81 pages) -> `clean_sap_pages.py` -> `cleaned_pages.json` -> `chunk_pages.py` (<=1000 characters) -> `chunks.json` (310 chunks, 75 distinct titles, 81 URLs) -> `create_embeddings.py` -> `chroma_db`. All 81 pages belong to one guide (`e52c8ee6...`, "Master Data", numeric 40374631). |
| Card-level or page-level content? | **Page-level only.** The application has no notion of cards. No file in the runtime chain (`rag_core`, `rag_chat`, `retrieve`) references the M2C cards, `sap_m2c_card_v1`, the resolver or `data/sap_help`, and tests enforce that. |
| Can `sap_m2c_card_v1` be introduced without replacing the existing system? | **Yes, technically.** It lives in a different directory (`data/vector_store/`) and has a different name; it uses the same embedding model name, so the same loaded model can embed queries for both; the card scripts refuse to write to `sap_docs` or to any directory named `chroma_db`. Constraint: `rag_core.get_collection()` is a single-collection singleton, so a second collection needs its own accessor rather than a parameter change to the existing one. |
| Failure behaviour | Missing `chroma_db/` -> `FileNotFoundError` with rebuild instructions; missing collection -> `RuntimeError`; `rag_chat` converts both to `SystemExit`. Empty query -> `[]`. Nothing within `MAX_DISTANCE` -> the refusal message and no LLM call (the five out-of-domain evaluation questions return no results under `improved`). Ollama errors are caught per question in the chat loop. |

Legacy baseline numbers (recorded in `data/retrieval_results*.json`, 25 scored questions): loose Top-1/3/5 = 22/24/25 (88/96/100%), strict 18/22/23, both `baseline` and `improved`. The `baseline` strategy shows the same document twice within its top 5 for 20 of 25 questions, the `improved` strategy for none. The legacy questions target legacy page titles ("Master Data", "SAP Business Partner", ...). **No card title equals any legacy page title** (checked: 0 of 29).

## B. Legacy interface vs the new card collection

| Aspect | Legacy (`sap_docs` via `rag_core`) | New (`sap_m2c_card_v1`, Phases 4-5) |
| --- | --- | --- |
| Status in the application | The production retriever | Not connected to anything; evaluation-only |
| Collection / store | `sap_docs` in `chroma_db/` | `sap_m2c_card_v1` in `data/vector_store/` |
| Indexed unit | Chunk of a SAP Help page (<=1000 characters, 310 chunks) | One whole card per vector (29 vectors); document = `embedding_text` (458 to 600 characters) |
| What the unit contains | Actual SAP documentation text | A 2-sentence description ("What it covers", "Meter-to-Cash relevance"), the category and the SAP Help URL. **No procedure, no SAP page body** (example M2C-17 below) |
| Embedding model / dimension | `all-MiniLM-L6-v2`, 384, loaded by name | `all-MiniLM-L6-v2`, 384, weights found locally by `resolve_model` (pip package `gt-all-minilm-l6-v2` in the sandbox; third-party re-packaging, provenance recorded in the manifest) |
| Normalisation | Normalised embeddings | Normalised embeddings |
| Distance space | Default **squared L2** (`d = 2 - 2cos`, range 0 to 4) | **Cosine** (`d = 1 - cos`, range 0 to 2) |
| Threshold | `MAX_DISTANCE = 1.0` (cos >= 0.5) | None defined. No out-of-domain queries exist in the card evaluation sets |
| Query input | A plain string, stripped; empty returns `[]` | A plain string; the evaluation helpers take question dictionaries (`query_collection(collection, model, questions, n_total)` in `evaluate_card_retrieval.py`). There is no production-shaped `search(question, top_k)` for cards |
| Output (in use) | List of `{document, metadata, distance, cosine}` (+ `semantic_score`, `title_score`, `keyword_score`, `final_score` after rerank) | Evaluation helper returns `{source_id, title, cosine_similarity}` rows; a raw Chroma query returns documents, metadatas, distances |
| Ids | `chunk_<n>` | `M2C-01` ... `M2C-29` (equal to `retrieval_unit_id`) |
| Metadata keys | `title`, `url` | `retrieval_unit_id`, `source_id`, `source_number`, `title`, `category`, `filename`, **`source_url`**, `source_status`, `source_url_status`, `has_source_correction`, `citation`, `sha256`, `corpus_document`, `page_start`, `page_end`, `embedding_text_sha256`, `full_text_sha256` |
| Top-k behaviour | candidates 10, filter, rerank, dedup, final 3 (strategy `improved`) | Raw dense ranking over all 29 (evaluations use n = 29). No rerank or dedup |
| Provenance / citation fields | `title` + `url` only (no guide, page or topic id; the url carries the numeric deliverable) | `citation` string (`[17] Contract Accounts Overview (17_Contract_Accounts_Overview.pdf, sha256:0b07f58bc21c)`), PDF file name and sha256, corpus record pointer, `source_status` (`verified` for 26, `needs_review` for M2C-14, M2C-18, M2C-23), `source_url_status`, correction flag; the SAP URL uses the 32-hex guide loio and page id |
| Failure behaviour | See section A | Build refuses the legacy collection/directory names, stale or over-limit token statistics, and a non-empty target; evaluation raises `SystemExit` with rebuild instructions if the store is missing. No refusal or fallback semantics exist |
| Measured quality | Legacy: loose 88/96/100% (Top-1/3/5) on its 25 questions | Phase 4 wording (50 q): R@1 0.92, R@3 0.96, R@5 1.00, MRR 0.95. Independent wording (54 q): R@1 0.7222, R@3 0.7963, R@5 0.8704, MRR 0.7873 (dense; hybrid not adopted) |

M2C-17's whole embedded text, as an example of what a card contains:

```
SAP Utilities M2C Source Reference 17
Contract Accounts Overview
Category: FI-CA / Contract Accounting

What it covers
Foundation reference for contract accounts and their role in subledger processing.

Meter-to-Cash relevance
Use to connect utility invoicing to receivables, payments and dunning.

Authoritative SAP Help source
Open this topic on SAP Help Portal
https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.html
```

## C. Incompatibilities: what silently goes wrong if the card collection is passed to the legacy code

These follow from reading the code. They were not executed, because neither store exists in this checkout.

1. **Missing `url` key.** The legacy code reads `metadata["url"]`; cards store `source_url`. The code would not crash: `metadata.get("url", "")` returns `""`, so context blocks and printouts would show an empty URL, and dedup would fall back to the title. The result: answers with **no citation URLs**, and no error.
2. **Matching `title` key.** Cards also use `title`, so `rerank_candidates` and the printouts would run without error, which hides problem 1.
3. **Distance scale.** Legacy `MAX_DISTANCE = 1.0` on squared L2 means cosine >= 0.5. Fed raw cosine distances, the same constant would mean cosine >= 0, i.e. it would accept nearly everything and silently disable the refusal gate. Converting properly (`cos = 1 - d`, keep cos >= 0.5) is the opposite problem (next item). `semantic_score = 1 - distance` would also change meaning: `2cos - 1` in the legacy space, `cos` in the card space, so the 0.60/0.30/0.10 weights would no longer mean what they were tuned for.
4. **The legacy threshold does not fit card similarities.** From the recorded Phase 4/5 dense rankings: with cos >= 0.5, the top-1 card survives for **15 of 54** independent queries (27.8%) and **34 of 50** Phase 4 queries. Only **14** of the 39 independent queries whose correct card is ranked first would survive the gate. The median top-1 cosine is 0.381 (independent) and 0.554 (Phase 4). The legacy gate was calibrated on page chunks (the out-of-domain questions there have nearest squared-L2 distances 1.09 to 1.71, i.e. cosine 0.45 down to 0.14). No out-of-domain queries exist for the card collection, so **no refusal threshold for cards is supported by evidence today**.
5. **Dedup and fingerprints.** `_document_fingerprints()` reads chunk ids `chunk_<n>` and the `url` key of the legacy collection; it has no meaning for cards (one vector per card, no duplicates).
6. **Content mismatch.** The prompt says "SAP DOCUMENTATION" and asks for answers "ONLY from the SAP documentation provided". A card is a two-sentence summary plus a link, so the model would answer from the summary lines, or refuse. This is not SAP page content.
7. **Model weights.** The legacy code loads the model by name (Hugging Face cache). The card collection was built from the PyPI re-packaging of the same model in the sandbox. If the application embeds queries with one set of weights and the collection was built with another, the two must be checked to be equivalent; the collection manifest records the provenance.
8. **Store identity and location.** `data/vector_store/` is gitignored and must be rebuilt on whichever machine runs the application (the user's shell is Windows PowerShell). Chroma rewrites bookkeeping files when a store is opened, so identity checks must use vector content, not file hashes.

## D. Adapter needed (not implemented)

A card retriever cannot be used through the legacy interface as it is. A thin adapter would have to supply, at minimum:

| Adapter duty | Why |
| --- | --- |
| Open `sap_m2c_card_v1` from `data/vector_store/` through its **own** accessor (separate client, separate cached singleton); never through `get_collection()` | Keeps the two stores independent and the legacy singleton untouched |
| Reuse the same embedding model instance and the same normalisation | One model in memory; consistent query vectors |
| Provide a function with the same shape as `search(question, top_k)` | Uniform calling convention |
| Return records with the **legacy keys plus card keys**: `document`, `metadata`, `distance`, `cosine`, and `metadata["url"] = source_url` (alias, original kept) | Avoid the silent empty-URL problem |
| Convert distances explicitly (`cosine = 1 - d`) and expose **cosine only**, never the legacy squared-L2 field as if comparable | Avoid the scale confusion in section C.3 |
| Carry `source_id`, `source_number` (topic id), `citation`, `source_status`, `source_url_status`, `has_source_correction` through unchanged | Provenance and the `needs_review` state must reach the citation layer |
| Own its threshold policy (initially **none**, return top-k) and a defined empty-result and store-missing behaviour | The legacy 0.5-cosine gate is unsuitable (section C.4); the store may be absent |
| Keep card text out of the LLM "documentation" context unless labelled as a routing summary | Section C.6 |
| Expose the join key to the page stage: `source_number` = topic id, plus the page id parsed from `source_url` (last 32-hex segment) | See section E |

## E. Architectural boundary: what the repository actually supports

### Evidence

1. **Cards are descriptions, not answers.** The 29 cards are 974 to 1116 characters of full text (458 to 600 of embedded text): a title, a category, a one- or two-sentence "what it covers", a relevance sentence, and the SAP Help URL. The full text also carries library-use and copyright boilerplate (Phase 0 measured 48% of the extracted PDF text as boilerplate); Phase 4 excludes only those two blocks from the embedded text. No card contains a procedure, definition list or configuration detail.
2. **The app answers from page text.** `rag_core` builds its context from chunk text of actual SAP Help pages and its prompt forbids outside knowledge; its evaluation questions (30 retrieval, 27 answer-quality) ask about page content and expect page titles.
3. **Local SAP page content exists for almost none of the 29 topics.**
   * The legacy corpus (81 pages, 310 chunks) is one guide ("Master Data", `e52c8ee6...`). Only card **M2C-17** points into it (its page id `0bfcc5536a51204be10000000a174cb4` appears in the legacy chunks, and in `data/sap_help/` as the one fully processed page, 4 chunks). The other 28 cards point to six guides that are not in the legacy corpus.
   * The recorded page-corpus build (`data/final_corpus_manifest.json`, `data/topic_resolution.json`, `data/sap_help/audit.md`) reports **1 of 29 topics resolved, 1 of 7 guides, `NOT READY`**; 28 topics are `UNRESOLVED_GUIDE`.
   * `data/toc/` now holds saved tables of contents for five more guides, and `captured_responses/` holds seven replayed page responses (raw HTML of single pages, 1.7 to 13.7 kB each). `data/captured_url_mapping.md` accepts five of them (topics 2, 7, 11, 14, 24), marks one `CARD_MISMATCH` (topic 5) and one `NOT_A_CARD_GUIDE` (topic 18's URL). **The recorded manifest and resolution files do not reflect these TOCs** (they show the state with one guide), so whether the page corpus was rebuilt after they were saved is unknown from the artefacts. No full page bodies for the remaining topics are stored.
   * So at most six of 29 topics (17 plus the five accepted captures) could have any page text locally today, and only topic 17 is in a processed, chunked form.
4. **The join keys exist.** Card metadata carries the SAP URL, so guide id (32-hex) and page id are recoverable; the new page corpus records use `guide_id`, `page_id`, `topic_id` (equal to the card number), `topic_title` and `source_url` on every chunk. The legacy chunks carry only `title` and a `url` with a numeric deliverable (a different URL shape), so the page id is the only reliable join there.
5. **Routing quality is bounded.** On user-style queries the card retriever puts the expected card in the top 5 for 87.0% of queries and at rank 1 for 72.2%. A hard "card first, then only that page" gate would lose the remaining 13% of queries (and 28% at rank 1) before page retrieval starts, whatever stage 2 does. Nothing in the repository measures page-level retrieval for the 29 topics.

### Conclusion (derived from the repository, not assumed)

* **Replacing the legacy page retriever with the card retriever is not supported.** It would feed two-sentence summaries into a prompt that promises SAP documentation, drop the URLs silently (section C.1), disable or over-trigger the refusal gate (C.3, C.4), and fail every existing evaluation question (no card title equals a page title). It would remove the only component that holds page text.
* **The correct target architecture is a separate, optional routing stage in front of page retrieval**: `query -> card retrieval (which SAP topics cover this?) -> topic/page identity (card -> guide + page) -> page-chunk retrieval restricted or boosted by that identity -> answer generation -> citations (page URL plus card provenance)`. It is the only design in which the cards' unique content (topic description, verified/needs-review status, source URL) is used for what it contains, and in which each citation traces to an actual SAP page.
* **It cannot be completed end to end today.** Stage 2 has page text for topic 17 only (and at most five further topics once the captured pages are ingested). A card-routed answer for the other 23 to 28 topics has no text to answer from. Until page content exists, the honest behaviours for a card-routed topic are (a) a **route-only response** ("this topic is covered by <title>; source: <URL>", no generated SAP content) or (b) the legacy refusal. Neither needs an LLM to invent content.
* **Open design question (not decided here):** whether card routing should be a hard gate, or a soft signal (boost or filter with fallback to the unrestricted legacy search), given that a hard gate caps recall at the card retriever's top-k recall. The evidence favours a fallback design but does not test it, and Phase 7 should measure it rather than assume it.
* **Not supported by evidence:** using hybrid (BM25) retrieval at the card stage. Phase 5 did not support it.
