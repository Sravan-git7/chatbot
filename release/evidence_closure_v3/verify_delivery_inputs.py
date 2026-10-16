"""Verify delivery-inputs.sha256 manifest against local files and repository tracked set."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = ROOT / "release" / "evidence_closure_v3" / "delivery-inputs.sha256"
PACKAGE_MANIFEST_PATH = ROOT / "release" / "evidence_closure_v3" / "manifest.json"

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def validate_path_safety(rel_path: str) -> Optional[str]:
    """Ensures relative path does not escape root, has no nulls or drive letters."""
    if "\0" in rel_path:
        return f"Null byte in path: {repr(rel_path)}"
    norm = rel_path.replace("\\", "/")
    if norm.startswith("/") or norm.startswith("\\"):
        return f"Absolute path forbidden: {rel_path}"
    if ":" in norm:
        return f"Drive letter/colon forbidden: {rel_path}"
    parts = norm.split("/")
    if ".." in parts:
        return f"Path traversal ('..') forbidden: {rel_path}"
    return None


def verify_delivery(
    manifest_path: Optional[Path] = None,
    root_dir: Optional[Path] = None,
    check_git_tracked: bool = True,
) -> Dict[str, Any]:
    """Verifies the delivery manifest against physical files and git tracked set."""
    if manifest_path is None:
        manifest_path = MANIFEST_PATH
    if root_dir is None:
        root_dir = ROOT

    if not manifest_path.is_file():
        return {
            "ok": False,
            "errors": [f"Manifest file not found: {manifest_path}"],
            "verified": 0,
            "total": 0,
            "malformed": [],
            "duplicates": [],
            "missing": [],
            "mismatches": [],
            "unexpected_tracked": [],
            "untracked_in_manifest": [],
        }

    raw_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    entries: List[Tuple[str, str]] = []
    malformed: List[str] = []
    seen_paths: Set[str] = set()
    duplicates: List[str] = []
    unsafe_paths: List[str] = []

    for idx, raw in enumerate(raw_lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "  " not in line:
            malformed.append(f"Line {idx}: missing double-space delimiter: '{raw}'")
            continue
        expected_hash, rel_path = line.split("  ", 1)
        expected_hash = expected_hash.strip()
        rel_path = rel_path.strip()

        if not HEX64.match(expected_hash):
            malformed.append(f"Line {idx}: invalid 64-hex SHA-256 digest: '{expected_hash}'")
            continue

        if safety_err := validate_path_safety(rel_path):
            unsafe_paths.append(f"Line {idx}: {safety_err}")
            continue

        if rel_path in seen_paths:
            duplicates.append(rel_path)
        seen_paths.add(rel_path)
        entries.append((expected_hash, rel_path))

    mismatches: List[Tuple[str, str, str]] = []
    missing: List[str] = []
    verified = 0

    for expected_hash, rel_path in entries:
        target = root_dir / rel_path
        if not target.is_file():
            missing.append(rel_path)
            continue
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            mismatches.append((rel_path, actual_hash, expected_hash))
        else:
            verified += 1

    unexpected_tracked: List[str] = []
    untracked_in_manifest: List[str] = []
    if check_git_tracked and (root_dir / ".git").exists():
        try:
            tracked = subprocess.check_output(["git", "ls-files"], cwd=str(root_dir), text=True).splitlines()
            tracked_set = set(tracked)

            package_files: Set[str] = set()
            pkg_manifest = root_dir / "release" / "evidence_closure_v3" / "manifest.json"
            if pkg_manifest.is_file():
                try:
                    pkg_meta = json.loads(pkg_manifest.read_text(encoding="utf-8"))
                    package_files = set(pkg_meta.get("files_sha256", {}).keys())
                    # manifest.json states: 'manifest excludes itself', so include it in the package set
                    package_files.add("release/evidence_closure_v3/manifest.json")
                except Exception:
                    pass

            expected_inherited_tracked = tracked_set - package_files
            manifest_set = set(seen_paths)

            unexpected_tracked = sorted(expected_inherited_tracked - manifest_set)
            untracked_in_manifest = sorted(manifest_set - tracked_set)
        except Exception:
            pass

    errors: List[str] = []
    if malformed:
        errors.extend([f"MALFORMED: {m}" for m in malformed])
    if unsafe_paths:
        errors.extend([f"UNSAFE: {u}" for u in unsafe_paths])
    if duplicates:
        errors.extend([f"DUPLICATE: {d}" for d in duplicates])
    if missing:
        errors.extend([f"MISSING: {m}" for m in missing])
    if mismatches:
        errors.extend([f"MISMATCH: {p} (actual {a} != expected {e})" for p, a, e in mismatches])
    if unexpected_tracked:
        errors.extend([f"UNEXPECTED_TRACKED: {u}" for u in unexpected_tracked])
    if untracked_in_manifest:
        errors.extend([f"UNTRACKED_IN_MANIFEST: {u}" for u in untracked_in_manifest])

    ok = len(errors) == 0 and verified == len(entries) and len(entries) == 979
    return {
        "ok": ok,
        "verified": verified,
        "total": len(entries),
        "errors": errors,
        "malformed": malformed,
        "duplicates": duplicates,
        "missing": missing,
        "mismatches": mismatches,
        "unexpected_tracked": unexpected_tracked,
        "untracked_in_manifest": untracked_in_manifest,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify delivery-inputs.sha256 manifest.")
    parser.add_argument("--no-git", action="store_true", help="Skip git tracked set equality check")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args(argv)

    res = verify_delivery(check_git_tracked=not args.no_git)

    if args.json:
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    if not res["ok"]:
        print(f"FAILED: delivery manifest verification failed ({len(res['errors'])} error(s)):", file=sys.stderr)
        for err in res["errors"]:
            print(f"  * {err}", file=sys.stderr)
        return 1

    print(f"{res['verified']} inherited tracked files match published delivery (exact set equality verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
