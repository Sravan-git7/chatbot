"""Regression and security tests for delivery inputs manifest verifier.

Tests duplicate path detection, malformed rows, unsafe paths, missing files,
hash mismatches, and exact set equality with git tracked files.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "release" / "evidence_closure_v3"))

import verify_delivery_inputs as VDI


class DeliveryInputsVerifierTests(unittest.TestCase):
    def test_real_delivery_inputs_exact_set_matches_repo(self):
        """Current repository delivery manifest matches exact inherited tracked files (1014 after Priority 1-3 fixes)."""
        res = VDI.verify_delivery()
        self.assertTrue(res["ok"], f"Real manifest verification failed: {res.get('errors')}")
        # After Priority 1-3 code fixes, inherited tracked set grew from 979 to 1014;
        # verify deterministically via git ls-files minus package files, not hardcoded.
        self.assertEqual(res["verified"], res["total"])
        self.assertEqual(len(res["errors"]), 0)
        self.assertGreater(res["total"], 0)

    def test_malformed_lines_detected(self):
        """Lines without double-space delimiter or invalid 64-hex SHA-256 digests fail."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "delivery-inputs.sha256"

            # 1. Missing double space
            manifest.write_text("bad_delimiter_single_space path.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertTrue(any("missing double-space" in m for m in res["malformed"]))

            # 2. Invalid SHA-256 (not 64-hex)
            manifest.write_text("not_a_valid_hex_hash  path.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertTrue(any("invalid 64-hex" in m for m in res["malformed"]))

    def test_duplicate_path_detected(self):
        """Duplicate path entries in manifest fail verification."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "delivery-inputs.sha256"
            f = root / "sample.txt"
            f.write_bytes(b"content")
            sha = hashlib.sha256(b"content").hexdigest()

            # Two identical paths
            manifest.write_text(f"{sha}  sample.txt\n{sha}  sample.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertIn("sample.txt", res["duplicates"])

    def test_unsafe_paths_rejected(self):
        """Path traversal sequences ('..') or absolute paths in manifest are rejected."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "delivery-inputs.sha256"
            sha = "0" * 64

            # Traversal
            manifest.write_text(f"{sha}  ../outside.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertTrue(any("traversal" in err for err in res["errors"]))

            # Absolute path
            manifest.write_text(f"{sha}  /root/abs.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertTrue(any("Absolute path" in err for err in res["errors"]))

    def test_missing_and_mismatched_files_detected(self):
        """Missing files and corrupted/modified byte content fail verification."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "delivery-inputs.sha256"
            sha = hashlib.sha256(b"expected_data").hexdigest()

            # Missing file
            manifest.write_text(f"{sha}  nonexistent.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertIn("nonexistent.txt", res["missing"])

            # Mismatched hash
            f = root / "corrupted.txt"
            f.write_bytes(b"actual_data")
            manifest.write_text(f"{sha}  corrupted.txt\n", encoding="utf-8")
            res = VDI.verify_delivery(manifest_path=manifest, root_dir=root, check_git_tracked=False)
            self.assertFalse(res["ok"])
            self.assertTrue(any(p == "corrupted.txt" for p, _, _ in res["mismatches"]))


if __name__ == "__main__":
    unittest.main()
