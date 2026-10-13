"""Portability regressions; native Windows certification still requires Windows."""
import builtins
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import chroma_temp
import platform_metrics
from build_chunk_candidates_portable import LFPath
from diagnose_windows_verification import compare_page_snapshot


def test_missing_resource_reports_unsupported_not_zero():
    original = builtins.__import__
    def no_resource(name, *args, **kwargs):
        if name == "resource":
            raise ImportError("Windows")
        return original(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=no_resource):
        assert platform_metrics.peak_rss_mb() is None
        sys.modules.pop("evaluate_phase9", None)
        assert importlib.import_module("evaluate_phase9")


@pytest.mark.parametrize("platform,value,expected", [("linux", 2048, 2.0), ("darwin", 2097152, 2.0)])
def test_rss_units_are_platform_correct(platform, value, expected):
    resource = types.SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: types.SimpleNamespace(ru_maxrss=value))
    with patch.dict(sys.modules, resource=resource), patch.object(sys, "platform", platform):
        assert platform_metrics.peak_rss_mb() == expected


def test_lf_writer_bypasses_text_mode(tmp_path):
    p = LFPath(tmp_path / "unicode.json")
    with patch.object(Path, "write_text", side_effect=AssertionError("native text writer forbidden")):
        assert p.write_text("é\nline\n", encoding="utf-8") == 7
    assert p.read_bytes() == "é\nline\n".encode()
    with pytest.raises(ValueError):
        p.write_text("x", newline="\r\n")


def test_portable_producer_matches_frozen_json_bytes(tmp_path):
    out = tmp_path / "new"
    subprocess.run([sys.executable, str(ROOT / "scripts/build_chunk_candidates_portable.py"), "--out-dir", str(out)], check=True)
    for p in (ROOT / "data/chunk_candidates").glob("*.json"):
        assert hashlib.sha256((out / p.name).read_bytes()).hexdigest() == hashlib.sha256(p.read_bytes()).hexdigest(), p.name
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/build_chunk_candidates_portable.py"), "--out-dir", str(out)], capture_output=True)
    assert proc.returncode != 0  # refuses overwriting even scratch output


def test_chroma_cleanup_only_stops_owned_persistent_systems(tmp_path):
    events = []
    def system(path, persistent=True):
        return types.SimpleNamespace(settings=types.SimpleNamespace(is_persistent=persistent, persist_directory=str(path)), stop=lambda: events.append(str(path)))
    inside = tmp_path / "temp/store"
    outside = tmp_path / "permanent"
    cache = {"owned": system(inside), "outside": system(outside), "ephemeral": system(inside, False)}
    module = types.SimpleNamespace(SharedSystemClient=types.SimpleNamespace(_identifier_to_system=cache))
    with patch.dict(sys.modules, {"chromadb.api.shared_system_client": module}):
        assert chroma_temp.close_systems_under(tmp_path / "temp") == 1
        assert events == [str(inside)]
        assert set(cache) == {"outside", "ephemeral"}


def test_cleanup_precedes_directory_removal():
    events = []
    with patch.object(chroma_temp, "close_systems_under", side_effect=lambda _: events.append("stop")):
        td = chroma_temp.ChromaTemporaryDirectory()
        path = Path(td.name)
        td.cleanup()
        assert events == ["stop"]
        assert not path.exists()


def test_real_chroma_temp_store_releases_and_reopens(tmp_path):
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared_system_client import SharedSystemClient
    permanent = chromadb.PersistentClient(path=str(tmp_path / "permanent"), settings=Settings(anonymized_telemetry=False))
    keep = permanent.get_or_create_collection("permanent")
    keep.add(ids=["kept"], embeddings=[[1., 0.]])
    with chroma_temp.ChromaTemporaryDirectory() as td:
        client = chromadb.PersistentClient(path=td, settings=Settings(anonymized_telemetry=False))
        col = client.create_collection("temporary")
        col.add(ids=["real"], embeddings=[[1., 0.]])
        assert col.count() == 1
        assert any(Path(s.settings.persist_directory).resolve() == Path(td).resolve()
                   for s in SharedSystemClient._identifier_to_system.values() if s.settings.is_persistent)
    assert not Path(td).exists()
    assert all(Path(s.settings.persist_directory).resolve() != Path(td).resolve()
               for s in SharedSystemClient._identifier_to_system.values() if s.settings.is_persistent)
    assert keep.count() == 1  # unrelated real store remains usable
    chroma_temp.close_systems_under(tmp_path)


def page_fixture():
    import build_page_collection as BP
    chunk = {"chunk_id": "expected", "text": "actual evidence", "content_hash": "hash", "embedding_text": "embed"}
    fp = BP.chunks_fingerprint([chunk])
    manifest = {"vector_count": 1, "corpus_sha256": "corpus", "chunks_fingerprint": fp,
                "embedding_model": "all-MiniLM-L6-v2", "embedding_dimensions": 384,
                "chunk_strategy": "B_heading_200", "collection_name": "sap_pages_v1"}
    md = dict(manifest)
    snapshot = {"ids": ["expected"], "documents": ["actual evidence"],
                "metadatas": [{"content_hash": "hash", "embedding_text_sha256": hashlib.sha256(b"embed").hexdigest()}],
                "collection_metadata": md, "collection_name": "sap_pages_v1"}
    return [chunk], manifest, {"corpus_sha256": "corpus"}, snapshot


def test_diagnostic_correct_store_and_wrong_ids_same_count():
    args = page_fixture()
    assert compare_page_snapshot(*args)["all_pass"]
    args[-1]["ids"] = ["wrong"]
    result = compare_page_snapshot(*args)
    assert result["checks"]["count_equals_manifest"]
    assert not result["all_pass"]
    assert result["missing_ids"] == ["expected"]
    assert result["extra_ids"] == ["wrong"]


def test_diagnostic_115_vs_113_not_repaired_or_hidden():
    args = page_fixture()
    args[-1]["ids"].extend(["extra1", "extra2"])
    args[-1]["documents"].extend(["x", "y"])
    args[-1]["metadatas"].extend([{}, {}])
    result = compare_page_snapshot(*args)
    assert result["actual_count"] == 3 and result["expected_count"] == 1
    assert result["extra_ids"] == ["extra1", "extra2"]
    assert not result["all_pass"]
    assert args[-1]["ids"] == ["expected", "extra1", "extra2"]


@pytest.mark.parametrize("key,value", [("corpus_sha256", "old"), ("chunks_fingerprint", "old"), ("embedding_model", "other"), ("embedding_dimensions", 12), ("chunk_strategy", "other")])
def test_diagnostic_rejects_metadata_drift(key, value):
    args = page_fixture()
    args[-1]["collection_metadata"][key] = value
    assert not compare_page_snapshot(*args)["all_pass"]


def test_diagnostic_requires_explicit_quiescence(tmp_path):
    out = tmp_path / "result.json"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_windows_verification.py"), "--out", str(out)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Stop SURA/Chroma" in proc.stderr
    assert not out.exists()


def test_real_diagnostic_uses_child_copy_and_preserves_wrong_store(tmp_path):
    import chromadb
    from chromadb.config import Settings
    from diagnose_windows_verification import hashes, investigate
    source = tmp_path / "original"
    client = chromadb.PersistentClient(path=str(source), settings=Settings(anonymized_telemetry=False))
    col = client.create_collection("sap_pages_v1", metadata={"embedding_model": "other-model"})
    col.add(ids=["wrong-extra"], documents=["wrong evidence"], embeddings=[[1., 0.]])
    chroma_temp.close_systems_under(source)
    before = hashes(source)
    result = investigate(source, "page")
    assert result["worker_exit"] == 0
    assert result["actual_count"] == 1
    assert result["expected_count"] == 113
    assert result["extra_ids"] == ["wrong-extra"]
    assert not result["all_pass"]
    assert result["original_store_unchanged"]
    assert hashes(source) == before


@pytest.mark.parametrize("name,outputs", [
    ("build_phase8_queries", {"OUT": "data/evaluation/phase8_queries.json"}),
    ("build_phase9_queries", {"OUT": "data/evaluation/phase9_queries.json", "FREEZE": "data/evaluation/phase9_queries_freeze.json"}),
    ("phase9_corpus_audit", {"OUT_JSON": "data/phase9/corpus_status.json", "OUT_MD": "data/phase9/corpus_status.md"}),
])
def test_unsealed_generators_match_frozen_bytes_without_text_mode(name, outputs, tmp_path):
    module = importlib.import_module(name)
    targets = {key: tmp_path / Path(original).name for key, original in outputs.items()}
    # Copy the immutable inputs; no symlinks or writes into the source checkout.
    import shutil
    shutil.copytree(ROOT / "data", tmp_path / "data", ignore=shutil.ignore_patterns("vector_store"))
    shutil.copytree(ROOT / "captured_responses", tmp_path / "captured_responses")
    shutil.copy2(ROOT / "master_data.json", tmp_path / "master_data.json")
    shutil.copytree(ROOT / "sap_pages", tmp_path / "sap_pages")
    with patch.multiple(module, **targets), patch.object(module, "ROOT", tmp_path), patch.object(Path, "write_text", side_effect=AssertionError("native text mode forbidden")):
        assert module.main() == 0
    for key, original in outputs.items():
        assert targets[key].read_bytes() == (ROOT / original).read_bytes()


def test_page_corpus_lf_outputs_match_frozen_records(tmp_path):
    import page_corpus as PC
    payload = {"records": {r["doc_id"]: r for r in PC.load_records()},
               "manifest": json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8")),
               "fetch_plan": json.loads((PC.CORPUS_DIR / "fetch_plan.json").read_text(encoding="utf-8"))}
    with patch.object(Path, "write_text", side_effect=AssertionError("native text mode forbidden")):
        PC.write_corpus(payload, tmp_path)
    for path in (PC.CORPUS_DIR / "pages").glob("*/*.json"):
        assert (tmp_path / path.relative_to(PC.CORPUS_DIR)).read_bytes() == path.read_bytes()
    for name in ("manifest.json", "fetch_plan.json"):
        assert (tmp_path / name).read_bytes() == (PC.CORPUS_DIR / name).read_bytes()


def test_temp_finalizer_also_closes_real_chroma():
    import gc
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared_system_client import SharedSystemClient
    td = chroma_temp.ChromaTemporaryDirectory()
    path = Path(td.name)
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    client.create_collection("finalizer_store")
    del td
    gc.collect()
    assert not path.exists()
    assert all(Path(s.settings.persist_directory).resolve() != path.resolve()
               for s in SharedSystemClient._identifier_to_system.values() if s.settings.is_persistent)
