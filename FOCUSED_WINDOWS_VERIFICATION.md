# Focused Windows store and rounding investigation — 2026-10-14

**Verdict: NOT READY. No public deployment.**

Branch: `arena/b450cda2-chatbot`. Baseline: `a155a8795e52135f6e55e298bf82965a6bcea8b2`.
Tested source commit: **`afc76b024b42d74b0951d8f29207abcd440b3503`**. The final documentation/evidence-only commit is given in the delivery message. No source changes followed the tested source commit.

The Windows artifact `D:\temp\SURA-verification-a155a87-20261014060253\store-diagnostic.json` was **not accessible from Arena**. The Windows findings below are the user's supplied summary, correlated with committed source evidence and new Linux experiments. Native Windows and PowerShell were not executed here.

## 1. Two extra chunks: confirmed source identity, not a corpus correction

Both IDs identify the same page:

- Guide `e4375c1cad104b2eb7d027369bd76638` — **Enterprise Services in Financials**.
- Page `b1a202c9bb3011da2b24000f20dac9ef` — HTML title **Contract Account**.
- Saved response `captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json`, SAP deliverable **40374490**, SHA-256 `02347ba7114d855d038aceac7d509071aa48f438729584fb3ef43c65b70fa8ce`.
- `data/page_corpus/manifest.json` explicitly lists this capture under `unused_captures`. M2C-18 is `excluded_conflicting_identity`; no effective guide/page is selected.

The card's guide is `9442486404b54071b4ebeab6a16628e7`, **not** this captured guide. Existence of content in the other deliverable does not authorize a source-identity correction. M2C-18 stays fail-closed.

Re-extracting and re-chunking the unused HTML **in memory**, with the current exact MiniLM tokenizer and `B_heading_200`, produces exactly:

```
e4375c1cad104b2eb7d027369bd76638/b1a202c9bb3011da2b24000f20dac9ef/000
e4375c1cad104b2eb7d027369bd76638/b1a202c9bb3011da2b24000f20dac9ef/001
```

These are **unadmitted/orphan vectors relative to the current 113-chunk corpus**, not valid additions to its manifest. They are not duplicate IDs of admitted chunks. IDs alone do not prove stored text equality, duplicate text, insertion time, or creator. The new diagnostic exports hashes/metadata, checks exact text duplication against admitted chunks, and compares each extra document against the unused capture's current chunks. The original a155a87 report did not export those extra documents, so the actual Windows content match still requires the new diagnostic.

**Safe reproduction:** Arena built clean card/page stores only under ignored scratch, cloned the scratch page store, and added live MiniLM embeddings of the two unused-capture chunks to that separate fixture, with no card mapping assigned. This reproduced 115 actual vs 113 expected, exactly the two reported IDs, and two positive capture-content matches. The diagnostic returned 2 with zero execution errors and verified both inspected source stores byte-unchanged. This demonstrates the mechanism, **not the historical insertion sequence on Windows**.

### Preventive implementation defect fixed

The page builder previously loaded every JSON returned by the directory glob, without checking the admission manifest. A stray/unadmitted page record could therefore be embedded while the collection inherited the current manifest's corpus hash. The builder now validates exact admitted document IDs, duplicate IDs, guide/page fields, source IDs, text hashes and the corpus fingerprint **before loading the model or opening/deleting/rebuilding any collection**.

It refuses inconsistent input; it does not silently drop files, rewrite the manifest, repair existing stores, or delete stray records. A regression with an existing-store sentinel and `rebuild=True` verifies rejection occurs before any store access. This closes a reproducible future contamination path. Because the user reports the current local corpus matches HEAD structurally, it does **not** prove that a stray file is the current Windows cause: the existing vector store is stale/inconsistent with that corpus and requires separately approved remediation.

## 2. Exit code 2 is expected for completed failed checks

At a155a87, the parent returned 2 for any failed aggregate gate, including the reported count/ID and strict score mismatches. It also conflated some blocked/child failures with that code. **Old code 2 alone was not sufficient to distinguish them.** For a completed investigation, `worker_exit == 0` and `original_store_unchanged == true` distinguish expected check failures from a child crash; check both workers, not only the page block.

The updated valid diagnostic invocation saves explicit `outcome` fields:

| Code | Saved status | Meaning |
|---|---|---|
| 0 | `PASS` | All existing checks passed |
| 2 | `CHECKS_FAILED` | Diagnosis completed; integrity or strict numerical reproduction failed; `execution_errors` is empty |
| 3 | `ERROR_OR_BLOCKED` | Missing store, child failure/180-second timeout, incomplete snapshot/read, inconsistent result, or original immutability not verified |

Standard argument/usage errors still use argparse's code 2 **without** a saved completed outcome; the JSON status is authoritative for completed investigations. A wholly unexpected top-level process failure is not a pass.

The PowerShell `-DiagnosticsOnly` path now prints a completed-check-failure warning and preserves code 2 instead of throwing the generic “Python failed” exception. It does not turn failed checks green. Original changes detected during investigation are retained in the report and treated as execution errors, never certified unchanged.

For the seeded Linux fixture, these checks correctly failed:

- `page.count_equals_manifest`
- `page.count_equals_generated_chunks`
- `page.exact_chunk_ids`
- `page.collection_vector_count_metadata_matches_actual`

The Windows failed-check list can additionally contain its known strict score mismatch. Changing only a vector-count stamp would neither fix IDs nor make the store valid.

## 3. Q35/M2C-22: rounding-boundary investigation and policy

Q35 asks “Which cards are in the Payments & Clearing category?”. The frozen Phase 4 result ranks M2C-22 fifth and stores only **0.3465**, not the historical raw similarity.

Fresh Linux measurements on a scratch-built card store:

| Measurement | Value |
|---|---|
| Chroma batch-query similarity | `0.34654998779296875` |
| Chroma single-query similarity (sealed router encoding shape) | `0.34654998779296875` |
| Nominal boundary between 0.3465 and 0.3466 | `0.34655` |
| Chroma score minus that boundary | `-1.220703125e-08` |
| Independent float64 normalized cosine, batch query + stored card | `0.3465500331046134` |
| Independent float64 normalized cosine, single query + stored card | `0.34655002513189165` |
| Single vs batch query-vector maximum element delta | `1.1920928955078125e-07` |
| Batch and single ranks | 5 and 5 |

The independent calculations are forensic measurements, **not replacement golden scores**. They cross the 4dp boundary even on Linux while Chroma matches the frozen result.

A regression reproduces the rounding mechanism with adjacent float32 cosine distances:

- Distance `0.65345001220703125` → similarity `0.34654998779296875` → **0.3465**.
- One float32 step lower distance `0.6534499526023865` → similarity `0.3465500473976135` → **0.3466**.
- Raw similarity change is only `5.960464477539063e-08`, despite the displayed 0.0001 difference.

Thus passing the existing card-vector `1e-6` threshold does **not** imply identical 4dp scores. Query batching, inference/library/CPU kernels and float32 distance reduction can change the side of this boundary without a rank change. The precise Windows component is **not independently established** from its rounded score alone. The new report records exact raw/hex scores, signed decimal-boundary offsets, both query shapes/hashes, float64 controls, Torch/CPU/thread configuration and versions to distinguish these cases.

### Acceptance policy — unchanged

- Frozen 4dp scores, queries, labels, source identities and historical results are unchanged.
- `round(float_score, 4) == recorded_score` remains mandatory for strict reproduction.
- The existing vector threshold remains unchanged; it is not repurposed as a score tolerance.
- The single-query focused result is now also an explicit gate, so a passing batched check cannot hide the reported router-shaped failure.
- No rounding bias, epsilon, score clamping, thread forcing, replacement vectors or baseline rewrite is introduced.

The known Windows mismatch should therefore **continue to fail strict reproduction**, with a useful explanation, until a reviewed numerical-portability policy/environment reproduction resolves it. Any future versioned policy should retain the old strict result as historical evidence, record raw vectors/scores/backend provenance, and assess ranking and semantic quality separately. It is not implemented or presumed approved here.

## 4. Changes and actual tests

Files changed:

- `scripts/page_corpus_integrity.py`, `scripts/build_page_collection.py`: fail-closed, read-only corpus admission/fingerprint preflight before store writes.
- `scripts/windows_diagnostic_policy.py`: explicit outcome classification, unchanged rounding-rule evidence, extra-ID provenance and in-memory capture probes.
- `scripts/diagnose_windows_verification.py`: integrate the above; focused batch/single/float64 numerical measurements; structured errors; finite child deadline; refuse existing output paths or reports inside corpus/store paths.
- `scripts/verify_windows.ps1`: distinguish expected diagnostic check failure from execution failure.
- `tests/test_focused_windows_diagnostic.py`: **27 new regression cases**.
- This report and separate `verification/focused_windows_v1/` evidence. Prior evidence/report files are not rewritten.

**Committed-source Linux result: 165 passed, zero failures/skips, 11.73 seconds**, across new diagnostics, prior Windows-portability tests, map-root identity, Phase 8 corpus/pipeline and Phase 7A suites. This includes 27 new regressions, real temporary Chroma tests, expected 115/113 diagnosis and byte-preservation tests. Synthetic-vector unit fixtures are labelled; the separate seeded CLI experiment used real MiniLM embeddings. No Ollama inference was claimed.

CLI experiments: clean scratch stores → **0/PASS**; seeded excluded-page scratch store → **2/CHECKS_FAILED**, zero execution errors; intentionally absent scratch stores → **3/ERROR_OR_BLOCKED**. An additional guarded fresh scratch build produced the unchanged 113 chunks/fingerprint.

Native Windows, PowerShell, Chromium, full backend and frontend suites were **not rerun in this focused mission**. Prior full-suite results remain historical; no new platform/full-suite success is inferred from these focused tests.

All **222 checkpoint hashes** verified unchanged; no diff from a155a87 in `data/`, `eval/`, both prior release reports, the sealed Phase 7B validator or Phase 4 evaluator. No production-path vector store was created in Arena: all new stores and mutations were isolated scratch experiments. The user's original stores, local corpus files and original diagnostic artifact were not accessed or changed by Arena.

## 5. Exact Windows verification (no rebuild/install/corpus refresh)

Stop SURA/Chroma/legacy writers first. Keep the original diagnostic and stores. Use the final exact SHA from the delivery message:

```powershell
Set-Location D:\chatbot-phase12
$ErrorActionPreference = 'Stop'
if (git status --porcelain) {
    throw 'Local changes detected: keep them untouched and review before updating. Do not stash/normalize corpus files to pass this diagnosis.'
}
git fetch origin
if ($LASTEXITCODE) { throw 'Fetch failed' }
if ((git branch --show-current).Trim() -ne 'arena/b450cda2-chatbot') {
    throw 'Wrong branch; stop and review without changing corpus/store files'
}
$Release = 'PASTE_EXACT_DELIVERED_SHA'
git merge --ff-only $Release
if ($LASTEXITCODE) { throw 'Divergence: stop without resetting or force pushing' }
if ((git rev-parse HEAD).Trim() -ne $Release) { throw 'Unexpected HEAD' }

$Out = Join-Path $env:TEMP ('SURA-focused-' + (Get-Date -Format yyyyMMddHHmmss))
New-Item -ItemType Directory -Path $Out | Out-Null
& .\av\Scripts\python.exe scripts\diagnose_windows_verification.py --store-quiesced --out (Join-Path $Out 'store-diagnostic-v2.json')
$DiagnosticExit = $LASTEXITCODE
Write-Host "Diagnostic exit: $DiagnosticExit; inspect JSON outcome. Expected current gate failure is 2, not a pass."
& .\av\Scripts\python.exe -m pytest tests/test_focused_windows_diagnostic.py tests/test_map_root_identity.py tests/test_phase8_corpus.py -q -ra "--junitxml=$Out\focused-junit.xml" | Tee-Object -FilePath (Join-Path $Out 'focused-tests.txt')
$TestExit = $LASTEXITCODE
Write-Host "Focused tests exit: $TestExit; original stores/corpus untouched; results: $Out"
```

This deliberately avoids the full helper's `--apply` checkout refresh, installation, builders or full suites that may regenerate historical audit outputs. The narrower Windows test selection validates diagnostics/admission without opening the original vector stores through Chroma. For the transcript wrapper alone, `verify_windows.ps1 -Python .\av\Scripts\python.exe -DiagnosticsOnly` is also available and preserves the diagnostic exit code.

Return `store-diagnostic-v2.json`, `focused-tests.txt` and `focused-junit.xml`. Inspect `page.extra_chunk_provenance[].capture_probe`, `card.datasets.phase4.focus_scores`, `card.numerical_backend` and `outcome`. Do not repair the original store by editing local corpus JSON, incrementing manifest counts or deleting vectors during diagnosis.

## 6. Outstanding release gates

An approved, backed-up **isolated store migration** is still needed before activating a cleaned candidate; no in-place repair is performed here. Windows numerical attribution/strict reproduction, full native verification and sealed-writer policy remain open. Semantic RAG correctness, real Ollama, browser and security gates remain unresolved as documented previously. Lexical support/retrieval metrics are not semantic correctness.

**NOT READY. Diagnostic correctness and preventive admission hardening do not make the existing 115-vector Windows store valid or its strict score mismatch pass.**
