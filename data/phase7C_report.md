# Phase 7C report - deterministic card -> SAP page identity layer

Scope kept: local files only. No scraping, no network, no ingestion, no LLM, no answer generation, no change to M2C retrieval or the legacy pipeline, no embedding or vector-store rebuild, no commit, no push.

**Headline:** 29 cards audited. **1** `resolved_local_page` (M2C-17), **23** `identified_not_local`, **1** `corrected_identity` (M2C-05), **3** `card_identity_only` (M2C-01, 13, 16), **1** `conflicting_identity` (M2C-18), **0** `unresolved`.
**Full suite: 354 passed, 24 skipped, 0 failed.** (The 24 skips are the store/model-dependent tests: 17 in `test_phase7b.py`, 5 in `test_card_retrieval_eval.py`, 2 in `test_phase5.py`. `data/vector_store/` does not exist and 7C forbids rebuilding it, so they skip by design. They passed in 7B with the store present. `tests/test_phase7c.py`: 48 tests, all passing; it needs no store.)

## 1. Source-of-truth rules
Written before the code: `data/m2c_page_identity_rules.md`. Summary:

| Question | Authoritative | Cross-checked only |
| --- | --- | --- |
| Card / source id | `data/retrieval_units.json` `source_id` / `source_number` | `topic_manifest` `topic_id`, `source_manifest` `id` |
| Card URL | `data/source_manifest.json` `authoritative_source` (verbatim copy in the router's `source_url`); never rewritten | `topic_manifest.url_as_given` |
| Card guide / page id | parsed from the card URL, nothing else | `topic_manifest.guide_id` / `page_id` |
| Corrections | `data/topic_corrections.json` only | its saved-response evidence is re-read; the user-reported browser observation is `machine_verified: false` and never counted |
| Verified guide registration | `data/guide_registrations.json`: `response_loio_verified` + saved TOC whose own loio equals the guide + a saved capture with that loio and a declared page. Exception: e52c8ee6 via the registry's local-evidence entry (`master_data.json`) | `guide_registry.json` and `final_corpus_manifest.json` are kept as stale sources |
| Saved TOCs | `data/toc/<guide>.json` (5) and `master_data.json` (e52c8ee6) | - |
| Local page records | `data/sap_help/pages/<guide>/<page>.json`, valid, status OK, non-empty text (the `m2c_page_join` criteria) | - |

Never evidence: a numeric deliverable id, a title, a page seen in another deliverable/TOC, a probe. Never content: a URL, an HTTP 200, a TOC, a raw capture, an HTML shell, a probe, a title.

## 2. Identity-resolution rules (first match wins; `resolution_basis` names the reason)
1. Correction present: honoured only if it matches the card's ids, the corrected guide is verified, the page is a node of its TOC, and the saved response is re-confirmed by code -> `corrected_identity`; otherwise `conflicting_identity` with the reasons.
2. Card guide verified and page in its TOC -> `identified_not_local`, or `resolved_local_page` when a usable local record exists.
3. Card guide verified, page not in its TOC: other evidence exists -> `conflicting_identity`; nothing else -> `unresolved`.
4. Card guide not verified: a probe places the page under another loio and no correction -> `conflicting_identity`; else `card_identity_only` (effective ids are `null`; hints are listed as non-authoritative).
5. No card / no URL / not a SAP Help page URL (a numeric guide segment included) -> `unresolved`.

`effective_*` ids are only ever the card's own ids (after rule 2) or the correction's `resolved_guide_id`; they are `null` whenever the rules do not establish an identity. `unresolved` has no real card today; it is kept because the contract needs it for unusable input (the 7A join already had that state).

## 3. All 29 results
Full table with short ids: `data/m2c_page_identity_report.md` section 2; full ids and evidence: `data/m2c_page_identity.json`.

| Status | Cards |
| --- | --- |
| `resolved_local_page` | M2C-17 |
| `corrected_identity` | M2C-05 |
| `conflicting_identity` | M2C-18 |
| `card_identity_only` | M2C-01, 13, 16 (guide 021b182b, no verified registration, no TOC) |
| `identified_not_local` | M2C-02, 03, 04, 10, 29 (f4a255a5); 06, 07, 08, 09 (2ac7fe29); 11, 12 (ed84b70c); 14, 15 (a003b275); 19-28 (94424864, includes 23 and 24) |

The baseline "1 local, 28 not local" is verified for local content. Those 28 are not one class: 23 identified, 1 corrected, 3 card-only, 1 conflicting. The recorded `final_corpus_manifest.json` (RESOLVED 1 / UNRESOLVED_GUIDE 28) is stale relative to the current registrations and TOCs; it was left untouched and is shown as a stale source.

## 4. #05
`corrected_identity`. Card guide `021b182b...`, page `8990d053...`; effective guide `2ac7fe29...` (Device Management), same page. The card record, the correction and the registrations are unchanged (pinned by hash in tests); 021b182b is not registered. Evidence attached: the saved response `captured_responses/1_40374657_8990d053...json` is machine re-checked (response loio = 2ac7fe29, currentPage = 8990d053); the user-reported browser observation is carried as `machine_checked: false`. The page is the landing page and a node of the verified 2ac7fe29 TOC. Numeric 40374657 is never used as an identity. Not local.

## 5. #18
`conflicting_identity`; not a correction. Card guide 94424864..., page `b1a202c9...` preserved; `card_needs_review` true (source and URL status `needs_review`). The card page is **not** a node of the saved 94424864 TOC (1481 nodes). The probe (`captured_responses/1_40374490_b1a202c9...json`, response loio `e4375c1c...`, "Enterprise Services in Financials") is attached with `authority: probe_evidence_only`, `used_as_effective_guide: false`, registered: false. `effective_guide_id` and `effective_page_id` are `null`. e4375c1c is not registered and appears in no identity field.

## 6. M2C-17 provenance chain (validated end to end)
card M2C-17 `source_url` (= `source_manifest` = `topic_manifest`) -> guide `e52c8ee6197147ec97dfc2eb8c46a3ad`, page `0bfcc5536a51204be10000000a174cb4` -> guide verified by the registry's local-evidence entry (not in `guide_registrations.json`; `master_data.json` TOC, loio equals guide id) -> page is a TOC node -> `data/sap_help/pages/e52c8ee6.../0bfcc553....json` -> valid JSON, status OK, 2683 characters of text, record guide/page ids equal the effective and the card ids, file location equals ids, `topic_ids` includes 17. All 11 checks pass (`local_page_validation` in the JSON). Provenance caveat: the record's `source_type` is `legacy_local_copy` (`fetched_via legacy_local:sap_pages/041.json`), i.e. it comes from the legacy local corpus, not a fresh fetch. The page file is unchanged (hash pinned).

## 7. Local pages
1 usable local page record (1 file indexed). Raw captures, TOCs, status != OK and empty-text records are tested as not local.

## 8. Unresolved / conflicting cases
Conflicting: M2C-18 only. Unresolved: none among the 29. Card-identity-only: M2C-01, 13, 16. Also visible but identity-neutral: M2C-14 (`needs_review`, lower-case product segment), M2C-23 (`needs_review`, `?version=2025.001`); pages of M2C-14/15 also appear in ed84b70c's TOC (hint only); M2C-01's page equals the map root of the e52c8ee6 TOC (hint only, not confirmed).

## 9. Join and orchestrator: not modified
Not necessary. The 7A join and orchestrator are pinned by hash in `tests/test_phase7b.py` and their states stay valid. The composition is additive in `scripts/m2c_page_identity.py`: `route_to_identity(query, backend, ctx)` calls the unchanged `route_to_page`, then resolves the identity and returns `IdentityRoute` (route state = identity status or `no_card_candidate`, `page_content_available`, `local_page_path`, the 7A join state, warnings). It carries no page text. M2C-17 routes to `resolved_local_page`; M2C-07 to `identified_not_local`; M2C-01 to `card_identity_only`; M2C-05 to `corrected_identity`; M2C-18 to `conflicting_identity` with warnings; no candidate to `no_card_candidate`. `identified_not_local` is never mapped to `resolved_page` (the 7A join still says `url_only` for it).

## 10. Files
Created: `scripts/m2c_page_identity.py`, `data/m2c_page_identity_rules.md`, `data/m2c_page_identity.json`, `data/m2c_page_identity_report.md`, `tests/test_phase7c.py`, `data/phase7C_report.md`.
Modified: none. The tracked-modification set is the same 9 files as before 7C. No store, `sap_docs` or `chroma_db` was created.
Environment: the test venv `/tmp/av` was recreated by `pip install` from PyPI (pytest, pypdf, beautifulsoup4, requests, numpy, chromadb 1.5.9, sentence-transformers 6.1.0, gt-all-minilm-l6-v2 0.1.0). This is test tooling only and is outside the repo.

## 11. Tests (`tests/test_phase7c.py`, 48)
Identity (29 cards, deterministic, ids/URL exact, no inference, hints not promoted, #14/#23, guide-verification history, card-only); #05 (4); #18 (3); local content (M2C-17 real, others not local, TOC/capture/bad-record cases); conflict handling on synthetic roots (unverified or mismatching corrections, page not in TOC, probe without correction, registration without a matching saved response, TOC loio mismatch, unusable cards, source disagreements); orchestration (resolved, identified, card-only, corrected, conflicting, unresolved, no-candidate, no text, unchanged 7A modules, subprocess with sockets blocked and no LLM/legacy/heavy module loaded, AST import check); determinism (two runs byte-identical, committed artefacts equal a fresh run, no timestamps or absolute paths); protected inputs pinned by hash. No old expectation was edited.

## 12. Remaining ambiguity
* Which guide SAP serves for #1, #13, #16: unknown (guide 021b182b unverified; no TOC, no own response). They stay `card_identity_only`.
* #18: which guide/page the card author meant is not established; only a constructed probe exists. A decision (and any correction/registration) is for the user.
* "Verified" for five guides rests on one saved response each, checked per guide, not per page. Page-level identity rests on TOC membership. Whether SAP serves each original card URL from that guide is not confirmed for any card except #5 (user-reported browser observation, not machine verified).
* M2C-17's guide is verified only by the registry's local-evidence entry; the page content is a legacy local copy.
* `data/guide_registry.json` and `data/final_corpus_manifest.json` are stale relative to the registrations and TOCs; regenerating them is out of scope.
* All 23 `identified_not_local` pages, plus #05, still need ingestion before any content exists. That belongs to a later phase.
