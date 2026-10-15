# Native Windows verification package — mission v3

**BLOCKED: no native Windows host. Linux, mocks and source inspection do not certify Windows.** No Windows package was installed or model downloaded. Runtime: `c324ffb366511b15385524aa8ed24e956f662780`.

## Supported package evidence

Fresh PyPI metadata for Chroma **1.5.9**, Python >=3.9:

- `chromadb-1.5.9-cp39-abi3-win_amd64.whl`
- SHA256 `4fd0b560e56761b7f3cb4d5c6205fd5f20814484b4a3e4e9af9038c2b428fc6c`
- 23,542,454 bytes. Metadata only; no wheel download/install.

Linux installed 1.5.9 source confirms Rust stop uses `del self.bindings` (not idempotent), public SDK release removes the cache entry before stopping, and Client.close marks `_closed` before releasing references. A partial exception cannot safely be treated as a retryable complete stop. SQLx/Tokio worker drop has no exposed Python join operation; no invented bindings.close/worker-await API was used.

## Implemented and tested safe preparation

- Cleanup only explicitly owned temporary trees, with exclusive-use contract. Outside systems and SDK reference counts are not cleared/reset.
- Pointer-sized Win32 HANDLE ABI, INVALID_HANDLE_VALUE, checked CloseHandle, read-only exclusive opens, bounded monotonic/nonbusy SQLite release barrier. Non-sharing errors and timeouts remain visible. This SQLite probe is not independent proof that every possible HNSW mapping/worker is released; actual directory cleanup and retained-reference assertions must pass natively.
- Healthy completed-stop/file-timeout retry rechecks files without invoking native stop twice. Same-path reuse/isolation have Linux real-SDK evidence.
- A real Linux SDK fault deletes actual Rust bindings before an injected failure; retry is blocked and the same retained fixture is queried successfully in a new process after the failed process exits. This strengthens preparation, not Windows certification.
- A partial stop/close/constructor failure retains diagnostic state and the directory, quarantines intersecting paths, rejects further helper/factory reuse, and requires **process restart**. It does not retry non-idempotent native stop or silently discard state. Temporary and production-owned adapters share the quarantine checks.
- Production owners validate actual vector shape/model contract and refuse missing database files before SDK initialization; no implicit page-store creation. These checks do not replace full model/corpus integrity verification.
- Public SDK clients created by the production wrapper are explicitly owned/closed. Existing external clients/unrelated stores remain usable. Ownership transfers through both evidence/service pipeline wrappers; partial construction cleans only newly owned clients.
- Weakref finalizer uses the same cleanup path; timeout exceptions are hook-observable/unraisable by Python design and retain the directory. No `ignore_cleanup_errors=True`, forced GC-as-join, global shutdown or cache/refcount reset.
- Direct third-party SDK calls can bypass adapter quarantine. They **must not** reopen/use a failed path in the same process. No globally patched SDK safety guarantee is claimed.

Latest combined lifecycle preparation: **86 passed, 1 native-sharing skip, 1 resource-dependent diagnostic deselected, 4 subtests passed**:

```sh
../.venv/bin/python -m pytest tests/test_release_runtime.py tests/test_release_evaluation.py tests/test_windows_portability.py -k 'not real_diagnostic_uses_child_copy_and_preserves_wrong_store' -q -ra --junitxml=../lifecycle-final-v7.xml
```

The full suite includes the deselected original diagnostic; it still fails because its child needs the missing model. Separate disposable reproduction: child exit 1/FileNotFoundError at resolve_model; source fixture hashes unchanged. This is not a certified Windows cleanup result.

**Original Windows test/assertion prefix preserved byte-exact:** first 11,037 bytes SHA256 `fdf52dbbaa0f18ec65db58befe65fe18d202088d5784a308eb3c81b45b017d7b`. Tests were appended; original failing assertions were not weakened.

## Native handoff (isolated candidate only)

Use an existing approved Windows environment, preserving `av`, backups/models/stores. Record Python/OS/architecture, `pip freeze --all`, exact Chroma wheel hash, Torch/ST/numpy/tokenizer versions and model hashes. Require installed Chroma 1.5.9 for this adapter review; do not replace the environment blindly. The Linux lock is **not** a Python 3.10/Windows closure.

In a new disposable clone of the same release branch (never update/normalize originals), with `$Py` pointing to that existing approved environment and `$Results` a new private directory:

```powershell
& $Py -m pytest tests/test_windows_portability.py tests/test_release_runtime.py -q -ra --junitxml="$Results\lifecycle.xml"
& $Py -m pytest tests -q -ra --junitxml="$Results\backend.xml"
# Only after all source-store writers are stopped and cold copies/hashes exist:
& $Py scripts/diagnose_windows_verification.py --store-quiesced --page-store "$OfflinePageCopy" --card-store "$OfflineCardCopy" --out "$Results\diagnostic.json"
& $Py scripts/probe_q35_reproducibility.py --store-quiesced --card-store "$OfflineCardCopy" --out "$Results\q35.json"
```

Retain stdout/stderr, exact exit codes, every failure/skip/warning and before/after source hashes. A 2/3 diagnostic outcome is not PASS. Do not use the existing broad `verify_windows.ps1` as a safety shortcut: it invokes checkout byte refresh and offers store-building/install switches. This handoff deliberately does **not** normalize source, alter checkpoint outputs, build into a live/default store or auto-repair.

Native mandatory cases: explicit cleanup/finalizer, actual SQLite sharing delay/timeout/recovery, retained clients/collections, outside-store liveness, two same-path lifecycles, stop-before/after-bindings failure, public close failure/constructor failure, no forced retry, and no leftover handles preventing removal after successful cleanup. Controlled faults must occur only in owned disposable systems.

## Q35 remains BLOCKED

Exact historical strict path/environment plus model/store/vector/query hashes, raw float scores, distance arithmetic, rank, single-vs-batch encoding, Torch/backend/thread settings and provenance are required. Historical Linux raw `.34654998779296875` differs from old Windows rounded `.3466`; Windows raw is unavailable. No raw score was inferred, tolerance changed or false historical reproduction claimed.

Current safe CLI attempt without an explicitly supplied quiesced store exits 2 (safety refusal); no Q35 output/inference was produced. Obtain the actual historical raw reference/environment or record the gate irreducibly blocked. New measurements cannot retroactively supply historical provenance.
