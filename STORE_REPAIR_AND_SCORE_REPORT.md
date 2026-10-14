# SURA — out-of-place store repair and Q35 investigation (v1)

**Status: NOT READY.** Linux disposable-copy engineering evidence, not native-Windows repair certification or permission to deploy/activate. Starting commit: `0a0e9ad9c03d68a8bdf42b2a8633b8a5588fe075`; working branch: `arena/b450cda2-chatbot`. Historical reports remain historical, including their readiness claims.

## Changes and root-cause groups

| New file | Purpose |
|---|---|
| `scripts/repair_page_store.py` | Separate opt-in, offline, out-of-place repair and read-only backup/candidate receipt verification. Not imported by production. |
| `scripts/probe_q35_reproducibility.py` | Offline Q35 inference on a temporary store copy; isolated backend controls and separately labelled frozen-vector arithmetic. Not an evaluator replacement. |
| `tests/test_page_store_repair.py` | 25 repair regressions, actual Chroma operations with explicitly synthetic fixture embeddings; no quality claim. |
| `tests/test_q35_probe.py` | Four probe arithmetic/path/worker safety tests. |
| `verification/store_repair_v1/linux_repair.json` | Actual cached-MiniLM-vector experiment: approved deletions, all remaining record hashes/metadata, ID sets, collection metadata, receipts and post-checks. |
| `verification/store_repair_v1/q35_controls.json` | Four real Linux inference configurations plus NumPy 1.26.4 frozen-vector arithmetic; versions, raw floats, query/vector evidence. |
| `verification/store_repair_v1/validation.json` | Test commands/outcomes, failed/blocked attempts, checkpoint verification and preservation evidence. |
| `STORE_REPAIR_AND_SCORE_REPORT.md` | This report, operator workflow, backup/rollback and remaining gates. |

1. **Store contamination:** two excluded capture-page records were present alongside 113 admitted chunks. This is not missing admitted content and must not be fixed by admitting the capture. Only IDs `e4375c1cad104b2eb7d027369bd76638/b1a202c9bb3011da2b24000f20dac9ef/000` and `/001` are approved for removal.
2. **Numerical reproduction:** Q35 sits near a four-decimal rounding boundary. Platform-specific strict disagreement is real; its historical numerical attribution is **not established**. It is independent of page-store contamination.
3. **Resource/harness context:** absent original-checkout stores block the original full backend run. The full-suite experiment uses independent disposable files and copied stores, not production-path installation in the original checkout.

## Repair contract and evidence

The utility requires BOTH offline/disposable acknowledgements, BOTH exact explicit IDs, a diagnostic matching the input's complete byte hashes, confirmed unadmitted capture provenance/exact target metadata/documents, sealed corpus/model identity, and the expected 113 admitted records. It rejects additional collections/IDs, missing chunks, admitted drift, unexpected collection stamps, changed corpus/checkpoint/capture inputs, stale diagnostic evidence, overlapping/existing destinations, symlinks and repository `data/` source/backup/output paths.

It takes a cooperative exclusive source lock outside the source; never opens source/backup through Chroma; copies and independently hashes a byte backup **before** creating the candidate; then audits a private candidate in subprocesses. It independently repeats the capture comparison, authorizes only the two deletions, and compares every remaining document SHA, **full metadata**, float32 embedding SHA, count and collection metadata before/after. The existing collection `vector_count=113` stamp is preserved, not changed with Chroma's forbidden metric-containing `modify` operation. Unexpected metadata aborts rather than being silently rewritten. Post-repair page integrity must pass.

Source/corpus/capture hashes and SQLite sidecars are checked at boundaries and polled every 100 ms; observed failures are sticky. **This does not lock out arbitrary Chroma writers or detect every write/revert between polls. Offline input is mandatory.** The source lock coordinates this utility only. An input copy says nothing about later changes in the original production directory; activation must separately compare current production state against its approved diagnostic. This utility does not make live-source repair safe.

Complete JSON receipts are fsynced to `.pending` files, then published without overwrite using hard links (NTFS/ext4 support required; unsupported filesystems abort). No directory-entry power-loss durability guarantee is made. Interruption/failure leaves inspection evidence and possibly a stage/store, but no valid verified candidate. Never resume or activate an interrupted output; choose new paths. A stale lock after a hard kill requires review, never automatic reclamation. Receipt verification detects byte/evidence drift; receipts are trusted local audit evidence, **not signatures against a malicious operator**. Opening a certified candidate directly through Chroma can change its bytes: test copies instead.

### Actual live-vector disposable experiment

Input: existing disposable `scratch/focused-windows/seeded-excluded-page-store`, NOT an original/production database. Diagnostic: `scratch/focused-windows/final-excluded.json`. Final utility outputs: `scratch/store-repair-v1/live-final-backup` and `scratch/store-repair-v1/live-final-candidate`. Earlier experimental outputs/logs are retained separately; they are not substituted for this final run.

| Check | Before → after |
|---|---|
| Count / ID set | 115 → exactly the expected 113; exactly two approved IDs removed |
| Admitted document hashes | All 113 identical and match generated corpus chunks |
| Admitted full record metadata | All 113 identical and match the canonical builder |
| Admitted float32 embedding hashes | All 113 identical |
| Entire collection metadata | Identical, including existing `vector_count=113` |
| Page integrity diagnostic | Expected extra-record failures → all checks pass, no missing/extra IDs |
| Input / verified backup bytes | Unchanged; independently matched before receipt publication |
| Backup / candidate read-only verification CLIs | Both exit 0 |
| Activation / original-store repair | **Neither performed** |

No new weights were downloaded. The earlier approved local MiniLM package and existing actual-vector fixture were used; synthetic repair-test embeddings are separate evidence.

## Q35: retained provenance and dependency/backend controls

### What historical evidence actually says

* `scripts/evaluate_card_retrieval.py:80,93` serializes similarities with `round(..., 4)`; `data/evaluation/card_retrieval_results.json` retains Q35/M2C-22 rank 5, `.3465`, **not a raw reference float**.
* `scripts/phase7b_validate.py:345–346` rounds retained top-5 distances to six decimals. `data/phase7B_validation.json` retains Q35 rank-5 distance `.65345`. Subtracting this rounded distance from 1 does not recover the raw historical similarity or tell which side of `.34655` it occupied.
* Q35 and the entire canonical `per_question` payload are unchanged at `c7527ed`, `9be6553`, and the starting HEAD. Canonical payload SHA-256: `b2252f3cba6e81084b05b07104d224c410ef6dacb61552fd33e7bbba01f28f32`. The `9be6553` change to this result file changed only `collection_manifest_sha256`, **not scores**.
* `data/retrieval_phase4_report.md` records the model files, tokenizer/sequence limit and third-party packaging. The retained card manifest contains a Windows Python310 model path, CPU/batch-16/normalized-384 configuration and Chroma 1.5.9. These are useful retained build clues, not a complete contemporaneous environment for original score generation; the manifest has later rebuild history.
* `data/phase7B_report.md`, section 3, explicitly documents a **recreated Phase 7B environment**: Torch **2.14.0**, Transformers **5.17.0**, sentence-transformers **6.1.0**, NumPy **2.4.6**, Chroma **1.5.9**, model package **0.1.0**. It also reports reproducing the earlier four-decimal results. This does not prove the original Phase 4 framework/kernel/CPU stack.
* `docs/RELEASE_REPORT.md`, section 16, separately claims ST 5.5.1 / Torch 2.5.1+cu121. This is a later generic dependency-inspection statement, not an original Q35 execution log. `data/phase12/ollama_comparison.json` records later Windows/Python 3.10.11 provenance, also not Phase 4 score-generation proof. `requirements.lock.txt` documents a later Linux Python 3.11 closure, not a retrospective original Windows lock.
* All 12 locally available commits were examined for available provenance. No authoritative original raw Q35 value, complete original dependency/artifact lock, CPU/BLAS/kernel configuration or contemporaneous score-generation log was located. Do not assert that one conflicting report identifies the original stack.

### New measurements (Linux CPU only)

Shared: Torch 2.14.1, ST 6.1.0, Chroma 1.5.9, NumPy 2.4.6, same local model file hashes and copied 29-card store. Default Transformers is 5.19.0. Controls affect only short-lived probe subprocesses, not production configuration.

| Transformers | Torch threads | MKLDNN | Q35 Chroma batch similarity | Single similarity | Both rank / 4dp |
|---|---:|---|---:|---:|---|
| 5.19.0 | 1 | on | .34654998779296875 | .34654998779296875 | 5 / .3465 |
| 5.19.0 | 2 | on | .34654998779296875 | .346549928188324 | 5 / .3465 |
| 5.19.0 | 1 | off | .34654998779296875 | .3465498685836792 | 5 / .3465 |
| 5.17.0 (isolated target) | 1 | on | .34654998779296875 | .34654998779296875 | 5 / .3465 |

Baseline comparison remains exact four-decimal equality. For the default observation, the difference from the **rounding boundary** `.34655` is about `-1.22e-8`; this is NOT a measured difference from an unknown historical raw score. A float32 distance ULP here is about `5.96e-8`. Float64 diagnostic cosine is `.3465500331046134` batch / `.34655002513189165` single, illustrating an arithmetic/backend boundary effect, **not an alternative accepted score**.

Isolated NumPy 1.26.4 frozen-vector arithmetic matched NumPy 2.4.6 here (float32 dot `.3465500473976135`, float64 cosine `.34655002513189165`). This did **not** rerun inference or Chroma under NumPy 1.26.4 and does not reproduce the original stack. Transformers 5.17.0 matched current inference here; these controls do not isolate Torch 2.14.0 vs 2.14.1, native Windows Chroma/kernel differences, or original hardware. No alternate large Torch/model download was performed. Small alternate library wheels were installed under ignored scratch targets only; release dependencies/venv were not replaced.

Latest Windows evidence remains **user-reported**, not Arena-executed or independently inspected: both single/batch `.3466`, rank 5, 70 prior focused passes, exact unadmitted capture matches, originals unchanged. Its strict mismatch remains a failed/unresolved reproduction gate. No batch-shape-only explanation, tolerant acceptance, baseline rewrite, dependency forcing or readiness inference is justified.

## Validation and preservation

Final affected run:

```bash
.venv/bin/python -m pytest tests/test_page_store_repair.py tests/test_q35_probe.py tests/test_focused_windows_diagnostic.py tests/test_windows_portability.py tests/test_map_root_identity.py tests/test_phase8_corpus.py tests/test_phase8_pipeline.py tests/test_phase7a.py -q -ra --junitxml=scratch/store-repair-v1/tests-final2-junit.xml
```

**194 passed in 43.27s.** Repair regressions cover successful 115→113 preservation, interruptions before/after deletion/before publication, copy/backup corruption and I/O failure, unexpected diagnostic/actual extra records, stale source bytes, observed concurrent/sidecar writes and sticky transient detection, corpus drift, actual post-delete admitted-metadata tampering, collection/target diagnostic metadata mismatch, exact approvals, production-path rejection, cooperative locks, atomic/no-overwrite receipts, byte-verification failure, and continuous capture-input hashing.

Original checkout `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest tests -q -ra`: **1283 passed, 124 skipped, 5 failed, 31 errors, 200 subtests passed (95.34s)**. All 36 nonpassing cases were inspected: `FileNotFoundError` for the absent original `data/vector_store/page_collection`, not repaired by installing a store there. Preserve these failed outcomes, not an all-green interpretation.

Independent disposable file copy: tracked files plus the four new code/test files; copied scratch card store to its `data/vector_store` and copied the verified candidate to its page-store subdirectory. No originals opened through Chroma. First run without local Git metadata: **1443 passed, 1 failed, 225 subtests passed (190.59s)**; the sole failure was the repository-surface secret scan receiving no tracked files in the ignored, non-Git file copy. No assertion was changed. An attempted shared-Git-environment rerun was stopped early on inspection because test fixtures execute Git writes; original HEAD/index/author settings remained unchanged. The final independent copy includes separate credential-free local Git metadata (HEAD/index/objects/refs/packed-refs; no shared Git environment/config/credentials/hooks), staying on the same branch. **Final independent-copy full suite: 1444 passed, 0 failed/errors/skips, 225 subtests passed in 186.00s**, with one Starlette/httpx deprecation warning. Command (cwd `scratch/store-repair-v1/full-suite-copy`): `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /home/user/chatbot/.venv/bin/python -m pytest tests -q -ra --junitxml=/home/user/chatbot/scratch/store-repair-v1/full-copy-final-junit.xml`. The committed validation JSON retains exact commands, all 36 original failure traces, skip reasons and log hashes. The original-checkout resource failure remains recorded regardless of isolated results.

All 222 Phase 7 checkpoint pins, source corpus, capture, historical results and starting tracked files are verified unchanged; no production-path store was created in the original checkout. Checkpoint-pinned evaluators, scores, queries, labels, manifests, caches and production configuration are untouched. Frontend/browser/security/real-Ollama and native-Windows repair/full-suite gates were not certified by these Linux backend runs.

## Safe Windows update and disposable repair procedure

Do not run the broad helper's checkout refresh `--apply`, builders, package reinstalls, or in-place repairs. Do not replace `av/`, normalize local corpus files or auto-activate a candidate. Run from the intended checkout and inspect any local edits; a normal fast-forward should stop rather than overwrite conflicting work. Use the delivered branch commit from the handoff.

```powershell
$ErrorActionPreference = 'Stop'
if ((git branch --show-current).Trim() -ne 'arena/b450cda2-chatbot') { throw 'Wrong session branch; do not switch branches automatically' }
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed' }
git merge --ff-only origin/arena/b450cda2-chatbot
if ($LASTEXITCODE -ne 0) { throw 'Review divergence/local edits; no reset/clean/force' }
$Py = (Resolve-Path .\av\Scripts\python.exe).Path
& $Py -m pytest tests/test_page_store_repair.py tests/test_q35_probe.py tests/test_focused_windows_diagnostic.py tests/test_map_root_identity.py tests/test_phase8_corpus.py -q -ra
if ($LASTEXITCODE -ne 0) { throw 'Native focused tests failed' }

# MANUAL PRECONDITION: stop every SURA/Chroma writer before taking a cold copy.
# Do not claim this acknowledgement establishes quiescence by itself.
$Out = Join-Path $env:TEMP ('SURA-store-repair-v1-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Out | Out-Null
$Original = (Resolve-Path .\data\vector_store\page_collection).Path
$InputCopy = Join-Path $Out 'offline-input'
$Backup = Join-Path $Out 'backup'
$Candidate = Join-Path $Out 'candidate'
$Diag = Join-Path $Out 'input-diagnostic.json'
$OriginalHashes = Join-Path $Out 'original-before.json'
& $Py -c "import sys,json; from pathlib import Path; sys.path.insert(0,'scripts'); import repair_page_store as r; Path(sys.argv[2]).write_text(json.dumps(r.tree(Path(sys.argv[1])),sort_keys=True),encoding='utf8')" $Original $OriginalHashes
if ($LASTEXITCODE -ne 0) { throw 'Original byte inventory failed' }
Copy-Item -LiteralPath $Original -Destination $InputCopy -Recurse
& $Py scripts/diagnose_windows_verification.py --store-quiesced --page-store $InputCopy --out $Diag
$DiagExit = $LASTEXITCODE
if ($DiagExit -notin @(0,2)) { throw 'Diagnostic execution/incompleteness failure' }
# Exit 2 retains integrity/strict-score failures; it is NOT a release pass.
# Repair independently checks the exact permitted page-only failure scope.
& $Py scripts/repair_page_store.py --source-store $InputCopy --diagnostic $Diag --backup-dir $Backup --output-dir $Candidate --approve-id 'e4375c1cad104b2eb7d027369bd76638/b1a202c9bb3011da2b24000f20dac9ef/000' --approve-id 'e4375c1cad104b2eb7d027369bd76638/b1a202c9bb3011da2b24000f20dac9ef/001' --store-quiesced --disposable-copy
if ($LASTEXITCODE -ne 0) { throw 'Repair aborted; retain evidence, never activate' }
& $Py scripts/repair_page_store.py --verify-backup $Backup
if ($LASTEXITCODE -ne 0) { throw 'Backup invalid' }
& $Py scripts/repair_page_store.py --verify-candidate $Candidate
if ($LASTEXITCODE -ne 0) { throw 'Candidate invalid' }
& $Py -c "import sys,json; from pathlib import Path; sys.path.insert(0,'scripts'); import repair_page_store as r; assert r.tree(Path(sys.argv[1])) == json.loads(Path(sys.argv[2]).read_text(encoding='utf8')), 'Original store changed'" $Original $OriginalHashes
if ($LASTEXITCODE -ne 0) { throw 'Original bytes changed; stop investigation' }
& $Py scripts/diagnose_windows_verification.py --store-quiesced --page-store (Join-Path $Candidate 'store') --out (Join-Path $Out 'candidate-diagnostic.json')
$CandidateDiagExit = $LASTEXITCODE
if ($CandidateDiagExit -notin @(0,2)) { throw 'Candidate diagnostic execution failed' }
# Inspect page.all_pass, 113 exact IDs and unchanged record evidence.
# Card Q35 may still return strict failure/exit 2. Do NOT call it a pass.
& $Py scripts/probe_q35_reproducibility.py --card-store .\data\vector_store --store-quiesced --out (Join-Path $Out 'q35-native.json')
if ($LASTEXITCODE -ne 0) { throw 'Q35 probe failed' }
# STOP: retain $Out. No activation/configuration/store replacement is authorized.
```

Use an external destination on a local NTFS filesystem, not the original store, repository `data/`, an existing output, a shared/network drive without hard-link support, or any nested source/backup/candidate path. Keep writers stopped throughout snapshot/diagnostic/repair checks. If the approved records are already absent or evidence differs, **abort and review**, do not add them back or force the utility. A new candidate is not automatically eligible after the original production data has changed.

### Backup / rollback

* For this experiment, no active store changed: rollback is **do not use the candidate**; retain the original and evidence untouched. Never delete/rebuild an original database as cleanup.
* The backup is the byte-exact **115-record pre-repair snapshot**, not an assertion of a healthy 113-record store. Keep it private and unopened through Chroma.
* Before any separately authorized restore, run `--verify-backup`; failure blocks restore. Copy `backup/store` to a **new, nonexistent** offline restore directory, independently compare its complete byte inventory against `BACKUP_VERIFIED.json`, and review application routing to that new path separately. Never overwrite a current store or copy WAL-backed live files. This task authorizes no production promotion or rollback operation.
* Retain `before.json`, `after.json`, `VERIFIED.json`, `BACKUP_VERIFIED.json`, diagnostic and test transcripts. Run `--verify-candidate` before reviewing eligibility. Missing/invalid receipts, changed bytes or an `ABORTED.json` block use; a directory named `store` alone proves nothing. Never automatically reclaim a lock or resume an interrupted candidate.

## Remaining blockers

1. Native Windows execution/review of this repair and its receipts, with the latest actual diagnostic and untouched-original evidence; current Windows input is user-reported only.
2. Strict Windows Q35 reproducibility/original raw numerical provenance unresolved; historical values and equality rules remain unchanged. Linux controls are not a Windows closure.
3. Separately reviewed activation/migration against **current** production state, after offline-source and writer exclusion are genuinely established. No activation is provided here.
4. Full native verification and outstanding semantic grounding/quality, real Ollama, browser, security/performance and M2C-18 authoritative-identity gates from prior reports. No unverified guide/page mapping is admitted.

**NOT READY. No public deployment performed or authorized.**
