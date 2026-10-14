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
from windows_diagnostic_policy import diagnostic_outcome, rounding_evidence, trace_extra_chunks, enrich_capture_probes

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
    result = {"checks": checks, "all_pass": all(checks.values()), "expected_count": len(expected),
            "manifest_count": manifest["vector_count"], "actual_count": len(actual),
            "extra_ids": sorted(set(actual) - set(expected)), "missing_ids": sorted(set(expected) - set(actual)),
            "changed_documents": changed, "changed_chunk_metadata": bad_meta, "generated_chunks_fingerprint": fp,
            "collection_metadata": md, "ids": sorted(actual)}
    result["extra_chunk_provenance"] = trace_extra_chunks(chunks, corpus, snapshot)
    return result


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
        focus = []
        for row_index, ((qid, query, recorded), actual_ids, distances) in enumerate(zip(rows, got["ids"], got["distances"])):
            if actual_ids != [t[0] for t in recorded]:
                rank_changes.append({"id": qid, "recorded": [t[0] for t in recorded], "actual": actual_ids})
            sims = dict(zip(actual_ids, [1 - d for d in distances]))
            for sid, score in recorded:
                if sid in sims:
                    delta = abs(sims[sid] - score); max_delta = max(max_delta, delta)
                    if round(sims[sid], 4) != score:
                        differences.append({"query_id": qid, "source_id": sid, **rounding_evidence(sims[sid], score)})
                    if name == "phase4" and qid == "Q35" and sid == "M2C-22":
                        single = model.encode([query], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
                        single_res = col.query(query_embeddings=single.tolist(), n_results=col.count(), include=["distances"])
                        single_scores = dict(zip(single_res["ids"][0], [1-d for d in single_res["distances"][0]]))
                        sv = np.asarray(by_id[sid], dtype="float64")
                        qbatch = np.asarray(qvec[row_index], dtype="float64")
                        qsingle = np.asarray(single[0], dtype="float64")
                        cosine = lambda q, v: float(q @ v / (np.linalg.norm(q) * np.linalg.norm(v)))
                        focus.append({"query_id": qid, "source_id": sid, "recorded_rank": 5,
                                      "batch_score": rounding_evidence(sims[sid], score),
                                      "single_score": rounding_evidence(single_scores[sid], score),
                                      "single_rank": single_res["ids"][0].index(sid) + 1,
                                      "batch_rank": actual_ids.index(sid) + 1,
                                      "single_vs_batch_query_max_abs_delta": float(np.max(np.abs(qsingle-qbatch))),
                                      "float64_cosine_batch_query_stored_card": cosine(qbatch, sv),
                                      "float64_cosine_single_query_stored_card": cosine(qsingle, sv),
                                      "float64_cosine_batch_query_fresh_card": cosine(qbatch, fresh[ids.index(sid)].astype("float64")),
                                      "single_query_float32_sha256": hashlib.sha256(single[0].astype("float32").tobytes()).hexdigest(),
                                      "batch_query_float32_sha256": hashlib.sha256(qvec[row_index].astype("float32").tobytes()).hexdigest(),
                                      "single_matches_sealed_router_encoding_shape": True,
                                      "independent_cosine_is_diagnostic_only": True})

        out["datasets"][name] = {"queries": len(rows), "rank_changes": rank_changes,
                                  "rounded_similarity_differences": differences, "max_abs_similarity_delta": max_delta, "focus_scores": focus}
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
        enrich_capture_probes(result["extra_chunk_provenance"], PK.STRATEGIES[manifest["chunk_strategy"]], count)
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
        focused = [f for d in result.get("datasets", {}).values() for f in d.get("focus_scores", [])]
        result["single_query_focus_match"] = len(focused) == 1 and focused[0]["single_score"]["strict_4dp_match"]
        import torch
        result["numerical_backend"] = {"device": "cpu", "torch_threads": torch.get_num_threads(),
                                       "cpu_capability": torch.backends.cpu.get_cpu_capability(),
                                       "mkldnn_enabled": torch.backends.mkldnn.enabled,
                                       "torch_config": torch.__config__.show()}
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
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            result = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"BLOCKED": "diagnostic child failed before writing results"}
            result["worker_exit"] = proc.returncode
            if proc.returncode:
                result["stderr"] = proc.stderr[-10000:]
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            result = {"error": type(exc).__name__, "worker_exit": 3, "BLOCKED": "diagnostic execution incomplete"}
        # No parent Chroma client exists. Child has exited before directory removal.
    after = hashes(store)
    result["original_store_unchanged"] = before == after
    result["original_file_sha256"] = before
    result["store_path"] = str(store.resolve())
    if before != after:
        result["error"] = "Original changed during diagnosis: stop writers and retain the store; do not rebuild"
        result["original_file_sha256_after"] = after
    return result


def collect_store_diagnostic(store, kind):
    try:
        return investigate(store, kind)
    except Exception as exc:
        # An incomplete snapshot/hash/read must never be labelled CHECKS_FAILED
        # or claim the source is unchanged. Retain a structured execution error.
        return {"BLOCKED": "store diagnosis incomplete", "error": type(exc).__name__,
                "store_path": str(store.resolve()), "original_store_unchanged": None}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--page-store", type=Path, default=ROOT / "data/vector_store/page_collection", help="Optional scratch candidate path; does not change runtime configuration")
    ap.add_argument("--card-store", type=Path, default=ROOT / "data/vector_store", help="Optional scratch candidate path; does not change runtime configuration")
    ap.add_argument("--store-quiesced", action="store_true", help="Confirm all SURA/Chroma writers are stopped")
    ap.add_argument("--worker", choices=["page", "card"], help=argparse.SUPPRESS)
    ap.add_argument("--store", type=Path, help=argparse.SUPPRESS)
    a = ap.parse_args()
    # Reports must never replace an existing artifact or live inside a source store.
    protected = [ROOT / "data", a.page_store, a.card_store]
    if a.store:
        protected.append(a.store)
    destination = a.out.resolve()
    if destination.exists() or any(destination == p.resolve() or p.resolve() in destination.parents for p in protected):
        ap.error("Use a NEW report path outside data/ and vector stores; existing files are never overwritten")
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
        result = {"schema_version": 2, "python": sys.version, "platform": sys.platform, "packages": packages,
                  "legacy": {"exists": legacy.exists(), "tracked_files": tracked, "git_ignored": ignored.returncode == 0,
                             "file_sha256": hashes(legacy) if legacy.is_dir() else {}, "current_shipped_runtime_store": False, "legacy_paths_use_it": ["scripts/rag_core.py", "scripts/test_retrieval.py", "scripts/test_search.py"]},
                  "page": collect_store_diagnostic(a.page_store, "page"),
                  "card": collect_store_diagnostic(a.card_store, "card")}
    if not a.worker:
        result["outcome"] = diagnostic_outcome(result)
    a.out.write_bytes((json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"Diagnostic saved: {a.out}. No original store was opened by Chroma or rebuilt.")
    if not a.worker:
        outcome = result["outcome"]
        print(f"{outcome['status']}: exit {outcome['exit_code']}; {len(outcome['failed_checks'])} failed checks; {len(outcome['execution_errors'])} execution errors")
        for check in outcome["failed_checks"]:
            print(f"  FAILED CHECK: {check}")
        return outcome["exit_code"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
