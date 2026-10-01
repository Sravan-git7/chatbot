# Card -> guide mapping investigation: topics #18 and #5 (read-only evidence; nothing was registered or changed)

## Source of the mapping (both cases)
* The only source of "card guide" is the link annotation (`/Annots` `/URI`) inside `NN_*.pdf`, extracted by the legacy audit
  (`audit_out/urls.json`, `inventory.csv`) and copied to `data/topic_manifest.json` (`url_as_given`).
* All 29 PDFs are ReportLab output with `/Author OpenAI`, created 2026-09-18 15:50:15-16 (one batch). They are generated
  reference sheets, not SAP content; the repo has no record of how each URL was produced.
* #18 card URL (as given): `.../SAP_S4HANA_ON-PREMISE/9442486404b54071b4ebeab6a16628e7/b1a202c9bb3011da2b24000f20dac9ef.html?version=2025.001`
* #5  card URL (as given): `.../SAP_S4HANA_ON-PREMISE/021b182b0c47416c8fafed67ebfd78a9/8990d0533f8e4308e10000000a174cb4.html`
* `?version=2025.001` (only #18, #23) equals the version of every captured deliverable, so it is not an older version.
* `audit_out/network_check.json` only probed cards #1-#3; every probe was HTTP 200 with the SAME 1160-byte JS shell
  (identical sha256): a 200 for `/docs/<guide>/<page>.html` says nothing about guide membership.

## Base rate
Of the 25 topics whose card guide has a saved TOC, 24 pages are in that TOC and exactly 1 (#18) is not.

## #18
* Response (deliverable_id=40374490, buildNo=1779): deliverable.loio `e4375c1cad104b2eb7d027369bd76638`
  "Enterprise Services in Financials" (669 TOC nodes), currentPage.loio = requested page, title "Contract Account",
  located at: Contract Accounting Receivables Payables Processing > Contract Account (children: Credit Commitment In,
  Credit Rating In/Out, Debt Recovery Score Processing In/Out, Manage Contract Account In, ...).
* Guide F TOC (94424864, 1481 page nodes): no node with this page id, no node titled "Contract Account" or
  "Contract Account Business Object", no legacy-GUID ids (`...11da2b24000f20dac9ef`); its 4 nodes with an `m` field point at themselves.
* e4375c1c shares 0 of its pages with any of the 6 saved TOCs / legacy master data. Legacy corpus/chunks/sap_pages do not mention it.
* Not proven: which guide the card author meant. Consistent with: page id taken from e4375c1c, guide segment taken from F.

## #5
* Response for deliverable_id=40374657 + page 8990d053 = guide C (2ac7fe29 "Device Management"); that page is C's
  landingPage and first root node. Card #5's guide segment says 021b182b.
* The other A cards (#1 0a6ace53, #13 c1a5e8ae, #16 549661e6) are in no saved TOC, so they are neither confirmed nor refuted.
* Not proven: whether 021b182b is a real guide, and what its deliverable_id is.

## Provenance of the two probe ids (user statement, 2026-09-30)
* The `deliverable_id` values 40374657 (#5) and 40374490 (#18) were NOT copied from a browser Network request made by opening
  the card URL. They were constructed/probed (40374490 was found by trying the pagecontent request with that page id).
* They are therefore probe inputs: a response only shows which deliverable the page is served from for that probe. It is NOT
  evidence about how SAP's own browser app resolves the card URL, and it does not confirm or refute the card's guide segment.
* Status unchanged: Guide A (021b182b) unresolved; #1/#5/#13/#16 unresolved; #18 unresolved; e4375c1c NOT registered; 6/7 guides, 24/29 topics.

## Open evidence (still needed, only if the mappings are to be settled)
The `pagecontent?deliverableInfo=1&deliverable_id=...&buildNo=...&file_path=...` request that SAP's own page issues when the ORIGINAL card URL is opened
(.../021b182b.../8990d053....html and .../9442.../b1a202c9....html), plus the address bar after load.

## Browser evidence for #5 (user-reported, 2026-09-30; not machine-verified here)
* Opening card #5's original URL `.../021b182b0c47416c8fafed67ebfd78a9/8990d053....html` redirects/resolves in the browser to
  `.../2ac7fe29a0c94cdd88fb80c2cb9f7758/8990d053....html`; the page's own `pagecontent?deliverableInfo=1` request uses deliverable_id=40374657
  and the response has deliverable.loio 2ac7fe29.... This agrees with the response already captured in `captured_responses/1_40374657_8990d053*.json`.
* Conclusion recorded: SAP's current resolution of #5 is Guide C. It is NOT evidence for Guide A; Guide A is not registered from this URL.
* NOT applied: the card's guide mapping is unchanged and #5 is still counted unresolved until a decision is made on how to record a
  card->guide correction (see report).
* Still open: #1, #13, #16 (021b182b) and #18 (9442...): same browser test not yet done.

## Decision applied 2026-09-30 (user choice "option 1")
* #5: per-topic correction recorded in `data/topic_corrections.json` (card guide 021b182b -> resolved guide 2ac7fe29), with the saved
  response (machine-checked each build) and the user-reported browser observation attached. The card record is unchanged. Guide A is not
  registered. #5 RESOLVED (page 8990d053 is a node of the verified TOC of 2ac7fe29). #1/#13/#16: nothing inferred.
* #18: NOT corrected. The only evidence is a constructed probe (deliverable_id 40374490 found by trying the request), which the user
  stated is not browser evidence; and e4375c1c would have to be registered as an eighth guide, which has not been authorised. Unresolved.
