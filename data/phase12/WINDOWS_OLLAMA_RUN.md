# Phase 12 - running the REAL Ollama evaluation on your Windows machine (`D:\chatbot`)

**Why locally:** the Arena sandbox cannot reach your Windows Ollama (`127.0.0.1:11434` in the sandbox is the sandbox itself; nothing listens there, and there is no route to your PC).
`ollama_raw` and `ollama` are therefore still BLOCKED in `data/evaluation/phase12_results.json` and nothing has been faked. The commands below produce the real run; the evaluator
refuses to start (exit 3) if Ollama / `llama3.2:3b` is not really answering, and it never substitutes the extractive generator.

What is measured: the model configured in `scripts/rag_core.py` (`LLM_MODEL_NAME = "llama3.2:3b"`, options `{"temperature": 0, "seed": 42}`, nothing else set - e.g. no `num_ctx`) through the
unchanged `rag_generate.OllamaClient` (`ollama.chat`). Configurations: `baseline`, `evidence` (re-run on your machine so the comparison is same-host and the extractive part can be checked
against the sealed run), `ollama_raw` (real LLM, no evidence guard), `ollama` (real LLM + the Phase 11.1 `EvidenceGuard`, tau 0.5). 113 frozen questions; ~230 LLM calls (only questions that reach
generation call the model). Expect roughly 20-120 minutes depending on CPU/GPU; the run is **resumable** (`<out>.partial.jsonl`).

No page import is needed for this run (see the end of this file).

```powershell
# 0. in D:\chatbot, on the session branch
cd D:\chatbot
git branch --show-current                  # arena/01a0ed60-chatbot
git pull origin arena/01a0ed60-chatbot     # brings the Phase 12 local-Ollama tooling commit ("Phase 12: add local Ollama evaluation tooling")
git log --oneline -1                        # the tooling commit (its hash is in the hand-over message); dc5c23a is its parent
git status --short                          # should be clean

# 1. Python environment (skip if an environment in which the earlier phases' tests pass already exists; `ollama` package is the only new need)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-phase11.txt "chromadb==1.5.9" "sentence-transformers==6.1.0" "gt-all-minilm-l6-v2==0.1.0" ollama pytest
#   gt-all-minilm-l6-v2 is how this repository locates the all-MiniLM-L6-v2 weights (scripts/m2c_common.py resolve_model; no download is attempted by the scripts)

# 2. the frozen question set must be byte-identical (CRLF conversion by git would change the hash)
(Get-FileHash data\evaluation\phase12_queries.json -Algorithm SHA256).Hash.ToLower()
#   must print 3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac
#   if it does not: git config core.autocrlf false ; git checkout-index -f data/evaluation/phase12_queries.json data/evaluation/phase12_freeze.json   (then re-check)

# 3. the vector stores (git-ignored). If both folders exist you can skip the two build commands.
Test-Path data\vector_store ; Test-Path data\vector_store\page_collection
python scripts/build_card_collection.py --manifest $env:TEMP\p12_card_manifest.json
python scripts/build_page_collection.py --manifest $env:TEMP\p12_page_manifest.json
#   (--manifest keeps the tracked manifests untouched; they are pinned by tests)

# 4. is a REAL Ollama answering?  (does one real 1-token generation; exit code 0 = ready)
ollama list                                  # llama3.2:3b must be listed
python scripts/phase12_ollama_check.py       # prints {"ready": true, "blockers": []}; rewrites data/phase12/ollama_environment.json
$LASTEXITCODE                                # 0

# 5. the real evaluation (writes ONLY the two new files below + a .partial.jsonl checkpoint; the sealed results are never overwritten)
python scripts/evaluate_phase12.py --configs baseline,evidence,ollama_raw,ollama --require-ollama --out data/evaluation/phase12_results_ollama.json
#   if it is interrupted (or stops with "consecutive generator errors"): fix Ollama, run the SAME command again - finished questions are reused.
#   in a second window `ollama ps` shows the model loaded while it runs.

# 6. comparison + review sheet (read-only; writes data/phase12/ollama_comparison.json and .md)
python scripts/phase12_compare_results.py --results data/evaluation/phase12_results_ollama.json

# 7. optional: the repository test suite on your machine
python -m pytest tests -q -p no:cacheprovider
```

**Send back** (attach to the chat): `data\evaluation\phase12_results_ollama.json`, `data\evaluation\phase12_results_ollama_performance.json`, `data\phase12\ollama_comparison.md`,
`data\phase12\ollama_comparison.json`, `data\phase12\ollama_environment.json` (and the console output of steps 4 and 5). Delete `data\evaluation\phase12_results_ollama.json.partial.jsonl` afterwards.
Do not commit anything yet; the final commit happens only after you approve it.

Optional manual check of the real UI with the real LLM (not part of the metrics):

```powershell
python scripts/rag_api.py --generator ollama --host 127.0.0.1 --port 8000      # build the UI first: cd web ; npm install ; npx vite build ; cd ..
# open http://127.0.0.1:8000 and ask: "Which transaction is used to monitor meter reading results?" and "What is the minimum installment amount?"
```

## What step 5 records (all in `phase12_results_ollama.json`)
model name + digest + size (`ollama_model`), Ollama version, python `ollama` package version, options, host CPU/RAM/OS (`ollama_environment`), git HEAD, Python and platform (`run`), question-set hash, corpus size,
router metrics, and per configuration and per routing mode: answerable correct / abstained / citation-evidence failures / wrong-page, unsupported answered vs abstained, absent-detail answers, grounding failures,
support-chain failures, phantom citations, URL changes, generator errors, reasons for every non-answer, chunk retrieval (R@1/3/5/MRR), per-stage latency (median, p95) and every answer text.
"correct" means: answered AND cited a chunk of the gold page that contains the gold evidence phrase (citation-evidence criterion). It does not prove the LLM's wording is right - the review sheet in
`ollama_comparison.md` lists every flagged answer with its text so that it can be judged by a person.

## Which existing local files can be imported (`IMPORT_INSTRUCTIONS.md`, part B) - checked in this sandbox, none
`python scripts/phase12_import_pages.py --from-dir captured_responses` (dry run) was executed here: 8 files seen, **0 accepted**, 18 pages still missing. The files are:
* `captured_responses\{1_40374657_8990d053…, 2_40374682_8082ce53…, 3_40374657_4d76765c…, 4_40404052_147bce53…, 5_40374633_cc7bce53…, 6_40374790_790dc553…}.json` = M2C-05, 02, 07, 11, 14, 24: **already ingested** (they are the 7-page corpus together with the local M2C-17 page); they are not in the fetch plan, so the validator rejects them as `PAGE_ID_NOT_IN_PLAN`.
* `captured_responses\1_40374490_b1a202c9….json` = a "Contract Account" page of the guide "Enterprise Services in Financials": not a card page, not in the plan.
* `captured_responses\_malformed_originals\*` = the pre-repair copy of the M2C-05 response (it only *mentions* the ids of M2C-06/08/09 as links) - not content for those cards; do not import.
The 18 missing pages (M2C-03, 04, 06, 08, 09, 10, 12, 15, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29) exist in no file of this repository. They can only come from `help.sap.com`
(`data\phase12\import_manifest.json` lists the exact request URL for each) and fetching them is your decision (saved `robots.txt`: `Disallow: /`). Nothing was fetched from the sandbox. The Ollama
evaluation above is valid and useful on the 7-page corpus; importing pages is a separate, later step that needs a **new** frozen question set.
