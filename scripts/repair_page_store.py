#!/usr/bin/env python3
"""Opt-in OUT-OF-PLACE repair. Source is never opened through Chroma or mutated.

Stop all writers and use an offline disposable copy. A verified byte backup is
made first. Only a private staged candidate loses the two approved records.
Nothing is activated; only an output with VERIFIED.json is a valid candidate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
APPROVED = tuple(f"e4375c1cad104b2eb7d027369bd76638/b1a202c9bb3011da2b24000f20dac9ef/{i:03d}" for i in (0, 1))


class RepairAborted(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def tree(path):
    if not path.is_dir():
        raise RepairAborted(f"Missing directory: {path}")
    result = {}
    for p in sorted(path.rglob("*")):
        if p.is_symlink():
            raise RepairAborted("Symlinks are not accepted in repair inputs")
        if p.is_file():
            result[p.relative_to(path).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def inputs():
    critical = [ROOT / p for p in ("data/source_corpus.json", "data/page_collection_manifest.json", "data/card_collection_manifest.json",
                "data/m2c_page_identity.json", "data/topic_corrections.json", "data/phase7_checkpoint.md",
                "captured_responses/1_40374490_b1a202c9bb3011da2b24000f20dac9ef.json")]
    critical += sorted((ROOT / "data/page_corpus").rglob("*.json"))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in critical}


def write_new(path, value):
    # Publish complete JSON atomically without replacing an existing receipt.
    # Hard-link support is required (NTFS/ext4); unsupported filesystems abort.
    pending = path.with_name(path.name + ".pending")
    with pending.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.link(pending, path)
    pending.unlink()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, reason):
    if not condition:
        raise RepairAborted(reason)


def expected_records():
    import build_page_collection as BP
    import page_corpus as PC
    import page_chunker as PK
    from page_corpus_integrity import validate_records
    records = PC.load_records()
    manifest = load(PC.CORPUS_DIR / "manifest.json")
    validate_records(records, manifest)
    count, info = PK.make_token_counter()
    require(info.get("exact"), "Exact tokenizer required")
    sealed = load(ROOT / "data/page_collection_manifest.json")
    chunks = PK.chunk_corpus(records, PK.STRATEGIES[sealed["chunk_strategy"]], count)
    require(len(chunks) == sealed["vector_count"] == 113, "Unexpected corpus size; reviewed repair scope is 113 + two")
    require(BP.chunks_fingerprint(chunks) == sealed["chunks_fingerprint"], "Source chunks changed")
    require(manifest["corpus_sha256"] == sealed["corpus_sha256"], "Source corpus changed")
    by_doc = {r["doc_id"]: r for r in records}
    return {c["chunk_id"]: {"document_sha256": hashlib.sha256(c["text"].encode()).hexdigest(),
                           "metadata": BP.chunk_metadata(c, by_doc)} for c in chunks}, sealed


def validate_report(report, source_hashes, sealed):
    page = report["page"]
    require(page.get("worker_exit") == 0 and page.get("original_store_unchanged") is True, "Diagnostic was incomplete or source changed")
    require(page.get("original_file_sha256") == source_hashes, "Store bytes no longer match diagnostic; obtain a new offline diagnostic")
    require(page.get("extra_ids") == list(APPROVED) and not page.get("missing_ids"), "Diagnostic contains unexpected IDs")
    require(page.get("actual_count") == 115 and page.get("expected_count") == page.get("manifest_count") == 113, "Unexpected diagnostic counts")
    require(not page.get("changed_documents") and not page.get("changed_chunk_metadata"), "Admitted content drift in diagnostic")
    require(page.get("model_files_equal_manifest") is True, "Embedding provenance mismatch")
    allowed = {"count_equals_manifest", "count_equals_generated_chunks", "exact_chunk_ids", "collection_vector_count_metadata_matches_actual"}
    require(all(v is True for k, v in page["checks"].items() if k not in allowed), "Unapproved failed diagnostic check")
    metadata = page["collection_metadata"]
    for k in ("corpus_sha256", "chunks_fingerprint", "embedding_model", "embedding_dimensions", "vector_count", "chunk_strategy"):
        require(metadata.get(k) == sealed[k], f"Unexpected collection metadata: {k}; repair never rewrites metadata")
    require(metadata.get("hnsw:space") == "cosine", "Unexpected metric")
    traces = {r["chunk_id"]: r for r in page["extra_chunk_provenance"]}
    require(set(traces) == set(APPROVED), "Incomplete/extra provenance")
    for cid in APPROVED:
        r = traces[cid]
        require(r.get("classification") == "UNADMITTED_CAPTURE_PAGE_VECTORS" and r.get("admitted") is False,
                "Target is not confirmed unadmitted")
        require(r.get("duplicate_text_of_admitted_chunk") is False and r.get("metadata_identity_matches_id") is True,
                "Target identity/duplicate status differs")
        probe = r.get("capture_probe", {})
        require(probe.get("stored_document_matches_current_probe") is True and probe.get("source_mapping_assigned") is False,
                "Target capture probe not verified")
        cap = ROOT / r["capture_file"]
        require(ROOT in cap.resolve().parents and hashlib.sha256(cap.read_bytes()).hexdigest() == probe.get("capture_sha256"), "Capture input changed")
    return page, traces


def snapshot(col):
    import numpy as np
    got = col.get(include=["documents", "metadatas", "embeddings"])
    rows = {}
    for cid, doc, md, vec in zip(got["ids"], got["documents"], got["metadatas"], got["embeddings"]):
        vector = np.asarray(vec, dtype="float32")
        require(vector.shape == (384,) and np.isfinite(vector).all(), "Invalid stored vector")
        rows[cid] = {"document_sha256": hashlib.sha256(doc.encode()).hexdigest(), "metadata": md,
                     "embedding_float32_sha256": hashlib.sha256(vector.tobytes()).hexdigest()}
    require(len(rows) == col.count(), "Incomplete collection snapshot")
    return {"collection_metadata": dict(col.metadata or {}), "records": rows, "count": len(rows)}


def worker(mode, store, out):
    import chromadb
    from chromadb.config import Settings
    # Internal workers can only open a private owned candidate, not any source.
    require(store.name == "stage" and (store.parent / "OWNED.json").is_file(), "Not an owned repair stage")
    client = chromadb.PersistentClient(path=str(store), settings=Settings(anonymized_telemetry=False))
    require([c.name for c in client.list_collections()] == ["sap_pages_v1"], "Unexpected collections")
    col = client.get_collection("sap_pages_v1")
    if mode == "delete":
        authorized = load(store.parent / "before.json")
        require(snapshot(col) == {k: authorized[k] for k in ("records", "count", "collection_metadata")}, "Stage changed before deletion")
        col.delete(ids=list(APPROVED))  # ONLY mutation, ONLY in the private candidate.
    result = snapshot(col)
    if mode in ("audit", "post"):
        from diagnose_windows_verification import worker as diagnose
        result["page_integrity"] = diagnose(store, "page")
    write_new(out, result)


def child(mode, stage, out):
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode, "--stage", str(stage), "--worker-out", str(out)],
                          capture_output=True, text=True, timeout=180)
    require(proc.returncode == 0, f"Repair child {mode} failed: {proc.stderr[-3000:]}")
    return load(out)


class SourceGuard:
    def __init__(self, source, baseline, corpus):
        self.source, self.baseline, self.corpus = source, baseline, corpus
        self.stop = threading.Event()
        self.failed = None

    def check(self):
        require(not self.failed, f"Concurrent activity detected: {self.failed}")
        require(not any((self.source / ("chroma.sqlite3" + suffix)).exists() for suffix in ("-wal", "-shm", "-journal")),
                "SQLite sidecar present; offline/quiesced copy required")
        require(tree(self.source) == self.baseline, "Concurrent writer or source-store drift detected")
        require(inputs() == self.corpus, "Source corpus/checkpoint inputs changed during repair")

    def watch(self):
        while not self.stop.wait(0.1):
            try:
                self.check()
            except Exception as exc:
                self.failed = str(exc)
                return


def repair(source, diagnostic, backup, output, approvals, quiesced, disposable_copy, checkpoint=lambda phase: None):
    source, diagnostic, backup, output = [Path(p).resolve() for p in (source, diagnostic, backup, output)]
    require(quiesced and disposable_copy, "Explicit offline disposable-copy acknowledgement required")
    protected = ROOT / "data"
    for p in (source, backup, output):
        require(p != protected and protected not in p.parents, "Refusing repository production/data paths; use disposable directories outside data/")
    require(tuple(sorted(approvals)) == APPROVED, "Exactly the two explicit approved IDs are required, once each")
    require(source.is_dir() and not backup.exists() and not output.exists(), "Source missing or backup/output already exists")
    for a, b in ((source, backup), (source, output), (backup, output)):
        require(a != b and a not in b.parents and b not in a.parents, "Source/backup/candidate trees must be disjoint")
    lock = source.parent / ("." + source.name + ".sura-repair.lock")
    # A surviving lock after a hard kill requires manual review, never auto-reclaim.
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid())); handle.flush(); os.fsync(handle.fileno())
    guard = None
    try:
        baseline, corpus = tree(source), inputs()
        card_manifest = load(ROOT / "data/card_collection_manifest.json")
        require(corpus["data/source_corpus.json"] == card_manifest["source_corpus_file_sha256"], "Source corpus differs from sealed card manifest")
        expected, sealed = expected_records()
        page, traces = validate_report(load(diagnostic), baseline, sealed)
        report_hash = hashlib.sha256(diagnostic.read_bytes()).hexdigest()
        guard = SourceGuard(source, baseline, corpus); guard.check()
        thread = threading.Thread(target=guard.watch, daemon=True); thread.start()
        backup.mkdir(parents=True)
        shutil.copytree(source, backup / "store")
        checkpoint("backup_copied")
        guard.check()
        require(tree(backup / "store") == baseline, "Backup verification failed")
        write_new(backup / "BACKUP_VERIFIED.json", {"source_file_sha256": baseline, "inputs_sha256": corpus, "diagnostic_sha256": report_hash})
        output.mkdir(parents=True)
        write_new(output / "OWNED.json", {"source": str(source), "backup": str(backup), "approved_ids": list(APPROVED)})
        stage = output / "stage"
        shutil.copytree(backup / "store", stage)
        require(tree(stage) == baseline, "Staging copy differs from verified backup")
        before = child("audit", stage, output / "before.json")
        require(set(before["records"]) == set(expected) | set(APPROVED), "Unexpected stage IDs")
        require(before["collection_metadata"] == page["collection_metadata"], "Collection metadata changed since diagnostic")
        for cid, exp in expected.items():
            row = before["records"][cid]
            require(row["document_sha256"] == exp["document_sha256"] and row["metadata"] == exp["metadata"], f"Admitted record differs from corpus: {cid}")
        fresh_traces = {r["chunk_id"]: r for r in before["page_integrity"]["extra_chunk_provenance"]}
        require(set(fresh_traces) == set(APPROVED), "Independent audit found unexpected orphan records")
        for cid in APPROVED:
            fresh = fresh_traces[cid]
            require(fresh.get("classification") == "UNADMITTED_CAPTURE_PAGE_VECTORS" and fresh.get("duplicate_text_of_admitted_chunk") is False
                    and fresh.get("capture_probe", {}).get("stored_document_matches_current_probe") is True,
                    "Independent capture comparison failed")
            row, trace = before["records"][cid], traces[cid]
            require(row["document_sha256"] == trace["stored_document_sha256"] and row["metadata"] == trace["stored_metadata"], "Approved target changed since diagnostic")
        checkpoint("before_delete"); guard.check()
        child("delete", stage, output / "delete.json")
        checkpoint("after_delete"); guard.check()
        after = child("post", stage, output / "after.json")
        require(after["records"] == {cid: row for cid, row in before["records"].items() if cid not in APPROVED}, "Post-repair record/document/metadata/vector drift")
        require(after["count"] == 113 and after["collection_metadata"] == before["collection_metadata"], "Post-repair count/collection metadata mismatch")
        require(after["page_integrity"].get("all_pass") is True and after["page_integrity"].get("model_files_equal_manifest") is True,
                "Post-repair integrity diagnostic failed")
        checkpoint("before_publish"); guard.check()
        require(tree(backup / "store") == baseline, "Verified backup changed")
        require(hashlib.sha256(diagnostic.read_bytes()).hexdigest() == report_hash, "Diagnostic artifact changed")
        stage.rename(output / "store")
        receipt = {"status": "VERIFIED_CANDIDATE_NOT_ACTIVATED", "before_count": before["count"], "after_count": after["count"],
                   "removed_ids": list(APPROVED), "remaining_records_unchanged": True, "collection_metadata_unchanged": True,
                   "before_snapshot_sha256": digest(before), "after_snapshot_sha256": digest(after), "after_records_sha256": digest(after["records"]),
                   "candidate_file_sha256": tree(output / "store"), "backup_file_sha256": baseline,
                   "inputs_sha256": corpus, "diagnostic_sha256": report_hash, "source_store_unchanged": True}
        guard.check()
        write_new(output / "VERIFIED.json", receipt)
        return receipt
    except BaseException as exc:
        if output.is_dir() and not (output / "VERIFIED.json").exists():
            write_new(output / "ABORTED.json", {"status": "ABORTED_DO_NOT_ACTIVATE", "error_type": type(exc).__name__})
        raise
    finally:
        if guard:
            guard.stop.set()
            if 'thread' in locals(): thread.join(timeout=5)
        lock.unlink()


def verify_backup(backup):
    backup = Path(backup).resolve()
    receipt = load(backup / "BACKUP_VERIFIED.json")
    require(tree(backup / "store") == receipt["source_file_sha256"], "Backup files no longer match verified snapshot")
    return receipt


def verify_candidate(output):
    output = Path(output).resolve()
    receipt = load(output / "VERIFIED.json")
    require(receipt["status"] == "VERIFIED_CANDIDATE_NOT_ACTIVATED", "Not a verified candidate")
    require(tree(output / "store") == receipt["candidate_file_sha256"], "Candidate files changed since verification")
    require(digest(load(output / "before.json")) == receipt["before_snapshot_sha256"], "Before evidence changed")
    require(digest(load(output / "after.json")) == receipt["after_snapshot_sha256"], "After evidence changed")
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify-backup", type=Path, help="Read-only verification before any rollback copy")
    ap.add_argument("--verify-candidate", type=Path, help="Read-only byte/evidence verification of a published candidate")
    ap.add_argument("--source-store", type=Path)
    ap.add_argument("--diagnostic", type=Path)
    ap.add_argument("--backup-dir", type=Path)
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--approve-id", action="append", default=[])
    ap.add_argument("--store-quiesced", action="store_true")
    ap.add_argument("--disposable-copy", action="store_true")
    ap.add_argument("--worker", choices=["audit", "delete", "post"], help=argparse.SUPPRESS)
    ap.add_argument("--stage", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--worker-out", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.verify_backup:
        try:
            verify_backup(args.verify_backup)
        except Exception as exc:
            print(f"INVALID BACKUP: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
        print("Verified backup bytes; no restore performed")
        return 0
    if args.verify_candidate:
        try:
            verify_candidate(args.verify_candidate)
        except Exception as exc:
            print(f"INVALID CANDIDATE: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
        print("Verified candidate bytes and evidence; NOT activated")
        return 0
    if args.worker:
        worker(args.worker, args.stage, args.worker_out)
        return 0
    if not all((args.source_store, args.diagnostic, args.backup_dir, args.output_dir)):
        ap.error("source-store, diagnostic, backup-dir and output-dir required")
    try:
        receipt = repair(args.source_store, args.diagnostic, args.backup_dir, args.output_dir, args.approve_id, args.store_quiesced, args.disposable_copy)
    except Exception as exc:
        print(f"ABORTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
