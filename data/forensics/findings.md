# Guide-identifier forensics (phases 1-4)

Reproduce: `python scripts/forensic_search.py`, `python scripts/inspect_pdf_cards.py`
(raw results: `local_forensics.json`, `pdf_deep_inspection.json`). No value below is inferred.

## Phase 1 - local search (168 sources: 136 git blobs + 32 untracked generated files, labelled DERIVED and not counted as evidence)
* Every card guide id occurs only in: its own card PDF(s), `audit_out/{audit_report.md,inventory.csv,urls.json}` (+ `network_check.json` for 2 guides) - all of which merely repeat the card URL.
  `audit_out/*` uses the column name `deliverable_id` for the **32-hex guide id**, not the numeric id.
* Guide `e52c8ee6...` additionally occurs in `master_data.json` (its own `deliverable.loio`).
* Numeric deliverable id `40374631` occurs only in `fetch_sap_pages.py` and the 81 scraped pages/chunks. `buildNo`/`BUILD_NO=1779` occurs only in `fetch_sap_pages.py`.
* `fullToc` / `deliverableInfo`: only `master_data.json`, `extract_toc.py`, `fetch_sap_pages.py`.
* Only SAP endpoint pattern in the repo: `help.sap.com/http.svc/pagecontent` (scraper) and `.../http.svc/sitemapxml/...` (robots.txt Sitemap line).
* No other numeric id, build number, TOC or guide id exists anywhere. The other 32-hex strings are TOC page ids, an image loio in `master_data.json`, and one ReportLab digest per PDF.

## Phase 2 - the 29 PDFs, byte level
Producer ReportLab (29/29), Author "OpenAI", no /Names /Dests /OpenAction /JavaScript /AcroForm /Outlines /Metadata, no XMP, no attachments,
no hidden text operators (render mode 3 / white fill: 0), one `%%EOF`, exactly 1 link annotation each (keys `/S /Type /URI` only) and exactly 1 help.sap.com URL per file.
Query parameters: only `?version=2025.001` (cards 18, 23). The only other 32-hex token per PDF is the ReportLab trailer `/ID` digest.
=> The PDFs carry guide id + page id (+ version) and nothing else. They cannot resolve a numeric id, build number or TOC.

## Phase 3 - git
One commit (`d85c31e`), no other local branch/tag/stash, empty reflog beyond clone/checkout, no unreachable objects; `git ls-remote origin` shows only `main` at the same commit.
No earlier scraper version, TOC, guide id, build number or additional pages ever existed in history.

## Phase 4 - SAP Help discovery: BLOCKED (nothing requested)
* Sandbox egress to `help.sap.com` is blocked at TLS: TCP connect to 23.41.4.84:443 succeeds, TLS handshake is closed immediately (curl `SSL_ERROR_SYSCALL`; python `SSLZeroReturnError`), even for `/robots.txt`.
  `github.com` and `pypi.org` complete TLS normally, so this is a sandbox policy, not a transient fault.
* I did not try to route around it (no proxies, no third-party fetchers, no spoofed user agents).
* The saved `audit_out/robots.txt` (dated 2025-10-17) has `User-agent: * / Disallow: /`; the only allowed agents are named search/AI crawlers, which this project is not. The live file could not be re-fetched.
* `audit_out/network_check.json` (from the project's earlier audit, 3 cards) recorded HTTP 200 JS-shell pages (~1.1 KB, 33 visible characters): the card URLs do not expose a numeric id or TOC in their HTML.
* The only known API mechanism (`pagecontent?deliverableInfo=1&deliverable_id=<numeric>&buildNo=<n>&file_path=...`) needs the numeric id as *input*; nothing local says how to obtain it from a 32-hex loio. I did not invent an endpoint.
