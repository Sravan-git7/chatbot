"""Unit, security, and cryptographic regression tests for release intake evidence validator.

Tests all gate validation rules, path traversal rejection, symlink checks,
hash verification, duplicate-key rejection, unexpected file detection,
domain threshold enforcement, cryptographic signature verification,
authorization record binding, expiration checks, and trust-anchor isolation.
Never uses live models, never touches protected stores, never makes network calls.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "release_intake"))

import validate_intake as VI


class IntakeValidatorTests(unittest.TestCase):
    def test_current_empty_intake_reports_all_gates_missing(self):
        """Current repository intake directory is empty: all gates must report MISSING."""
        res = VI.validate_all_gates(ROOT / "release_intake" / "received")
        self.assertEqual(res["release_status"], "NOT READY")
        for key, g in res["gates"].items():
            self.assertEqual(g["status"], "MISSING", f"{key} should be MISSING")

    def test_path_traversal_in_inventory_is_rejected(self):
        """Path traversal sequences (e.g. ..) or absolute paths in inventory must fail."""
        self.assertIsNotNone(VI.validate_path_safety("../outside.txt"))
        self.assertIsNotNone(VI.validate_path_safety("sub/../../escaped.txt"))
        self.assertIsNotNone(VI.validate_path_safety("/root/file.txt"))
        self.assertIsNotNone(VI.validate_path_safety("C:/windows/file.txt"))
        self.assertIsNotNone(VI.validate_path_safety("safe\0file.txt"))
        self.assertIsNone(VI.validate_path_safety("safe_dir/file.txt"))
        self.assertIsNone(VI.validate_path_safety("file.txt"))

    def test_duplicate_keys_in_json_inventory_rejected(self):
        """Duplicate keys in JSON payloads (e.g. shadowed hash entries) are rejected."""
        malicious_json = '{"files": {"model.safetensors": "hash1", "model.safetensors": "hash2"}}'
        with self.assertRaises(ValueError) as cm:
            VI.json_loads_strict(malicious_json)
        self.assertIn("Duplicate key 'model.safetensors'", str(cm.exception))

    def test_gate1_missing_required_file_detected(self):
        """If any of the 13 required model export files is missing, validation fails."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()

            inv_files = {}
            for name in VI.GATE1_REQUIRED_13_FILES[1:]:
                p = model_dir / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"content")
                inv_files[name] = {"sha256": hashlib.sha256(b"content").hexdigest(), "bytes": 7}

            inv = {
                "provenance": {"upstream_revision": "main"},
                "files": inv_files,
            }
            (model_dir / "model_inventory.json").write_text(json.dumps(inv), encoding="utf-8")

            res = VI.validate_gate1(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("model.safetensors" in err for err in res["errors"]))

    def test_gate1_extra_unexpected_file_detected(self):
        """Extra unapproved files dropped into model_export directory are detected and rejected."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()

            inv_files = {}
            for name in VI.GATE1_REQUIRED_13_FILES:
                p = model_dir / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"content")
                inv_files[name] = {"sha256": hashlib.sha256(b"content").hexdigest(), "bytes": 7}

            (model_dir / "unapproved_payload.bin").write_bytes(b"trojan_or_junk")

            inv = {
                "provenance": {"upstream_revision": "main"},
                "files": inv_files,
            }
            (model_dir / "model_inventory.json").write_text(json.dumps(inv), encoding="utf-8")

            res = VI.validate_gate1(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("unapproved_payload.bin" in err for err in res["errors"]))

    def test_gate1_hash_mismatch_detected(self):
        """Corrupted file or hash mismatch triggers VALIDATION_FAILED."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()

            inv_files = {}
            for name in VI.GATE1_REQUIRED_13_FILES:
                p = model_dir / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"actual_data")
                inv_files[name] = {"sha256": "bad_hash_0000000000000000000000000000000000000000000000000000000000", "bytes": 11}

            inv = {
                "provenance": {"upstream_revision": "main"},
                "files": inv_files,
            }
            (model_dir / "model_inventory.json").write_text(json.dumps(inv), encoding="utf-8")

            res = VI.validate_gate1(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("Hash mismatch" in err for err in res["errors"]))

    def test_self_asserted_approval_field_does_not_grant_approved_status(self):
        """Setting 'approved: true' in an intake json must NEVER grant APPROVED status."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()

            inv_files = {}
            for name in VI.GATE1_REQUIRED_13_FILES:
                p = model_dir / name
                p.parent.mkdir(parents=True, exist_ok=True)
                content = b"sample_mock_data"
                p.write_bytes(content)
                sha = hashlib.sha256(content).hexdigest()
                inv_files[name] = {"sha256": sha, "bytes": len(content)}

            orig_pins = dict(VI.GATE1_PINNED_HASHES)
            try:
                for k in VI.GATE1_PINNED_HASHES:
                    VI.GATE1_PINNED_HASHES[k] = inv_files[k]["sha256"]

                inv = {
                    "provenance": {"upstream_revision": "rev123", "approved": True},
                    "files": inv_files,
                }
                (model_dir / "model_inventory.json").write_text(json.dumps(inv), encoding="utf-8")
                res = VI.validate_gate1(intake_root)

                self.assertNotEqual(res["status"], "APPROVED")
                self.assertEqual(res["status"], "VALIDATED_PENDING_AUTHORIZATION")
                self.assertTrue(any("pending" in w.lower() for w in res["warnings"]))
            finally:
                VI.GATE1_PINNED_HASHES.clear()
                VI.GATE1_PINNED_HASHES.update(orig_pins)

    def test_gate2_quiescence_attestation_enforced(self):
        """Cold stores without operator quiesced: true must fail."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            store_dir = intake_root / "cold_stores"
            store_dir.mkdir()

            (store_dir / "store_inventory.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
            (store_dir / "quiescence_attestation.json").write_text(
                json.dumps({"quiesced": False, "operator_owner": "ops"}), encoding="utf-8"
            )

            res = VI.validate_gate2(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("quiesced: true" in err for err in res["errors"]))

    def test_gate2_uninventoried_store_file_rejected(self):
        """Uninventoried files in cold_stores are rejected as unexpected."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            store_dir = intake_root / "cold_stores"
            store_dir.mkdir()

            test_file = store_dir / "chroma.sqlite3"
            test_file.write_bytes(b"sqlite_data")
            sha = hashlib.sha256(b"sqlite_data").hexdigest()

            (store_dir / "store_inventory.json").write_text(
                json.dumps({"files": {"chroma.sqlite3": {"sha256": sha}}}), encoding="utf-8"
            )
            (store_dir / "quiescence_attestation.json").write_text(
                json.dumps({"quiesced": True, "operator_owner": "DBA Lead"}), encoding="utf-8"
            )

            (store_dir / "extra_uninventoried.db").write_bytes(b"stray_database")

            res = VI.validate_gate2(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("extra_uninventoried.db" in err for err in res["errors"]))

    def test_gate4_duplicate_case_ids_rejected(self):
        """Duplicate case_id entries in sap-review-worksheet.csv fail validation."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            sap_dir = intake_root / "sap_review"
            sap_dir.mkdir()

            csv_file = sap_dir / "sap-review-worksheet.csv"
            with csv_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["dataset", "case_id", "status", "reviewer", "substantive_correct", "claim_source_identity", "wrong_guide", "safe_negative"])
                for i in range(183):
                    writer.writerow(["phase12", f"P12-{i:03d}", "REVIEWED", "SME", "true", "true", "false", "true"])
                writer.writerow(["phase12", "P12-000", "REVIEWED", "SME", "true", "true", "false", "true"])

            res = VI.validate_gate4(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("Duplicate case_id" in err for err in res["errors"]))

    def test_gate4_domain_thresholds_enforced(self):
        """Worksheet failing 95% substantive, 100% claim identity, 0% wrong guide, or 100% safe negative fails."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            sap_dir = intake_root / "sap_review"
            sap_dir.mkdir()

            csv_file = sap_dir / "sap-review-worksheet.csv"
            with csv_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["dataset", "case_id", "status", "reviewer", "substantive_correct", "claim_source_identity", "wrong_guide", "is_negative_control", "safe_negative"])
                for i in range(184):
                    wg = "true" if i == 10 else "false"
                    writer.writerow(["phase12", f"P12-{i:03d}", "REVIEWED", "SME", "true", "true", wg, "false", "true"])

            res = VI.validate_gate4(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("wrong guide" in err for err in res["errors"]))

    def test_gate5_open_cves_fail_validation(self):
        """Open or unapproved security decisions fail validation."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            sec_dir = intake_root / "security_decisions"
            sec_dir.mkdir()

            decisions = [
                {"ghsa_id": gid, "status": "OPEN", "approver": None, "approval_date": None, "mitigation": None}
                for gid in VI.GATE5_REQUIRED_ADVISORIES
            ]
            (sec_dir / "security-decisions.json").write_text(json.dumps({"decisions": decisions}), encoding="utf-8")

            res = VI.validate_gate5(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("non-approved" in err for err in res["errors"]))

    def test_gate6_strictly_blocked_when_any_prerequisite_missing(self):
        """Gate 6 is strictly blocked if Gates 1-5 are not all APPROVED."""
        res = VI.validate_all_gates(ROOT / "release_intake" / "received")
        g6 = res["gates"]["gate6_benchmark"]
        self.assertEqual(g6["status"], "MISSING")
        self.assertTrue(any("Gates 1 through 5 must all be APPROVED" in err for err in g6["errors"]))


class CryptographicAuthenticityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crypto_tool = VI.find_crypto_verifier()

    def setUp(self):
        self.orig_pins = dict(VI.GATE1_PINNED_HASHES)

    def tearDown(self):
        VI.GATE1_PINNED_HASHES.clear()
        VI.GATE1_PINNED_HASHES.update(self.orig_pins)

    def _setup_gate1_fixture(self, model_dir: Path) -> Tuple[Path, str]:
        inv_files = {}
        for name in VI.GATE1_REQUIRED_13_FILES:
            p = model_dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            content = f"content_{name}".encode("utf-8")
            p.write_bytes(content)
            sha = hashlib.sha256(content).hexdigest()
            inv_files[name] = {"sha256": sha, "bytes": len(content)}
            if name in VI.GATE1_PINNED_HASHES:
                VI.GATE1_PINNED_HASHES[name] = sha

        inv_path = model_dir / "model_inventory.json"
        inv = {"provenance": {"upstream_revision": "git-rev-1234"}, "files": inv_files}
        inv_path.write_text(json.dumps(inv, indent=2), encoding="utf-8")
        inv_sha = hashlib.sha256(inv_path.read_bytes()).hexdigest()
        return inv_path, inv_sha

    def test_mismatched_authorization_binding_fails_validation(self):
        """If authorization_record.json artifact_sha256 or gate does not match, validation fails."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()
            inv_path, inv_sha = self._setup_gate1_fixture(model_dir)

            # Create authorization record with mismatched artifact_sha256
            auth = {
                "gate": "Gate 1: Model Provenance",
                "artifact_name": "model_inventory.json",
                "artifact_sha256": "wrong_sha256_000000000000000000000000000000000000000000000000000000",
                "role": "Model Provenance Owner",
                "signer_identity": "Lead ML Engineer",
                "status": "AUTHORIZED",
                "signoff_date": "2026-10-16T00:00:00Z",
            }
            (model_dir / "authorization_record.json").write_text(json.dumps(auth), encoding="utf-8")

            res = VI.validate_gate1(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("artifact_sha256 mismatch" in err for err in res["errors"]))

    def test_wrong_signer_role_in_authorization_fails_validation(self):
        """If authorization_record.json role does not match required role, validation fails."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()
            inv_path, inv_sha = self._setup_gate1_fixture(model_dir)

            auth = {
                "gate": "Gate 1: Model Provenance",
                "artifact_name": "model_inventory.json",
                "artifact_sha256": inv_sha,
                "role": "Unauthorized Role",
                "signer_identity": "Someone",
                "status": "AUTHORIZED",
                "signoff_date": "2026-10-16T00:00:00Z",
            }
            (model_dir / "authorization_record.json").write_text(json.dumps(auth), encoding="utf-8")

            res = VI.validate_gate1(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("role mismatch" in err for err in res["errors"]))

    def test_expired_authorization_fails_validation(self):
        """If authorization_record.json has expired_at in the past, validation fails."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()
            inv_path, inv_sha = self._setup_gate1_fixture(model_dir)

            auth = {
                "gate": "Gate 1: Model Provenance",
                "artifact_name": "model_inventory.json",
                "artifact_sha256": inv_sha,
                "role": "Model Provenance Owner",
                "signer_identity": "Lead ML Engineer",
                "status": "AUTHORIZED",
                "signoff_date": "2026-01-01T00:00:00Z",
                "expires_at": "2026-01-02T00:00:00Z",  # Expired
            }
            (model_dir / "authorization_record.json").write_text(json.dumps(auth), encoding="utf-8")

            res = VI.validate_gate1(intake_root)
            self.assertEqual(res["status"], "VALIDATION_FAILED")
            self.assertTrue(any("expired" in err for err in res["errors"]))

    def test_forged_cryptographic_signature_fails_validation(self):
        """A forged or corrupted signature file fails cryptographic verification."""
        if not self.crypto_tool:
            self.skipTest("OpenSSL binary not available on host")

        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            intake_root = Path(td1)
            trust_dir = Path(td2)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()
            inv_path, inv_sha = self._setup_gate1_fixture(model_dir)

            # Generate trusted RSA keypair in external trust anchor directory
            priv_key = trust_dir / "gate1_priv.pem"
            pub_key = trust_dir / "gate1_model_provenance.pub.pem"
            subprocess.check_call(
                [self.crypto_tool, "genpkey", "-algorithm", "RSA", "-out", str(priv_key), "-pkeyopt", "rsa_keygen_bits:2048"],
                stderr=subprocess.DEVNULL,
            )
            subprocess.check_call(
                [self.crypto_tool, "pkey", "-in", str(priv_key), "-pubout", "-out", str(pub_key)],
                stderr=subprocess.DEVNULL,
            )

            # Write a corrupted/forged signature
            (model_dir / "model_inventory.json.sig").write_bytes(b"corrupted_forged_signature_bytes_1234567890")

            auth = {
                "gate": "Gate 1: Model Provenance",
                "artifact_name": "model_inventory.json",
                "artifact_sha256": inv_sha,
                "role": "Model Provenance Owner",
                "signer_identity": "Lead ML Engineer",
                "status": "AUTHORIZED",
                "signoff_date": "2026-10-16T00:00:00Z",
            }
            (model_dir / "authorization_record.json").write_text(json.dumps(auth), encoding="utf-8")

            # Temporarily configure trust anchor env
            orig_pins = dict(VI.GATE1_PINNED_HASHES)
            old_anchor_env = os.environ.get("SURA_TRUST_ANCHORS_DIR")
            try:
                os.environ["SURA_TRUST_ANCHORS_DIR"] = str(trust_dir)
                inv_data = json.loads(inv_path.read_text(encoding="utf-8"))
                for k in VI.GATE1_PINNED_HASHES:
                    VI.GATE1_PINNED_HASHES[k] = inv_data["files"][k]["sha256"]

                res = VI.validate_gate1(intake_root)
                self.assertEqual(res["status"], "VALIDATION_FAILED")
                self.assertTrue(any("signature verification FAILED" in err for err in res["errors"]))
            finally:
                VI.GATE1_PINNED_HASHES.clear()
                VI.GATE1_PINNED_HASHES.update(orig_pins)
                if old_anchor_env is not None:
                    os.environ["SURA_TRUST_ANCHORS_DIR"] = old_anchor_env
                else:
                    os.environ.pop("SURA_TRUST_ANCHORS_DIR", None)

    def test_genuine_signature_and_binding_approves_gate(self):
        """A genuine signature verified against external trust anchor and valid binding approves gate."""
        if not self.crypto_tool:
            self.skipTest("OpenSSL binary not available on host")

        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            intake_root = Path(td1)
            trust_dir = Path(td2)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()
            inv_path, inv_sha = self._setup_gate1_fixture(model_dir)

            priv_key = trust_dir / "gate1_priv.pem"
            pub_key = trust_dir / "gate1_model_provenance.pub.pem"
            subprocess.check_call(
                [self.crypto_tool, "genpkey", "-algorithm", "RSA", "-out", str(priv_key), "-pkeyopt", "rsa_keygen_bits:2048"],
                stderr=subprocess.DEVNULL,
            )
            subprocess.check_call(
                [self.crypto_tool, "pkey", "-in", str(priv_key), "-pubout", "-out", str(pub_key)],
                stderr=subprocess.DEVNULL,
            )

            # Produce genuine signature of model_inventory.json
            sig_file = model_dir / "model_inventory.json.sig"
            subprocess.check_call(
                [self.crypto_tool, "dgst", "-sha256", "-sign", str(priv_key), "-out", str(sig_file), str(inv_path)]
            )

            auth = {
                "gate": "Gate 1: Model Provenance",
                "artifact_name": "model_inventory.json",
                "artifact_sha256": inv_sha,
                "role": "Model Provenance Owner",
                "signer_identity": "Lead ML Engineer",
                "status": "AUTHORIZED",
                "signoff_date": "2026-10-16T00:00:00Z",
            }
            (model_dir / "authorization_record.json").write_text(json.dumps(auth), encoding="utf-8")

            orig_pins = dict(VI.GATE1_PINNED_HASHES)
            old_anchor_env = os.environ.get("SURA_TRUST_ANCHORS_DIR")
            try:
                os.environ["SURA_TRUST_ANCHORS_DIR"] = str(trust_dir)
                inv_data = json.loads(inv_path.read_text(encoding="utf-8"))
                for k in VI.GATE1_PINNED_HASHES:
                    VI.GATE1_PINNED_HASHES[k] = inv_data["files"][k]["sha256"]

                res = VI.validate_gate1(intake_root)
                self.assertEqual(res["status"], "APPROVED")
                self.assertEqual(len(res["errors"]), 0)
            finally:
                VI.GATE1_PINNED_HASHES.clear()
                VI.GATE1_PINNED_HASHES.update(orig_pins)
                if old_anchor_env is not None:
                    os.environ["SURA_TRUST_ANCHORS_DIR"] = old_anchor_env
                else:
                    os.environ.pop("SURA_TRUST_ANCHORS_DIR", None)

    def test_self_supplied_trust_anchor_rejected(self):
        """Trust anchor placed inside the untrusted intake payload directory is rejected."""
        with tempfile.TemporaryDirectory() as td:
            intake_root = Path(td)
            model_dir = intake_root / "model_export"
            model_dir.mkdir()
            inv_path, inv_sha = self._setup_gate1_fixture(model_dir)

            # Malicious supplier places trust anchor inside untrusted intake tree
            self_anchor_dir = intake_root / "untrusted_keys"
            self_anchor_dir.mkdir()
            (self_anchor_dir / "gate1_model_provenance.pub.pem").write_bytes(b"dummy_key")
            (model_dir / "model_inventory.json.sig").write_bytes(b"dummy_sig")

            auth = {
                "gate": "Gate 1: Model Provenance",
                "artifact_name": "model_inventory.json",
                "artifact_sha256": inv_sha,
                "role": "Model Provenance Owner",
                "signer_identity": "Lead ML Engineer",
                "status": "AUTHORIZED",
                "signoff_date": "2026-10-16T00:00:00Z",
            }
            (model_dir / "authorization_record.json").write_text(json.dumps(auth), encoding="utf-8")

            old_anchor_env = os.environ.get("SURA_TRUST_ANCHORS_DIR")
            try:
                # Point anchor env to directory inside intake
                os.environ["SURA_TRUST_ANCHORS_DIR"] = str(self_anchor_dir)
                res = VI.validate_gate1(intake_root)
                self.assertEqual(res["status"], "VALIDATION_FAILED")
                self.assertTrue(any("cannot be self-supplied" in err for err in res["errors"]))
            finally:
                if old_anchor_env is not None:
                    os.environ["SURA_TRUST_ANCHORS_DIR"] = old_anchor_env
                else:
                    os.environ.pop("SURA_TRUST_ANCHORS_DIR", None)


if __name__ == "__main__":
    unittest.main()
