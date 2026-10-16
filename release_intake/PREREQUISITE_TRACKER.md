# SURA Release Prerequisites Tracker

**Target Branch:** `arena/b450cda2-chatbot`  
**Synchronized Commit:** `582f9930846f7e080e2d1bfb50ef8bec6d7aae47`  
**Overall Release Status:** **`NOT READY`**  
**Last Updated:** `2026-10-16`

---

## 1. Local Verification & Compatibility Migration Status

| Item / Task | Classification | Verification Result | Evidence |
|---|---|---|---|
| Windows chunk candidate determinism (`scripts/build_chunk_candidates.py`) | **`VERIFIED COMPLETE`** | LF byte-identical runs match committed candidate bytes | `test_chunk_candidates.py::RealChunkTests` PASSED |
| Chroma protection regression logic (`assert_no_forbidden_directory`) | **`VERIFIED COMPLETE`** | Verified forbidden directory detection across `test_phase10.py`, `test_phase7b.py`, `test_phase7g.py`, `test_phase7e.py` | Unit tests PASSED |
| Cross-drive path normalization (`scripts/m2c_page_join.py`) | **`VERIFIED COMPLETE`** | Stable POSIX relative fallback on Windows cross-drive resolution | `test_phase7c.py::LocalContentTests` PASSED |
| Deterministic page identity output (`scripts/m2c_page_identity.py`) | **`VERIFIED COMPLETE`** | Byte-identical LF JSON serialization & report rendering | `test_phase7c.py::DeterminismTests` PASSED |
| Checkpoint integrity pins (Phase 7B, 7C, 7E, 7F) | **`VERIFIED COMPLETE`** | All modified producer and test hashes accurately pinned | Safety/Scope/Regression tests PASSED in 7B, 7C, 7E, 7F |
| Delivery inputs verification tool (`verify_delivery_inputs.py`) | **`VERIFIED COMPLETE`** | 979/979 inherited tracked files match published SHA-256 hashes (exact set equality verified) | Exit code 0 from `verify_delivery_inputs.py`; 5/5 unit tests PASSED |
| Release intake validator (`release_intake/validate_intake.py`) | **`VERIFIED COMPLETE`** | Strict JSON duplicate-key checks, path traversal/symlink guards, domain criteria, OpenSSL cryptographic verification & binding | 19/19 regression tests PASSED (`test_intake_validator.py`) |
| Windows portability suite (`tests/test_windows_portability.py`) | **`VERIFIED COMPLETE`** | Win32 handle contention, cleanup, and release verified | 47 passed, 4 subtests passed |

---

## 2. Six Mandatory Release Gates

| Gate | Responsible Role | Required Deliverable | Classification | Acceptance Criteria | Current Evidence Status | Next Action |
|:---:|---|---|:---:|---|---|---|
| **1: Model Export** | Model / Content Provenance Owner & Supply-Chain Security Approver | Materialized 13-file `all-MiniLM-L6-v2` export directory (`M2C_MODEL_DIR`), signed full-tree SHA256 inventory JSON, upstream git revision reference | **`BLOCKED BY MISSING AUTHORIZED ARTIFACT`** | Stdlib verification across 6 pinned SHA-256 hashes; full-tree inventory equality; exact tokenizer probe (`exact: true`) and CPU SentenceTransformer dimension probe (384-d, 256 max seq) | None received in `release_intake/received/`. Host `gt-all-minilm-l6-v2==0.1.0` is an unapproved third-party repackaging; `M2C_MODEL_DIR` is unset. | Transmit Gate 1 handoff request to Model Provenance / Supply-Chain Owner |
| **2: Cold Stores** | Store / Corpus Owner & Storage Operations Lead | Approved, coherent cold snapshot bundle (`ColdExport`) of combined card and nested page stores; signed physical byte inventory; operator quiescence attestation | **`BLOCKED BY MISSING AUTHORIZED ARTIFACT`** | Signed byte inventory verified before and after copy (`COLD_COPY.md`); read-only diagnostic on disposable copy verifies 115-vs-113 discrepancy as unadmitted M2C-18 (`original_store_unchanged: true`, exit 2); original stores untouched | None received in `release_intake/received/`. Local page store has 115 embeddings vs 113 declared; physical byte hashes unknown; no quiescence attestation; original stores remain completely untouched. | Transmit Gate 2 handoff request to Storage Owner; setup 3-tier transfer layout |
| **3: Windows Runtime** | Windows AMD64 Runtime Owner & Release Engineer | Certified Windows AMD64 Python dependency graph and wheelhouse; signed inventory of native libraries (`chromadb` Win wheel, Torch CPU/BLAS DLLs, onnxruntime) | **`WAITING FOR EXTERNAL OWNER`** | Clean `pip check` and `pip freeze --all` matching approved Windows artifact inventory; pass of native Win32 handle contention tests (`test_windows_portability.py`) without skips | Local Windows tests pass (47 passed, 4 subtests in `test_windows_portability.py`), but formal dependency closure is uncertified (host runs Python 3.10.11 with Torch 2.5.1+cu121 vs reference Linux 3.11.2 lock). | Transmit Gate 3 handoff request to Windows Runtime Owner |
| **4: SAP Review** | Independent SAP Domain Reviewer & SAP Content Supplier | Legally authorized authoritative SAP source captures (body, TOC, LOIO, version); completed and signed `sap-review-worksheet.csv` (184 rows); authoritative reconciliation of M2C-18 | **`WAITING FOR EXTERNAL OWNER`** | Blind first-pass review; second-pass claim alignment meeting criteria: $\ge 95\%$ substantive correctness, $100\%$ claim/source identity, $0\%$ wrong guide/version, $100\%$ safe negatives; M2C-18 resolved or excluded | None received. All 184 rows in `release/evidence_closure_v3/sap-review-worksheet.csv` remain unreviewed; independent human domain sign-off not supplied. | Transmit Gate 4 handoff request to SAP Content Supplier & Independent Reviewer |
| **5: Security Decisions** | Security Authority Lead & Target Operations Owner | Signed risk determinations, mitigations, and network containment evidence for 5 open Chroma 1.5.9 advisories (CVE-2026-45829 through -45833); completed `security-decisions.json` | **`BLOCKED BY SECURITY APPROVAL`** | Formal sign-off on all 5 advisories with approver names, approval dates, expiry, and residual risk; network containment verified (Chroma HTTP port blocked, private identity separation, no untrusted `.configuration` reconstruction) | None received. All 5 advisories remain `status: OPEN`, `approver: null`; upstream PR 7602 is open/unmerged with no official patch release. | Transmit Gate 5 handoff request to Security Authority Lead |
| **6: Full RAG Evaluation** | Runtime / Test Owner & Release Approver | Strict current-production extractive RAG benchmark execution (113 frozen queries); `current-strict-phase12.json`, `backend.xml`, `store-diagnostic.json`, and `q35-t1-on.json` | **`BLOCKED BY MISSING AUTHORIZED ARTIFACT`** | Execution on isolated test host with approved model export and cold store snapshot; all 113 queries recorded; zero cached replay substitution; verification against independent SAP gold claims | Benchmark execution is strictly prohibited until Gates 1 through 5 are formally approved and provisioned. | Stand by until Gates 1–5 deliverables are staged in `release_intake/received/` and verified |

---

## 3. Outstanding External Items Checklist

- [ ] **Gate 1:** Authorized 13-file `all-MiniLM-L6-v2` export directory staged at `release_intake/received/model_export/`.
- [ ] **Gate 1:** Signed full-tree SHA-256 inventory (`model_inventory.json`) and upstream commit reference.
- [ ] **Gate 2:** Cold-store snapshot bundle staged at `release_intake/received/cold_stores/`.
- [ ] **Gate 2:** Signed physical byte inventory and signed storage operator quiescence attestation.
- [ ] **Gate 2:** Authorized disposable-copy execution of diagnostic confirming root cause of 115-vs-113 discrepancy.
- [ ] **Gate 3:** Signed Windows AMD64 runtime specification and approved wheelhouse manifest staged at `release_intake/received/windows_runtime/`.
- [ ] **Gate 4:** Authoritative completed and signed `sap-review-worksheet.csv` (184 rows) staged at `release_intake/received/sap_review/`.
- [ ] **Gate 5:** Signed `security-decisions.json` containing formal approvals and mitigations for CVE-2026-45829 through -45833 staged at `release_intake/received/security_decisions/`.
- [ ] **Gate 6:** Controlled execution of 113-query RAG benchmark on certified isolated test host (only after Gates 1–5 are closed).

---

## 4. Priority Tracking & Execution Sequence

```
[Priority 1 - Parallel]  Gate 1 (Model Export)        [BLOCKED BY MISSING AUTHORIZED ARTIFACT]
                         Gate 2 (Cold Stores)         [BLOCKED BY MISSING AUTHORIZED ARTIFACT]
                                  │
[Priority 2 - Parallel]  Gate 3 (Windows Runtime)     [WAITING FOR EXTERNAL OWNER]
                         Gate 4 (SAP Domain Review)   [WAITING FOR EXTERNAL OWNER]
                         Gate 5 (Chroma Security)     [BLOCKED BY SECURITY APPROVAL]
                                  │
[Final Gate]             Gate 6 (113-Query Benchmark) [BLOCKED BY PREREQUISITES]
```

*Release status remains strictly **`NOT READY`** until all six gates are closed with approved evidence.*

