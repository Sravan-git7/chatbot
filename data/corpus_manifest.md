# SAP Utilities RAG - intended corpus manifest (29 topics)

Generated 2026-09-29 from **local files only** (29 root PDFs, `master_data.json`, `sap_pages/`, `chunks.json`, `audit_out/`, pipeline scripts). No network requests were made; nothing was scraped, re-embedded or modified. Machine-readable version: [`corpus_manifest.json`](corpus_manifest.json).

## What the local data is

* The 29 PDFs are **reference/link cards** (title, category, "what it covers", relevance, one SAP Help URL taken from the PDF link annotation). They contain no SAP documentation body.
* The cards point at **7 different SAP Help guides** (32-hex guide IDs). Only one guide (loio `e52c8ee6197147ec97dfc2eb8c46a3ad`, "Master Data", version 2025.001) has a TOC saved locally (`master_data.json`, one saved `pagecontent?deliverableInfo=1` response).
* The 81 scraped pages / 310 chunks are exactly the 81 nodes of that saved TOC, fetched with numeric deliverable ID `40374631`. 48 of them (227 chunks) relate to none of the 29 topics; 33 pages (83 chunks) relate to at least one; 6 pages are duplicates (75 unique pages).

## Summary

| Metric | Value |
|---|---|
| Intended topics (PDF cards) | 29 |
| COMPLETE | 1 |
| PARTIAL | 6 |
| MISSING | 22 |
| UNCERTAIN | 0 |
| Distinct SAP guides referenced by the cards | 7 |
| Guides with a TOC saved locally | 1 |
| Topic pages present in the saved TOC | 1 |
| Topics whose child pages are identifiable from the saved TOC | 1 (topic 17; topic 01 is inference only) |
| Scraped pages / unique / chunks / unique chunks | 81 / 75 / 310 / 287 |
| Duplicate pages / redundant chunks | 6 / 23 |

**Definitions.** COMPLETE: exact SAP page ID present in the saved TOC and scraped. PARTIAL: exact page not scraped, but a scraped page's main subject falls inside the topic's scope. MISSING: no dedicated scraped page (only incidental keyword mentions, or none). UNCERTAIN: undecidable locally.

## 29-topic manifest

"Pages" = locally scraped pages related to the topic (exact + TOC descendants + judged-related; **not** additive across rows). "Chunks" = chunks from those pages. "Incid." = pages outside that set that only mention the topic keywords.

| # | Topic (PDF title) | Guide | Page ID | In saved TOC | Children from TOC | Class | Pages | Chunks | Incid. | Evidence |
|--:|---|---|---|:-:|:-:|:-:|--:|--:|--:|---|
| 01 | Utilities Master Data | `021b18` | `0a6ace53` | map root | inferred | **PARTIAL** | 9 | 29 | 0 | Exact page (guide 021b18) not scraped, but its page ID equals buildableMapLoio of the saved TOC (the guide map root, not a TOC node). Scraped landing page 'Master Data' (sap_pages/001) lists the same objects; 8 of the 9 objects ... |
| 02 | Move-In/Out Overview | `f4a255` | `8082ce53` | no | no | **PARTIAL** | 1 | 3 | 15 | Exact page not in saved TOC. Only sap_pages/066 'Handling the Exact Move-In and Move-Out Time' is on-topic (a sub-aspect). No overview page. 'move-in/out' occurs in 16 pages, mainly Customer Change (menu path) and contract pages. |
| 03 | Move-In Process | `f4a255` | `0981ce53` | no | no | **PARTIAL** | 1 | 3 | 15 | Exact page not in saved TOC. Only sap_pages/066 addresses move-in (exact move-in time/date). No page describing the move-in process or creation of the customer-service relationship. |
| 04 | Move-Out Process | `f4a255` | `0f81ce53` | no | no | **PARTIAL** | 1 | 3 | 7 | Exact page not in saved TOC. Only sap_pages/066 addresses move-out (exact move-out time/date). No page on final processing/termination. |
| 05 | Device Management Overview | `021b18` | `8990d053` | no | no | **PARTIAL** | 4 | 7 | 8 | Exact page not in saved TOC. Related: sap_pages/072 Technical Installation, 073 Creating a Technical Installation, 074 Utility Installation, 080 Device location. No device-management or meter-reading pages. |
| 06 | Reading Meters | `2ac7fe` | `bc90d053` | no | no | **MISSING** | 0 | 0 | 9 | Exact page not in saved TOC. No page title contains 'meter reading'; the term occurs 18 times in 9 pages, all incidental (e.g. scheduling/meter reading unit on Utility Installation). |
| 07 | Monitoring Meter Reading Results | `2ac7fe` | `4d76765c` | no | no | **MISSING** | 0 | 0 | 9 | Exact page not in saved TOC. No dedicated page; only the incidental 'meter reading' mentions (18 occurrences). |
| 08 | Meter Reading Estimation | `2ac7fe` | `d090d053` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'estimat*' has 0 occurrences in the 81 scraped pages. |
| 09 | Estimation Procedure Details | `2ac7fe` | `bf74c1d2` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'extrapolat*', 'interpolat*' and 'estimat*' have 0 occurrences. |
| 10 | Meter Reading Data During Move-In | `f4a255` | `b781ce53` | no | no | **MISSING** | 0 | 0 | 9 | Exact page not in saved TOC. No scraped page combines meter reading with move-in; sap_pages/066 contains no 'reading'. |
| 11 | SAP Utilities Billing Procedure | `ed84b7` | `147bce53` | no | no | **MISSING** | 0 | 0 | 12 | Exact page not in saved TOC. No page titled/about billing procedure; 'billing' occurs 64 times in 12 pages as contract/contract-account fields or transfer prerequisites (e.g. Customer Change, Relevant Fields in the Contract). |
| 12 | Automatic Billing | `ed84b7` | `297bce53` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'automatic billing', 'rate type', 'schema', 'operand' have 0 occurrences. |
| 13 | Budget Billing Plan | `021b18` | `c1a5e8ae` | no | no | **MISSING** | 0 | 0 | 5 | Exact page not in saved TOC. 'budget billing' occurs 21 times in 5 pages, incidental (e.g. plan transfer prerequisites in Customer Change). |
| 14 | SAP Utilities Invoicing Procedure | `a003b2` | `cc7bce53` | no | no | **MISSING** | 0 | 0 | 11 | Exact page not in saved TOC (card URL uses lowercase product segment 'sap_s4hana_on-premise'). 'invoic*' occurs 52 times in 11 pages, incidental (contract / contract-account fields). |
| 15 | Processing Budget Billing Plans | `a003b2` | `147cce53` | no | no | **MISSING** | 0 | 0 | 5 | Exact page not in saved TOC. Only incidental 'budget billing' mentions (see #13). |
| 16 | Periodic Billing and Invoicing Analysis | `021b18` | `549661e6` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. No page about periodic billing/invoicing analysis or monitoring. |
| 17 | Contract Accounts Overview | `e52c8e` | `0bfcc553` | yes | yes (21) | **COMPLETE** | 22 | 50 | 0 | COMPLETE by page ID: page 0bfcc5536a51204be10000000a174cb4 is in the saved TOC and scraped as sap_pages/041 'Contracts Accounts'; the card's guide ID (e52c8e...) equals the saved TOC loio. The TOC subtree under this node adds 21 ... |
| 18 | Contract Account Business Object | `944248` | `b1a202c9` | no | no | **PARTIAL** | 2 | 10 | 0 | Exact page (guide 944248) not in saved TOC (URL has ?version=2025.001). Related: sap_pages/043 'Contract Account' (Definition section) and 044 'Controlling Specifications in Contract Accounts'. Content equivalence with the card's ... |
| 19 | Analyze Incoming Payments | `944248` | `063bf3eb` | no | no | **MISSING** | 0 | 0 | 6 | Exact page not in saved TOC. 'incoming payment' occurs 17 times in 6 pages, mostly one transfer-type note in 'Special Cases' (sap_pages/009); no analysis/clarification page. |
| 20 | Clearing Control in Incoming Payments | `944248` | `edcd0c58` | no | no | **MISSING** | 0 | 0 | 8 | Exact page not in saved TOC. 'clearing' occurs 13 times in 8 pages, incidental. |
| 21 | Clearing Types | `944248` | `e63529e1` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'clearing type' has 0 occurrences. |
| 22 | Processing Incoming Payments from External Cash Desks | `944248` | `3d0ac553` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'cash desk' has 0 occurrences. |
| 23 | Installment Plan Overview | `944248` | `730dc553` | no | no | **MISSING** | 0 | 0 | 4 | Exact page not in saved TOC (URL has ?version=2025.001). 'installment' occurs 14 times in 4 pages, mostly the 'Loans (IS-U)' page (sap_pages/062) referring to installment plans; no installment-plan page. |
| 24 | Creating Installment Plans | `944248` | `790dc553` | no | no | **MISSING** | 0 | 0 | 4 | Exact page not in saved TOC. Only incidental 'installment' mentions (see #23). |
| 25 | Displaying and Changing Installment Plans | `944248` | `630dc553` | no | no | **MISSING** | 0 | 0 | 4 | Exact page not in saved TOC. Only incidental 'installment' mentions (see #23). |
| 26 | FI-CA Dunning | `944248` | `b1ffc553` | no | no | **MISSING** | 0 | 0 | 13 | Exact page not in saved TOC. 'dunning' occurs 42 times in 13 pages, but as dunning-control fields in contract-account master data (e.g. sap_pages/044), not the dunning process. |
| 27 | Submission of Receivables to Collection Agency | `944248` | `10e7c553` | no | no | **MISSING** | 0 | 0 | 7 | Exact page not in saved TOC. 'collection agenc*' occurs 9 times in 7 pages, incidental (e.g. 3 in sap_pages/022 blocked business partners). |
| 28 | Collection Agency APIs and Enterprise Services | `944248` | `9c9c2344` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'enterprise service' and 'API' have 0 occurrences. |
| 29 | Disconnection/Reconnection of a Utility Installation | `f4a255` | `8682ce53` | no | no | **MISSING** | 0 | 0 | 0 | Exact page not in saved TOC. 'disconnect*' and 'reconnect*' have 0 occurrences. |

Full URLs, category, description, URL anomalies, hashes and complete evidence for every topic are in the JSON.

### SAP Help URLs (from PDF link annotations)

| # | URL |
|--:|---|
| 01 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/021b182b0c47416c8fafed67ebfd78a9/0a6ace53118d4308e10000000a174cb4.html |
| 02 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f4a255a5de524e3992155767996fb1fd/8082ce53118d4308e10000000a174cb4.html |
| 03 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f4a255a5de524e3992155767996fb1fd/0981ce53118d4308e10000000a174cb4.html |
| 04 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f4a255a5de524e3992155767996fb1fd/0f81ce53118d4308e10000000a174cb4.html |
| 05 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/021b182b0c47416c8fafed67ebfd78a9/8990d0533f8e4308e10000000a174cb4.html |
| 06 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/2ac7fe29a0c94cdd88fb80c2cb9f7758/bc90d0533f8e4308e10000000a174cb4.html |
| 07 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/2ac7fe29a0c94cdd88fb80c2cb9f7758/4d76765c1e012b8ae10000000a42189b.html |
| 08 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/2ac7fe29a0c94cdd88fb80c2cb9f7758/d090d0533f8e4308e10000000a174cb4.html |
| 09 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/2ac7fe29a0c94cdd88fb80c2cb9f7758/bf74c1d28fd54f77b228772b98b72fba.html |
| 10 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f4a255a5de524e3992155767996fb1fd/b781ce53118d4308e10000000a174cb4.html |
| 11 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/ed84b70c199d4470ae2e5ccb93b2e45b/147bce53118d4308e10000000a174cb4.html |
| 12 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/ed84b70c199d4470ae2e5ccb93b2e45b/297bce53118d4308e10000000a174cb4.html |
| 13 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/021b182b0c47416c8fafed67ebfd78a9/c1a5e8aee73440ee971a768af5b9ea1b.html |
| 14 | https://help.sap.com/docs/sap_s4hana_on-premise/a003b275c98148ee8a4c3fafe9588fe3/cc7bce53118d4308e10000000a174cb4.html |
| 15 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/a003b275c98148ee8a4c3fafe9588fe3/147cce53118d4308e10000000a174cb4.html |
| 16 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/021b182b0c47416c8fafed67ebfd78a9/549661e6541f403ea56196782e040bcc.html |
| 17 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4.html |
| 18 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/b1a202c9bb3011da2b24000f20dac9ef.html?version=2025.001 |
| 19 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/063bf3eb68e347efa5c0fc1d389f70f7.html |
| 20 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/edcd0c5823854d3296f2591e9f5d118c.html |
| 21 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/e63529e1a3fd42e3a0e2c009ac783e0d.html |
| 22 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/3d0ac5536a51204be10000000a174cb4.html |
| 23 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/730dc5536a51204be10000000a174cb4.html?version=2025.001 |
| 24 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/790dc5536a51204be10000000a174cb4.html |
| 25 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/630dc5536a51204be10000000a174cb4.html |
| 26 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/b1ffc5536a51204be10000000a174cb4.html |
| 27 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/10e7c5536a51204be10000000a174cb4.html |
| 28 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/9c9c2344851f412f823d5f8a9dc7c694.html |
| 29 | https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f4a255a5de524e3992155767996fb1fd/8682ce53118d4308e10000000a174cb4.html |

## Guides referenced

| Guide ID | Topics | TOC saved locally |
|---|---|:-:|
| `021b182b0c47416c8fafed67ebfd78a9` | 01, 05, 13, 16 | no |
| `f4a255a5de524e3992155767996fb1fd` | 02, 03, 04, 10, 29 | no |
| `2ac7fe29a0c94cdd88fb80c2cb9f7758` | 06, 07, 08, 09 | no |
| `ed84b70c199d4470ae2e5ccb93b2e45b` | 11, 12 | no |
| `a003b275c98148ee8a4c3fafe9588fe3` | 14, 15 | no |
| `e52c8ee6197147ec97dfc2eb8c46a3ad` | 17 | yes (saved TOC loio) |
| `9442486404b54071b4ebeab6a16628e7` | 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28 | no |

## Duplicates in the current scrape

| Duplicate page | Identical to | Title | Chunks |
|--:|--:|---|--:|
| sap_pages/035 (`4371ce53118d4308e10000000a174cb4-35.html`) | sap_pages/029 | Merging Business Partners (IS-U) | 3 |
| sap_pages/036 (`1971ce53118d4308e10000000a174cb4-36.html`) | sap_pages/030 | Objects in Contract Accounts Receivable and Payable | 6 |
| sap_pages/037 (`2b71ce53118d4308e10000000a174cb4-37.html`) | sap_pages/031 | Objects and Enhancements in SAP Utilities | 4 |
| sap_pages/038 (`f780ce53118d4308e10000000a174cb4-38.html`) | sap_pages/032 | Customer Change | 6 |
| sap_pages/039 (`4071ce53118d4308e10000000a174cb4-39.html`) | sap_pages/033 | Objects and Enhancements in SAP CRM | 1 |
| sap_pages/040 (`1071ce53118d4308e10000000a174cb4-40.html`) | sap_pages/034 | Automatic Business Partner Merging | 3 |

6 pages / 23 redundant chunks. None of them relate to any of the 29 topics.

## Can the current scraper ingest all 29 topics?

**No. The scraper can only re-fetch the single guide whose TOC is saved in master_data.json; 28 of 29 topic pages belong to guides (or pages) it has no TOC, identifier or URL logic for.**

What would need to change later (not done):

1. TOC source: fetch_sap_pages.py only reads one local file (master_data.json = a single saved pagecontent?deliverableInfo=1 response for landing page e369ce53...). There is no step that obtains a TOC. TOCs for the 6 other guides are not stored locally, so page/child discovery for 28 of 29 topics is impossible offline.
2. Guide identifier: DELIVERABLE_ID='40374631' and BUILD_NO='1779' are module-level constants applied to every request. The cards carry 7 different 32-hex guide IDs. Local files do not show whether the API accepts 32-hex IDs, nor the numeric ID / build number of the other guides (the scraped guide is 40374631 in URLs but its saved loio is e52c8ee6...; the mapping between the two forms is not documented locally).
3. URL construction: source_url is hard-coded as help.sap.com/docs/SAP_S4HANA_ON-PREMISE/{DELIVERABLE_ID}/{file_path}. It cannot represent other guides, and even for topic 17 it differs from the card URL (numeric ID vs 32-hex loio), giving two URL forms for the same page ID.
4. Input scope: the scraper walks every node of the TOC; it has no topic list, no 'single page vs subtree' switch and no page-ID allowlist, so it cannot be driven by the 29 cards.
5. Output naming: files are numbered by loop index (001.json...) into one sap_pages/ folder; adding guides would overwrite or interleave with the current 81 files. Filenames/records carry no guide ID or topic number.
6. Metadata loss downstream: fetch keeps title/parent/file_path/source_url/current_page, but clean_sap_pages.py keeps only title/url/text, chunk_pages.py keeps title/url/text, and create_embeddings.py stores only title/url in Chroma. Topic number, guide ID, page ID and TOC path are lost, so per-topic evaluation/filtering is not possible.
7. Duplicates: TOC nodes reused under several parents (-NN.html) are fetched again; there is no dedupe by page ID or content (6 duplicates, 23 redundant chunks today).
8. URL normalization: cards 18 and 23 carry ?version=2025.001 and card 14 uses a lowercase product segment; the manifest-to-scraper mapping must normalize URLs to (guide ID, page ID).
9. Robustness/compliance: errors are printed and skipped without a failure log or resume; the request uses the default requests User-Agent (the audit script used an identifying one); audit_out/robots.txt states 'User-agent: * / Disallow: /' - permission to scrape further pages must be resolved before any run.

## Caveats

* Scraped `source_url`s use numeric ID `40374631`; card URLs use 32-hex IDs. For topic 17 the page ID matches and the card guide ID equals the saved TOC loio, but the numeric-to-loio equivalence is not documented in any local file.
* Topic 01: its page ID equals the saved TOC `buildableMapLoio`, but the card's guide ID differs from the saved loio, so it is classified PARTIAL rather than COMPLETE.
* "Related" pages are a text-based judgment from the local scraped text, not an ID match; keyword counts for MISSING topics are evidence of absence of dedicated content, not proof about the live SAP pages.
