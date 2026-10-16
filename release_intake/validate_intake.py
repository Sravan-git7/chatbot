"""Standard-library evidence validator for SURA release intake staging.

Validates incoming external deliverables staged under release_intake/received/
against documented project specifications (release/evidence_closure_v3/ and release_intake/).
Uses ONLY Python standard library modules (and optional system openssl CLI if provisioned).
Never imports external packages, never initializes Chroma stores, never downloads models,
and never runs model inference.

Security & Integrity Principles:
- Rejects path traversal ('..'), absolute paths, drive letters, and null bytes in all inventories.
- Rejects symlinks, directory junctions, and non-regular files (fifos, sockets, devices).
- Rejects paths escaping the intake root.
- Detects and rejects duplicate keys in JSON inventories and duplicate records in CSV worksheets.
- Enforces exact file inventories: detects both missing required files and unexpected extra files.
- Distinguishes cryptographic integrity from authenticity: SHA-256 byte matches prove only
  equality with a supplied digest, not author identity. Self-asserted fields like 'approved: true'
  or unverified '.sig' files do not constitute authorization.
- Validates cryptographic binding between authorization records and exact inventory SHA-256 digests.
- Fails closed when required trust anchors, signing keys, schemas, or authorization records
  are absent or unverified.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent

# Gate 1: Pinned SHA-256 digests for all-MiniLM-L6-v2 export files
GATE1_PINNED_HASHES: Dict[str, str] = {
    "model.safetensors": "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    "config.json": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
    "sentence_bert_config.json": "fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7",
    "modules.json": "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf",
}

GATE1_REQUIRED_13_FILES = [
    "model.safetensors",
    "tokenizer.json",
    "vocab.txt",
    "config.json",
    "sentence_bert_config.json",
    "modules.json",
    "1_Pooling/config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "config_sentence_transformers.json",
    "data_config.json",
    "README.md",
    ".gitattributes",
]

GATE1_PERMITTED_METADATA_FILES = {
    "model_inventory.json",
    "model_inventory.json.sig",
    "model_inventory.sig",
    "chain_of_custody.json",
    "chain_of_custody.json.sig",
    "authorization_record.json",
    "authorization_record.json.sig",
}

# Gate 5: Required advisory IDs
GATE5_REQUIRED_ADVISORIES = [
    "GHSA-f4j7-r4q5-qw2c",  # CVE-2026-45829
    "GHSA-36p7-vc44-83pf",  # CVE-2026-45830
    "GHSA-xph7-9rjv-w5fr",  # CVE-2026-45831
    "GHSA-2wm9-hf6c-p5cr",  # CVE-2026-45832
    "GHSA-x97m-f58v-9cwg",  # CVE-2026-45833
]


def sha256_file(path: Path) -> str:
    """Computes SHA-256 digest of a regular file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def json_loads_strict(text: str) -> Any:
    """Parses JSON while explicitly rejecting duplicate keys in objects."""
    def raise_on_duplicates(ordered_pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for k, v in ordered_pairs:
            if k in d:
                raise ValueError(f"Duplicate key '{k}' detected in JSON object")
            d[k] = v
        return d

    return json.loads(text, object_pairs_hook=raise_on_duplicates)


def find_crypto_verifier() -> Optional[str]:
    """Locates OpenSSL executable on the host system without external dependencies."""
    tool = shutil.which("openssl")
    if tool:
        return tool
    git_openssl = Path("C:/Program Files/Git/usr/bin/openssl.exe")
    if git_openssl.is_file():
        return str(git_openssl)
    return None


def check_directory_safety(directory: Path, base_root: Path) -> List[str]:
    """Rejects symlinks, junctions, non-regular files, or paths resolving outside base_root."""
    violations: List[str] = []
    if not directory.exists():
        return violations

    if directory.is_symlink():
        violations.append(f"Symlink detected on directory itself: {directory}")
        return violations

    try:
        if not directory.resolve().is_relative_to(base_root.resolve()):
            violations.append(f"Directory resolves outside intake root: {directory}")
            return violations
    except (ValueError, RuntimeError, AttributeError):
        try:
            directory.resolve().relative_to(base_root.resolve())
        except ValueError:
            violations.append(f"Directory resolves outside intake root: {directory}")
            return violations

    for root_dir, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs:
            p = Path(root_dir) / name
            if p.is_symlink():
                violations.append(f"Symlink directory detected (forbidden): {p.relative_to(base_root)}")

        for name in files:
            p = Path(root_dir) / name
            if p.is_symlink():
                violations.append(f"Symlink file detected (forbidden): {p.relative_to(base_root)}")
            elif not p.is_file():
                violations.append(f"Unexpected non-regular file type (fifo/socket/device): {p.relative_to(base_root)}")

    return violations


def validate_path_safety(rel_path: str) -> Optional[str]:
    """Ensures a relative path is strictly safe from directory traversal and absolute referencing."""
    if "\0" in rel_path:
        return f"Null byte in path forbidden: {repr(rel_path)}"
    norm = rel_path.replace("\\", "/")
    if norm.startswith("/") or norm.startswith("\\"):
        return f"Absolute path forbidden: {rel_path}"
    if ":" in norm:
        return f"Drive letter or colon forbidden: {rel_path}"
    parts = norm.split("/")
    if ".." in parts:
        return f"Path traversal ('..') forbidden: {rel_path}"
    if "." in parts:
        if len(parts) > 1 and any(part == "." for part in parts):
            return f"Relative current-dir '.' in path forbidden: {rel_path}"
    return None


def verify_authenticity_and_signoff(
    intake_dir: Path,
    artifact_path: Path,
    required_role: str,
    trust_anchor_id: str,
    target_gate: str,
) -> Tuple[bool, str, List[str], List[str]]:
    """Evaluates whether an artifact has verified cryptographic authenticity and human authorization.

    Returns:
        (is_authorized, status_detail, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    auth_file = intake_dir / "authorization_record.json"
    sig_file_candidates = [
        artifact_path.with_name(artifact_path.name + ".sig"),
        artifact_path.with_name(artifact_path.name + ".sha256.sig"),
        intake_dir / f"{artifact_path.name}.sig",
    ]
    sig_file = next((f for f in sig_file_candidates if f.is_file()), None)

    # 1. Authorization record validation
    if not auth_file.is_file():
        warnings.append(
            f"Missing formal external authorization record ({auth_file.name}) from {required_role}; authorization pending."
        )
        return False, f"Authorization record missing from {required_role}", errors, warnings

    try:
        auth_data = json_loads_strict(auth_file.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"Failed to parse {auth_file.name}: {e}")
        return False, "Malformed authorization record", errors, warnings

    # Validate binding: gate, artifact_name, artifact_sha256, role
    if auth_data.get("gate") != target_gate:
        errors.append(f"Authorization record gate mismatch: expected '{target_gate}', got '{auth_data.get('gate')}'")

    if auth_data.get("artifact_name") != artifact_path.name:
        errors.append(
            f"Authorization record artifact_name mismatch: expected '{artifact_path.name}', got '{auth_data.get('artifact_name')}'"
        )

    actual_sha = sha256_file(artifact_path)
    if auth_data.get("artifact_sha256") != actual_sha:
        errors.append(
            f"Authorization record artifact_sha256 mismatch (altered signed content or mismatched inventory): "
            f"expected '{actual_sha}', got '{auth_data.get('artifact_sha256')}'"
        )

    if auth_data.get("role") != required_role:
        errors.append(f"Authorization record role mismatch: expected '{required_role}', got '{auth_data.get('role')}'")

    if auth_data.get("status") != "AUTHORIZED":
        errors.append(f"Authorization record status is '{auth_data.get('status')}', not 'AUTHORIZED'")

    if not auth_data.get("signer_identity"):
        errors.append("Authorization record lacks 'signer_identity'")

    if not auth_data.get("signoff_date"):
        errors.append("Authorization record lacks 'signoff_date'")

    # Check expiration if present
    if expires_at := auth_data.get("expires_at"):
        try:
            # Handle ISO string or integer timestamp
            if isinstance(expires_at, (int, float)):
                exp_dt = datetime.datetime.fromtimestamp(expires_at, tz=datetime.timezone.utc)
            else:
                exp_dt = datetime.datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            if exp_dt < now:
                errors.append(f"Authorization record expired at {expires_at} (current UTC: {now.isoformat()})")
        except Exception as e:
            errors.append(f"Malformed expires_at in authorization record: {e}")

    if errors:
        return False, "Authorization record binding error", errors, warnings

    # 2. Cryptographic signature verification
    if not sig_file:
        warnings.append(f"Cryptographic signature file missing for {artifact_path.name}.")
        return False, f"Evidence and authorization binding verified; signature file missing for {artifact_path.name}", errors, warnings

    # Locate trust anchor
    anchor_env = os.environ.get("SURA_TRUST_ANCHORS_DIR")
    anchor_dir = Path(anchor_env) if anchor_env else ROOT / "release_intake" / "trusted_anchors"

    # CRITICAL: Verify trust anchor does not reside within the intake directory or intake root
    try:
        anchor_res = anchor_dir.resolve()
        intake_res = intake_dir.resolve()
        if (
            anchor_res.is_relative_to(intake_res)
            or anchor_res.is_relative_to(intake_res.parent)
            or "release_intake/received" in anchor_res.as_posix()
        ):
            errors.append("Trust anchor directory cannot be self-supplied within the untrusted intake payload.")
            return False, "Self-supplied trust anchor rejected", errors, warnings
    except (ValueError, RuntimeError):
        pass

    anchor_candidates = [
        anchor_dir / f"{trust_anchor_id}.pub.pem",
        anchor_dir / f"{trust_anchor_id}.pub",
        anchor_dir / f"{trust_anchor_id}.pem",
    ]
    anchor_file = next((f for f in anchor_candidates if f.is_file()), None)

    if not anchor_file:
        warnings.append(
            f"Signature file {sig_file.name} present, but trusted signing anchor '{trust_anchor_id}' "
            f"is not provisioned in SURA_TRUST_ANCHORS_DIR; signature authenticity cannot be proven."
        )
        return False, f"Evidence and authorization binding verified; pending verified trust anchor for {required_role}", errors, warnings

    crypto_tool = find_crypto_verifier()
    if not crypto_tool:
        warnings.append("OpenSSL verification binary unavailable; cannot verify cryptographic signature.")
        return False, "Evidence verified; pending OpenSSL verification tool", errors, warnings

    # Execute cryptographic signature verification
    proc = subprocess.run(
        [crypto_tool, "dgst", "-sha256", "-verify", str(anchor_file), "-signature", str(sig_file), str(artifact_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        errors.append(f"Cryptographic signature verification FAILED for {artifact_path.name}: bad signature or altered content ({err_msg})")
        return False, "Cryptographic signature verification failed (forged or corrupted signature)", errors, warnings

    warnings.append(f"Cryptographic signature verified against trusted anchor '{trust_anchor_id}'.")
    return True, f"Cryptographic authenticity and {required_role} authorization verified", errors, warnings


# -------------------------------------------------------------------------------------------------
# GATE 1: Model Provenance & File Inventory
# -------------------------------------------------------------------------------------------------

def validate_gate1(intake_root: Path) -> Dict[str, Any]:
    """Validates Gate 1: Model Provenance & 13-File Inventory."""
    model_dir = intake_root / "model_export"
    if not model_dir.exists() or not any(model_dir.iterdir()):
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "MISSING",
            "details": "release_intake/received/model_export/ is absent or empty",
            "errors": [],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []

    # Check symlinks and non-regular files
    violations = check_directory_safety(model_dir, intake_root)
    if violations:
        errors.extend(violations)

    inv_path = model_dir / "model_inventory.json"
    if not inv_path.is_file():
        errors.append("Missing required model_inventory.json manifest")
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "VALIDATION_FAILED",
            "details": "Inventory manifest missing",
            "errors": errors,
            "warnings": warnings,
        }

    try:
        inv = json_loads_strict(inv_path.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"Invalid or duplicate-key JSON in model_inventory.json: {e}")
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "VALIDATION_FAILED",
            "details": "JSON parse or duplicate-key error",
            "errors": errors,
            "warnings": warnings,
        }

    files_dict = inv.get("files")
    if not isinstance(files_dict, dict):
        errors.append("model_inventory.json missing 'files' dictionary mapping")
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "VALIDATION_FAILED",
            "details": "Schema violation",
            "errors": errors,
            "warnings": warnings,
        }

    # Verify all 13 required regular files exist
    for expected_file in GATE1_REQUIRED_13_FILES:
        target = model_dir / expected_file
        if not target.is_file():
            errors.append(f"Missing required model export file: {expected_file}")
        elif expected_file not in files_dict:
            errors.append(f"File {expected_file} present on disk but omitted from model_inventory.json")

    # Detect unexpected extra files in model_export directory
    allowed_files = set(GATE1_REQUIRED_13_FILES) | GATE1_PERMITTED_METADATA_FILES
    for root_dir, _, files in os.walk(model_dir):
        for name in files:
            rel = Path(root_dir, name).relative_to(model_dir).as_posix()
            if rel not in allowed_files and rel not in files_dict:
                errors.append(f"Unexpected extra file in model_export: {rel}")

    # Verify inventory path safety and checksums
    for rel_path, meta in files_dict.items():
        if path_err := validate_path_safety(rel_path):
            errors.append(path_err)
            continue
        p = model_dir / rel_path
        if not p.is_file():
            errors.append(f"Inventoried file missing from disk: {rel_path}")
            continue
        expected_sha = meta.get("sha256") if isinstance(meta, dict) else meta
        actual_sha = sha256_file(p)
        if actual_sha != expected_sha:
            errors.append(f"Hash mismatch for {rel_path}: actual {actual_sha} != expected {expected_sha}")

        norm_key = rel_path.replace("\\", "/")
        if norm_key in GATE1_PINNED_HASHES:
            pinned = GATE1_PINNED_HASHES[norm_key]
            if actual_sha != pinned:
                errors.append(f"Pinned collection manifest hash mismatch for {norm_key}: actual {actual_sha} != pinned {pinned}")

    provenance = inv.get("provenance", {})
    if not provenance.get("upstream_revision"):
        errors.append("model_inventory.json missing 'provenance.upstream_revision' commit reference")

    if errors:
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} validation error(s) found in model export",
            "errors": errors,
            "warnings": warnings,
        }

    is_auth, auth_detail, auth_errors, auth_notes = verify_authenticity_and_signoff(
        model_dir, inv_path, "Model Provenance Owner", "gate1_model_provenance", "Gate 1: Model Provenance"
    )
    warnings.extend(auth_notes)
    if auth_errors:
        errors.extend(auth_errors)
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in model provenance authorization",
            "errors": errors,
            "warnings": warnings,
        }

    if not is_auth:
        return {
            "gate": "Gate 1: Model Provenance",
            "status": "VALIDATED_PENDING_AUTHORIZATION",
            "details": f"13 regular files and 6 pinned digests verified; {auth_detail}",
            "errors": [],
            "warnings": warnings,
        }

    return {
        "gate": "Gate 1: Model Provenance",
        "status": "APPROVED",
        "details": "13 regular files, 6 pinned SHA-256 digests, and supply-chain authenticity approved",
        "errors": [],
        "warnings": warnings,
    }


# -------------------------------------------------------------------------------------------------
# GATE 2: Cold Stores Snapshot & Physical Checksums
# -------------------------------------------------------------------------------------------------

def validate_gate2(intake_root: Path) -> Dict[str, Any]:
    """Validates Gate 2: Cold Stores Snapshot & Physical Checksums."""
    store_dir = intake_root / "cold_stores"
    if not store_dir.exists() or not any(store_dir.iterdir()):
        return {
            "gate": "Gate 2: Cold Stores",
            "status": "MISSING",
            "details": "release_intake/received/cold_stores/ is absent or empty",
            "errors": [],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []

    violations = check_directory_safety(store_dir, intake_root)
    if violations:
        errors.extend(violations)

    inv_path = store_dir / "store_inventory.json"
    quiescence_path = store_dir / "quiescence_attestation.json"

    if not inv_path.is_file():
        errors.append("Missing required store_inventory.json")
    if not quiescence_path.is_file():
        errors.append("Missing required operator quiescence_attestation.json")

    if errors:
        return {
            "gate": "Gate 2: Cold Stores",
            "status": "VALIDATION_FAILED",
            "details": "Required cold-store manifests missing",
            "errors": errors,
            "warnings": warnings,
        }

    try:
        inv = json_loads_strict(inv_path.read_text(encoding="utf-8"))
        quiescence = json_loads_strict(quiescence_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "gate": "Gate 2: Cold Stores",
            "status": "VALIDATION_FAILED",
            "details": f"Manifest JSON parsing or duplicate-key failure: {e}",
            "errors": [str(e)],
            "warnings": warnings,
        }

    if quiescence.get("quiesced") is not True:
        errors.append("quiescence_attestation.json does not attest 'quiesced: true'")
    if not quiescence.get("operator_owner"):
        errors.append("quiescence_attestation.json missing 'operator_owner' identity")

    files_dict = inv.get("files", {})
    if not isinstance(files_dict, dict) or not files_dict:
        errors.append("store_inventory.json has missing or empty 'files' mapping")
    else:
        for rel_path, meta in files_dict.items():
            if path_err := validate_path_safety(rel_path):
                errors.append(path_err)
                continue
            p = store_dir / rel_path
            if not p.is_file():
                errors.append(f"Inventoried store file missing from disk: {rel_path}")
                continue
            expected_sha = meta.get("sha256") if isinstance(meta, dict) else meta
            actual_sha = sha256_file(p)
            if actual_sha != expected_sha:
                errors.append(f"Store hash mismatch for {rel_path}: actual {actual_sha} != expected {expected_sha}")

        permitted_meta = {
            "store_inventory.json", "store_inventory.json.sig", "store_inventory.sig",
            "quiescence_attestation.json", "quiescence_attestation.json.sig",
            "authorization_record.json", "authorization_record.json.sig", "COLD_COPY.md"
        }
        for root_dir, _, files in os.walk(store_dir):
            for name in files:
                rel = Path(root_dir, name).relative_to(store_dir).as_posix()
                if rel not in permitted_meta and rel not in files_dict:
                    errors.append(f"Uninventoried/unexpected store file on disk: {rel}")

    if errors:
        return {
            "gate": "Gate 2: Cold Stores",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in cold store bundle",
            "errors": errors,
            "warnings": warnings,
        }

    is_auth, auth_detail, auth_errors, auth_notes = verify_authenticity_and_signoff(
        store_dir, inv_path, "Storage Operations Lead", "gate2_cold_stores", "Gate 2: Cold Stores"
    )
    warnings.extend(auth_notes)
    if auth_errors:
        errors.extend(auth_errors)
        return {
            "gate": "Gate 2: Cold Stores",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in cold stores authorization",
            "errors": errors,
            "warnings": warnings,
        }

    if not is_auth:
        return {
            "gate": "Gate 2: Cold Stores",
            "status": "VALIDATED_PENDING_AUTHORIZATION",
            "details": f"Physical checksums and quiescence format verified; {auth_detail}",
            "errors": [],
            "warnings": warnings,
        }

    return {
        "gate": "Gate 2: Cold Stores",
        "status": "APPROVED",
        "details": "Quiesced cold store snapshot and physical byte checksums verified",
        "errors": [],
        "warnings": warnings,
    }


# -------------------------------------------------------------------------------------------------
# GATE 3: Windows AMD64 Runtime Certification
# -------------------------------------------------------------------------------------------------

def validate_gate3(intake_root: Path) -> Dict[str, Any]:
    """Validates Gate 3: Windows AMD64 Runtime Certification."""
    runtime_dir = intake_root / "windows_runtime"
    if not runtime_dir.exists() or not any(runtime_dir.iterdir()):
        return {
            "gate": "Gate 3: Windows Runtime",
            "status": "MISSING",
            "details": "release_intake/received/windows_runtime/ is absent or empty",
            "errors": [],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []

    violations = check_directory_safety(runtime_dir, intake_root)
    if violations:
        errors.extend(violations)

    spec_path = runtime_dir / "runtime_spec.json"
    if not spec_path.is_file():
        errors.append("Missing required runtime_spec.json in windows_runtime/")
        return {
            "gate": "Gate 3: Windows Runtime",
            "status": "VALIDATION_FAILED",
            "details": "Runtime specification manifest missing",
            "errors": errors,
            "warnings": warnings,
        }

    try:
        spec = json_loads_strict(spec_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "gate": "Gate 3: Windows Runtime",
            "status": "VALIDATION_FAILED",
            "details": f"Failed to parse runtime_spec.json: {e}",
            "errors": [str(e)],
            "warnings": warnings,
        }

    if not spec.get("python_version"):
        errors.append("runtime_spec.json missing certified 'python_version'")
    if not spec.get("native_binaries"):
        errors.append("runtime_spec.json missing 'native_binaries' inventory")

    if errors:
        return {
            "gate": "Gate 3: Windows Runtime",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in runtime specification",
            "errors": errors,
            "warnings": warnings,
        }

    is_auth, auth_detail, auth_errors, auth_notes = verify_authenticity_and_signoff(
        runtime_dir, spec_path, "Windows Runtime Owner", "gate3_windows_runtime", "Gate 3: Windows Runtime"
    )
    warnings.extend(auth_notes)
    if auth_errors:
        errors.extend(auth_errors)
        return {
            "gate": "Gate 3: Windows Runtime",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in runtime authorization",
            "errors": errors,
            "warnings": warnings,
        }

    if not is_auth:
        return {
            "gate": "Gate 3: Windows Runtime",
            "status": "VALIDATED_PENDING_AUTHORIZATION",
            "details": f"Windows AMD64 runtime graph specified; {auth_detail}",
            "errors": [],
            "warnings": warnings,
        }

    return {
        "gate": "Gate 3: Windows Runtime",
        "status": "APPROVED",
        "details": "Windows AMD64 dependency closure certified and signed",
        "errors": [],
        "warnings": warnings,
    }


# -------------------------------------------------------------------------------------------------
# GATE 4: SAP Domain Review Worksheet & Captures
# -------------------------------------------------------------------------------------------------

def validate_gate4(intake_root: Path) -> Dict[str, Any]:
    """Validates Gate 4: SAP Domain Review Worksheet & Captures."""
    sap_dir = intake_root / "sap_review"
    if not sap_dir.exists() or not any(sap_dir.iterdir()):
        return {
            "gate": "Gate 4: SAP Review",
            "status": "MISSING",
            "details": "release_intake/received/sap_review/ is absent or empty",
            "errors": [],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []

    violations = check_directory_safety(sap_dir, intake_root)
    if violations:
        errors.extend(violations)

    worksheet_path = sap_dir / "sap-review-worksheet.csv"
    if not worksheet_path.is_file():
        errors.append("Missing required sap-review-worksheet.csv")
        return {
            "gate": "Gate 4: SAP Review",
            "status": "VALIDATION_FAILED",
            "details": "Worksheet CSV missing",
            "errors": errors,
            "warnings": warnings,
        }

    try:
        with worksheet_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return {
            "gate": "Gate 4: SAP Review",
            "status": "VALIDATION_FAILED",
            "details": f"Failed to parse CSV: {e}",
            "errors": [str(e)],
            "warnings": warnings,
        }

    if len(rows) != 184:
        errors.append(f"Expected exactly 184 rows in sap-review-worksheet.csv; got {len(rows)}")

    seen_cases: Set[str] = set()
    duplicate_cases: List[str] = []
    for r in rows:
        cid = r.get("case_id", "")
        if cid in seen_cases:
            duplicate_cases.append(cid)
        seen_cases.add(cid)
    if duplicate_cases:
        errors.append(f"Duplicate case_id(s) detected in worksheet: {duplicate_cases[:5]}")

    unreviewed = [r.get("case_id", "unknown") for r in rows if r.get("status") == "UNREVIEWED" or not r.get("reviewer")]
    if unreviewed:
        errors.append(f"{len(unreviewed)} row(s) remain UNREVIEWED in sap-review-worksheet.csv")

    if not unreviewed and rows:
        # 1. At least 95% substantive correctness
        substantive = sum(1 for r in rows if str(r.get("substantive_correct", "")).lower() in ("true", "1", "yes"))
        sub_rate = substantive / len(rows)
        if sub_rate < 0.95:
            errors.append(f"Substantive correctness {sub_rate:.2%} is below required 95% threshold")

        # 2. 100% claim-source identity
        claim_identity = sum(1 for r in rows if str(r.get("claim_source_identity", "")).lower() in ("true", "1", "yes"))
        if claim_identity < len(rows):
            errors.append(f"Claim-source identity is {claim_identity}/{len(rows)}; requires 100%")

        # 3. 0% wrong guide or version
        wrong_guides = sum(1 for r in rows if str(r.get("wrong_guide", "")).lower() in ("true", "1", "yes"))
        if wrong_guides > 0:
            errors.append(f"{wrong_guides} case(s) cite wrong guide or version; requires 0%")

        # 4. 100% safe negatives
        neg_rows = [r for r in rows if str(r.get("is_negative_control", "")).lower() in ("true", "1", "yes")]
        if neg_rows:
            safe_neg = sum(1 for r in neg_rows if str(r.get("safe_negative", "")).lower() in ("true", "1", "yes"))
            if safe_neg < len(neg_rows):
                errors.append(f"Safe negatives {safe_neg}/{len(neg_rows)}; requires 100%")

    if errors:
        is_only_unreviewed = all("remain UNREVIEWED" in e for e in errors)
        return {
            "gate": "Gate 4: SAP Review",
            "status": "RECEIVED_UNVALIDATED" if is_only_unreviewed else "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in SAP review worksheet",
            "errors": errors,
            "warnings": warnings,
        }

    is_auth, auth_detail, auth_errors, auth_notes = verify_authenticity_and_signoff(
        sap_dir, worksheet_path, "Independent SAP Domain Reviewer", "gate4_sap_review", "Gate 4: SAP Review"
    )
    warnings.extend(auth_notes)
    if auth_errors:
        errors.extend(auth_errors)
        return {
            "gate": "Gate 4: SAP Review",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in SAP review authorization",
            "errors": errors,
            "warnings": warnings,
        }

    if not is_auth:
        return {
            "gate": "Gate 4: SAP Review",
            "status": "VALIDATED_PENDING_AUTHORIZATION",
            "details": f"All 184 rows meet acceptance thresholds; {auth_detail}",
            "errors": [],
            "warnings": warnings,
        }

    return {
        "gate": "Gate 4: SAP Review",
        "status": "APPROVED",
        "details": "All 184 rows independently reviewed, meet all 4 thresholds, and signed off",
        "errors": [],
        "warnings": warnings,
    }


# -------------------------------------------------------------------------------------------------
# GATE 5: Chroma Security Advisory Decisions & Containment
# -------------------------------------------------------------------------------------------------

def validate_gate5(intake_root: Path) -> Dict[str, Any]:
    """Validates Gate 5: Chroma Security Advisory Decisions & Containment."""
    sec_dir = intake_root / "security_decisions"
    if not sec_dir.exists() or not any(sec_dir.iterdir()):
        return {
            "gate": "Gate 5: Security Decisions",
            "status": "MISSING",
            "details": "release_intake/received/security_decisions/ is absent or empty",
            "errors": [],
            "warnings": [],
        }

    errors: List[str] = []
    warnings: List[str] = []

    violations = check_directory_safety(sec_dir, intake_root)
    if violations:
        errors.extend(violations)

    decisions_path = sec_dir / "security-decisions.json"
    if not decisions_path.is_file():
        errors.append("Missing required security-decisions.json")
        return {
            "gate": "Gate 5: Security Decisions",
            "status": "VALIDATION_FAILED",
            "details": "Decisions JSON missing",
            "errors": errors,
            "warnings": warnings,
        }

    try:
        data = json_loads_strict(decisions_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "gate": "Gate 5: Security Decisions",
            "status": "VALIDATION_FAILED",
            "details": f"JSON parse or duplicate-key error: {e}",
            "errors": [str(e)],
            "warnings": warnings,
        }

    decisions_list = data.get("decisions", [])
    if not isinstance(decisions_list, list) or len(decisions_list) < 5:
        errors.append(f"Expected at least 5 advisory decisions; found {len(decisions_list)}")

    found_ids = set()
    for d in decisions_list:
        ghsa = d.get("ghsa_id")
        found_ids.add(ghsa)
        if d.get("status") != "APPROVED":
            errors.append(f"Advisory {ghsa} has non-approved status: '{d.get('status')}'")
        if not d.get("approver"):
            errors.append(f"Advisory {ghsa} has null/empty approver")
        if not d.get("approval_date"):
            errors.append(f"Advisory {ghsa} has null/empty approval_date")
        if not d.get("mitigation"):
            errors.append(f"Advisory {ghsa} missing explicit mitigation description")

    missing_ghsa = set(GATE5_REQUIRED_ADVISORIES) - found_ids
    if missing_ghsa:
        errors.append(f"Missing required advisory decisions: {sorted(missing_ghsa)}")

    containment_file = sec_dir / "containment_evidence.json"
    if not containment_file.is_file():
        warnings.append("containment_evidence.json not provided; process containment must be verified.")
    else:
        try:
            cont = json_loads_strict(containment_file.read_text(encoding="utf-8"))
            if not cont.get("network_containment_verified"):
                errors.append("containment_evidence.json does not verify network_containment_verified: true")
        except Exception as e:
            errors.append(f"Malformed containment_evidence.json: {e}")

    if errors:
        return {
            "gate": "Gate 5: Security Decisions",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in security decisions",
            "errors": errors,
            "warnings": warnings,
        }

    is_auth, auth_detail, auth_errors, auth_notes = verify_authenticity_and_signoff(
        sec_dir, decisions_path, "Security Authority Lead", "gate5_security_authority", "Gate 5: Security Decisions"
    )
    warnings.extend(auth_notes)
    if auth_errors:
        errors.extend(auth_errors)
        return {
            "gate": "Gate 5: Security Decisions",
            "status": "VALIDATION_FAILED",
            "details": f"{len(errors)} error(s) in security authorization",
            "errors": errors,
            "warnings": warnings,
        }

    if not is_auth:
        return {
            "gate": "Gate 5: Security Decisions",
            "status": "VALIDATED_PENDING_AUTHORIZATION",
            "details": f"All 5 Chroma advisories formatted; {auth_detail}",
            "errors": [],
            "warnings": warnings,
        }

    return {
        "gate": "Gate 5: Security Decisions",
        "status": "APPROVED",
        "details": "All 5 Chroma advisories formally signed and approved",
        "errors": [],
        "warnings": warnings,
    }


# -------------------------------------------------------------------------------------------------
# AGGREGATION & REPORTING
# -------------------------------------------------------------------------------------------------

def validate_all_gates(intake_root: Optional[Path] = None) -> Dict[str, Any]:
    """Validates all five prerequisite gates and computes overall readiness."""
    if intake_root is None:
        intake_root = ROOT / "release_intake" / "received"

    g1 = validate_gate1(intake_root)
    g2 = validate_gate2(intake_root)
    g3 = validate_gate3(intake_root)
    g4 = validate_gate4(intake_root)
    g5 = validate_gate5(intake_root)

    gates = [g1, g2, g3, g4, g5]
    all_approved = all(g["status"] == "APPROVED" for g in gates)

    g6 = {
        "gate": "Gate 6: Full 113-Query Evaluation",
        "status": "VALIDATED_PENDING_AUTHORIZATION" if all_approved else "MISSING",
        "details": "Evaluation authorized" if all_approved else "BLOCKED by prerequisite gates (Gates 1-5 must all be APPROVED)",
        "errors": [] if all_approved else ["Gates 1 through 5 must all be APPROVED before Gate 6 may execute"],
        "warnings": [],
    }

    overall_ready = all_approved and (g6["status"] == "APPROVED")

    return {
        "release_status": "READY" if overall_ready else "NOT READY",
        "intake_root": str(intake_root),
        "gates": {
            "gate1_model": g1,
            "gate2_stores": g2,
            "gate3_runtime": g3,
            "gate4_sap_review": g4,
            "gate5_security": g5,
            "gate6_benchmark": g6,
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate SURA release intake deliverables (stdlib only).")
    parser.add_argument("--intake-dir", default=None, help="Path to release_intake/received directory")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args(argv)

    intake_dir = Path(args.intake_dir) if args.intake_dir else ROOT / "release_intake" / "received"
    report = validate_all_gates(intake_dir)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["release_status"] == "READY" else 1

    print("================================================================================")
    print("                      SURA RELEASE INTAKE VALIDATION REPORT                    ")
    print("================================================================================")
    print(f"Intake Directory : {report['intake_root']}")
    print(f"Release Status   : {report['release_status']}")
    print("--------------------------------------------------------------------------------")

    for key, g in report["gates"].items():
        print(f"[{g['status']:<32}] {g['gate']}")
        print(f"  Details: {g['details']}")
        for err in g.get("errors", []):
            print(f"  * ERROR: {err}")
        for warn in g.get("warnings", []):
            print(f"  * WARNING: {warn}")

    print("================================================================================")
    return 0 if report["release_status"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
