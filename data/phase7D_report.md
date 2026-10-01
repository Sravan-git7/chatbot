# Phase 7D report: Citation flow

Status: implemented and tested. No commit, no push, no network, no vector-store rebuild, no `rag_chat.py` edit, no answer generation, no LLM. Phases 7E, 7F and 7G were not started.

## 1. What the spec defines as 7D

`data/phase6_next_phase_spec.md`, section 5: **7D = "Citation flow"**. It is not page ingestion or fetching, so nothing was fetched, scraped or ingested. The provenance chain below is built only from data already in the repository.

The spec requires:

- Every `sources` entry has `title`, `url` and `origin` (`page_chunk` or `card_route`).
- Routed items also carry `citation`, `source_id`, `source_status`, `review_flag` and the recorded review reason.
- URLs are never rewritten. Where a numeric-deliverable chunk URL and a loio card URL differ, both are shown and the join is recorded by page id.
- `needs_review` cards (#14, #18, #23) carry their flag. None are dropped or corrected.
- The list is labelled "sources provided to the model". A `card_route` entry is never presented as used text.

## 2. Files added

| File | Purpose |
|---|---|
| `scripts/m2c_citations.py` | Citation builder. Uses `m2c_page_identity` (7C) and, only in `cite_query`, `m2c_orchestrator` and `m2c_router` (7A). No network, store, legacy-module or LLM imports. |
| `tests/test_phase7d.py` | 33 tests. |
| `data/m2c_citation_audit.json` | Deterministic citation entry for each of the 29 cards. |
| `data/phase7D_report.md` | This report. |

No 7A, 7B or 7C file, protected artifact, `rag_core.py` or `rag_chat.py` was modified. The same 9 tracked files are modified as before 7D.

## 3. Citation entry shape

**`card_route` entry** (from the 7A `RoutingOutcome.selected_card`, or any card mapping):

- `origin`, `title`, `url` (the card's stored `source_url`, byte-identical), `url_flag` (`NO_URL` or `URL_NOT_A_SAP_HELP_PAGE_URL` when the URL is missing or unparseable, otherwise null).
- `citation`, `source_id`, `source_status`, `source_url_status`, `review_flag`, `review_reasons`.
- `rank`, `distance` and `distance_metric` as stored by the router. No confidence is derived.
- `provided_as_context=false`, `used_as_answer_text=false`, `verified_used=false`.
- An `identity` block: the 7C status passed through unchanged, plus the effective and card ids, the #05 correction, the #18 conflict and probe evidence, and the local-content provenance. The local-content provenance carries `record_source_type`, `record_fetched_via`, `is_legacy_local_copy` and `fresh_network_fetch_claimed=false`.
- `flags` (for example `PAGE_IDENTIFIED_NOT_LOCAL`) and a statement that the entry is a pointer, not page text.

**`page_chunk` entry** (from a legacy-shaped retrieval result or a bare chunk dict):

- `origin`, `title`, `url` as stored, and `url_flag`.
- `page_id`, `chunk_id` and `doc_id` where present. The chunk text is not copied (only `chunk_chars`).
- `provided_as_context=true`, `used_as_answer_text=null` (unknown: the legacy code does not verify usage), `verified_used=false`.
- `card_url`, the routed card's own URL, shown beside the chunk URL.
- A `join` block: `joined_to_card`, `by="page_id"`, both page ids, the chunk URL segment and its kind, `guide_relation` and `reason`.

**Join rule.** A chunk is joined to the routed card only if all three hold:

1. The page ids are equal.
2. The card has an effective identity.
3. The guide relation is established independently of the URL string. That means the chunk's guide id equals the effective guide id, or its loio URL segment does, or its numeric deliverable is a recorded unique pair for that guide.

Otherwise `joined_to_card=false` with a reason: `PAGE_ID_EQUAL_GUIDE_NOT_ESTABLISHED`, `PAGE_ID_DIFFERS`, `CARD_HAS_NO_EFFECTIVE_IDENTITY_*`, `CHUNK_HAS_NO_PAGE_ID` or `NO_ROUTED_CARD`.

**Recorded numeric pairs** (from the verified registrations): `40374631` → `e52c8ee6…` (M2C-17), `40374633`, `40374682`, `40374790` and `40404052`, each with its own guide. `40374657` is deliberately **not** paired because a recorded source lists it for more than one guide, so it is never converted to a guide by inference.

**Label.** `format_sources` prints "Sources provided to the model (page_chunk = retrieved context, not verified as used; card_route = topic pointer, not page text)". When only a card route exists it prints "…card route only (topic identification; no page text was provided)". No card selected gives an explicit "(none)".

Example, M2C-17 with a legacy chunk (both URLs shown, joined by page id `0bfcc553…` through the recorded pair):

```
1. [card_route] Contract Accounts Overview (M2C-17) | identity=resolved_local_page
   https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/e52c8ee6…/0bfcc553….html
2. [page_chunk] Contract Accounts | joined_to_card=True (by page id; numeric_deliverable_recorded_pair)
   https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/40374631/0bfcc553….html
```

## 4. Results over the 29 cards (`data/m2c_citation_audit.json`)

- Every card has a non-empty `url` and `url_flag=null`, with a `card_route` origin.
- `review_flag=true` for exactly **M2C-14, M2C-18 and M2C-23**, each with its recorded reasons and its URL shown unchanged.
  - #14: lower-case product segment.
  - #18 and #23: the `?version=2025.001` query string.
- Identity status counts are unchanged from 7C: 1 `resolved_local_page` (M2C-17), 23 `identified_not_local`, 1 `corrected_identity` (#05), 3 `card_identity_only` (#1, #13, #16), 1 `conflicting_identity` (#18).
- #18 keeps no effective guide. The conflict and probe evidence (`e4375c1c…`) are shown and not resolved, and a chunk routed to #18 is never joined.
- #05's correction is shown as metadata. The card URL is not rewritten.
- The only card with local content is M2C-17. Its content is a legacy local copy (`legacy_local:sap_pages/041.json`) and is not relabelled as a network fetch.
- `used_as_answer_text` is `false` for all 29 entries.

## 5. Tests

`tests/test_phase7d.py`: 33 tests, all passing. They cover the spec's "Citations" tests:

- **Non-empty URL or explicit flag:** all 29 cards, plus missing-URL and unparseable-URL chunks.
- **Origin set correctly:** `card_route` and `page_chunk`.
- **Review-flag cards:** #14, #18 and #23 carry their flag and reasons, and only those three are flagged.
- **No URL rewritten:** card URLs are byte-identical to the manifest; the numeric chunk URL and the loio card URL are both shown.
- **`card_route` not reported as used:** `used_as_answer_text`, `verified_used` and `provided_as_context` are all false.

They also cover:

- join by page id via the recorded pair;
- no join for an equal page id with an unestablished guide, for the ambiguous `40374657`, or for a different page id;
- the #18 conflict and the #05 correction staying intact;
- #1, #13 and #16 staying `card_identity_only`;
- the local-content provenance;
- no-card giving no sources;
- audit determinism, CLI equality and the committed audit matching the generator;
- an AST check for no network, store, legacy or LLM imports, and `rag_chat.py` untouched by 7D;
- pinned hashes for `data/source_manifest.json` and `data/card_collection_manifest.json`.

**Full suite:** `pytest tests` → **387 passed, 24 skipped, 0 failed**. The baseline was 354 passed and 24 skipped, so 7D adds 33 tests. The 24 skips are the store-dependent tests (the vector store is absent). The existing hash-pinned checkpoint tests still pass, so protected artifacts are unchanged. `git diff --check` is clean.

Environment note: `/tmp/av` was recreated from PyPI for testing, with the same pins as before (`chromadb==1.5.9`, `sentence-transformers==6.1.0`, `gt-all-minilm-l6-v2==0.1.0`). It is outside the repository.

## 6. What 7D does not do

- It does not ingest or fetch any page. Only M2C-17 has local content, and its SAP content is not verified.
- It does not wire citations into `rag_chat.py` (7G, optional) or change retrieval.
- It does not create page chunks for the card route. `page_chunks` are supplied by the caller. The real legacy chunk shape (`title`, `url`, `text` with numeric-deliverable URLs) is handled.
- It does not claim usage. `used_as_answer_text` for a `page_chunk` is `null` because the legacy flow does not verify it.

## 7. Git state

Nothing is committed or staged. `scripts/m2c_citations.py`, `tests/test_phase7d.py`, `data/m2c_citation_audit.json` and `data/phase7D_report.md` are new untracked files. HEAD is still `d85c31e`, and the earlier consolidation commit `a4182ff…` is still lost (the working tree persists). `data/repository_consolidation_report.md` still cites that hash. Nothing has been pushed.

## 8. Next phase per the spec

**7E** is router and regression evaluation (`scripts/evaluate_two_stage.py`). It covers router recall through the adapter, legacy regression over the 30 questions, and the answerable-subset comparison. That subset is too small today (one local topic), so `routed` stays off. 7F covers out-of-domain card queries and an optional threshold. 7G is an optional CLI switch.
