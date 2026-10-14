"""Probe safety/forensic arithmetic, never a replacement score acceptance policy."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from probe_q35_reproducibility import arithmetic


def test_frozen_vector_arithmetic_is_not_inference():
    result = arithmetic({"query": [1., 0.], "card": [0., 1.]})
    assert result["float32_dot"] == result["float64_cosine"] == 0.
    assert not result["inference_rerun"]


def test_probe_refuses_report_inside_source(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "keep").write_bytes(b"unchanged")
    out = source / "new.json"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/probe_q35_reproducibility.py"),
                           "--card-store", str(source), "--store-quiesced", "--out", str(out)], capture_output=True)
    assert proc.returncode == 2 and not out.exists()
    assert (source / "keep").read_bytes() == b"unchanged"


def test_probe_refuses_existing_report(tmp_path):
    out = tmp_path / "old.json"; out.write_bytes(b"old artifact")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/probe_q35_reproducibility.py"), "--out", str(out)], capture_output=True)
    assert proc.returncode == 2 and out.read_bytes() == b"old artifact"


def test_internal_worker_refuses_unowned_store_before_chroma(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/probe_q35_reproducibility.py"),
                           "--worker", "--card-store", str(source), "--out", str(tmp_path / "result.json")], capture_output=True)
    assert proc.returncode != 0
    assert b"owned scratch copy" in proc.stderr
    assert list(source.iterdir()) == []
