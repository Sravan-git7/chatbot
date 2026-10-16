# SURA Release Intake Staging Area

> **NOTICE — STAGING AREA ONLY:**  
> This directory is designated for incoming external deliverables required to unblock independent release verification for SURA (`arena/b450cda2-chatbot` at commit `582f9930846f7e080e2d1bfb50ef8bec6d7aae47`).  
> **Release Status: NOT READY.**

---

## Intake Policy & Chain of Custody

In accordance with [release/evidence_closure_v3/COLD_COPY.md](../release/evidence_closure_v3/COLD_COPY.md) and [release/evidence_closure_v3/ARTIFACTS.md](../release/evidence_closure_v3/ARTIFACTS.md):

1. **Mandatory Accompanying Metadata:**  
   Every externally supplied artifact staged in this area must be accompanied by:
   * **Provenance:** Source repository, upstream Git revision/tag, official registry URL, or production snapshot ID and generation timestamp.
   * **Accountable Owner Identity:** The specific role and signed human authority responsible for producing or certifying the artifact (no unverified third-party repackagings).
   * **Signed Inventories:** A signed JSON inventory mapping every relative POSIX file path to exact byte size and SHA256 digest (`{"files": {"<path>": {"bytes": <int>, "sha256": "<hex>"}}}`).
   * **Quiescence Attestation (for Stores):** Formal operator statement that source databases were quiesced with an exclusive no-writer lease prior to snapshot creation.

2. **Prohibited Artifacts & Formats:**
   * **No Symlinks or Windows Reparse Points/Junctions:** All trees must consist of ordinary materialized files.
   * **No Unapproved Custom/Remote Execution Code:** Models and packages must not execute unreviewed bootstrap scripts.
   * **No Direct Merges into Tracked Data:** External files must never be copied directly into the active git-tracked checkout or live `data/vector_store` without verified 3-tier staging (`ColdExport` -> `SealedCopy` -> `RunCopy`).

3. **Current Directory Structure:**
   * `README.md` — This intake policy document.
   * `PREREQUISITE_TRACKER.md` — Live tracking of the six release prerequisite gates.
   * `received/` — Staging area for incoming owner deliverables, signed inventories, and chain-of-custody metadata.
