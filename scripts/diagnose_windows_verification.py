#!/usr/bin/env python3
"""Non-destructive store/numerical investigation. Stop SURA before --store-quiesced.

Chroma is opened ONLY in an offline scratch copy, in a child process. The child
exits before cleanup (including on Windows). Originals are hashed before/after.
No rebuild, delete_collection, label changes or tolerance changes are performed.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def compare_page_snapshot(chunks, manifest, corpus, snapshot):
    import build_page_collection as BP
    expected = {c["chunk_id"]: c for c in chunks}
    actual = dict(zip(snapshot["ids"], snapshot["documents"]))
    md = snapshot["collection_metadata"]
    fp = BP.chunks_fingerprint(chunks)
    checks = {
        "count_equals_manifest": len(actual) == manifest["vector_count"],
        "count_equals_generated_chunks": len(actual) == len(expected),
        "exact_chunk_ids": set(actual) == set(expected),
        "manifest_corpus_equals_current": manifest["corpus_sha256"] == corpus["corpus_sha256"],
        "collection_corpus_equals_current": md.get("corpus_sha256") == corpus["corpus_sha256"],
        "manifest_chunks_fingerprint_equals_current": manifest["chunks_fingerprint"] == fp,
        "collection_chunks_fingerprint_equals_current": md.get("chunks_fingerprint") == fp,
        "embedding_model_equals_manifest": md.get("embedding_model") == manifest["embedding_model"],
        "collection_dimensions_equal_manifest": md.get("embedding_dimensions") == manifest["embedding_dimensions"],
        "collection_strategy_equals_manifest": md.get("chunk_strategy") == manifest["chunk_strategy"],
        "collection_name_equals_manifest": snapshot["collection_name"] == manifest["collection_name"],
    }
    changed = [cid for cid in sorted(set(actual) & set(expected)) if actual[cid] != expected[cid]["text"]]
    checks["documents_equal_current_chunks"] = not changed
    metas = dict(zip(snapshot["ids"], snapshot["metadatas"]))
    bad_meta = [cid for cid in sorted(set(actual) & set(expected))
                if (metas[cid] or {}).get("content_hash") != expected[cid]["content_hash"]
                or (metas[cid] or {}).get("embedding_text_sha256") != hashlib.sha256(expected[cid]["embedding_text"].encode()).hexdigest()]
    checks["chunk_metadata_hashes_equal_current"] = not bad_meta
    return {"checks": checks, "all_pass": all(checks.values()), "expected_count": len(expected),
            "manifest_count": manifest["vector_count"], "actual_count": len(actual),
            "extra_ids": sorted(set(actual) - set(expected)), "missing_ids": sorted(set(expected) - set(actual)),
            "changed_documents": changed, "changed_chunk_metadata": bad_meta, "generated_chunks_fingerprint": fp,
            "collection_metadata": md, "ids": sorted(actual)}


def numerical_diagnostics(col, model, units):
    import numpy as np
    stored = col.get(include=["embeddings", "documents"])
    by_id = dict(zip(stored["ids"], stored["embeddings"]))
    ids = [u["source_id"] for u in units]
    missing = sorted(set(ids) - set(by_id))
    if missing:
        return {"BLOCKED": "missing card IDs", "missing_ids": missing}
    matrix = np.asarray([by_id[i] for i in ids], dtype="float32")
    fresh = model.encode([u["embedding_text"] for u in units], batch_size=16,
                         normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype("float32")
    diff = np.abs(matrix - fresh)
    out = {"max_abs_vector_delta": float(diff.max()), "mean_abs_vector_delta": float(diff.mean()),
           "existing_phase7b_vector_threshold": 1e-6, "passes_existing_vector_threshold": bool(diff.max() <= 1e-6),
           "stored_float32_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
           "fresh_float32_sha256": hashlib.sha256(fresh.tobytes()).hexdigest(), "datasets": {}}
    p4 = json.loads((ROOT / "data/evaluation/card_retrieval_results.json").read_text(encoding="utf-8"))
    p5 = json.loads((ROOT / "data/evaluation/phase5_results.json").read_text(encoding="utf-8"))
    datasets = {
        "phase4": [(r["question_id"], r["question"], [(t["source_id"], t["cosine_similarity"]) for t in r["retrieved_top5"]]) for r in p4["per_question"]],
        "phase5": [(r["id"], r["query"], [(t["source_id"], t["score"]) for t in r["top5"]]) for r in p5["datasets"]["phase5"]["systems"]["dense"]["rows"]],
    }
    for name, rows in datasets.items():
        qvec = model.encode([r[1] for r in rows], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        got = col.query(query_embeddings=qvec.tolist(), n_results=5, include=["distances"])
        differences = []; rank_changes = []; max_delta = 0.0
        for (qid, _, recorded), actual_ids, distances in zip(rows, got["ids"], got["distances"]):
            if actual_ids != [t[0] for t in recorded]:
                rank_changes.append({"id": qid, "recorded": [t[0] for t in recorded], "actual": actual_ids})
            sims = dict(zip(actual_ids, [1 - d for d in distances]))
            for sid, score in recorded:
                if sid in sims:
                    delta = abs(sims[sid] - score); max_delta = max(max_delta, delta)
                    if round(sims[sid], 4) != score:
                        differences.append({"query_id": qid, "source_id": sid, "recorded_4dp": score,
                                            "actual_raw": sims[sid], "actual_4dp": round(sims[sid], 4), "delta": delta,
                                            "distance_to_recorded_rounding_boundary": min(abs(sims[sid] - (score - 0.00005)), abs(sims[sid] - (score + 0.00005)))})
        out["datasets"][name] = {"queries": len(rows), "rank_changes": rank_changes,
                                  "rounded_similarity_differences": differences, "max_abs_similarity_delta": max_delta}
    return out


def worker(store, kind):
    import chromadb
    from chromadb.config import Settings
    import m2c_common as C
    model_dir, info = C.resolve_model()
    client = chromadb.PersistentClient(path=str(store), settings=Settings(anonymized_telemetry=False))
    names = [c.name for c in client.list_collections()]
    name = "sap_pages_v1" if kind == "page" else C.COLLECTION_NAME
    if name not in names:
        return {"BLOCKED": "expected collection absent", "collections": names}
    col = client.get_collection(name)
    if kind == "page":
        import page_corpus as PC
        import page_chunker as PK
        manifest = json.loads((ROOT / "data/page_collection_manifest.json").read_text(encoding="utf-8"))
        corpus = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
        count, tokenizer = PK.make_token_counter(model_dir)
        if not tokenizer.get("exact"):
            raise RuntimeError("Exact tokenizer unavailable; no approximate chunk comparison permitted")
        records = PC.load_records()
        chunks = PK.chunk_corpus(records, PK.STRATEGIES[manifest["chunk_strategy"]], count)
        got = col.get(include=["documents", "metadatas"])
        got.update(collection_metadata=dict(col.metadata or {}), collection_name=col.name)
        result = compare_page_snapshot(chunks, manifest, corpus, got)
        text_hashes = {r["doc_id"]: hashlib.sha256(r["text"].encode("utf-8")).hexdigest() for r in records}
        computed_corpus = hashlib.sha256("\n".join(f"{d} {text_hashes[d]}" for d in sorted(text_hashes)).encode("utf-8")).hexdigest()
        result["checks"].update(
            actual_page_text_hashes_match_records=all(text_hashes[r["doc_id"]] == r["text_sha256"] for r in records),
            actual_page_text_fingerprint_matches_corpus=computed_corpus == corpus["corpus_sha256"],
            actual_page_ids_match_manifest=sorted(text_hashes) == manifest["page_doc_ids"],
            collection_vector_count_metadata_matches_actual=(col.metadata or {}).get("vector_count") == col.count(),
        )
        result["all_pass"] = all(result["checks"].values())
        result["computed_corpus_sha256"] = computed_corpus
        result["model_files_equal_manifest"] = info["files_sha256"] == manifest["embedding_model_provenance"]["files_sha256"]
    else:
        from sentence_transformers import SentenceTransformer
        units = json.loads(C.UNITS_PATH.read_text(encoding="utf-8"))["units"]
        result = numerical_diagnostics(col, SentenceTransformer(model_dir, device="cpu"), units)
        result["collection_metadata"] = dict(col.metadata or {})
        manifest = json.loads((ROOT / "data/card_collection_manifest.json").read_text(encoding="utf-8"))
        result["model_files_equal_manifest"] = info["files_sha256"] == manifest["embedding_model_provenance"]["files_sha256"]
        result["stored_count"] = col.count()
        result["manifest_count"] = manifest["vector_count"]
        result["ranking_and_4dp_match"] = all(not d["rank_changes"] and not d["rounded_similarity_differences"] for d in result.get("datasets", {}).values())
    result["model"] = info
    result["collections"] = names
    return result


def investigate(store, kind):
    if not (store / "chroma.sqlite3").is_file():
        return {"BLOCKED": "store missing", "store_path": str(store)}
    before = hashes(store)
    # The operator must stop writers before copying. A copy is never a migration.
    with tempfile.TemporaryDirectory(prefix="SURA-store-diagnostic-") as td:
        copy = Path(td) / "store"
        shutil.copytree(store, copy)
        target = Path(td) / (kind + "-worker.json")
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", kind, "--store", str(copy), "--out", str(target)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        result = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"BLOCKED": "diagnostic child failed"}
        result["worker_exit"] = proc.returncode
        if proc.returncode:
            result["stderr"] = proc.stderr[-10000:]
        # No parent Chroma client exists. Child has exited before directory removal.
    after = hashes(store)
    result["original_store_unchanged"] = before == after
    result["original_file_sha256"] = before
    result["store_path"] = str(store.resolve())
    if before != after:
        raise RuntimeError("Original changed during diagnosis: stop writers and retain the store; do not rebuild")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--page-store", type=Path, default=ROOT / "data/vector_store/page_collection", help="Optional scratch candidate path; does not change runtime configuration")
    ap.add_argument("--card-store", type=Path, default=ROOT / "data/vector_store", help="Optional scratch candidate path; does not change runtime configuration")
    ap.add_argument("--store-quiesced", action="store_true", help="Confirm all SURA/Chroma writers are stopped")
    ap.add_argument("--worker", choices=["page", "card"], help=argparse.SUPPRESS)
    ap.add_argument("--store", type=Path, help=argparse.SUPPRESS)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.worker:
        result = worker(a.store, a.worker)
    else:
        if not a.store_quiesced:
            ap.error("Stop SURA/Chroma processes first, then pass --store-quiesced. No store was opened.")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        packages = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
        legacy = ROOT / "chroma_db"
        tracked = subprocess.check_output(["git", "ls-files", "--", "chroma_db"], cwd=ROOT, text=True).splitlines()
        ignored = subprocess.run(["git", "check-ignore", "chroma_db/"], cwd=ROOT, capture_output=True, text=True)
        result = {"schema_version": 1, "python": sys.version, "platform": sys.platform, "packages": packages,
                  "legacy": {"exists": legacy.exists(), "tracked_files": tracked, "git_ignored": ignored.returncode == 0,
                             "file_sha256": hashes(legacy) if legacy.is_dir() else {}, "current_shipped_runtime_store": False, "legacy_paths_use_it": ["scripts/rag_core.py", "scripts/test_retrieval.py", "scripts/test_search.py"]},
                  "page": investigate(a.page_store, "page"),
                  "card": investigate(a.card_store, "card")}
    a.out.write_bytes((json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"Diagnostic saved: {a.out}. No original store was opened by Chroma or rebuilt.")
    if not a.worker:
        page, card = result["page"], result["card"]
        return 0 if (page.get("all_pass") and page.get("model_files_equal_manifest") and not card.get("BLOCKED")
                     and not page.get("worker_exit") and not card.get("worker_exit")
                     and card.get("passes_existing_vector_threshold") and card.get("ranking_and_4dp_match")
                     and card.get("model_files_equal_manifest") and card.get("stored_count") == card.get("manifest_count")) else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
