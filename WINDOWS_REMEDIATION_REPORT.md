# SURA — native Windows remediation (2026-10-14)

**Verdict: NOT READY. No public deployment.**

Repository `Sravan-git7/chatbot`, branch `arena/b450cda2-chatbot`. Baseline release: `d7ca2156b5352f0e2a5e5a00c7c14d5b1f1ed1a8`. **Verified source commit: `191ce5d83ea1e7802052d380a47f09ec9f8f78e5`.** The final evidence/docs-only delivery SHA is provided in the delivery message (this report cannot contain its own commit hash). No source changes followed that source commit.

## Evidence boundary

The user reports **35 failed, 1 error, 1 skipped, 1,330 passed and 225 subtests passed** on native Windows/Python 3.10, with output at `D:\temp\SURA-verification-d7ca215-20261014001118`. Arena cannot read that drive. The full tracebacks, test names and environment output have been requested but not received. **This report does not claim to have inspected that output or assigned all 35 failures to known causes.** The table below separates code-confirmed defects, user-reported observations, Linux reproductions and pending investigation.

## Root-cause groups and dispositions

| Group | Established evidence | Remediation / remaining gate |
|---|---|---|
| Unix-only resource import | `evaluate_phase9.py` unconditionally imported `resource`; an import hook reproduces its absence. | Optional `platform_metrics.peak_rss_mb()` returns `None` plus explicit UNSUPPORTED status on Windows. Linux/macOS units are distinguished. Evaluation correctness is independent of RSS availability. |
| Native newline translation in unsealed writers | `Path.write_text()` uses platform-native newline output. Phase 9's corpus audit is executed by a test that compares original bytes after writing; on Windows this could mutate an otherwise byte-correct historical checkout. Query freeze hashes describe UTF-8 LF data, not translated CRLF bytes. | Phase 8/9 query, page-corpus, corpus-audit and evaluation writers use explicit UTF-8 bytes. New tests prohibit the text-mode writer and compare scratch outputs against the exact committed queries, freeze, corpus records and audit. No labels/serialization content/pins change. |
| Sealed generators' newline translation | The Phase 3 chunk producer, Phase 7C identity/citation producers and other historical scripts are pinned by checkpoint or later tests. Original byte-reproduction tests remain unchanged. | A **separate** LF-path adapter reproduces all three committed chunk JSON hashes using the original chunk algorithm and refuses overwriting existing output or repository data. It does NOT replace the original sealed producer or make its native Windows test green. An approved producer/checkpoint migration is still required. Other sealed text writers are also unresolved; no global newline monkeypatch hides their failures. |
| Chroma temporary-store handles | `PersistentClient` caches systems beyond client lifetime. Several sealed tests and Phase 5's evaluator clean temporary directories while those cached systems remain live. Linux unlink behavior masks Windows handle restrictions. | Scoped `ChromaTemporaryDirectory` stops only cached persistent systems inside the owned tree, removes those cache entries, then cleans up. Explicit cleanup and GC/finalizer paths are covered. A pytest lifecycle fixture uses this real resource adapter for the sealed tests without changing their assertions/code/pins. A standalone Phase 5 wrapper provides the same lifecycle; the original pinned evaluator remains unchanged. Real Chroma 1.5.9 tests retain an unrelated store and verify it stays usable. Native Windows cleanup and other Chroma versions still require a run. |
| Page collection 115 vs manifest 113 / wrong IDs | User-reported; the Windows database has not been inspected. The database is **ignored local generated state**, not a tracked committed store. Its existence alone does not prove freshness. | A diagnostic snapshots quiesced stores, opens ONLY scratch copies in child processes, and reports exact extra/missing IDs, document/metadata differences, corpus hash, chunk fingerprint, collection name/config, model file hashes and counts. It hashes originals before/after; children exit before scratch cleanup. No rebuild/migration has been performed on the user's store. Actual origin of the two extra vectors is pending the diagnostic. |
| Floating-point Phase 4/5/7B discrepancies | Sealed reference similarities are quantized to 4 decimals; Phase 7B also retains its existing `1e-6` vector threshold. A hardware/library change can alter raw float32 bits or a rounding boundary without altering rank, but that has NOT been established for Windows. | The diagnostic records package/model provenance, raw vector deltas and hashes, ranking changes, exact 4dp disagreements and proximity to rounding boundaries. Linux reproduced all recorded top-five rankings and 4dp scores. No tolerances, expected scores, ranking rules or decision criteria were changed. Windows classification remains pending. |
| Legacy `chroma_db` existence | `.gitignore` excludes it; `git ls-files chroma_db` is empty. Current SURA uses card/page stores under `data/vector_store`. **Legacy** `rag_core.py`, `rag_modes.py --mode legacy`, `test_search.py` and `test_retrieval.py` can use `chroma_db`; it is not universally inert. | No directory deleted or automatically moved; absence assertions retained. The diagnostic records local existence/tracking/ignore status and file hashes. Only after the user confirms legacy tooling is stopped/unused may it be archived outside the checkout with a verified backup. |
| Other product/dependency/local-state failures | Exact failed test identities/tracebacks and native package closure are not yet available. | Pending full original output and new native run. Do not classify these as fixed or replace Python 3.10 dependencies blindly. |

## Files changed and why

- `scripts/platform_metrics.py`, `scripts/evaluate_phase9.py`: remove mandatory Unix import; explicit unsupported telemetry; byte-exact LF outputs.
- `scripts/{page_corpus,build_phase8_queries,build_phase9_queries,phase9_corpus_audit,evaluate_phase8}.py`: explicit bytes for unsealed deterministic writers; same Linux output bytes.
- `scripts/chroma_temp.py`, `tests/conftest.py`: scoped real-Chroma resource ownership, including finalizer; preserve frozen test files and unrelated persistent systems.
- `scripts/run_portable_evaluation.py`: opt-in standalone lifecycle wrapper around the unchanged Phase 5 evaluator, scratch output only.
- `scripts/build_chunk_candidates_portable.py`: versioned scratch-only LF writer adapter; no historical regeneration in place.
- `scripts/diagnose_windows_verification.py`: non-destructive copied-store/model/numerical diagnostic; optional scratch candidate paths do not repoint production.
- `scripts/preflight_verification.py`: accurate warnings for legacy local state and the unapproved sealed-writer migration.
- `scripts/verify_windows.ps1`: diagnostic-only mode, transcript/package capture and complete pytest text/JUnit output. It still fails on failed gates.
- `tests/test_windows_portability.py`: 22 parametrized regression cases covering unavailable metrics, units, LF writes/frozen bytes, real client cleanup/isolation/finalizer, diagnostics and failure detection.
- This report, local verification documentation and new machine-readable Linux remediation results. Prior release/evaluation reports are preserved, not silently updated as new measurements.

## Actual verification

| Gate | Before | Final actual run |
|---|---|---|
| Native Windows/Python 3.10 | User-reported 1,330 passed /35 failed /1 error /1 skipped /225 subtests | **NOT RUN**, original full output not received |
| Complete Linux backend | Historical d7ca215: 1,366 passed +225 subtests | **1,388 passed +225 subtests**, zero failures/skips, one warning, **144.51 s** |
| Final focused portability/Phase 3/5/7A/8/9 suites | Not a native baseline | **251 passed**, zero failures, **25.77 s** |
| New portability regressions | None at d7ca215 | **22 passed**, including real Chroma and byte-exact scratch reproduction |
| Frontend typecheck / full ordinary suite / production build | Existing release pass | **PASS /119 passed +1 live-test skip /PASS** |
| Frontend full live-HTTP component suite | Existing release pass | **120 passed, zero skips**, 12 files; real API +jsdom, NOT Chromium |
| Standalone Phase 5 lifecycle wrapper | Original leaves cached temp system alive | **PASS** on Linux; recorded deterministic result reproduced |
| Copied-store diagnostic | Windows 115/113 reported; inaccessible | **PASS** on Linux; user Windows diagnosis pending |
| Native PowerShell / real browser / real Ollama | Required independent gates | **NOT RUN** in this remediation environment |

Machine-readable source/evidence hashes, full backend/focused output, live component output and copied-store diagnosis: `verification/windows_remediation_v1/`. Final backend gate ran against source commit 191ce5d; no source/test/dependency changes followed it.

Linux environment: Python 3.11.2, Chroma 1.5.9, sentence-transformers 6.1.0, Torch 2.14.1, NumPy 2.4.6; Node 22.22.3. Dependencies reconstructed from the existing Linux lock. Arena had no vector stores, so **only missing Arena stores** were provisioned with manifests under ignored `scratch/windows-remediation/`; no user store was touched and no tracked manifest overwritten. Native Windows/Python 3.10 and PowerShell execution are **NOT RUN** here. No new generative model was downloaded.

First pre-final Linux full run: 1,382 passed +225 subtests, zero failures/skips, one warning, 144.04 s (16 regressions at that point). A later focused run overlapped another suite opening the same store and produced one Phase-5 raw-file-hash failure; deterministic results and ranking still matched. That run is **invalid as isolated reproduction evidence**, documented here, and was rerun serially. Tests are not weakened to ignore the concurrent mutation. Final results above refer only to serialized runs after final changes.

Fresh diagnostic on Arena's 113-vector page store: expected/manifest/actual counts all 113; exact IDs, corpus fingerprint, chunk fingerprint, metadata and model files match. Card count 29; stored-vs-recomputed max vector delta `7.450580596923828e-09`, below the unchanged `1e-6` threshold. Phase 4: 50 queries; Phase 5: 54 queries; no rank or 4dp changes. Maximum difference from *quantized* recorded scores: approximately `4.9988e-05` and `4.9443e-05`, respectively (not a new tolerance). Copied-store diagnostics verified original file hashes unchanged. These are **Linux results, not an explanation of the Windows discrepancy**.

The standalone portable Phase 5 evaluator also reproduced recorded JSON behavior, identical Phase 4 top-five rankings, and unchanged source-store hashes. Its recomputed vectors had a different informational float hash but max difference `9e-08`; the existing threshold and evaluation assertions remain unchanged.

## Historical preservation

Verified all **222 Phase 7 checkpoint hashes** unchanged. Verified no diff from d7ca215 in `data/`, `eval/`, `RELEASE_REPORT.md` or `docs/RELEASE_REPORT.md`. Original sealed chunk producer, Phase 5 evaluator, Phase 7A–F tests, identity/citation producers and all frozen labels/results/manifests remain unchanged. No changes to M2C-18 mapping: it remains fail-closed. New Linux evidence is separate, not a replacement for old evaluations.

## Windows pull and diagnostic first

Stop SURA/backend/frontend/legacy scripts and any Chroma process first. Do **not** rebuild the existing stores. Retain the original failed result directory. Run this compact PowerShell sequence, substituting the exact delivered SHA:

```powershell
Set-Location D:\chatbot-phase12
$ErrorActionPreference = 'Stop'
if (git status --porcelain) {
    git stash push -u -m 'pre-windows-remediation-backup'
    if ($LASTEXITCODE) { throw 'Preservation failed' }
}
git fetch origin
if ($LASTEXITCODE) { throw 'Fetch failed' }
if ((git branch --show-current).Trim() -ne 'arena/b450cda2-chatbot') {
    throw 'Wrong branch; stop and switch safely after preserving changes'
}
$Release = 'PASTE_EXACT_DELIVERED_SHA'
git merge --ff-only $Release
if ($LASTEXITCODE) { throw 'Divergence: stop; no reset or force push' }
if ((git rev-parse HEAD).Trim() -ne $Release) { throw 'Unexpected HEAD' }
.\scripts\verify_windows.ps1 -Python .\av\Scripts\python.exe -DiagnosticsOnly
```

The diagnostic exits nonzero for mismatched stores/numerical gates but saves its JSON and transcript. **Send these plus the original failure output**; do not resolve an integrity warning by rebuilding in place. Existing venv/model/caches/legacy store stay untouched. No dependency installation is requested before capturing drift evidence.

After diagnosis (or to measure remaining failures without changing local state):

```powershell
.\scripts\verify_windows.ps1 -Python .\av\Scripts\python.exe
```

This runs the full existing verification, not a selected subset. Its output includes `backend-pytest.txt`, `backend-junit.xml`, `verification-transcript.txt`, and the prior versioned quality/benchmark outputs under a new `%TEMP%\SURA-verification-*` directory. Do not add `-BuildMissingStores` for the reported inconsistent existing stores. Native sealed newline/legacy-absence tests may still fail; those failures are retained, not certified away. `-Ollama` is a separate positive inference/performance gate using the already installed model, not extractive evidence.

## Optional reviewed experiments (not a migration)

Portable chunk-byte reproduction to a NEW directory outside repository data:

```powershell
$Scratch = Join-Path $env:TEMP ('SURA-portability-' + (Get-Date -Format yyyyMMddHHmmss))
New-Item -ItemType Directory $Scratch | Out-Null
.\av\Scripts\python.exe scripts\build_chunk_candidates_portable.py --out-dir (Join-Path $Scratch 'chunks')
.\av\Scripts\python.exe scripts\run_portable_evaluation.py --out (Join-Path $Scratch 'phase5.json')
```

If the diagnostic establishes a stale page store, a **reviewed** proposal is: keep an offline verified backup of the entire original store; build a candidate into `$Scratch\page-store` using `build_page_collection.py --vector-dir ... --manifest ...` WITHOUT `--rebuild`; inspect it with `diagnose_windows_verification.py --page-store ... --store-quiesced --out ...`; compare corpus/IDs/model/quality and numerical gates; approve activation separately. Current production still points at its original store. This mission does not silently replace it.

Only if the legacy store is confirmed unrelated to the active workflow, archive it **outside the checkout** after stopping legacy tooling and recording hashes. Check `git ls-files -- chroma_db` returns no tracked paths; make a verified backup, then use an explicit approved `Move-Item -LiteralPath .\chroma_db -Destination <new-external-archive-path>`. Do not delete it, put it into protected backups, or weaken absence assertions. Restoring it supports legacy tooling but will again violate the historical clean-checkout test precondition.

## Outstanding gates

1. Obtain original Windows output; account for every failed test and the error; inspect local diagnostic (115-vector origin, float precision/ranking changes and package drift).
2. Review sealed-writer/checkpoint migration; native Windows full suite must pass without lowered assertions, changed gold or excluded tests.
3. Native Windows handle cleanup and PowerShell runner must actually be executed. Chroma internal lifecycle adapter is verified with 1.5.9 here, not every ranged dependency version.
4. Semantic quality remains a separate prior gate: strict reference correctness 37/65 and Phase-3 prohibited flags are unresolved; lexical grounding is not semantic truth. No new semantic-quality claims are made in this portability run.
5. Real Ollama, Chromium browser, Chroma advisories/public auth/TLS/per-user isolation and hard execution cancellation remain open as documented in `FINAL_RELEASE_REPORT.md`.

**NOT READY. These changes are remediation and better evidence capture, not a native Windows certification or deployment authorization.**
