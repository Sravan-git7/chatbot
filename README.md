# SAP S/4HANA Utilities RAG assistant (local)

Answers questions strictly from the indexed SAP Help documentation
(81 pages, 310 chunks) using ChromaDB + `all-MiniLM-L6-v2` for retrieval and a
local Ollama model (`llama3.2:3b`) for generation. Nothing leaves the machine
at query time.

## Setup

```
pip install -r requirements.txt
ollama pull llama3.2:3b
```

## Build the index (only needed once, or after the data changes)

`chroma_db/` is git-ignored, so rebuild it on a fresh checkout. Scripts can be
run from any directory.

```
python scripts/clean_sap_pages.py    # sap_pages/*.json -> cleaned_pages.json
python scripts/chunk_pages.py        # cleaned_pages.json -> chunks.json
python scripts/create_embeddings.py  # chunks.json -> chroma_db (collection sap_docs)
```

## Use

```
python scripts/rag_chat.py           # chat
python scripts/retrieve.py           # show retrieved chunks for one question
```

## Evaluate

```
python scripts/evaluate_retrieval.py                     # baseline: raw dense top-k (original numbers)
python scripts/evaluate_retrieval.py --strategy improved # pipeline the chatbot uses
python scripts/evaluate_retrieval.py --compare           # all strategies side by side

python scripts/evaluate_answers.py --retrieval-only      # no LLM needed
python scripts/evaluate_answers.py                       # full answer-quality run (needs Ollama)
python scripts/evaluate_answers.py --self-test           # test the checker itself
```

`data/evaluation_questions.json` (30 questions) drives retrieval evaluation;
`data/answer_quality_questions.json` (27 questions) drives answer-quality
evaluation. Retrieval strategies live in `scripts/rag_core.py`.

## Distances

The collection uses ChromaDB's default **squared L2** distance on unit vectors:
`distance = 2 - 2*cosine`. Lower is closer; `MAX_DISTANCE = 1.0` means
cosine similarity >= 0.5. It is not a cosine distance.

## Corpus ingestion pipeline (29 target topics)

Builds a clean, deduplicated, chunked **source corpus** for the 29 topic cards. It is completely separate from the
legacy RAG data (`sap_pages/`, `chunks.json`, `chroma_db/`), does **no embedding**, and never touches ChromaDB.

```powershell
python scripts/build_corpus.py                                  # cache only, network OFF (default); fails clearly if pages are missing
python scripts/build_corpus.py --offline                        # cache + the saved legacy copies of the one verified guide
python scripts/build_corpus.py --allow-network                  # explicit opt-in: SAP Help content API, retries, robots/ToS are YOUR call
python scripts/build_corpus.py --allow-network --require-complete   # exit 1 unless all 29 topics are RESOLVED
python scripts/build_corpus.py --offline --scope page_and_descendants --out-dir data/sap_help_e2e/page_and_descendants
python scripts/build_corpus.py --offline --topic-scope 17=page_and_descendants --max-depth 2
python scripts/compare_with_legacy.py data/sap_help_e2e/page_and_descendants
```

Pipeline: validate 29-topic manifest -> guide registry (+ `data/guide_registrations.json`) -> saved TOCs -> topic/page
resolution -> scope expansion (`page_only` | `page_and_descendants`, `--max-depth`, per-topic overrides) -> fetch
(raw cache in `<corpus>/raw/`) -> page-identity dedup (guide_id + page_id) -> content dedup (normalised hash; one
canonical document, `duplicate_of` on the rest, every topic link kept) -> clean -> chunk -> statistics ->
`data/final_corpus_manifest.{json,md}`.

Output (`data/sap_help/`): `pages/<guide_id>/<page_id>.json` (raw + cleaned text + full identity),
`chunks/chunks.jsonl` (ids `<guide_id>/<page_id>#NNNN`), `chunks/embedding_input.jsonl` (for a later embedding step),
`corpus_stats.json`, `logs/`. Exit codes: 0 ok, 1 incomplete with `--require-complete`, 2 fetch/registration
failure, 3 invalid input. Unresolved guides are reported as `UNRESOLVED_GUIDE` (counts UNKNOWN, never 0) and skipped
while other guides continue.

**Adding one of the six missing guides (no code change):** each guide needs two numbers that exist in no local file:
the numeric `deliverable_id` and the `buildNo` of the `http.svc/pagecontent` request the browser makes for that
guide (the same two parameters `fetch_sap_pages.py` uses). Then:

```powershell
python scripts/guide_intake.py template        # (done) fill-in skeletons for the 6 guides in data/guide_registrations.json
python scripts/guide_intake.py status          # what is known / missing per guide
python scripts/guide_intake.py add --guide-id <32hex> --pagecontent-url "<request URL copied from DevTools>"
python scripts/guide_intake.py add --guide-id <32hex> --numeric-id <digits> --build-no <digits> [--toc-file saved.json]
python scripts/guide_intake.py check           # offline validation
python scripts/build_corpus.py --allow-network --require-complete
```

With ids registered and no saved TOC, `--allow-network` downloads ONE TOC per guide, refuses it unless its `loio`
equals the registered `guide_id` (wrong ids are rejected, nothing is saved), stores it in `data/toc/<guide_id>.json`
and continues: resolve -> scope -> fetch -> dedup -> clean -> chunk -> manifest. Ids are never guessed; a 32-hex
loio is rejected as a numeric id; conflicting values are refused. You can also edit `data/guide_registrations.json`
by hand (`numeric_id`, `build_no`, or `pagecontent_url`; optional `toc_file`).

**Captured browser URLs:** put them (one per line) in `data/captured_pagecontent_urls.txt` (`&amp;` is accepted) and run
`python scripts/guide_intake.py capture --allow-network`. Each request is replayed once (read-only GET); the response's
`deliverable.loio` decides which guide it belongs to, the response (which contains the full TOC) is saved to
`data/toc/<guide_id>.json`, and the guide is registered. A numeric id that would identify two different guides is held
(`AMBIGUOUS`) and registered for neither. Without `--allow-network` the mapping uses only the card page ids and is marked
`card_page_match_unverified`. Report: `data/captured_url_mapping.{json,md}`.

**No network in the place where the code runs?** `scripts/capture_responses.py` is a single stdlib-only file: run it on a
machine that can reach SAP Help (it replays your captured URLs read-only and saves each response plus a summary that shows
every response's `loio`), then run `python scripts/guide_intake.py capture --responses-dir captured_responses` anywhere.
A response is accepted only if its `loio` is a card guide, equals the guide named by the card carrying that page id, and its
`currentPage` is the requested page; otherwise the URL is reported (`CARD_MISMATCH`, `PAGE_MISMATCH`, `AMBIGUOUS`, ...) and nothing is registered.

**Audit + legacy comparison after a build:** `python scripts/audit_corpus.py [corpus_dir]` (topics/guides resolved, pages and
chunks per guide/topic, duplicates, chunk sizes, pages outside target topics, suspicious or cross-guide pages, failed fetches,
`ready_for_embedding`) and `python scripts/compare_with_legacy.py [corpus_dir]`. A numeric `deliverable_id` may be shared by
several guides; identity is always the response `loio` + requested page, re-verified on every TOC/page fetch. URL files may
contain a BOM / be UTF-16 / contain zero-width characters: they are cleaned programmatically.
