# M2C card -> SAP page identity: source-of-truth rules (Phase 7C)

Written BEFORE `scripts/m2c_page_identity.py`. The code implements exactly these rules; `tests/test_phase7c.py` pins them.
Scope: local files only. No network, no scraping, no ingestion, no LLM, no change to retrieval.

## 1. Which file is authoritative for what

| Question | Authoritative source | Only cross-checked against (never overrides) |
| --- | --- | --- |
| **Card / source id** | `data/retrieval_units.json` -> `units[].source_id` (`M2C-NN`) and `source_number` (= topic id NN). This is what the 7A router returns. | `data/topic_manifest.json` `topic_id`; `data/source_manifest.json` `id` (`"NN"`). |
| **Card URL** | `data/source_manifest.json` `authoritative_source` (Phase 1 source of record, taken from the PDF link annotation). The router's `source_url` (units file) is its verbatim copy. The URL is never rewritten, never "fixed" (#14 casing, #18/#23 `?version=`). | `data/topic_manifest.json` `url_as_given`: any difference is reported as a disagreement. |
| **Card guide segment** | The guide segment (32-hex) **parsed from the card URL** and nothing else. | `topic_manifest.guide_id` (must be equal; a difference is reported). |
| **Card page id** | The page segment (32-hex) parsed from the card URL. | `topic_manifest.page_id`. |
| **Topic corrections** | `data/topic_corrections.json` only. A correction changes the *effective* guide, never the card record, and never registers a guide. It is honoured only if the corrected guide is verified (rule below) AND the card's page id is a node of that guide's saved TOC. Otherwise it is reported as `conflicting_identity`. | The correction's own saved-response evidence is re-read from `captured_responses/` (loio and currentPage must match). The user-reported browser observation is carried as `machine_verified: false` and is never counted as machine evidence. |
| **Verified guide registration** | `data/guide_registrations.json` (declarative). A guide is *verified* only if ALL hold: `verification == "response_loio_verified"`; its saved TOC exists and the TOC's own `deliverable.loio` equals the guide id; and (machine check) at least one saved `captured_responses/N_*.json` has `deliverable.loio == guide id` and a `currentPage.loio` listed in the registration's `captured_page_ids`. Exception with its own label: guide `e52c8ee6` is not in `guide_registrations.json`; `data/guide_registry.json` (status `verified`, `toc_file` = `master_data.json`, written by the legacy/local-evidence discovery) is its only source, and the TOC's own loio must still equal the guide id. | `data/guide_registry.json` for the other five guides says `unresolved` (stale, written before the registrations and TOCs were saved); `data/final_corpus_manifest.json` likewise says `RESOLVED 1 / UNRESOLVED_GUIDE 28`. Both are recorded as *stale sources*, not silently preferred or ignored. A guide with `verification` starting `unresolved` (021b182b) is **not** verified. |
| **Saved TOCs** | `data/toc/<guide>.json` (5 files) and `master_data.json` (e52c8ee6, via the registry's `toc_file`). Membership of a page in a TOC is tested on the TOC's page file names (`<32hex>[-NN].html`, alias suffix stripped, exactly as `sap_resolver/urls.py`). A TOC is a map of one guide; it is not page content. | -- |
| **Local page records** | `data/sap_help/pages/<guide>/<page>.json`, using the existing `m2c_page_join` criteria: a valid record whose `guide_id`/`page_id` match its path, `status == "OK"`, non-empty `text`. | -- |
| **Probe / capture evidence** | `captured_responses/N_*.json` (+ `captured_responses/summary.json`, `data/captured_url_mapping.md`): *evidence only*. | -- |

## 2. What is NEVER evidence of identity or of local content

* A numeric deliverable id (40374657 is shared by 021b182b's probe and 2ac7fe29; it never names a guide).
* A page title, or a page id that also appears in another guide's TOC or another deliverable's response.
* A probe response. It proves the page exists inside that deliverable; it does **not** prove that SAP serves the original card URL from it.
* The card URL, an HTTP 200, a saved TOC, a raw `captured_responses/*.json`, an HTML shell, a network probe, or a title: none of these is page content, so none makes a page local.
* The user-reported browser observation for #5 (`machine_verified: false`): recorded, not counted as machine evidence.

## 3. Resolution order (first match wins; the reason is always in `resolution_basis`)

For one card with a parseable URL (card guide `G`, card page `P`):

1. **Correction present** (`topic_corrections.json`, matched by topic id and by the correction's `card_guide_id`/`card_page_id` equalling the card's parsed ids; a mismatch is a `conflicting_identity` with reason `CORRECTION_DOES_NOT_MATCH_CARD`):
   corrected guide `R` verified AND `P` is a node of R's TOC AND the correction's `saved_response` evidence is re-confirmed by code (saved response loio == `R`, its currentPage == `P`) -> **`corrected_identity`** (effective guide `R`, page `P`).
   Otherwise -> **`conflicting_identity`** (no effective identity; the correction is not honoured, and this is stated).
2. **`G` verified and its saved TOC contains `P`:** -> **`resolved_local_page`** if a usable local page record exists for `(G,P)`, else **`identified_not_local`**. Effective identity = `(G,P)`.
3. **`G` verified, saved TOC exists, but `P` is NOT a node of it:**
   * a capture/probe places `P` under another loio, or another saved TOC contains `P` -> **`conflicting_identity`** (effective ids are `null`; the other guide is evidence only and is never promoted);
   * nothing else is known -> **`unresolved`** (reason `PAGE_NOT_IN_TOC`).
4. **`G` not verified / no saved TOC:**
   * a capture/probe places `P` under another loio and there is no correction -> **`conflicting_identity`**;
   * otherwise -> **`card_identity_only`**: the card states `(G,P)`; nothing confirms that SAP serves it. Effective ids are `null` (the card's own ids stay in the `card_*` fields; "effective" means established by the rules, not merely stated), `resolution_basis` says `CARD_URL_ONLY_GUIDE_UNVERIFIED`, and any hint (e.g. `P` equals another guide's map root, `P` found in another TOC) is listed as non-authoritative evidence.
5. **Card missing, URL missing or not a SAP Help page URL** -> **`unresolved`**.

`local_page_available` is computed on the *effective* identity only and is independent of the identity status: it is true only when a usable local record exists for `(effective_guide, effective_page)`. A local record found under the card's own ids while there is no effective identity (`conflicting_identity`, `card_identity_only`) is listed as evidence with `counted: false`.

## 4. Discrepancies that are preserved, not reconciled

| Discrepancy | How it is represented |
| --- | --- |
| **#05** card guide 021b182b vs SAP-resolved guide 2ac7fe29 | `corrected_identity`; `card_guide_id` = 021b182b, `effective_guide_id` = 2ac7fe29; correction evidence attached; card record untouched; 021b182b not registered. |
| **#18** card guide 94424864 vs probe result e4375c1c | `conflicting_identity`; card ids preserved; `needs_review` preserved; probe finding attached as `authority: "probe_evidence_only"`; e4375c1c is never an effective guide and is not registered; no correction. |
| **#14** URL status | `needs_review` (lower-case product segment) carried in `evidence`; identity unaffected (guide/page parse and TOC membership are independent of the product spelling). |
| **#23** `?version=2025.001` | `needs_review` and the query carried in `evidence`; the version pin is not interpreted. |
| Guide-verification history (older registry 1 verified vs registrations 5 verified + e52c8ee6 = 6 of 7; 021b182b unresolved) | Per-guide table in `data/m2c_page_identity.json` -> `guides`, each row with declared status, stale-registry status, TOC check and capture check. |
| 5 saved TOCs in `data/toc/` (+ `master_data.json` for e52c8ee6) | Per-guide table; which TOC backs which card. |
| Only 1 usable local page record | `local_pages` summary; all other cards are `local_page_available: false`. |
| `final_corpus_manifest.json` (stale: 1 RESOLVED / 28 UNRESOLVED_GUIDE) vs current registrations + TOCs | Summary `stale_sources`. The identity layer follows the rules above, not the stale manifest. |

## 5. Statuses: only those the evidence requires

`resolved_local_page`, `identified_not_local`, `corrected_identity`, `card_identity_only`, `conflicting_identity`, `unresolved`.
`unresolved` is kept because the contract must describe a card with no usable URL / no card (the join already has that state); no real card is expected to reach it.
