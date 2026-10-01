# Phase 12 - what you have to do on a machine that CAN reach the internet

This sandbox cannot reach `help.sap.com`, `ollama.com`, `registry.ollama.ai` or `huggingface.co` (TCP connects, then TLS is dropped - see
`data/phase12/corpus_status.json`, section `network_probe`, and `fetch_attempt_log.json`). So two things were **not** done here and are described below. Nothing in this
repository pretends otherwise. Commands are for Windows PowerShell, run from the repository root.

## A. Real Ollama run (the real-LLM validation)

```powershell
winget install Ollama.Ollama            # then restart the terminal so `ollama` is on PATH
ollama pull llama3.2:3b                 # the model configured in scripts/rag_core.py (LLM_MODEL_NAME); ~2 GB download
pip install ollama
python scripts/phase12_ollama_check.py  # must print {"ready": true, ...}; exit code 0. It also does one real generation round-trip.
python scripts/evaluate_phase12.py --configs baseline,evidence,ollama_raw,ollama --out data/evaluation/phase12_results_ollama.json
python scripts/rag_api.py --generator ollama --host 127.0.0.1 --port 8000      # chat UI + API with the real LLM (build the UI first: cd web; npm install; npx vite build)
```

* `ollama_raw` = real LLM without the evidence guard; `ollama` = real LLM + `EvidenceGuard` (Phase 11.1). A configuration is **never** replaced by the extractive generator;
  if the check fails the evaluator records `BLOCKED` with the blockers.
* The existing results file `data/evaluation/phase12_results.json` is sealed and is not overwritten - hence `--out`.
* Then re-run the real-browser E2E with that server: `node web/e2e/phase12_browser_e2e.cjs` (see the header of that file for the environment variables). With a working Ollama the
  "generator failure" scenario will no longer fail - that scenario only makes sense without Ollama; skip it or point `E2E_PORT_FAIL` at a server whose Ollama is stopped.
* Please report the numbers as they are. The Phase 11.1 `EvidenceGuard` for LLM answers has only been tested with a stub so far; if `ollama` is worse than `evidence` that is a finding.

## B. The other 22 documentation pages (corpus 7/29 -> up to 25/29)

18 cards have a verified guide id and page id but no local content (`import_manifest.json` lists the exact request URL for each). 4 cards cannot be fetched at all:
M2C-01, M2C-13, M2C-16 (identity-only: no verified guide) and M2C-18 (conflicting identity, stays a protected conflict). So **25/29 is the maximum**, never 29/29.

**Decision for you first:** the `robots.txt` of `help.sap.com` that was saved on 2025-10-17 says `Disallow: /`, and its current state is unknown here. Fetching programmatically
is your decision, not this repository's; the tooling below therefore **never fetches** - it only validates files that you saved by whatever means you consider appropriate
(e.g. a browser "Save as" of the `request_url` of each item, as `.json`).

```powershell
# 1. put the saved responses (any file names, *.json) in one folder, e.g. C:\saved_pages
python scripts/phase12_import_pages.py --from-dir C:\saved_pages            # dry run: shows accepted / rejected (+reason) / still_missing
python scripts/phase12_import_pages.py --from-dir C:\saved_pages --apply    # copies ONLY accepted files to data/page_corpus/fetched/<n>_<deliverable>_<page>.json

# 2. rebuild the corpus manifest and the page collection (write the manifest to a temp path - the default path is pinned by tests)
python scripts/page_corpus.py
python scripts/build_page_collection.py --rebuild --manifest $env:TEMP\page_collection_manifest.json
python scripts/phase12_corpus_status.py                                      # new numbers

# 3. review, do not auto-update: tests that pin the 7-page corpus WILL fail on purpose
python -m pytest tests -q -p no:cacheprovider
```

Acceptance rules (the same `page_fetch.check_response` that Phase 9 used): envelope `status == OK`, not a fallback page, `currentPage.loio` equals the planned page id,
`deliverable.loio` equals the planned guide id, non-empty body. A page that fails is reported and ignored; a duplicate for the same card is rejected.

After importing, the Phase 12 question set (113 questions, frozen, sha256 in `data/evaluation/phase12_freeze.json`) must NOT be edited: its 10 `not_ingested` questions will then
have answers. Write a new, separately frozen set for the enlarged corpus (see `scripts/build_phase12_queries.py` for the method) before judging the enlarged-corpus behaviour.
