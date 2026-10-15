"""Repair tests use disposable stores only; synthetic vectors are labelled."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import repair_page_store as R
import diagnose_windows_verification as D


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    import chromadb
    from chromadb.config import Settings
    import build_page_collection as BP
    import page_corpus as PC
    import page_extract as PE
    import page_chunker as PK
    from chroma_temp import close_systems_under
    base = tmp_path_factory.mktemp("repair-seed")
    source = base / "source"
    count, info = PK.make_token_counter(); assert info["exact"]
    records = PC.load_records()
    chunks = PK.chunk_corpus(records, PK.STRATEGIES[PK.DEFAULT_STRATEGY], count)
    cap = next(c for c in PC.load_captures() if c.get("numeric_deliverable_id") == "40374490")
    ex = PE.extract_html(cap["body"])
    orphan = {"guide_id": cap["guide_id"], "page_id": cap["page_id"], "doc_id": f"{cap['guide_id']}/{cap['page_id']}",
              "source_ids": [], "source_url": "", "title": ex["title"], "blocks": ex["blocks"], "text": ex["text"], "text_sha256": PC.sha256_text(ex["text"])}
    extras = PK.chunk_page(orphan, PK.STRATEGIES[PK.DEFAULT_STRATEGY], count)
    manifest = R.load(ROOT / "data/page_collection_manifest.json")
    client = chromadb.PersistentClient(path=str(source), settings=Settings(anonymized_telemetry=False))
    col = client.create_collection("sap_pages_v1", metadata=BP.collection_metadata(384, PK.STRATEGIES[PK.DEFAULT_STRATEGY],
                                  manifest["corpus_sha256"], BP.chunks_fingerprint(chunks), 113, "repair-test-fixture"))
    by_doc = {r["doc_id"]: r for r in records + [orphan]}
    all_chunks = chunks + extras
    # Actual Chroma lifecycle/deletion, but no embedding-quality claim for synthetic vectors.
    col.add(ids=[c["chunk_id"] for c in all_chunks], documents=[c["text"] for c in all_chunks],
            metadatas=[BP.chunk_metadata(c, by_doc) for c in all_chunks], embeddings=[[1.] + [0.] * 383] * len(all_chunks))
    close_systems_under(source)
    report = {"page": D.investigate(source, "page")}
    assert report["page"]["extra_ids"] == list(R.APPROVED)
    diagnostic = base / "diagnostic.json"; R.write_new(diagnostic, report)
    return source, diagnostic


def setup_paths(seed, tmp_path):
    source, diagnostic = seed
    local = tmp_path / "source"; shutil.copytree(source, local)
    return local, diagnostic, tmp_path / "backup", tmp_path / "candidate"


def run(paths, hook=lambda phase: None):
    return R.repair(*paths, list(R.APPROVED), True, True, checkpoint=hook)


def test_success_removes_only_approved_records_and_backup_is_exact(seed, tmp_path):
    paths = setup_paths(seed, tmp_path); source, _, backup, output = paths
    original, corpus = R.tree(source), R.inputs()
    receipt = run(paths)
    assert receipt["before_count"] == 115 and receipt["after_count"] == 113
    assert R.tree(source) == original == R.tree(backup / "store")
    assert R.inputs() == corpus
    before, after = R.load(output / "before.json"), R.load(output / "after.json")
    assert set(before["records"]) - set(after["records"]) == set(R.APPROVED)
    assert after["records"] == {k: v for k, v in before["records"].items() if k not in R.APPROVED}
    assert after["collection_metadata"] == before["collection_metadata"]
    assert after["page_integrity"]["all_pass"]
    assert R.verify_candidate(output) == receipt
    assert R.verify_backup(backup)["source_file_sha256"] == original
    with (output / "store/chroma.sqlite3").open("ab") as handle: handle.write(b"later drift")
    with pytest.raises(R.RepairAborted, match="Candidate files changed"): R.verify_candidate(output)
    with (backup / "store/chroma.sqlite3").open("ab") as handle: handle.write(b"later backup drift")
    with pytest.raises(R.RepairAborted, match="Backup files no longer match"): R.verify_backup(backup)


@pytest.mark.parametrize("phase", ["before_delete", "after_delete", "before_publish"])
def test_interruption_keeps_backup_original_and_no_activation(seed, tmp_path, phase):
    paths = setup_paths(seed, tmp_path); original = R.tree(paths[0])
    def interrupt(current):
        if current == phase: raise KeyboardInterrupt("simulated interruption")
    with pytest.raises(KeyboardInterrupt): run(paths, interrupt)
    assert R.tree(paths[0]) == original == R.tree(paths[2] / "store")
    assert (paths[2] / "BACKUP_VERIFIED.json").is_file()
    assert not (paths[3] / "VERIFIED.json").exists()
    assert R.load(paths[3] / "ABORTED.json")["status"] == "ABORTED_DO_NOT_ACTIVATE"
    with pytest.raises(R.RepairAborted, match="already exists"): run(paths)


def test_failed_backup_verification_never_reaches_delete(seed, tmp_path):
    paths = setup_paths(seed, tmp_path); original = R.tree(paths[0])
    def corrupt(phase):
        if phase == "backup_copied": (paths[2] / "store/chroma.sqlite3").write_bytes(b"bad backup")
    with pytest.raises(R.RepairAborted, match="Backup verification failed"): run(paths, corrupt)
    assert R.tree(paths[0]) == original
    assert not (paths[2] / "BACKUP_VERIFIED.json").exists()
    assert not paths[3].exists()


def test_backup_copy_io_error_is_fatal(seed, tmp_path):
    paths = setup_paths(seed, tmp_path); original = R.tree(paths[0])
    with patch.object(R.shutil, "copytree", side_effect=OSError("simulated disk full")):
        with pytest.raises(OSError): run(paths)
    assert R.tree(paths[0]) == original
    assert not (paths[3] / "VERIFIED.json").exists()


@pytest.mark.parametrize("phase", ["before_delete", "after_delete"])
def test_concurrent_source_writer_aborts(seed, tmp_path, phase):
    paths = setup_paths(seed, tmp_path)
    def writer(current):
        if current == phase: (paths[0] / "chroma.sqlite3-wal").write_bytes(b"external writer")
    with pytest.raises(R.RepairAborted, match="Concurrent|sidecar"): run(paths, writer)
    assert not (paths[3] / "VERIFIED.json").exists()
    assert (paths[2] / "BACKUP_VERIFIED.json").exists()


def test_transient_observed_writer_is_sticky_even_after_bytes_restored(seed, tmp_path):
    paths = setup_paths(seed, tmp_path); original = R.tree(paths[0])
    def writer(phase):
        if phase == "before_delete":
            marker = paths[0] / "external-writer"
            marker.write_bytes(b"active"); time.sleep(0.3); marker.unlink()
    with pytest.raises(R.RepairAborted, match="Concurrent"): run(paths, writer)
    assert R.tree(paths[0]) == original
    assert not (paths[3] / "VERIFIED.json").exists()


def test_changed_corpus_guard_aborts_without_touching_real_corpus(seed, tmp_path):
    paths = setup_paths(seed, tmp_path)
    real = R.inputs; marker = tmp_path / "simulated-corpus-input"; marker.write_bytes(b"before")
    def watched_inputs():
        return dict(real(), simulated_input=hashlib.sha256(marker.read_bytes()).hexdigest())
    def change(phase):
        if phase == "before_delete": marker.write_bytes(b"after")
    with patch.object(R, "inputs", side_effect=watched_inputs):
        with pytest.raises(R.RepairAborted, match="corpus|Concurrent"): run(paths, change)
    assert not (paths[3] / "VERIFIED.json").exists()


def test_unexpected_extra_id_in_diagnostic_aborts(seed, tmp_path):
    paths = list(setup_paths(seed, tmp_path)); report = R.load(paths[1])
    report["page"]["extra_ids"].append("unexpected/page/000")
    paths[1] = tmp_path / "changed-diagnostic.json"; R.write_new(paths[1], report)
    with pytest.raises(R.RepairAborted, match="unexpected IDs"): run(paths)
    assert not paths[2].exists() and not paths[3].exists()


def test_stale_diagnostic_source_bytes_aborts(seed, tmp_path):
    paths = setup_paths(seed, tmp_path)
    (paths[0] / "new-file").write_bytes(b"source drift")
    with pytest.raises(R.RepairAborted, match="no longer match"): run(paths)
    assert not paths[2].exists()


def test_post_repair_metadata_tamper_detected(seed, tmp_path):
    paths = setup_paths(seed, tmp_path); original = R.tree(paths[0])
    def tamper(phase):
        if phase == "after_delete":
            import chromadb
            from chromadb.config import Settings
            from chroma_temp import close_systems_under
            stage = paths[3] / "stage"
            client = chromadb.PersistentClient(path=str(stage), settings=Settings(anonymized_telemetry=False))
            col = client.get_collection("sap_pages_v1")
            cid = next(i for i in col.get()["ids"] if i not in R.APPROVED)
            col.update(ids=[cid], metadatas=[{"unexpected_attribute": "tampered"}])
            close_systems_under(stage)
    with pytest.raises(R.RepairAborted, match="Post-repair record"): run(paths, tamper)
    assert R.tree(paths[0]) == original
    assert not (paths[3] / "VERIFIED.json").exists()


def test_repair_refuses_source_under_production_data(tmp_path):
    # This must refuse before reading a diagnostic or opening any store. Requiring
    # the model-dependent seed hid this safety assertion behind tokenizer setup.
    with patch.object(R, "load", side_effect=AssertionError("must refuse before input reads")):
        with pytest.raises(R.RepairAborted, match="production/data"):
            R.repair(ROOT / "data/vector_store/page_collection", tmp_path / "diagnostic.json", tmp_path / "backup", tmp_path / "candidate", R.APPROVED, True, True)
    assert not (tmp_path / "backup").exists() and not (tmp_path / "candidate").exists()


@pytest.mark.parametrize("approvals", [[], list(R.APPROVED[:1]), list(R.APPROVED) + [R.APPROVED[0]], list(R.APPROVED) + ["other"]])
def test_explicit_exact_approval_required(tmp_path, approvals):
    paths = tuple(tmp_path / name for name in ("source", "diagnostic.json", "backup", "candidate"))
    with patch.object(R, "load", side_effect=AssertionError("must refuse before input reads")):
        with pytest.raises(R.RepairAborted, match="two explicit"): R.repair(*paths, approvals, True, True)
    assert all(not path.exists() for path in paths)


def test_cooperating_job_lock_is_not_reclaimed(seed, tmp_path):
    paths = setup_paths(seed, tmp_path)
    lock = paths[0].parent / ("." + paths[0].name + ".sura-repair.lock")
    lock.write_bytes(b"another job")
    with pytest.raises(FileExistsError): run(paths)
    assert lock.read_bytes() == b"another job"


def test_receipt_write_is_atomic_and_no_overwrite(tmp_path):
    target = tmp_path / "receipt.json"
    R.write_new(target, {"valid": True})
    with pytest.raises(FileExistsError): R.write_new(target, {"valid": False})
    assert R.load(target) == {"valid": True}


def test_preexisting_source_corpus_drift_is_rejected(seed, tmp_path):
    paths = setup_paths(seed, tmp_path); real = R.inputs()
    real["data/source_corpus.json"] = "not-the-sealed-digest"
    with patch.object(R, "inputs", return_value=real):
        with pytest.raises(R.RepairAborted, match="Source corpus differs"): run(paths)
    assert not paths[2].exists()


def test_unexpected_extra_record_in_private_stage_aborts(seed, tmp_path):
    paths = setup_paths(seed, tmp_path)
    def contaminate(phase):
        if phase == "before_delete":
            import chromadb
            from chromadb.config import Settings
            from chroma_temp import close_systems_under
            stage = paths[3] / "stage"
            client = chromadb.PersistentClient(path=str(stage), settings=Settings(anonymized_telemetry=False))
            client.get_collection("sap_pages_v1").add(ids=["unexpected/page/999"], documents=["other"], embeddings=[[1.] + [0.] * 383])
            close_systems_under(stage)
    with pytest.raises(R.RepairAborted, match="Stage changed before deletion"): run(paths, contaminate)
    assert not (paths[3] / "VERIFIED.json").exists()


def test_unexpected_collection_metadata_aborts_before_backup(seed, tmp_path):
    paths = list(setup_paths(seed, tmp_path)); report = R.load(paths[1])
    report["page"]["collection_metadata"]["corpus_sha256"] = "changed"
    paths[1] = tmp_path / "changed-report.json"; R.write_new(paths[1], report)
    with pytest.raises(R.RepairAborted, match="collection metadata"): run(paths)
    assert not paths[2].exists()


def test_target_metadata_must_match_diagnostic_exactly(seed, tmp_path):
    paths = list(setup_paths(seed, tmp_path)); original = R.tree(paths[0]); report = R.load(paths[1])
    report["page"]["extra_chunk_provenance"][0]["stored_metadata"]["source_ids"] = "tampered-report"
    paths[1] = tmp_path / "changed-report.json"; R.write_new(paths[1], report)
    with pytest.raises(R.RepairAborted, match="Approved target changed"): run(paths)
    assert R.tree(paths[0]) == original
    assert not (paths[3] / "VERIFIED.json").exists()


def test_approved_capture_is_in_continuously_guarded_inputs():
    key = "captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json"
    assert key in R.inputs()
    assert R.inputs()[key] == hashlib.sha256((ROOT / key).read_bytes()).hexdigest()
