"""Diagnostic regressions: actual temporary Chroma, immutable references, no relabels."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import diagnose_windows_verification as D
from windows_diagnostic_policy import diagnostic_outcome, rounding_evidence, trace_extra_chunks

GUIDE = "e4375c1cad104b2eb7d027369bd76638"
PAGE = "b1a202c9bb3011da2b24000f20dac9ef"
EXTRAS = [f"{GUIDE}/{PAGE}/{n:03d}" for n in (0, 1)]


def completed_result():
    return {"page": {"checks": {"exact_chunk_ids": True, "count_equals_manifest": True}, "all_pass": True,
                     "model_files_equal_manifest": True, "original_store_unchanged": True, "worker_exit": 0},
            "card": {"passes_existing_vector_threshold": True, "ranking_and_4dp_match": True,
                     "single_query_focus_match": True, "model_files_equal_manifest": True,
                     "original_store_unchanged": True, "stored_count": 29, "manifest_count": 29, "worker_exit": 0}}


def test_completed_diagnostic_failure_is_not_a_crash():
    result = completed_result()
    result["page"]["checks"]["exact_chunk_ids"] = False
    result["page"]["all_pass"] = False
    result["card"]["ranking_and_4dp_match"] = False
    outcome = diagnostic_outcome(result)
    assert outcome["exit_code"] == 2
    assert outcome["status"] == "CHECKS_FAILED"
    assert outcome["execution_errors"] == []
    assert outcome["failed_checks"] == ["page.exact_chunk_ids", "card.ranking_and_4dp_match"]


def test_pass_requires_all_unchanged_existing_gates():
    assert diagnostic_outcome(completed_result())["exit_code"] == 0


@pytest.mark.parametrize("fault", ["child_crash", "store_missing", "source_changed", "missing_check_results", "contradictory_check_results"])
def test_incomplete_or_error_is_exit_three(fault):
    result = completed_result()
    if fault == "child_crash": result["page"]["worker_exit"] = 1
    if fault == "store_missing": result["page"]["BLOCKED"] = "store missing"
    if fault == "source_changed": result["page"]["original_store_unchanged"] = False
    if fault == "missing_check_results": result["page"].pop("checks")
    if fault == "contradictory_check_results": result["page"]["all_pass"] = False
    assert diagnostic_outcome(result)["exit_code"] == 3


def test_single_vs_batch_failure_is_not_hidden():
    result = completed_result()
    result["card"]["single_query_focus_match"] = False
    outcome = diagnostic_outcome(result)
    assert outcome["exit_code"] == 2
    assert "card.single_query_focus_match" in outcome["failed_checks"]


def test_q35_one_float32_distance_ulp_crosses_frozen_rounding_boundary():
    # Reproduction of the arithmetic mechanism, NOT a Windows inference result.
    # Adjacent positive float32 cosine distances either side of 0.65345.
    distance_bits = struct.unpack("I", struct.pack("f", 0.65345))[0]
    d1 = struct.unpack("f", struct.pack("I", distance_bits))[0]
    d2 = struct.unpack("f", struct.pack("I", distance_bits - 1))[0]
    left, right = rounding_evidence(1-d1, 0.3465), rounding_evidence(1-d2, 0.3465)
    assert left["actual_4dp"] == 0.3465 and left["strict_4dp_match"]
    assert right["actual_4dp"] == 0.3466 and not right["strict_4dp_match"]
    assert right["actual_raw"] - left["actual_raw"] == 2 ** -24
    assert left["nominal_upper_decimal_boundary"] == "0.34655"
    assert left["signed_delta_from_upper_boundary"] < 0 < right["signed_delta_from_upper_boundary"]
    assert right["reference_raw_score_available"] is False
    assert float.fromhex(right["actual_hex"]) == right["actual_raw"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_similarity_is_an_execution_error(value):
    with pytest.raises(ValueError): rounding_evidence(value, 0.3465)


def test_extra_ids_trace_to_excluded_capture_not_admitted_duplicate():
    manifest = json.loads((ROOT / "data/page_corpus/manifest.json").read_text(encoding="utf-8"))
    excluded = next(c for c in manifest["cards"] if c["source_id"] == "M2C-18")
    assert excluded["corpus_status"] == "excluded_conflicting_identity"
    capture = ROOT / "captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json"
    data = json.loads(capture.read_text(encoding="utf-8"))["data"]
    assert data["deliverable"]["loio"] == GUIDE
    assert data["deliverable"]["title"] == "Enterprise Services in Financials"
    assert data["currentPage"]["loio"] == PAGE
    snapshot = {"ids": EXTRAS, "documents": ["probe 0", "probe 1"],
                "metadatas": [{"guide_id": GUIDE, "page_id": PAGE}] * 2}
    rows = trace_extra_chunks([], manifest, snapshot)
    assert len(rows) == 2
    assert all(r["classification"] == "UNADMITTED_CAPTURE_PAGE_VECTORS" for r in rows)
    assert all(r["admitted"] is False and r["metadata_identity_matches_id"] for r in rows)
    assert all(r["insertion_time_or_creator_known"] is False for r in rows)
    assert all(not r["duplicate_text_of_admitted_chunk"] for r in rows)
    assert all(r["capture_identity_match_is_not_content_verification"] for r in rows)


def test_text_duplication_is_separate_from_page_admission():
    manifest = {"unused_captures": [{"guide_id": GUIDE, "page_id": PAGE, "file": "probe.json"}]}
    snap = {"ids": [EXTRAS[0]], "documents": ["same body"], "metadatas": [{}]}
    rows = trace_extra_chunks([{"chunk_id": "admitted", "text": "same body"}], manifest, snap)
    assert rows[0]["duplicate_text_of_admitted_chunk"] is True
    assert rows[0]["admitted"] is False
    assert rows[0]["metadata_identity_matches_id"] is False


def test_refuses_overwriting_existing_report_or_corpus_file(tmp_path):
    target = tmp_path / "original.json"
    target.write_bytes(b"original bytes")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_windows_verification.py"),
                           "--out", str(target), "--store-quiesced"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert target.read_bytes() == b"original bytes"
    assert "never overwritten" in proc.stderr
    corpus = ROOT / "data/source_corpus.json"
    before = hashlib.sha256(corpus.read_bytes()).hexdigest()
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_windows_verification.py"),
                           "--out", str(corpus), "--store-quiesced"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert hashlib.sha256(corpus.read_bytes()).hexdigest() == before


def test_real_113_plus_two_store_is_diagnosed_without_repair(tmp_path):
    import build_page_collection as BP
    import chromadb
    import page_chunker as PK
    import page_corpus as PC
    from chromadb.config import Settings
    from chroma_temp import close_systems_under
    records = PC.load_records()
    count, info = PK.make_token_counter()
    assert info["exact"]
    chunks = PK.chunk_corpus(records, PK.STRATEGIES[PK.DEFAULT_STRATEGY], count)
    assert len(chunks) == 113
    original = tmp_path / "original"
    client = chromadb.PersistentClient(path=str(original), settings=Settings(anonymized_telemetry=False))
    manifest = json.loads((ROOT / "data/page_collection_manifest.json").read_text(encoding="utf-8"))
    corpus = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    md = BP.collection_metadata(384, PK.STRATEGIES[PK.DEFAULT_STRATEGY], corpus["corpus_sha256"], BP.chunks_fingerprint(chunks), 113, "synthetic-fixture")
    col = client.create_collection("sap_pages_v1", metadata=md)
    by_doc = {r["doc_id"]: r for r in records}
    # Real Chroma lifecycle, but synthetic vectors: not an embedding quality run.
    col.add(ids=[c["chunk_id"] for c in chunks], documents=[c["text"] for c in chunks],
            metadatas=[BP.chunk_metadata(c, by_doc) for c in chunks], embeddings=[[1.] + [0.] * 383] * len(chunks))
    col.add(ids=EXTRAS, documents=["probe 0", "probe 1"],
            metadatas=[{"guide_id": GUIDE, "page_id": PAGE}] * 2, embeddings=[[1.] + [0.] * 383] * 2)
    close_systems_under(original)
    before = D.hashes(original)
    result = D.investigate(original, "page")
    assert result["worker_exit"] == 0
    assert result["actual_count"] == 115 and result["manifest_count"] == 113
    assert result["missing_ids"] == [] and result["extra_ids"] == EXTRAS
    assert not result["all_pass"]
    assert result["original_store_unchanged"] and D.hashes(original) == before
    assert all(r["classification"] == "UNADMITTED_CAPTURE_PAGE_VECTORS" for r in result["extra_chunk_provenance"])
    complete = completed_result(); complete["page"] = result
    assert diagnostic_outcome(complete)["exit_code"] == 2


def test_timeout_is_reported_and_original_hashes_still_checked(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    (original / "chroma.sqlite3").write_bytes(b"fixture")
    before = D.hashes(original)
    with patch.object(D.subprocess, "run", side_effect=subprocess.TimeoutExpired("child", 180)):
        result = D.investigate(original, "page")
    assert result["worker_exit"] == 3 and result["error"] == "TimeoutExpired"
    assert result["original_store_unchanged"] and D.hashes(original) == before


def test_source_change_is_reported_not_raised_before_evidence_saved(tmp_path):
    original = tmp_path / "original"; original.mkdir()
    (original / "chroma.sqlite3").write_bytes(b"fixture")
    def external_writer(*args, **kwargs):
        (original / "external-writer.txt").write_bytes(b"concurrent operator activity")
        return subprocess.CompletedProcess(args, 1, "", "child failed")
    with patch.object(D.subprocess, "run", side_effect=external_writer):
        result = D.investigate(original, "page")
    assert not result["original_store_unchanged"]
    assert result["original_file_sha256_after"] != result["original_file_sha256"]
    complete = completed_result(); complete["page"] = result
    assert diagnostic_outcome(complete)["exit_code"] == 3


def test_incomplete_snapshot_is_structured_not_failed_integrity(tmp_path):
    with patch.object(D, "investigate", side_effect=PermissionError("denied")):
        result = D.collect_store_diagnostic(tmp_path, "page")
    assert result["original_store_unchanged"] is None
    assert result["error"] == "PermissionError"
    complete = completed_result(); complete["page"] = result
    assert diagnostic_outcome(complete)["exit_code"] == 3


def test_page_builder_rejects_unadmitted_file_before_model_or_existing_store(tmp_path):
    import build_page_collection as BP
    import page_corpus as PC
    records = PC.load_records()
    manifest = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    orphan = copy.deepcopy(records[0])
    orphan.update(doc_id=f"{GUIDE}/{PAGE}", guide_id=GUIDE, page_id=PAGE, source_ids=[])
    corpus = tmp_path / "corpus"
    PC.write_corpus({"records": {r["doc_id"]: r for r in records + [orphan]}, "manifest": manifest, "fetch_plan": {}}, corpus)
    target = tmp_path / "existing-store"; target.mkdir()
    (target / "chroma.sqlite3").write_bytes(b"do not open or replace")
    before = D.hashes(target)
    with patch.object(BP, "load_embedder", side_effect=AssertionError("must fail before loading model")):
        with pytest.raises(SystemExit, match="unadmitted page doc_ids"):
            BP.build(target, "sap_pages_v1", "B_heading_200", True, None, tmp_path / "new-manifest.json", corpus_dir=corpus)
    assert D.hashes(target) == before
    assert not (tmp_path / "new-manifest.json").exists()
    assert (corpus / "pages" / GUIDE / f"{PAGE}.json").is_file()  # no deletion/filtering


def test_current_corpus_passes_read_only_admission_guard():
    import page_corpus as PC
    from page_corpus_integrity import validate_records
    manifest = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert validate_records(PC.load_records(), manifest) == manifest["corpus_sha256"]


@pytest.mark.parametrize("fault", ["duplicate", "text", "identity", "source", "missing", "fingerprint"])
def test_corpus_integrity_guard_rejects_drift_without_rebaseline(fault):
    import page_corpus as PC
    from page_corpus_integrity import validate_records
    records = PC.load_records()
    manifest = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    if fault == "duplicate": records.append(copy.deepcopy(records[0]))
    if fault == "text": records[0]["text"] += " altered"
    if fault == "identity": records[0]["page_id"] = "wrong"
    if fault == "source": records[0]["source_ids"] = ["M2C-18"]
    if fault == "missing": records.pop()
    if fault == "fingerprint": manifest["corpus_sha256"] = "wrong"
    with pytest.raises(ValueError, match="no store was opened or changed"):
        validate_records(records, manifest)
