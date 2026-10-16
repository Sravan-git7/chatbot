# SURA External Owner Handoff Package — Gates 1 Through 5

> **NOTICE — DRAFT ONLY:**  
> The messages below are actionable, copy-paste-ready transmittal drafts for an authorized human coordinator.  
> **No messages have been sent, no owners have been contacted, and no approvals have been granted or assumed.**  
> Release Status: **NOT READY**

---

## Executive Overview

Per the SURA release prerequisites ([release_intake/PREREQUISITE_TRACKER.md](PREREQUISITE_TRACKER.md) and [release/evidence_closure_v3/prerequisites.json](../release/evidence_closure_v3/prerequisites.json)), all five external prerequisite gates (**Gates 1 through 5**) must be formally satisfied before Gate 6 (the final strict 113-query RAG quality benchmark) can be authorized and executed:

```
┌────────────────────────────────────────────────────────────────────────┐
│                         PARALLEL PRIORITY 1                            │
│  Gate 1: Model Provenance Export  │  Gate 2: Coherent Cold-Store Bundle│
│  (13-file tree + signed inventory)│  (quiesced snapshot + byte hashes) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         PARALLEL PRIORITY 2                            │
│  Gate 3: Windows AMD64 Runtime    │  Gate 4: SAP Domain Review         │
│  (dependency graph + native DLLs) │  (captures + 184-row worksheet)    │
│                                   │                                    │
│  Gate 5: Chroma Security Sign-offs│                                    │
│  (containment for 5 open CVEs)    │                                    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                             FINAL GATE                                 │
│  Gate 6: Full 113-Query Current-Production Extractive RAG Benchmark    │
│  (strict answer/quote criteria; only after Gates 1–5 are approved)     │
└────────────────────────────────────────────────────────────────────────┘
```

All five gates are currently **BLOCKED / NOT SUPPLIED**. Below are the exact transmittal packages, required formats, validation criteria, and intake destinations for each accountable role.

---

## 1. Gate 1: Model Provenance & Full File Export

### Handoff Metadata
* **Target Gate:** Gate 1 (Embedding Model & Tokenizer Export)
* **Responsible External Role:** Model / Content Provenance Owner & Supply-Chain Security Approver
* **Current Blocker:** `M2C_MODEL_DIR` is unset. Fallback relies on an unapproved third-party wheel repackaging (`gt-all-minilm-l6-v2==0.1.0`) without signed full-tree provenance or upstream revision certification (`approved: false`).
* **Requested Deliverable:** Standalone directory containing the complete 13 regular files for `all-MiniLM-L6-v2`, signed full-tree SHA-256 inventory JSON, and upstream git revision reference.
* **Required Format:** Ordinary materialized directory (no symlinks, Windows reparse points, or custom code), accompanied by signed JSON: `{"files": {"<relpath>": {"bytes": <int>, "sha256": "<hex>"}}}`.
* **Intake Staging Path:** `release_intake/received/model_export/`
* **Validation Criteria:**
  1. All 13 regular files present with exact byte matches.
  2. The 6 pinned SHA-256 hashes match collection manifests:
     * `model.safetensors`: `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`
     * `tokenizer.json`: `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037`
     * `vocab.txt`: `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3`
     * `config.json`: `953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41`
     * `sentence_bert_config.json`: `fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7`
     * `modules.json`: `84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf`
  3. Offline probe: Tokenizer reports `exact: true`; SentenceTransformer CPU embedder produces 384 dimensions with 256 max sequence length.

### Copy-Paste-Ready Message

```text
To: Model / Content Provenance Owner & Supply-Chain Security Approver
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Supply-Chain Approval & Complete Export for all-MiniLM-L6-v2

We are preparing independent verification of the SURA chatbot release candidate (branch arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

Model loading and embedding inference are currently BLOCKED. In accordance with release/evidence_closure_v3/ARTIFACTS.md and release/evidence_closure_v3/prerequisites.json, we require an approved, standalone export of all-MiniLM-L6-v2 with verifiable supply-chain provenance.

Please provide:
1. An approved, standalone directory export containing the complete set of 13 regular files:
   - model.safetensors
   - tokenizer.json
   - vocab.txt
   - config.json
   - sentence_bert_config.json
   - modules.json
   - 1_Pooling/config.json
   - tokenizer_config.json
   - special_tokens_map.json
   - config_sentence_transformers.json
   - data_config.json
   - README.md
   - .gitattributes
2. A signed regular-file inventory JSON containing the relative path, exact byte size, and SHA256 digest for every file in the export tree:
   {"files": {"<relative/path>": {"bytes": <int>, "sha256": "<hex>"}}}
3. Official upstream revision reference (Git commit/revision) and chain-of-custody documentation replacing the unapproved third-party wheel repackaging (gt-all-minilm-l6-v2).

Acceptance Checks Grounded in the Repository:
- The export must contain ordinary materialized files (no symlinks, Windows reparse points/junctions, or custom execution code).
- Pinned SHA256 hashes must match collection manifests exactly.
- Python offline probe: Tokenizer reports exact: true; CPU embedder produces 384 dimensions with max sequence length 256.

Please stage the export at release_intake/received/model_export/ and deliver the signed inventory JSON. This message is a draft ready for transmittal.
```

---

## 2. Gate 2: Coherent Cold-Store Bundle & 115-vs-113 Investigation

### Handoff Metadata
* **Target Gate:** Gate 2 (Cold Vector Store Snapshot & Signed Inventory)
* **Responsible External Role:** Store / Corpus Owner & Storage Operations Lead
* **Current Blocker:** Physical SQLite and HNSW byte hashes are unknown in the repository. The local unquiesced store contains 115 page embeddings vs. 113 declared in the manifest. No operator quiescence attestation or signed byte inventory exists (`approved_cold_snapshot: false`). Original stores must remain completely untouched.
* **Requested Deliverable:** Approved, coherent cold snapshot bundle (`ColdExport`) of combined card store root (`data/vector_store`) and nested page store (`data/vector_store/page_collection`), signed physical byte inventory, operator exclusive quiescence attestation, and disposable-copy diagnostic authorization.
* **Required Format:** Tarball or directory tree with signed JSON inventory (`{"files": {"<relpath>": {"bytes": <int>, "sha256": "<hex>"}}}`) and signed operator statement.
* **Intake Staging Path:** `release_intake/received/cold_stores/`
* **Validation Criteria:**
  1. Signed byte inventory verified before and after transfer (`COLD_COPY.md`).
  2. Exclusive quiescence attestation confirming zero writers/clients active during snapshot.
  3. Strict adherence to 3-tier transfer layout (`ColdExport` -> `SealedCopy` -> `RunCopy`).
  4. Disposable-copy diagnostic (`scripts/diagnose_windows_verification.py`) confirms that the 2 extra vectors belong to unadmitted capture M2C-18 (exit code 2 `CHECKS_FAILED`, `UNADMITTED_CAPTURE_PAGE_VECTORS`, `original_store_unchanged: true`). Original stores remain completely untouched.

### Copy-Paste-Ready Message

```text
To: Store / Corpus Owner & Storage Operations Lead
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Quiesced Cold Vector Store Snapshot & Signed Byte Inventory

We are preparing independent verification of the SURA release branch (arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

Direct access to, migration of, or repair of existing stores is strictly PROHIBITED. In accordance with release/evidence_closure_v3/COLD_COPY.md, we require an approved cold-copy snapshot bundle and signed byte inventory.

Please provide:
1. An approved, coherent cold snapshot bundle (ColdExport) containing the combined card store root (data/vector_store) and nested page store (data/vector_store/page_collection).
2. Operator attestation of exclusive quiescence/lease, confirming all application workers, Chroma clients, and background writers were stopped before snapshot creation and remain stopped through inventory generation.
3. A signed physical byte inventory JSON covering all files: chroma.sqlite3, every SQLite sidecar present (-wal, -shm, journal), and every HNSW UUID index segment directory and data file for both collections (sap_m2c_card_v1 and sap_pages_v1):
   {"files": {"<relative/path>": {"bytes": <int>, "sha256": "<hex>"}}}
4. Authorization to execute the 3-tier transfer layout (ColdExport -> SealedCopy -> RunCopy) on an isolated private test host.

Discrepancy Investigation Protocol (115 vs 113):
- The page collection manifest declares 113 vectors across 28 pages. Local inspection of historical stores observed 115 embeddings.
- Under NO circumstances may the original stores be repaired, rebuilt (--rebuild), migrated, or altered.
- The 115-vs-113 investigation must execute strictly on a disposable clone of RunCopy using:
  python scripts/diagnose_windows_verification.py --store-quiesced --card-store "$DisposableCardCopy" --page-store "$DisposablePageCopy" --out "$Results/store-diagnostic.json"
- Acceptance requirement: The diagnostic must verify that the 2 extra vectors belong to unadmitted capture M2C-18 (Guide e4375c1cad104b2eb7d027369bd76638 / Page b1a202c9bb3011da2b24000f20dac9ef), report exit code 2 (CHECKS_FAILED), classify them as UNADMITTED_CAPTURE_PAGE_VECTORS, and prove original store bytes are unchanged (original_store_unchanged: true).

Please stage the snapshot at release_intake/received/cold_stores/ and deliver the signed inventory JSON and quiescence attestation. This message is a draft ready for transmittal.
```

---

## 3. Gate 3: Windows AMD64 Runtime Certification & Dependency Evidence

### Handoff Metadata
* **Target Gate:** Gate 3 (Windows AMD64 Runtime & Dependency Certification)
* **Responsible External Role:** Windows AMD64 Runtime Owner & Release Engineer
* **Current Blocker:** The reference lock file ([requirements.lock.txt](../requirements.lock.txt)) is a Linux Python 3.11.2 lock with 127 entries including Linux-only NVIDIA/CUDA packages. Windows AMD64 compatibility is uncertified (`windows_compatibility_verified: false`).
* **Requested Deliverable:** Certified Windows AMD64 dependency specification/lockfile, hash-inventoried wheelhouse, and signed inventory of native libraries (`chromadb-1.5.9-cp39-abi3-win_amd64.whl`, CPU/BLAS Torch binaries, `onnxruntime` DLLs).
* **Required Format:** Signed lockfile and manifest mapping package filenames to SHA-256 hashes and download/provenance sources.
* **Intake Staging Path:** `release_intake/received/windows_runtime/`
* **Validation Criteria:**
  1. `python -m pip check` passes with zero conflicts.
  2. `python -m pip freeze --all` matches the certified Windows inventory.
  3. Native Win32 file-sharing tests pass without skips (`test_windows_portability.py`: `test_windows_sqlite_probe_observes_real_handle_release`, Chroma cleanup, WinError 32 sharing barrier).

### Copy-Paste-Ready Message

```text
To: Windows AMD64 Runtime Owner & Release Engineer
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Windows AMD64 Runtime Certification & Dependency Graph Closure

We are preparing independent verification of the SURA release branch on native Windows (arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

While hermetic lifecycle and handle contention tests have passed on Windows (tests/test_windows_portability.py), formal Windows runtime certification remains BLOCKED. In accordance with release/evidence_closure_v3/COMMANDS.md and release/evidence_closure_v3/prerequisites.json, we require an approved Windows AMD64 dependency closure.

Please provide:
1. Certified Windows AMD64 dependency graph and hash-inventoried wheelhouse reconciling reference Linux Python 3.11.2 with Windows AMD64 Python (Python 3.10.11 or certified 3.11.x).
2. Signed inventory of native wheels and binary shared libraries, specifically:
   - chromadb-1.5.9-cp39-abi3-win_amd64.whl (SHA256: 4fd0b560e56761b7f3cb4d5c6205fd5f20814484b4a3e4e9af9038c2b428fc6c)
   - Certified CPU/BLAS Torch binaries (reference lock targets CPU Torch 2.14.1; current environment has 2.5.1+cu121)
   - onnxruntime Windows AMD64 binaries
3. Documented configuration for thread allocation, OpenMP/MKL, and Win32 file sharing semantics.

Acceptance Checks Grounded in the Repository:
- python -m pip check passes with zero conflicts.
- python -m pip freeze --all matches the approved Windows inventory.
- Native Win32 file-sharing tests must run and pass without skips:
  * test_windows_sqlite_probe_observes_real_handle_release (kernel32 CreateFileW, WinError 32 sharing barrier)
  * Real Chroma client lifecycle, retained-client cleanup, and scoped shutdown isolation.

Please stage deliverables at release_intake/received/windows_runtime/ and deliver the signed dependency manifest. This message is a draft ready for transmittal.
```

---

## 4. Gate 4: Authoritative SAP Captures & 184-Row Review Worksheet

### Handoff Metadata
* **Target Gate:** Gate 4 (Authoritative SAP Captures & Independent Domain Review)
* **Responsible External Role:** Independent SAP Domain Reviewer & SAP Content Supplier
* **Current Blocker:** All 184 rows in [release/evidence_closure_v3/sap-review-worksheet.csv](../release/evidence_closure_v3/sap-review-worksheet.csv) are unadjudicated. M2C-18 (*Contract Account*) has conflicting guide LOIO mappings and remains excluded. AI-authored frozen reference labels cannot certify SAP truth.
* **Requested Deliverable:** Legally authorized SAP page body captures (TOC, LOIO, version, locale metadata), completed and signed `sap-review-worksheet.csv` (184 rows), and authoritative resolution/exclusion determination for M2C-18.
* **Required Format:** Signed CSV matching `release/evidence_closure_v3/sap-review-worksheet.csv`, accompanied by raw HTML/PDF source captures and JSON alignment evidence.
* **Intake Staging Path:** `release_intake/received/sap_review/`
* **Validation Criteria:**
  1. Two-pass review protocol: Blind first-pass (no AI answers shown) + second-pass claim alignment.
  2. >= 95% substantive answerable correctness (keyword overlap or abstention is NOT correctness).
  3. 100% claim-to-source identity.
  4. 0% unsupported, wrong-guide, or wrong-version answers.
  5. 100% safe negatives.
  6. M2C-18 resolved with authoritative TOC or formally documented as excluded.

### Copy-Paste-Ready Message

```text
To: Independent SAP Domain Reviewer & SAP Content Supplier
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Independent SAP Domain Review & Authoritative Captures

We are preparing independent verification of the SURA release candidate (branch arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

Release quality acceptance requires independent human domain adjudication. In accordance with release/evidence_closure_v3/SAP_REVIEW.md, we require authoritative source captures and completion of the 184-row review worksheet.

Please provide:
1. Legally authorized, authoritative SAP page body captures including TOC, deliverable LOIO, page LOIO, product edition, release/version/build, and locale.
2. Completed and signed sap-review-worksheet.csv covering:
   - All 113 frozen Phase-12 questions
   - All 70 frozen cached Phase-3 questions
   - 1 M2C-18 identity resolution row
3. Authoritative resolution for M2C-18:
   - Requested guide: 9442486404b54071b4ebeab6a16628e7, page b1a202c9bb3011da2b24000f20dac9ef (version 2025.001)
   - Competing deliverable: 40374490 (guide e4375c1cad104b2eb7d027369bd76638, Enterprise Services in Financials)
   - Provide authoritative TOC and page body proving whether any mapping is valid. Until signed reconciliation exists, M2C-18 remains strictly excluded.

Review Protocol:
- Blind First Pass: Provide only questions and source documents; reviewer independently records answerability, required facts, and procedure scopes WITHOUT seeing candidate answers or AI gold labels.
- Second Pass: Candidate answers and focus evidence (sap-focus-evidence.json) are disclosed. Reviewer records exact answer span -> source span alignment, claim completeness, and polarity.
- Acceptance Criteria:
  * >=95% substantive answerable correctness.
  * 100% claim-to-source identity.
  * 0% unsupported, wrong-guide, or wrong-version answers.
  * 100% safe negatives.

Please stage deliverables at release_intake/received/sap_review/ and return the completed, signed worksheet. This message is a draft ready for transmittal.
```

---

## 5. Gate 5: Chroma Security Advisory Determinations & Containment

### Handoff Metadata
* **Target Gate:** Gate 5 (Chroma Security Determinations & Containment Sign-Off)
* **Responsible External Role:** Security Authority Lead & Target Operations Owner
* **Current Blocker:** Five security advisories on `chromadb 1.5.9` remain with status `OPEN` and approver fields set to `null` in [release/evidence_closure_v3/security-decisions.json](../release/evidence_closure_v3/security-decisions.json). Upstream PR 7602 is open/unmerged with no released patch.
* **Requested Deliverable:** Formally completed and signed `security-decisions.json` providing determinations, mitigations, and residual risk sign-offs for CVE-2026-45829 through -45833, plus verified deployment network/process containment evidence.
* **Required Format:** Signed JSON matching `release/evidence_closure_v3/security-decisions.json` schema (`status: APPROVED`, approver name, approval date, expiry, residual risk) and containment checklist.
* **Intake Staging Path:** `release_intake/received/security_decisions/`
* **Validation Criteria:**
  1. Formal sign-off on all 5 advisories:
     * GHSA-f4j7-r4q5-qw2c (CVE-2026-45829, Critical) — kwargs injection before auth
     * GHSA-36p7-vc44-83pf (CVE-2026-45833, Critical) — collection update config reconstruction
     * GHSA-xph7-9rjv-w5fr (CVE-2026-45831, High) — SimpleRBAC tenant isolation flaw
     * GHSA-2wm9-hf6c-p5cr (CVE-2026-45830, High) — Python v1 API cross-tenant CRUD
     * GHSA-x97m-f58v-9cwg (CVE-2026-45832, High) — Python v1 authorization bypass
  2. Verified deployment containment:
     * Untrusted Chroma HTTP port ingress is blocked; Chroma is restricted to owned loopback/in-process SDK.
     * Untrusted users are denied collection/config mutations across all API versions.
     * Strict avoidance of untrusted SDK `.configuration` reconstruction.
     * Single-tenant process and storage isolation boundaries verified.

### Copy-Paste-Ready Message

```text
To: Security Authority Lead & Target Operations Owner
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Security Determinations for Five Open Chroma 1.5.9 Advisories

We are preparing independent verification of the SURA release branch (arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

Security release gates remain BLOCKED. In accordance with release/evidence_closure_v3/SECURITY_DECISIONS.md and release/evidence_closure_v3/security-decisions.json, we require formal determinations and containment verification for five open advisories affecting chromadb 1.5.9.

Advisories Under Review:
1. GHSA-f4j7-r4q5-qw2c (CVE-2026-45829, Critical) — HTTP provider constructor kwargs injection before auth.
2. GHSA-36p7-vc44-83pf (CVE-2026-45833, Critical) — Collection update config reconstruction.
3. GHSA-xph7-9rjv-w5fr (CVE-2026-45831, High) — SimpleRBAC tenant isolation flaw.
4. GHSA-2wm9-hf6c-p5cr (CVE-2026-45830, High) — Python v1 API cross-tenant CRUD.
5. GHSA-x97m-f58v-9cwg (CVE-2026-45832, High) — Python v1 authorization bypass.

Please provide:
1. Formal signed risk determinations, mitigations, and residual risk approvals for each advisory in security-decisions.json.
2. Verified deployment containment evidence:
   - Untrusted Chroma HTTP port ingress is blocked; Chroma is restricted to owned loopback/in-process SDK.
   - Untrusted users are denied collection/config mutations across all API versions.
   - Strict avoidance of untrusted SDK .configuration reconstruction.
   - Verification of single-tenant process and storage isolation boundaries.
3. Sign-off recording: Security Owner, Operations Owner, Decision, Approver Name, Approval Date, Review Expiry Date, and Residual Risk.

Please stage deliverables at release_intake/received/security_decisions/ and provide the signed security decision package. This message is a draft ready for transmittal.
```

---

## 6. Actionable Human Coordinator Next Steps

1. **Transmit Requests (Priority 1 & Priority 2 in Parallel)**:
   - Transmit Gate 1 message to the **Model / Content Provenance Owner & Supply-Chain Security Approver**.
   - Transmit Gate 2 message to the **Store / Corpus Owner & Storage Operations Lead**.
   - Transmit Gate 3 message to the **Windows AMD64 Runtime Owner & Release Engineer**.
   - Transmit Gate 4 message to the **Independent SAP Domain Reviewer & SAP Content Supplier**.
   - Transmit Gate 5 message to the **Security Authority Lead & Target Operations Owner**.
2. **Monitor Incoming Staging Areas**:
   - Deliverables must land in their dedicated subdirectories under `release_intake/received/`:
     * `model_export/` (Gate 1)
     * `cold_stores/` (Gate 2)
     * `windows_runtime/` (Gate 3)
     * `sap_review/` (Gate 4)
     * `security_decisions/` (Gate 5)
3. **Receipt Verification Protocol**:
   - Confirm ordinary materialized regular files (reject symlinks or Windows reparse points).
   - Verify SHA-256 digests against the signed owner inventory JSON.
   - Record received evidence in [release_intake/PREREQUISITE_TRACKER.md](PREREQUISITE_TRACKER.md).
4. **Final Evaluation Authorization (Gate 6)**:
   - Only when Gates 1 through 5 have approved evidence and signed records may Gate 6 (the full 113-query RAG quality benchmark) be scheduled and executed on an isolated test host.

*Release status remains strictly **NOT READY** until all six gates are closed with approved evidence.*
