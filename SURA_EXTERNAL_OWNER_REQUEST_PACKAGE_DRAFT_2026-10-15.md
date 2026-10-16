# SURA External Owner Request Package — DRAFT (2026-10-15)

> **NOTICE — DRAFT ONLY:**  
> The requests in this package are actionable drafts prepared for authorized coordinators. **None of these requests have been sent, and no approvals or deliverables have been granted or assumed.**  
> Release Status: **NOT READY** (Release gates remain closed pending external owner deliverables and formal verification).

---

## Executive Summary & Dependency Order

This package specifies the required external deliverables, acceptance criteria, and communication drafts needed to unblock independent verification of the SURA SAP Utilities RAG chatbot release candidate (`arena/b450cda2-chatbot` at commit `582f9930846f7e080e2d1bfb50ef8bec6d7aae47`).

Local testing on the synchronized release branch has completed all hermetic lifecycle and security regression suites (135 tests + 4 passing subtests, 0 failures, 0 skips; recorded in `scratch/lifecycle.xml`). However, execution of the full RAG quality benchmark, model inference, and production verification remains **BLOCKED** because the required models, cold stores, runtime graphs, domain adjudications, and security sign-offs have not been supplied.

### Deliverable Dependency Order

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

1. **Priority 1 (Parallel Execution):** Gate 1 (Model Export) and Gate 2 (Cold Stores) must proceed immediately. They supply the physical assets required for any vector search or diagnostic.
2. **Priority 2 (Parallel Execution):** Gate 3 (Windows Runtime certification), Gate 4 (SAP Review worksheet and M2C-18 reconciliation), and Gate 5 (Security determinations for 5 open CVEs) can proceed concurrently with Priority 1.
3. **Final Gate:** Gate 6 (Full 113-query RAG evaluation) is strictly gated on the successful completion and approval of Gates 1 through 5.

---

## Gate 1: Model Provenance & Full File Inventory

* **Accountable Role:** Model / Content Provenance Owner & Supply-Chain Security Approver
* **Draft Subject:** `[ACTION REQUIRED] SURA Release — Supply-Chain Approval & Complete Export for all-MiniLM-L6-v2`
* **Current Blocker:** Environment variable `M2C_MODEL_DIR` is unset. The repository code fallback relies on `gt_all_minilm_l6_v2==0.1.0` in site-packages, which is an unapproved third-party wheel repackaging lacking upstream supply-chain provenance (`approved: false` in [release/evidence_closure_v3/prerequisites.json](release/evidence_closure_v3/prerequisites.json)). The fallback `gt_all_minilm_l6_v2` is explicitly rejected. No official model export, signed inventory, or trusted signature has been supplied.
* **Requested Deliverables:**
  1. Standalone directory containing the complete set of 13 regular files for `all-MiniLM-L6-v2`.
  2. Inventory manifest `model_inventory.json` with full-tree relative paths, exact byte sizes, SHA-256 digests, and upstream git revision/provenance.
  3. Detached cryptographic signature `model_inventory.json.sig` generated using the owner's private key.
  4. Out-of-band provisioned public key trust anchor `gate1_model_provenance.pub.pem` delivered securely outside the intake payload to `release_intake/trusted_anchors/`.
  5. Formal `authorization_record.json` binding the inventory artifact SHA-256 to the gate, role, and authorized signer identity.
* **Required Format:** Ordinary materialized directory (no symlinks, Windows reparse points/junctions, or custom code), accompanied by signed JSON: `{"files": {"<relpath>": {"bytes": <int>, "sha256": "<hex>"}}, "provenance": {"upstream_revision": "<git-sha>"}}`.
* **Validation Criteria:**
  - 13 regular files verified against pinned SHA-256 hashes for the 6 critical files.
  - Zero unexpected extra files in the export directory.
  - Cryptographic verification: OpenSSL `dgst -sha256 -verify` against `gate1_model_provenance.pub.pem`. Self-supplied keys inside the intake tree are strictly rejected.
  - Authorization binding: `gate == "Gate 1: Model Provenance"`, `artifact_sha256 == sha256(model_inventory.json)`, `role == "Model Provenance Owner"`, `status == "AUTHORIZED"`, unexpired sign-off date.
  - Python probe verification: Tokenizer reports `exact: true`, CPU SentenceTransformer embedder produces 384 dimensions with maximum sequence length 256.
* **Intake Destination:** `release_intake/received/model_export/`
* **Verification Feedback Mechanism:** The recipient validation outcome is communicated via automated execution report generated by `python release_intake/validate_intake.py`.
* **Approval Condition:** Staging or submitting evidence initiates intake validation but does NOT constitute gate approval. Approval is granted solely when all cryptographic, inventory, and domain probes pass with zero errors.

### Draft Message (Copyable)

```text
To: Model / Content Provenance Owner & Supply-Chain Security Approver
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Supply-Chain Approval & Complete Export for all-MiniLM-L6-v2

We are preparing independent verification of the SURA chatbot release candidate (branch arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

1. Purpose and Current Blocker:
Model loading and embedding inference are currently BLOCKED. In accordance with release/evidence_closure_v3/ARTIFACTS.md and release/evidence_closure_v3/prerequisites.json, environment variable M2C_MODEL_DIR is unset. The repository fallback gt_all_minilm_l6_v2==0.1.0 is an unapproved third-party repackaging that is strictly REJECTED for release. We require an approved, standalone export of all-MiniLM-L6-v2 with verifiable supply-chain provenance.

2. Exact Deliverables:
Please provide:
a. An approved, standalone directory export containing the complete set of 13 regular files:
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
b. An inventory manifest (model_inventory.json) containing the relative path, exact byte size, and SHA256 digest for every file in the export tree, plus upstream git commit revision:
   {"files": {"<relpath>": {"bytes": <int>, "sha256": "<hex>"}}, "provenance": {"upstream_revision": "<git-sha>"}}
c. Detached cryptographic signature (model_inventory.json.sig) verifying the authenticity of model_inventory.json.
d. Out-of-band provisioned public key trust anchor (gate1_model_provenance.pub.pem) transmitted directly to the release security team for placement in release_intake/trusted_anchors/.
e. Formal authorization record (authorization_record.json) binding the exact artifact SHA-256, gate name, accountable role, authorized signer identity, and signoff timestamp.

3. Signature and Authenticity Verification:
- Cryptographic signatures are verified via OpenSSL (dgst -sha256 -verify).
- The public key must be provisioned independently outside the intake tree; trust anchors placed inside the intake directory are rejected as self-supplied.
- The authorization record must bind gate ("Gate 1: Model Provenance"), role ("Model Provenance Owner"), artifact_sha256, and status ("AUTHORIZED").

4. Submission Destination:
Please stage all export files, model_inventory.json, model_inventory.json.sig, and authorization_record.json into:
release_intake/received/model_export/

5. Verification Feedback:
The intake validator (python release_intake/validate_intake.py) will automatically execute against the staged files, verifying inventory completeness, hash pins, absence of symlinks/junctions/extra files, cryptographic signature validity, and authorization binding. The resulting structured validation report will be transmitted back to the owner.

6. Non-Automatic Approval Notice:
Submitting evidence does NOT automatically approve Gate 1. Approval requires the successful, error-free completion of all automated validation checks, probe executions, and cryptographic authentications.
```

* **Deliverables to Return:** Export directory, signed inventory JSON, detached signature, out-of-band trust anchor, signed authorization record.

---

## Gate 2: Coherent Cold-Store Bundle & 115-vs-113 Investigation

* **Accountable Role:** Store / Corpus Owner & Storage Operations Lead
* **Draft Subject:** `[ACTION REQUIRED] SURA Release — Quiesced Cold Vector Store Snapshot & Signed Byte Inventory`
* **Current Blocker:** Physical vector store hashes are unknown in the repository. The local page store contains 115 embeddings whereas manifests declare 113. No signed byte inventory, exclusive quiescence attestation, or approved cold-copy snapshot exists (`approved_cold_snapshot: false` in [release/evidence_closure_v3/prerequisites.json](release/evidence_closure_v3/prerequisites.json)). The original stores (`data/vector_store/chroma.sqlite3` and `data/vector_store/page_collection/chroma.sqlite3`) must NOT be accessed, queried, copied, repaired, or modified.
* **Requested Deliverables:**
  1. Approved, coherent cold snapshot bundle (`ColdExport`) of combined card store root (`data/vector_store`) and nested page store (`data/vector_store/page_collection`).
  2. Physical byte inventory manifest `cold_store_inventory.json` with relative paths, byte counts, and SHA-256 digests.
  3. Detached cryptographic signature `cold_store_inventory.json.sig`.
  4. Out-of-band provisioned public key trust anchor `gate2_cold_stores.pub.pem` delivered to `release_intake/trusted_anchors/`.
  5. Operator quiescence attestation `quiescence_attestation.json` confirming all writers were stopped before snapshot creation and during inventory generation.
  6. Explicit written permission for disposable RunCopy diagnostics (`disposable_runcopy_diagnostic_authorization.json`).
  7. Formal `authorization_record.json` binding the inventory artifact SHA-256 to the gate, role, and authorized signer identity.
* **Required Format:** Tarball or directory snapshot containing `data/vector_store` and nested `data/vector_store/page_collection`, accompanied by signed JSON manifests.
* **Validation Criteria:** Checksum verification before and after transfer; exclusive quiescence attestation; 3-tier transfer layout (`ColdExport` -> `SealedCopy` -> `RunCopy`); disposable-copy diagnostic confirms 115-vs-113 discrepancy is caused by unadmitted capture M2C-18 (`original_store_unchanged: true`, exit code 2). Original stores remain completely untouched.
* **Intake Destination:** `release_intake/received/cold_stores/`
* **Verification Feedback Mechanism:** The recipient validation outcome is communicated via automated execution report generated by `python release_intake/validate_intake.py`.
* **Approval Condition:** Staging or submitting evidence initiates intake validation but does NOT constitute gate approval. Approval is granted solely when all cryptographic, inventory, and domain probes pass with zero errors.

### Draft Message (Copyable)

```text
To: Store / Corpus Owner & Storage Operations Lead
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Quiesced Cold Vector Store Snapshot & Signed Byte Inventory

We are preparing independent verification of the SURA release branch (arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

1. Purpose and Current Blocker:
Direct access to, migration of, or repair of existing stores is strictly PROHIBITED. Physical store hashes are unverified and local stores contain 115 embeddings vs 113 declared. In accordance with release/evidence_closure_v3/COLD_COPY.md, we require an approved cold-copy snapshot bundle, signed physical byte inventory, and operator quiescence attestation. Under NO circumstances may the original stores (data/vector_store/chroma.sqlite3 or data/vector_store/page_collection/chroma.sqlite3) be opened, modified, queried, or repaired.

2. Exact Deliverables:
Please provide:
a. An approved, coherent cold snapshot bundle (ColdExport) containing the combined card store root (data/vector_store) and nested page store (data/vector_store/page_collection).
b. Operator attestation of exclusive quiescence/lease (quiescence_attestation.json), confirming all application workers, Chroma clients, and background writers were stopped before snapshot creation and remain stopped through inventory generation.
c. A signed physical byte inventory JSON (cold_store_inventory.json) covering all files: chroma.sqlite3, SQLite sidecars (-wal, -shm, journal), and every HNSW UUID index segment directory/data file for both collections.
d. Detached cryptographic signature (cold_store_inventory.json.sig) verifying cold_store_inventory.json.
e. Out-of-band provisioned public key trust anchor (gate2_cold_stores.pub.pem) transmitted to the release security team for placement in release_intake/trusted_anchors/.
f. Formal authorization record (authorization_record.json) binding artifact_sha256, gate ("Gate 2: Cold Stores"), role ("Store / Corpus Owner"), signer identity, and status ("AUTHORIZED").
g. Explicit permission to execute the 3-tier transfer layout (ColdExport -> SealedCopy -> RunCopy) and read-only diagnostics on a disposable RunCopy.

3. Discrepancy Investigation Protocol (115 vs 113):
- The 115-vs-113 investigation must execute strictly on a disposable clone of RunCopy using:
  python scripts/diagnose_windows_verification.py --store-quiesced --card-store "$DisposableCardCopy" --page-store "$DisposablePageCopy" --out "$Results/store-diagnostic.json"
- Acceptance requirement: The diagnostic must verify that the 2 extra vectors belong to unadmitted capture M2C-18, report exit code 2 (CHECKS_FAILED), classify them as UNADMITTED_CAPTURE_PAGE_VECTORS, and prove original store bytes are unchanged (original_store_unchanged: true).

4. Submission Destination:
Please stage all snapshot assets, inventories, signatures, and authorizations into:
release_intake/received/cold_stores/

5. Verification Feedback:
The intake validator (python release_intake/validate_intake.py) will automatically execute against the staged files, verifying inventory completeness, absence of symlinks/junctions/extra files, quiescence attestation, cryptographic signature validity, and authorization binding. The resulting structured validation report will be transmitted back to the owner.

6. Non-Automatic Approval Notice:
Submitting evidence does NOT automatically approve Gate 2. Approval requires the successful, error-free completion of all automated validation checks, diagnostic executions, and cryptographic authentications.
```

* **Deliverables to Return:** Snapshot location, signed `cold_store_inventory.json`, detached signature, out-of-band trust anchor, signed quiescence lease attestation, disposable store approval.

---

## Gate 3: Windows AMD64 Runtime & Dependency Certification

* **Accountable Role:** Windows AMD64 Runtime Owner & Release Engineer
* **Draft Subject:** `[ACTION REQUIRED] SURA Release — Windows AMD64 Runtime Certification & Dependency Graph Closure`
* **Current Blocker:** The reference lock file ([requirements.lock.txt](requirements.lock.txt)) is a Linux Python 3.11.2 lock with 127 entries including Linux-only NVIDIA/CUDA packages. The local Windows host operates Python 3.10.11 AMD64 with Torch `2.5.1+cu121`. Windows AMD64 compatibility is uncertified (`windows_compatibility_verified: false` in [release/evidence_closure_v3/prerequisites.json](release/evidence_closure_v3/prerequisites.json)). No package installation is authorized by this request.
* **Requested Deliverables:**
  1. Certified Windows AMD64 dependency specification/lockfile and offline wheelhouse inventory manifest `windows_runtime_manifest.json`.
  2. Signed native-binary inventory mapping wheels and binary DLLs (`chromadb-1.5.9-cp39-abi3-win_amd64.whl`, CPU/BLAS Torch binaries, `onnxruntime` DLLs) to SHA-256 hashes and download provenance.
  3. Detached cryptographic signature `windows_runtime_manifest.json.sig`.
  4. Out-of-band provisioned public key trust anchor `gate3_windows_runtime.pub.pem` delivered to `release_intake/trusted_anchors/`.
  5. Formal `authorization_record.json` binding the runtime manifest artifact SHA-256 to the gate, role, and authorized signer identity.
* **Required Format:** Signed lockfile and manifest mapping package filenames to SHA-256 hashes and download/provenance sources. No installation will occur during verification.
* **Validation Criteria:** `python -m pip check` passes with zero conflicts; `python -m pip freeze --all` matches approved Windows inventory; native Win32 handle contention tests pass without skips (`test_windows_portability.py`).
* **Intake Destination:** `release_intake/received/windows_runtime/`
* **Verification Feedback Mechanism:** The recipient validation outcome is communicated via automated execution report generated by `python release_intake/validate_intake.py`.
* **Approval Condition:** Staging or submitting evidence initiates intake validation but does NOT constitute gate approval. Approval is granted solely when all cryptographic, inventory, and domain probes pass with zero errors.

### Draft Message (Copyable)

```text
To: Windows AMD64 Runtime Owner & Release Engineer
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Windows AMD64 Runtime Certification & Dependency Graph Closure

We are preparing independent verification of the SURA release branch on native Windows (arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

1. Purpose and Current Blocker:
Formal Windows runtime certification remains BLOCKED. In accordance with release/evidence_closure_v3/COMMANDS.md and release/evidence_closure_v3/prerequisites.json, the reference lock is Linux-only, while Windows AMD64 requires certified dependency graph closure. No package installation is authorized by this request; all validation is performed against offline inventories and manifests.

2. Exact Deliverables:
Please provide:
a. Certified Windows AMD64 dependency graph and hash-inventoried offline wheelhouse manifest (windows_runtime_manifest.json) reconciling reference Linux Python 3.11.2 with Windows AMD64 Python (Python 3.10.11 or certified 3.11.x).
b. Signed native-binary inventory of native wheels and binary shared libraries, specifically:
   - chromadb-1.5.9-cp39-abi3-win_amd64.whl (SHA256: 4fd0b560e56761b7f3cb4d5c6205fd5f20814484b4a3e4e9af9038c2b428fc6c)
   - Certified CPU/BLAS Torch binaries (reference lock targets CPU Torch 2.14.1; current environment has 2.5.1+cu121)
   - onnxruntime Windows AMD64 binaries
c. Detached cryptographic signature (windows_runtime_manifest.json.sig) verifying windows_runtime_manifest.json.
d. Out-of-band provisioned public key trust anchor (gate3_windows_runtime.pub.pem) transmitted to the release security team for placement in release_intake/trusted_anchors/.
e. Formal authorization record (authorization_record.json) binding artifact_sha256, gate ("Gate 3: Windows Runtime"), role ("Windows AMD64 Runtime Owner"), signer identity, and status ("AUTHORIZED").
f. Documented configuration for thread allocation, OpenMP/MKL, and Win32 file sharing semantics.

3. Signature and Authenticity Verification:
- Cryptographic signatures are verified via OpenSSL (dgst -sha256 -verify).
- The public key must be provisioned independently outside the intake tree; trust anchors placed inside the intake directory are rejected as self-supplied.
- The authorization record must bind gate ("Gate 3: Windows Runtime"), role ("Windows AMD64 Runtime Owner"), artifact_sha256, and status ("AUTHORIZED").

4. Submission Destination:
Please stage all runtime manifests, inventories, signatures, and authorizations into:
release_intake/received/windows_runtime/

5. Verification Feedback:
The intake validator (python release_intake/validate_intake.py) will automatically execute against the staged files, verifying inventory completeness, absence of symlinks/junctions/extra files, cryptographic signature validity, and authorization binding. The resulting structured validation report will be transmitted back to the owner.

6. Non-Automatic Approval Notice:
Submitting evidence does NOT automatically approve Gate 3. Approval requires the successful, error-free completion of all automated validation checks, environment probes, and cryptographic authentications.
```

* **Deliverables to Return:** Windows AMD64 dependency specification, native wheel inventory, detached signature, out-of-band trust anchor, certified environment configuration.

---

## Gate 4: Authoritative SAP Captures & 184-Row Review Worksheet

* **Accountable Role:** Independent SAP Domain Reviewer & SAP Content Supplier
* **Draft Subject:** `[ACTION REQUIRED] SURA Release — Independent SAP Domain Review & Authoritative Captures`
* **Current Blocker:** All 184 rows in [release/evidence_closure_v3/sap-review-worksheet.csv](release/evidence_closure_v3/sap-review-worksheet.csv) are unadjudicated. M2C-18 (*Contract Account*) has conflicting guide LOIO mappings and remains excluded. AI-authored frozen reference labels cannot certify SAP truth.
* **Requested Deliverables:**
  1. Legally authorized SAP page body captures (TOC, LOIO, version, locale metadata) in raw HTML/PDF format.
  2. Completed and independently signed `sap-review-worksheet.csv` (184 rows).
  3. Authoritative resolution/exclusion determination for M2C-18.
  4. Detached cryptographic signature `sap-review-worksheet.csv.sig`.
  5. Out-of-band provisioned public key trust anchor `gate4_sap_review.pub.pem` delivered to `release_intake/trusted_anchors/`.
  6. Formal `authorization_record.json` binding the worksheet artifact SHA-256 to the gate, role, and authorized reviewer identity.
* **Required Format:** Signed CSV matching `release/evidence_closure_v3/sap-review-worksheet.csv`, accompanied by raw HTML/PDF source captures and JSON alignment evidence.
* **Validation Criteria (All 4 SAP Acceptance Thresholds Enforced):**
  - **Substantive correctness:** $\ge 95\%$ on answerable questions.
  - **Claim-source identity:** $100\%$ exact match between answer claims and authoritative source text.
  - **Wrong-guide/version errors:** $0\%$ answers citing incorrect guides, LOIOs, or versions.
  - **Safe negatives:** $100\%$ proper abstention on unanswerable/out-of-scope questions.
  - Zero duplicate `case_id` values across the 184 rows.
  - M2C-18 reconciled or formally excluded.
* **Intake Destination:** `release_intake/received/sap_review/`
* **Verification Feedback Mechanism:** The recipient validation outcome is communicated via automated execution report generated by `python release_intake/validate_intake.py`.
* **Approval Condition:** Staging or submitting evidence initiates intake validation but does NOT constitute gate approval. Approval is granted solely when all cryptographic, inventory, and domain probes pass with zero errors.

### Draft Message (Copyable)

```text
To: Independent SAP Domain Reviewer & SAP Content Supplier
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Independent SAP Domain Review & Authoritative Captures

We are preparing independent verification of the SURA release candidate (branch arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

1. Purpose and Current Blocker:
Release quality acceptance requires independent human domain adjudication. In accordance with release/evidence_closure_v3/SAP_REVIEW.md, we require authoritative source captures, completion of the 184-row review worksheet, and formal reconciliation of M2C-18. AI-authored frozen reference labels cannot certify SAP truth.

2. Exact Deliverables:
Please provide:
a. Legally authorized, authoritative SAP page body captures including TOC, deliverable LOIO, page LOIO, product edition, release/version/build, and locale.
b. Completed and signed sap-review-worksheet.csv covering:
   - All 113 frozen Phase-12 questions
   - All 70 frozen cached Phase-3 questions
   - 1 M2C-18 identity resolution row
c. Authoritative resolution for M2C-18:
   - Requested guide: 9442486404b54071b4ebeab6a16628e7, page b1a202c9bb3011da2b24000f20dac9ef (version 2025.001)
   - Competing deliverable: 40374490 (guide e4375c1cad104b2eb7d027369bd76638, Enterprise Services in Financials)
   - Provide authoritative TOC and page body proving whether any mapping is valid. Until signed reconciliation exists, M2C-18 remains strictly excluded.
d. Detached cryptographic signature (sap-review-worksheet.csv.sig) verifying sap-review-worksheet.csv.
e. Out-of-band provisioned public key trust anchor (gate4_sap_review.pub.pem) transmitted to the release security team for placement in release_intake/trusted_anchors/.
f. Formal authorization record (authorization_record.json) binding artifact_sha256, gate ("Gate 4: SAP Review"), role ("Independent SAP Domain Reviewer"), reviewer identity, and status ("AUTHORIZED").

3. Mandatory Domain Acceptance Criteria:
The review worksheet must meet all four repository acceptance thresholds:
- Substantive correctness: >= 95% on answerable questions (keyword overlap or generic answers are NOT correctness).
- Claim-to-source identity: 100% exact alignment between answer facts and source text.
- Wrong-guide/version errors: 0% answers citing wrong guides or wrong versions.
- Safe negatives: 100% correct abstention on unanswerable/out-of-scope queries.
- Zero duplicate case_id values across all 184 rows.

4. Submission Destination:
Please stage all captures, sap-review-worksheet.csv, signatures, and authorization records into:
release_intake/received/sap_review/

5. Verification Feedback:
The intake validator (python release_intake/validate_intake.py) will automatically execute against the staged files, verifying row count (184), absence of duplicate case_ids, all 4 domain thresholds, absence of symlinks/extra files, cryptographic signature validity, and authorization binding. The resulting structured validation report will be transmitted back to the owner.

6. Non-Automatic Approval Notice:
Submitting evidence does NOT automatically approve Gate 4. Approval requires the successful, error-free completion of all automated validation checks, domain threshold calculations, and cryptographic authentications.
```

* **Deliverables to Return:** Signed `sap-review-worksheet.csv`, detached signature, out-of-band trust anchor, source captures with TOC hashes, M2C-18 determination.

---

## Gate 5: Chroma Security Advisory Determinations & Containment

* **Accountable Role:** Security Authority Lead & Target Operations Owner
* **Draft Subject:** `[ACTION REQUIRED] SURA Release — Security Determinations for Five Open Chroma 1.5.9 Advisories`
* **Current Blocker:** Five security advisories on `chromadb 1.5.9` remain with status `OPEN` and approver fields set to `null` in [release/evidence_closure_v3/security-decisions.json](release/evidence_closure_v3/security-decisions.json). Upstream PR 7602 is open/unmerged with no released patch.
* **Requested Deliverables:**
  1. Formally completed and signed `security-decisions.json` providing determinations, mitigations, and residual risk sign-offs for CVE-2026-45829 through CVE-2026-45833.
  2. Verified deployment network/process containment evidence.
  3. Detached cryptographic signature `security-decisions.json.sig`.
  4. Out-of-band provisioned public key trust anchor `gate5_security_decisions.pub.pem` delivered to `release_intake/trusted_anchors/`.
  5. Formal `authorization_record.json` binding the security decisions artifact SHA-256 to the gate, role, and authorized CISO delegate identity.
* **Required Format:** Signed JSON matching `release/evidence_closure_v3/security-decisions.json` schema (`status: APPROVED`, approver name, approval date, expiry, residual risk) and containment checklist.
* **Validation Criteria:** Formal sign-off on all 5 Chroma 1.5.9 advisories; zero OPEN CVEs; verified deployment containment (untrusted Chroma HTTP ingress blocked, single-tenant process boundaries enforced, untrusted `.configuration` reconstruction denied).
* **Intake Destination:** `release_intake/received/security_decisions/`
* **Verification Feedback Mechanism:** The recipient validation outcome is communicated via automated execution report generated by `python release_intake/validate_intake.py`.
* **Approval Condition:** Staging or submitting evidence initiates intake validation but does NOT constitute gate approval. Approval is granted solely when all cryptographic, inventory, and domain probes pass with zero errors.

### Draft Message (Copyable)

```text
To: Security Authority Lead & Target Operations Owner
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Security Determinations for Five Open Chroma 1.5.9 Advisories

We are preparing independent verification of the SURA release branch (arena/b450cda2-chatbot, commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47).

1. Purpose and Current Blocker:
Security release gates remain BLOCKED. In accordance with release/evidence_closure_v3/SECURITY_DECISIONS.md and release/evidence_closure_v3/security-decisions.json, we require formal determinations and containment verification for five open advisories affecting chromadb 1.5.9:
- GHSA-f4j7-r4q5-qw2c (CVE-2026-45829, Critical) — HTTP provider constructor kwargs injection before auth.
- GHSA-36p7-vc44-83pf (CVE-2026-45833, Critical) — Collection update config reconstruction.
- GHSA-xph7-9rjv-w5fr (CVE-2026-45831, High) — SimpleRBAC tenant isolation flaw.
- GHSA-2wm9-hf6c-p5cr (CVE-2026-45830, High) — Python v1 API cross-tenant CRUD.
- GHSA-x97m-f58v-9cwg (CVE-2026-45832, High) — Python v1 authorization bypass.

2. Exact Deliverables:
Please provide:
a. Formally completed security-decisions.json recording: Security Owner, Operations Owner, Decision, Approver Name, Approval Date, Review Expiry Date, and Residual Risk for each advisory. Status must be "APPROVED" with zero open CVEs.
b. Verified deployment network and process containment evidence:
   - Untrusted Chroma HTTP port ingress is blocked; Chroma is restricted to owned loopback/in-process SDK.
   - Untrusted users are denied collection/config mutations across all API versions.
   - Strict avoidance of untrusted SDK .configuration reconstruction.
   - Verification of single-tenant process and storage isolation boundaries.
c. Detached cryptographic signature (security-decisions.json.sig) verifying security-decisions.json.
d. Out-of-band provisioned public key trust anchor (gate5_security_decisions.pub.pem) transmitted to the release security team for placement in release_intake/trusted_anchors/.
e. Formal authorization record (authorization_record.json) binding artifact_sha256, gate ("Gate 5: Security Decisions"), role ("Security Authority Lead"), CISO delegate identity, and status ("AUTHORIZED").

3. Signature and Authenticity Verification:
- Cryptographic signatures are verified via OpenSSL (dgst -sha256 -verify).
- The public key must be provisioned independently outside the intake tree; trust anchors placed inside the intake directory are rejected as self-supplied.
- The authorization record must bind gate ("Gate 5: Security Decisions"), role ("Security Authority Lead"), artifact_sha256, and status ("AUTHORIZED").

4. Submission Destination:
Please stage security-decisions.json, containment evidence, signatures, and authorizations into:
release_intake/received/security_decisions/

5. Verification Feedback:
The intake validator (python release_intake/validate_intake.py) will automatically execute against the staged files, verifying decision completeness, absence of open CVEs, absence of symlinks/extra files, cryptographic signature validity, and authorization binding. The resulting structured validation report will be transmitted back to the owner.

6. Non-Automatic Approval Notice:
Submitting evidence does NOT automatically approve Gate 5. Approval requires the successful, error-free completion of all automated validation checks, containment audits, and cryptographic authentications.
```

* **Deliverables to Return:** Signed `security-decisions.json`, detached signature, out-of-band trust anchor, verified network and process containment evidence.

---

## Gate 6: Strict 113-Query Current-Production Extractive RAG Benchmark

* **Accountable Role:** Runtime / Test Owner & Release Approver
* **Draft Subject:** `[ACTION REQUIRED] SURA Release — Authorization & Execution of Strict 113-Query Quality Benchmark`
* **Current Blocker:** This gate is strictly contingent on the prior approval and provisioning of Gates 1 through 5. Executing `benchmarks/run_quality.py` or diagnostic quality commands without approved models, cold stores, and runtime graphs is prohibited.

### Draft Message (Copyable)

```text
To: Runtime / Test Owner & Release Approver
From: SURA Release Coordination
Subject: [ACTION REQUIRED] SURA Release — Authorization & Execution of Strict 113-Query Quality Benchmark

Following the formal approval and provisioning of Gates 1 through 5 (Model Export, Cold Stores, Windows Runtime, SAP Review, and Security Decisions), we request authorization to execute the final current-production RAG quality evaluation.

Prerequisite Gates Checklist:
[ ] Gate 1: Approved all-MiniLM-L6-v2 directory and signed 13-file inventory verified.
[ ] Gate 2: Quiesced cold-store bundle verified via byte inventory; disposable diagnostic executed.
[ ] Gate 3: Windows AMD64 dependency closure and native binary graph certified.
[ ] Gate 4: Independent SAP domain review completed on 184 rows; M2C-18 resolved or excluded.
[ ] Gate 5: Security determinations signed and containment attested for all 5 Chroma CVEs.

Execution Specification (On an Isolated Private Host):
1. Environment variables:
   HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, HF_DATASETS_OFFLINE=1, PYTHONDONTWRITEBYTECODE=1, M2C_MODEL_DIR=<approved_export_path>
2. Quality command:
   python benchmarks/run_quality.py --source-commit 582f9930846f7e080e2d1bfb50ef8bec6d7aae47 --out "$Results/current-strict-phase12.json"
3. Full backend test suite:
   python -m pytest tests -q -ra --tb=long --junitxml="$Results/backend.xml"
4. Native Windows Q35 probe:
   python scripts/probe_q35_reproducibility.py --store-quiesced --card-store "$RunCopyCard" --threads 1 --mkldnn on --out "$Results/q35-t1-on.json"

Acceptance Criteria:
- Strict evidence criteria: Expected guide/page context cited AND reference quote present in answer.
- All 113 queries recorded: 65 answerable, 40 negative, 8 ambiguous (matching dataset hash 3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac).
- Zero reliance on cached replay or relaxed tolerances.
- Independent alignment with SAP gold review determinations.

Please issue authorization and test execution parameters once Gates 1–5 are signed. This request is a draft and has not been pre-approved.
```

* **Deliverables to Return:** Execution authorization, signed execution log, `current-strict-phase12.json`, `backend.xml`, `q35-t1-on.json`.

---

## Actionable Owner Handoff Summary

| Gate | Target Deliverable | Accountable Role | Status | Next Milestone Action |
|:---:|---|---|:---:|---|
| **1** | Materialized 13-file model export + signed inventory | Model / Content Provenance Owner | **BLOCKED** | Authorized coordinator transmits Gate 1 request |
| **2** | Quiesced snapshot bundle + signed byte inventory | Store / Corpus Owner | **BLOCKED** | Authorized coordinator transmits Gate 2 request |
| **3** | Windows AMD64 dependency closure & DLL inventory | Windows AMD64 Runtime Owner | **BLOCKED** | Authorized coordinator transmits Gate 3 request |
| **4** | Completed 184-row review worksheet + source captures | Independent SAP Domain Reviewer | **BLOCKED** | Authorized coordinator transmits Gate 4 request |
| **5** | Signed decisions & containment for 5 Chroma CVEs | Security Authority Lead | **BLOCKED** | Authorized coordinator transmits Gate 5 request |
| **6** | Strict 113-query RAG benchmark & Q35 run | Release Approver & Test Lead | **BLOCKED** | Execute only after Gates 1–5 approvals are verified |

*Release status remains strictly **NOT READY** until all six gates are formally closed.*
