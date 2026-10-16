# Received Artifacts Staging Area

> **STATUS:** No external artifacts have been received. This staging directory is empty.

---

## Incoming Artifact Requirements

When an accountable owner provides deliverables, deposit them into dedicated subdirectories here along with their provenance manifests:

* `received/model_export/` — Standalone directory containing the 13 regular files for `all-MiniLM-L6-v2`, accompanied by `model_inventory.json` and signed supplier provenance.
* `received/cold_stores/` — Quiesced snapshot of `vector_store` and nested `page_collection`, accompanied by `store_inventory.json` and signed quiescence lease attestation.
* `received/windows_runtime/` — Certified Windows AMD64 wheelhouse and dependency graph closure metadata.
* `received/sap_review/` — Authoritative SAP source captures and completed, signed `sap-review-worksheet.csv` (184 rows).
* `received/security_decisions/` — Formally completed and signed `security-decisions.json` with containment evidence.

Do not stage or unzip any archives without verifying regular-file contents, absence of reparse points/symlinks, and SHA256 checksum equality against signed owner inventories.
