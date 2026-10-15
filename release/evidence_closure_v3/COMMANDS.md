# Minimal command book — exact scope and blockers

**No runtime commands below were executed for this package.** Only the integrity/provenance/metadata checks explicitly reported in [validation.json](validation.json) ran. Full backend/current quality/real Ollama/native Windows remain **BLOCKED / NOT RUN** in this fresh clone. Do not reuse the vanished historical scratch interpreter path or claim archived results as new execution.

## A. Runnable now: no models, dependencies, SDK or service

From the isolated clone root, with an existing standard-library Python and a **new private** results directory outside tracked data:

```sh
git rev-parse HEAD
git ls-remote origin refs/heads/arena/b450cda2-chatbot
gh api repos/Sravan-git7/chatbot/branches/arena%2Fb450cda2-chatbot --jq .commit.sha
git diff --name-status 29ca4ba2182b47f8452630ae5dd856ac946afe70 8895a964f7ac9a4543a30073a16ce66b12f9857a
sha256sum --check release/evidence_closure_v3/delivery-inputs.sha256
"$P" release/closure_v2/reconcile_provenance.py --out "$R/historical-provenance-recheck.json"
cmp release/closure_v2/historical-provenance.json "$R/historical-provenance-recheck.json"
```

The starting remote was `8895a96…`; after this package is published it should be the new documentation-only delivery. Verify ancestry and exact inherited hashes, not equality to an obsolete branch head. The reconciliation writes only the explicitly new result file; ensure it does not already exist. These commands prove integrity/reconciliation only, not RAG, Windows or security readiness. On Windows use the standard-library verifier below instead of requiring GNU `sha256sum`/`cmp`.

Cross-platform inherited-file verification (stdlib only):

```sh
"$P" - <<'PY'
import hashlib
from pathlib import Path
n = 0
for line in Path('release/evidence_closure_v3/delivery-inputs.sha256').read_text().splitlines():
    expected, name = line.split('  ', 1)
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
    n += 1
print(n, 'inherited tracked files match published delivery')
PY
```

## B. Provision first — no installation/repair shortcut

Required owner deliveries are in [ARTIFACTS](ARTIFACTS.md) / [prerequisites.json](prerequisites.json). The [cold-copy procedure](COLD_COPY.md) must complete before any Chroma diagnostic, factory, test or evaluation. Use a new private host/test clone and approved runtime, model inventory, independent disposable stores and signed owner approval. Enforce offline model loading and deny unapproved egress at the host; environment variables alone are not a network isolation boundary.

Set explicit paths, then run from the isolated test clone root:

```sh
# Operator supplies P, R and M2C_MODEL_DIR as absolute approved paths.
# R is a newly created, initially empty private directory outside the checkout/data.
: "${P:?approved interpreter required}" "${R:?new private result directory required}" "${M2C_MODEL_DIR:?approved complete local model export required}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
Delivery=$(git rev-parse HEAD)
CardCopy="$PWD/data/vector_store"
PageCopy="$CardCopy/page_collection"
```

`Delivery` must be the actual reviewed checkout ID. Passing `--source-commit` merely records a supplied string; **the evaluator does not verify it for you**. First verify inherited hashes and `git status`, no runtime diff against `29ca4ba…`, and full model/store inventories. Record exact approved platform/CPU/thread/native graph, package/model/store/source hashes and relevant non-secret configuration. Do not dump all environment variables or credentials.

Recommended Bash recording wrapper (no pipeline masking; no reused logs; private paths only):

```sh
run() {
    local label="$1" rc; shift
    for suffix in stdout.log stderr.log exit argv; do
        test ! -e "$R/$label.$suffix" || { echo 'STOP: output exists'; return 99; }
    done
    printf '%q ' "$@" > "$R/$label.argv"
    printf '\n' >> "$R/$label.argv"
    if "$@" > "$R/$label.stdout.log" 2> "$R/$label.stderr.log"; then rc=0; else rc=$?; fi
    printf '%s\n' "$rc" > "$R/$label.exit"
    printf '%s exit=%s\n' "$label" "$rc"
    return "$rc"
}
```

Run each command separately, retain failures and all warnings/skips. Do not continue a failed prerequisite. A suite failure should be retained and investigated; after confirming no safety/input-integrity failure, an owner may separately authorize the diagnostic quality run, never relabel the suite PASS. Ensure every helper's JSON/XML output is new too; several helpers overwrite their `--out` file if it exists. No blanket restore/delete/reset of a failed test tree.

## C. Full backend and strict **current-production** RAG

After complete approvals/inventories only:

```sh
run python-version "$P" -VV
run package-graph "$P" -m pip check
run installed-versions "$P" -m pip freeze --all
run preflight "$P" scripts/preflight_verification.py
```

Preflight checks package metadata, six model hashes and SQLite-path existence only. It neither opens/validates stores nor certifies complete model provenance. Its generic install/build hints are **not approval**; stop rather than follow them. If pip is unavailable, record that blocker; do not bootstrap it automatically.

Exact-tokenizer and real local embedding load probe (model inference, therefore blocked until artifacts/runtime approved):

```sh
run tokenizer-model "$P" -c 'import sys,json; sys.path.insert(0,"scripts"); import m2c_common as C, page_chunker as K, build_page_collection as B; p,_=C.resolve_model(); count,t=K.make_token_counter(p); assert t["exact"] is True,t; embed,m=B.load_embedder(p); assert m["dimensions"]==384,m; assert m["max_seq_length"]==256,m; v=embed(["SAP Utilities verification probe"]); assert len(v)==1 and len(v[0])==384; print(json.dumps({"tokenizer":t,"embedding":m,"probe_tokens":count("SAP Utilities verification probe")}))'
run store-diagnostic "$P" scripts/diagnose_windows_verification.py --store-quiesced --card-store "$CardCopy" --page-store "$PageCopy" --out "$R/store-diagnostic.json"
run backend "$P" -m pytest tests -q -ra --tb=long --junitxml="$R/backend.xml"
run current-quality "$P" benchmarks/run_quality.py --source-commit "$Delivery" --out "$R/current-strict-phase12.json"
```

`--store-quiesced` is an operator attestation, not a mechanism to stop writers. The diagnostic itself makes temporary owned copies; its source arguments must still be approved cold **test** copies. Treat cleanup errors, worker failures, inventory drift or unsupported internals as failures/BLOCKED, not PASS because the outer process exited.

Require 113 per-query records with the frozen SHA `3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`, actual current config/corpus/model/store IDs, all 65 answerable/40 negative/eight ambiguous requests and honest raw metrics. Capture full stdout/stderr/XML/JSON and every failure/skip/warning; no `-k` exclusion or cached substitute for the full run. Missing resources may expose additional genuine defects after provisioning; historical 7 failures/49 errors do not establish their absence. Independently review substantive completeness, polarity, source/version identity and safe negatives; the runner is lexical/quote evidence, not SAP semantic certification. Recheck inherited files and sealed/source inventories afterwards.

## D. Real local Ollama — separately blocked

Additional prerequisites: approved already-present daemon/model **digest**, daemon/binary/blob inventory, license/capacity approval, built `web/dist` and its inventory, plus explicit private-service launch permission. On a private test host only; do not run merely to inventory, do not expose via a public preview/port and do not start or interrupt production. Default `llama3.2:3b` is not a digest.

```sh
export OLLAMA_HOST=http://127.0.0.1:11434
export OLLAMA_MODEL=llama3.2:3b  # only if this exact tag maps to the approved digest
run ollama-version ollama --version
run ollama-daemon-metadata "$P" -c 'import json,urllib.request; host="http://127.0.0.1:11434"; print(json.dumps({p:json.load(urllib.request.urlopen(host+p,timeout=5)) for p in ("/api/version","/api/tags")},indent=2))'
# Compare /api/tags model digest to the signed approval BEFORE generation.
run ollama-http "$P" scripts/live_smoke.py --generator ollama --out "$R/ollama-http.json"
```

The helper binds an owned loopback service, terminates its child and uses existing Ollama; it does not pull models. `status=BLOCKED`, exit 2 and outage behavior are **not** real-inference PASS. Require `real_ollama_round_trip=true`, actual generator/digest, substantive grounded answers and correct source/version review. The smoke output lists statuses/sources, not complete answer bodies: retain complete private API request/response bodies separately for independent review. Preserve outage/error/cancel/queue/permit/drain/recovery evidence in [PRIVATE_REHEARSAL](PRIVATE_REHEARSAL.md). Readiness/tags/mocks/extractive fallback are insufficient.

Do **not** run `phase12_ollama_check.py` as-is: its fixed default output overwrites `data/phase12/ollama_environment.json`. If supplemental full *historical-config* 113-query real/oracle LLM evidence is wanted, the existing explicit-output invocation is:

```sh
run supplemental-legacyconfig-ollama "$P" scripts/evaluate_phase12.py --configs ollama_raw,ollama --require-ollama --out "$R/supplemental-legacyconfig-ollama.json" --perf-out "$R/supplemental-legacyconfig-ollama-perf.json" --checkpoint "$R/supplemental-legacyconfig-ollama.partial.jsonl"
```

This uses the hardcoded `rag_core.LLM_MODEL_NAME` in its environment check, not an arbitrary `OLLAMA_MODEL` override. Run only when that default tag/digest is approved. It uses dataclass-default pipeline flags and context-based correctness, **not the current production flags/strict answer criterion**. Do not market it as current-production LLM acceptance. No existing current strict runner flag switches it to Ollama. Complete current-production real-model semantic replay remains an external evidence gate; no new runtime/evaluator code was added in this documentation-only task. Never reuse an old checkpoint or change pins/labels/configuration to improve scores.

## E. Native Windows cleanup and Q35 — actual Windows required

Run only on an approved supported AMD64 Windows host with approved Python/native graph, local model/tokenizer, new disposable cold copies and private result paths. Record `$PSVersionTable`, `& $Py -VV`, CPU/OS/ABI, wheel/native/model/store hashes, exact commands and stdout/stderr/exit codes. `$env:HF_HUB_OFFLINE='1'`, `$env:TRANSFORMERS_OFFLINE='1'`, `$env:HF_DATASETS_OFFLINE='1'`, `$env:PYTHONDONTWRITEBYTECODE='1'`, `$env:M2C_MODEL_DIR='<approved-absolute-export>'`; no literal placeholder paths may be used.

```powershell
$CardCopy = Join-Path (Get-Location) 'data\vector_store'
$PageCopy = Join-Path $CardCopy 'page_collection'
& $Py -m pip check
& $Py -m pip freeze --all
& $Py scripts/preflight_verification.py
& $Py -m pytest tests/test_windows_portability.py tests/test_release_runtime.py tests/test_release_closure.py tests/test_stored_vector_safety.py tests/test_page_reader_no_implicit_create.py tests/test_focused_windows_diagnostic.py -q -ra --tb=long --junitxml="$Results\lifecycle.xml"
& $Py -m pytest tests -q -ra --tb=long --junitxml="$Results\backend.xml"
& $Py scripts/diagnose_windows_verification.py --store-quiesced --card-store "$CardCopy" --page-store "$PageCopy" --out "$Results\diagnostic.json"
& $Py scripts/probe_q35_reproducibility.py --store-quiesced --card-store "$CardCopy" --threads 1 --mkldnn on --out "$Results\q35-t1-on.json"
```

These are individual commands, **not** a run-all-without-checking script. For each native command capture `$LASTEXITCODE` immediately, save stdout/stderr and that exit code to new files, and stop on failed prerequisites. PowerShell redirection encoding varies by version; record it, retain JSON/XML direct outputs and never normalize sealed byte fixtures. Ensure all result files are absent before execution. The full suite includes the unchanged original retrieval/equality/newline assertions, not just the focused subset.

Require actual native `test_windows_sqlite_probe_observes_real_handle_release` **not skipped**, retained-client/finalizer tests, correct Win32 ABI/last-error/handle-close behavior, bounded nonbusy barrier, visible close/timeout errors, timeout then retry/same-path recreation and owner-bound outside-tree safety. No swallowed errors, global shutdown, Chroma cache/refcount reset or arbitrary sleep-as-PASS.

Q35 also needs the **historical raw Windows float**, exact producing source/model/query/card vectors/runtime/CPU/thread/BLAS settings and provenance. The probe explicitly reports `historical_raw_score_available=false`; a successful new run does not close historical provenance. Preserve original equality/rounding/tolerances. Optional separately approved forensic runs use new outputs with `--threads 2 --mkldnn on` or `--threads 1 --mkldnn off`; record changed process flags, never adopt them as a baseline correction. `--arithmetic-only` does not rerun inference. No `verify_windows.ps1` repair/install/refresh shortcut is authorized.

## F. Browser and evidence retention

After browser/build/private-test approval, limited same-host local browser smoke:

```sh
export SURA_PYTHON="$P"
node web/e2e/predeployment_smoke.mjs --out "$R/browser-local.json"
```

The existing script starts a loopback backend (default port 8347); ensure it is unused. This is not actual gateway/IAM/full accessibility certification. Complete the independent two-principal and semantic/accessibility/capacity/rollback matrix in [PRIVATE_REHEARSAL](PRIVATE_REHEARSAL.md), using approved secret injection, no public service and no production stores.

Retain a new evidence index with source commit, commands/exits, start/end times, input inventories, full results/tracebacks, all skips/warnings, model/corpus/daemon identity, reviewer/approver signatures and status per gate. Store sensitive or licensed raw responses/traces privately; publish only approved redacted evidence/hash references. No assertion/label/threshold change or failed-case omission is permitted.
