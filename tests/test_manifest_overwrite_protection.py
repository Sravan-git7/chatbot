"""Regression test: building to a staging/temporary vector-store must not alter tracked manifests."""
import json
import pathlib
import hashlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CARD_MANIFEST = ROOT / "data" / "card_collection_manifest.json"
PAGE_MANIFEST = ROOT / "data" / "page_collection_manifest.json"

def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def test_build_to_temp_does_not_overwrite_tracked_manifests(tmp_path):
    # Record current tracked manifests
    before_card_sha = _sha(CARD_MANIFEST)
    before_page_sha = _sha(PAGE_MANIFEST)
    before_card_content = CARD_MANIFEST.read_text()
    before_page_content = PAGE_MANIFEST.read_text()

    # Ensure we have model available; if not, skip (same as other integration tests)
    try:
        import m2c_common as C
        C.resolve_model()
    except FileNotFoundError:
        import pytest
        pytest.skip("model not available")

    # Use ephemeral isolated stores to avoid touching protected data/vector_store
    card_tmp = tmp_path / "card_tmp"
    page_tmp = tmp_path / "page_tmp"
    card_tmp.mkdir()
    page_tmp.mkdir()

    # Build card to temp - should not touch tracked manifest
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_card_collection.py"), "--vector-dir", str(card_tmp), "--rebuild"],
        capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    # Tracked manifest unchanged
    assert _sha(CARD_MANIFEST) == before_card_sha, "tracked card manifest was overwritten by temp build"
    assert CARD_MANIFEST.read_text() == before_card_content
    # Temp manifest created alongside temp store
    assert (card_tmp / "card_collection_manifest.json").is_file()
    alt = json.loads((card_tmp / "card_collection_manifest.json").read_text())
    assert alt["vector_store_dir"] == str(card_tmp) or str(card_tmp) in alt["vector_store_dir"]

    # Build page to temp - should not touch tracked manifest
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_page_collection.py"), "--vector-dir", str(page_tmp), "--rebuild"],
        capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert _sha(PAGE_MANIFEST) == before_page_sha, "tracked page manifest was overwritten by temp build"
    assert PAGE_MANIFEST.read_text() == before_page_content
    assert (page_tmp / "page_collection_manifest.json").is_file()
    alt2 = json.loads((page_tmp / "page_collection_manifest.json").read_text())
    assert str(page_tmp) in alt2["vector_store_dir"]
