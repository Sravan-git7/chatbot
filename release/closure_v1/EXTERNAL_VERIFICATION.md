# Minimal external verification — prerequisites, not executed certification

**All workflows below are BLOCKED until actual resources/evidence exist.** These are operator procedures, not authorization to deploy/activate, repair stores or download models. Use a new isolated clone of the same branch at the reviewed delivery SHA; keep original user work, historical artifacts and live stores untouched. Select an approved existing interpreter as `P`/`$Py` and a new private results directory `R`/`$Results`. Record exact exits, stdout/stderr, all failures/skips/warnings, OS/architecture/package/model/store hashes and source commit. Never put credentials in command arguments, URLs or reports.

## Common model/store prerequisite

Need approved local all-MiniLM-L6-v2 files + exact tokenizer and original model provenance, compatible installed Torch/sentence-transformers/transformers/numpy/Chroma graph, and verified **cold disposable copies** of both card and page stores with their corpus/chunk/collection manifests. The Linux version lock is not a Windows artifact lock. Do not install a large substitute runtime or build/repair a live store to hide a blocker.

After all source writers exit, hash every source file including sidecars/HNSW files; copy to a new private backup, verify exact bytes, restore to another new test path, then recheck source hashes. Any concurrent writer/drift aborts. Application factories resolve stores relative to the release root: arrange disposable copies in that isolated test root's expected `data/vector_store` layout only under operator approval; do not invent an environment override or populate the preserved checkout. Diagnostics below accept explicit copy paths.

```sh
P scripts/preflight_verification.py
P -m pytest tests -q -ra --tb=long --junitxml=R/backend.xml
P benchmarks/run_quality.py --source-commit <reviewed-delivery-SHA> --out R/quality.json
```

`P`/`R` are shell placeholders, not literal executables. Run explicit arguments with quoting on the target. Preflight success is only resource availability. Full model-backed startup, routing, query embedding reuse, golden evaluation, all safety/concurrency assertions and independent substantive correctness must still execute.

## Native Windows / Q35 — specific runtime + historical owner

Prerequisites: actual supported AMD64 Windows, approved Python environment (record exact version, including whether 3.10), exact Chroma **1.5.9** package provenance and complete Windows dependency/native closure. Published PyPI wheel `chromadb-1.5.9-cp39-abi3-win_amd64.whl`, SHA256 `4fd0b560e56761b7f3cb4d5c6205fd5f20814484b4a3e4e9af9038c2b428fc6c`; metadata is not evidence of installation or successful cleanup. Also require common local model/tokenizer and cold-copy stores.

```powershell
& $Py -m pip freeze --all
& $Py -m pytest tests/test_windows_portability.py tests/test_release_runtime.py tests/test_release_closure.py -q -ra --tb=long --junitxml="$Results\lifecycle.xml"
& $Py -m pytest tests -q -ra --tb=long --junitxml="$Results\backend.xml"
& $Py scripts/diagnose_windows_verification.py --store-quiesced --page-store "$OfflinePageCopy" --card-store "$OfflineCardCopy" --out "$Results\diagnostic.json"
& $Py scripts/probe_q35_reproducibility.py --store-quiesced --card-store "$OfflineCardCopy" --out "$Results\q35.json"
```

Paths/results must be new; writers stopped before diagnostic acknowledgements. Original Windows test/assertions stay unchanged. Require actual retained-client/finalizer/SQLite-sharing delay/timeout/retry/same-path/outside-owner/partial-stop assertions, with visible cleanup failures and no global shutdown/cache/refcount resets. No `verify_windows.ps1` refresh/repair/install shortcut.

Q35 additionally requires **historical raw Windows float and producing environment**, exact historical strict path, card/query/vector hashes, single-vs-batch encoding/rank/distance arithmetic and Torch/backend/thread provenance. Old Windows `.3466` is rounded, not recoverable raw data. New measurements or float64 diagnostics cannot supply historical provenance; unchanged strict equality/tolerances remain mandatory. Missing historical artifacts keep Q35 BLOCKED even after a successful new run.

## Real Ollama — specific runtime + approved model owner

Need actual local daemon, already-approved exact model name/digest and common retrieval resources. Record daemon/version and `/api/tags` digest without pulling/downloading. No paid/external provider substitution. After explicit approval to run a **private disposable test service**, not production activation:

```sh
P scripts/live_smoke.py --generator ollama --out R/ollama-http.json
```

The smoke launches a local test process; do not run it merely for inventory. Pin the approved model through the documented process configuration. Verify returned generator/model, grounded substantive answers and citations, insufficient-evidence refusal and no extractive fallback. Interrupt only the owned test daemon/network; record timeout/failure, concurrent requests, client cancel, permit/queue recovery, subsequent successful answer, shutdown/drain and restart. A tags response or mocked generation is not real inference/cancellation proof. Existing smoke alone does not certify the entire failure matrix.

## Real browser / accessibility — specific runtime + production-like ingress

Need installed supported Chromium/Playwright binary, locked frontend dependencies + production build, common live resources, and a private approved gateway/session for production-profile tests. **No browser was installed or run here.** Frontend tests are jsdom, not browser certification.

For the limited local real-browser smoke after private-test approval, point `SURA_PYTHON` to the approved interpreter, choose an unused local port (the existing script uses 8347), ensure a new output path, then:

```sh
node web/e2e/predeployment_smoke.mjs --out R/browser-local.json
```

This script starts a loopback test service and checks grounded rendering/network failure/recovery only. It is **not** the authenticated production-ingress, full cancellation or accessibility gate. Against the approved private gateway separately verify login/logout/session expiry; no bearer secret in browser assets/storage; two principals/contexts; 401/403/429/413/504 and service/model outage/recovery; cancel while queued/generating and subsequent successful request; complete answer + source display; keyboard-only operation, focus/live-region announcements and axe results with screenshots/raw browser traces. Keep every failure and skip. No public binding/deployment is authorized by these procedures.

The Python `frontend_live_verification.py` is a jsdom + real-HTTP helper, **not a browser test**. `--help`/invalid arguments are now parsed without launching anything; invoking it without arguments still intentionally starts a local backend and requires private-test approval/resources.

## Authoritative SAP evidence — external content and independent reviewer

Need authentic guide/version/build/TOC/page captures from the authoritative SAP source, their hashes/URLs/retrieval provenance and independent SAP review. For M2C-18 specifically reconcile requested guide `9442486404b54071b4ebeab6a16628e7` and page `b1a202c9bb3011da2b24000f20dac9ef` with the conflicting capture under `e4375c1cad104b2eb7d027369bd76638` / deliverable `40374490`. Capture identity alone is not substantive page/version verification. Keep the current exclusion until validated; no corpus/store mutation or invented mapping.

Reconcile the published 37/65 narrative against exact producing artifacts; the frozen `phase12_results.json` evidence configuration reports 38/65 and two wrong-page answers, not a new run. Review P12-002 ELDM vs FPR3 and P12-027 ISU_AMI_1 navigation-pointer evidence, all negative-label answers, ambiguity, list relevance and procedure completeness. Frozen labels remain immutable; any independently approved additional gold must be separately versioned with rationale, reviewer and claim-level source spans.

After resource/authority prerequisites and private API approval:

```sh
P eval/release_v1/verify.py --url https://<approved-private-gateway> --out R/adversarial-observations.json
```

Supply the backend/gateway credential through the approved secret manager only if that endpoint's authentication contract requires it. Do not paste it in a command. Quote/identity overlap is CANDIDATE, not substantive correctness. Require >=95% strict answerable correctness, 100% claim/source identity, zero unsupported/wrong-guide/version factual answers and 100% safe negatives. Abstention never counts as a substantive correct positive answer. Full frozen/new RAG/API replay and independent adjudication are mandatory.

## Production infrastructure / rollback / human approval

Need actual deployed known-good code ID, compatible model/store/corpus backup, platform/service/ingress configuration, authorization/log sinks, intended capacity host, monitoring/owners, restore plan and explicit approver. Repository ancestry is not production rollback. Before any activation, rehearse cold backup -> hash validation -> restore into a new unused path -> authenticated semantic smoke -> service-manager/release-pointer rollback on a **private isolated infrastructure rehearsal**, preserving originals and both trees. Inject backup corruption and failed readiness; verify rejection, recovery and no acknowledged data/work loss. Document RTO/RPO and compare measured restore time to the operator's declared requirements.

On intended hardware measure full HTTP p50/p95/p99/RPS/cold/warm/stage/resource and cancellation/drain/recovery with frozen workloads, actual limits and multiple legitimate client IPs where needed. Count every reject/429/error/timeout/incorrect answer; no sandbox capacity extrapolation. Security must validate actual OS/native/model graph, Chroma mitigations and ingress isolation before authorized risk acceptance. Human approval remains required for exposure, migrations, store replacement, candidate activation and any material security exception. **None is authorized or executed by this handoff.**
