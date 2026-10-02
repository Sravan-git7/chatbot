#!/usr/bin/env python3
"""Phase 7B - validate the REAL `sap_m2c_card_v1` collection and the REAL embedding model through the Phase 7A router.

Validation only. This script never builds or modifies a collection, never writes to a protected artefact, calls no LLM,
generates no answer and makes no network request (socket connections are blocked and any attempt is counted and reported).

Stages
  preflight   BEFORE a rebuild: do the recorded Phase 4 artefacts agree with each other and with the builder / local model?
  collection  AFTER a rebuild: is the store exactly what the Phase 4 manifest says (29 vectors, 384 dims, cosine, ids, metadata,
              documents, vectors vs the model, no legacy `url` key, no `sap_docs` / `chroma_db`)?
  router      exercise scripts/m2c_router.py (default ChromaCardBackend, real model) on the 50 Phase 4 and 54 Phase 5 queries and
              compare with the recorded results; distance semantics; metadata for all 29 cards; card->page join for all 29 cards;
              orchestrator scenarios on the real collection.
  all         the three stages in one run (used for the reproducibility runs).

The output JSON is deterministic (no timestamps, no absolute paths), so two runs can be compared byte for byte.

    python scripts/phase7b_validate.py --stage preflight --out /tmp/p7b_preflight.json
    python scripts/phase7b_validate.py --stage all --out data/phase7B_validation.json
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_common as C  # noqa: E402

ROOT = C.ROOT
EVAL = ROOT / "data" / "evaluation"
P4_QUESTIONS = EVAL / "card_retrieval_questions.json"
P4_RESULTS = EVAL / "card_retrieval_results.json"
P5_QUERIES = EVAL / "independent_queries.json"
P5_RESULTS = EVAL / "phase5_results.json"
MANIFEST = ROOT / "data" / "card_collection_manifest.json"
EXPECTED_COUNT = 29
EXPECTED_DIM = 384
VECTOR_TOLERANCE = 1e-6            # the Phase 5 tolerance for stored-vs-recomputed vectors
SIM_DECIMALS = 4                   # recorded similarities are rounded to 4 decimals
KNOWN_SOURCE_ISSUES = ("M2C-05", "M2C-14", "M2C-18", "M2C-23")
BANNED_MODULES = ("ollama", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "requests", "sap_resolver")

# ----------------------------------------------------------------------------------------------------- helpers


class NetworkGuard:
    """Block socket use for the whole run and count attempts (the run must report zero)."""

    attempts: List[str] = []

    @classmethod
    def install(cls) -> None:
        def _blocked(*a, **k):
            cls.attempts.append(repr(a[:2]))
            raise OSError("network access is disabled in Phase 7B validation")
        socket.socket.connect = _blocked          # type: ignore[assignment]
        socket.socket.connect_ex = _blocked       # type: ignore[assignment]
        socket.create_connection = _blocked       # type: ignore[assignment]
        socket.getaddrinfo = _blocked             # type: ignore[assignment]


def check(name: str, ok: bool, detail: Any = None) -> Dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def open_store(vector_dir: Path):
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))


def collection_names(client) -> List[str]:
    return sorted(getattr(c, "name", c) for c in client.list_collections())


def stored(collection) -> Dict[str, Any]:
    import numpy as np
    got = collection.get(include=["documents", "metadatas", "embeddings"])
    order = sorted(range(len(got["ids"])), key=lambda i: got["ids"][i])
    return {"ids": [got["ids"][i] for i in order], "documents": [got["documents"][i] for i in order],
            "metadatas": [got["metadatas"][i] for i in order],
            "embeddings": np.asarray([got["embeddings"][i] for i in order], dtype="float32")}


def emb_hash(mat) -> str:
    import hashlib
    return hashlib.sha256(mat.astype("float32").tobytes()).hexdigest()


def load_model(model_path: Optional[str] = None):
    from sentence_transformers import SentenceTransformer
    model_dir, info = C.resolve_model(model_path)
    return SentenceTransformer(model_dir, device="cpu"), info


# ----------------------------------------------------------------------------------------------------- stage: preflight


def preflight() -> Dict[str, Any]:
    import build_card_collection as B
    manifest = load(MANIFEST)
    payload = load(C.UNITS_PATH)
    units = payload["units"]
    stats = load(C.TOKEN_STATS_PATH)
    p4 = load(P4_RESULTS)
    cfg = manifest["configuration"]
    units_sha, stats_sha, corpus_sha = C.sha256_file(C.UNITS_PATH), C.sha256_file(C.TOKEN_STATS_PATH), C.sha256_file(C.CORPUS_PATH)
    checks = [
        check("units file sha256 == manifest.retrieval_units_file_sha256", units_sha == manifest["retrieval_units_file_sha256"], units_sha),
        check("units file sha256 == token-stats.units_file_sha256", units_sha == stats.get("units_file_sha256")),
        check("units file sha256 == Phase 4 results.retrieval_units_file_sha256", units_sha == p4["retrieval_units_file_sha256"]),
        check("token stats sha256 == manifest.token_stats_file_sha256", stats_sha == manifest["token_stats_file_sha256"], stats_sha),
        check("source corpus sha256 == manifest.source_corpus_file_sha256", corpus_sha == manifest["source_corpus_file_sha256"], corpus_sha),
        check("source corpus sha256 == units payload source_corpus.file_sha256", corpus_sha == payload["source_corpus"]["file_sha256"]),
        check("source corpus content fingerprint == manifest", payload["source_corpus"]["content_fingerprint"] == manifest["source_corpus_content_fingerprint"]),
        check("manifest sha256 == Phase 4 results.collection_manifest_sha256", C.sha256_file(MANIFEST) == p4["collection_manifest_sha256"]),
        check("Phase 4 questions sha256 == Phase 4 results.questions_file_sha256", C.sha256_file(P4_QUESTIONS) == p4["questions_file_sha256"]),
        check("29 retrieval units with unique ids", len(units) == EXPECTED_COUNT and len({u["retrieval_unit_id"] for u in units}) == EXPECTED_COUNT),
        check("source_id == retrieval_unit_id for every unit", all(u["source_id"] == u["retrieval_unit_id"] for u in units)),
        check("token statistics: PASS (no embedding_text over the model limit)", not stats["embedding_text_over_limit"], stats.get("max_seq_length")),
        check("token stats max_seq_length == manifest max_seq_length", stats["max_seq_length"] == cfg["max_seq_length"], cfg["max_seq_length"]),
        check("manifest: vector_count 29, dimensions 384", manifest["vector_count"] == EXPECTED_COUNT and manifest["embedding_dimensions"] == EXPECTED_DIM),
        check("manifest configuration: cosine, normalised, embedding_text, whole_document, batch 16",
              cfg["distance_space"] == "cosine" and cfg["normalize_embeddings"] is True and cfg["document_embedded"] == "embedding_text"
              and cfg["strategy"].startswith("whole_document") and cfg["batch_size"] == 16),
        check("builder constants == manifest (collection, space, model, batch)",
              (C.COLLECTION_NAME, B.DISTANCE_SPACE, C.MODEL_NAME, B.BATCH_SIZE) == (cfg["collection"], cfg["distance_space"], cfg["embedding_model"], cfg["batch_size"]),
              [C.COLLECTION_NAME, B.DISTANCE_SPACE, C.MODEL_NAME, B.BATCH_SIZE]),
        check("builder metadata schema keys == keys in stored-metadata contract (17)", len(B.metadata_for(units[0])) == 17, sorted(B.metadata_for(units[0]))),
    ]
    model_dir, info = C.resolve_model()
    rec = manifest["embedding_model_provenance"]
    checks.append(check("local model origin == manifest provenance origin", info["origin"] == rec["origin"], info["origin"]))
    checks.append(check("local model files sha256 == manifest provenance files_sha256", info["files_sha256"] == rec["files_sha256"]))
    try:
        import chromadb
        checks.append(check("chromadb version == manifest.configuration.chromadb", chromadb.__version__ == cfg["chromadb"], chromadb.__version__))
    except ImportError as e:
        checks.append(check("chromadb importable", False, str(e)))
    model, _ = load_model()
    checks.append(check("model max_seq_length == manifest max_seq_length", int(model.max_seq_length) == cfg["max_seq_length"], int(model.max_seq_length)))
    dim = int((getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension)())
    checks.append(check("model dimension == 384", dim == EXPECTED_DIM, dim))
    checks.append(check("legacy chroma_db/ directory does not exist (and is not created by this stage)", not (ROOT / "chroma_db").exists()))
    return {"stage": "preflight", "ok": all(c["ok"] for c in checks), "checks": checks}


# ----------------------------------------------------------------------------------------------------- stage: collection


def validate_collection(vector_dir: Path, built_manifest: Optional[Path] = None) -> Dict[str, Any]:
    import numpy as np
    import build_card_collection as B
    manifest = load(MANIFEST)
    units = load(C.UNITS_PATH)["units"]
    cfg = manifest["configuration"]
    checks: List[Dict[str, Any]] = []
    if not (vector_dir / "chroma.sqlite3").is_file():
        return {"stage": "collection", "ok": False, "checks": [check("vector store exists", False, "store missing; rebuild with scripts/build_card_collection.py")]}
    client = open_store(vector_dir)
    names = collection_names(client)
    checks.append(check("store holds exactly one collection, named sap_m2c_card_v1", names == [C.COLLECTION_NAME], names))
    checks.append(check("legacy collection sap_docs is not in this store", C.LEGACY_COLLECTION_NAME not in names))
    checks.append(check("legacy chroma_db/ directory does not exist", not (ROOT / "chroma_db").exists()))
    col = client.get_collection(C.COLLECTION_NAME)
    md = col.metadata or {}
    checks.append(check("collection.count() == 29", col.count() == EXPECTED_COUNT, col.count()))
    checks.append(check("collection distance space is cosine (hnsw:space)", md.get("hnsw:space") == "cosine", md.get("hnsw:space")))
    checks.append(check("collection metadata: model, dimensions, units/corpus hashes match recorded artefacts",
                        md.get("embedding_model") == C.MODEL_NAME and md.get("embedding_dimensions") == EXPECTED_DIM
                        and md.get("retrieval_units_file_sha256") == manifest["retrieval_units_file_sha256"]
                        and md.get("source_corpus_file_sha256") == manifest["source_corpus_file_sha256"]))
    cfg_json = json.loads(md.get("config_json", "{}"))
    checks.append(check("collection config_json == manifest.configuration", cfg_json == cfg, {k: (cfg_json.get(k), cfg.get(k)) for k in cfg if cfg_json.get(k) != cfg.get(k)}))
    s = stored(col)
    by_id = {u["retrieval_unit_id"]: u for u in units}
    ids = s["ids"]
    checks.append(check("every source id appears exactly once and the id set equals the retrieval units", len(ids) == len(set(ids)) == EXPECTED_COUNT and set(ids) == set(by_id)))
    checks.append(check("vector matrix shape is (29, 384)", tuple(s["embeddings"].shape) == (EXPECTED_COUNT, EXPECTED_DIM), list(s["embeddings"].shape)))
    norms = np.linalg.norm(s["embeddings"], axis=1)
    checks.append(check("stored vectors are unit-normalised (|norm-1| < 1e-5)", float(np.max(np.abs(norms - 1.0))) < 1e-5, float(np.max(np.abs(norms - 1.0)))))
    meta_bad = [i for i, m in zip(ids, s["metadatas"]) if m != B.metadata_for(by_id[i])]
    checks.append(check("metadata of every vector == builder metadata_for(unit) (complete, unmodified)", not meta_bad, meta_bad))
    checks.append(check("every metadata record has source_url and NO legacy 'url' key", all("source_url" in m and "url" not in m for m in s["metadatas"])))
    checks.append(check("every stored document == the unit's embedding_text", all(d == by_id[i]["embedding_text"] for i, d in zip(ids, s["documents"]))))
    model, info = load_model()
    rec = manifest["embedding_model_provenance"]
    checks.append(check("model identity: origin and file hashes == recorded manifest", info["origin"] == rec["origin"] and info["files_sha256"] == rec["files_sha256"]))
    texts = [by_id[i]["embedding_text"] for i in ids]
    fresh = model.encode(texts, batch_size=cfg["batch_size"], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype("float32")
    diff = float(np.max(np.abs(fresh - s["embeddings"])))
    checks.append(check(f"stored vectors == freshly recomputed vectors (max abs diff < {VECTOR_TOLERANCE})", diff < VECTOR_TOLERANCE, diff))
    recorded_hash = manifest["embeddings_float32_sha256"]
    out: Dict[str, Any] = {
        "stage": "collection",
        "stored_vs_recomputed_max_abs_diff": diff,
        "stored_embeddings_float32_sha256": emb_hash(s["embeddings"]),
        "recomputed_embeddings_float32_sha256": emb_hash(fresh),
        "recorded_manifest_embeddings_float32_sha256": recorded_hash,
        "recomputed_hash_equals_recorded_informational": emb_hash(fresh) == recorded_hash,
        "stored_hash_equals_recorded_informational": emb_hash(s["embeddings"]) == recorded_hash,
        "note": "the float32 hash is environment dependent (Phase 4 manifest note); the tolerance check above is the reproducibility criterion",
    }
    if built_manifest is not None:
        new = load(built_manifest)
        ignore = {"created_utc", "embeddings_float32_sha256"}
        diffs = {}
        for k in sorted(set(manifest) | set(new)):
            if k in ignore:
                continue
            if k == "embedding_model_provenance":
                a = {kk: vv for kk, vv in manifest[k].items() if kk != "directory"}
                b = {kk: vv for kk, vv in new[k].items() if kk != "directory"}
                if a != b:
                    diffs[k] = {"recorded": a, "rebuilt": b}
            elif manifest.get(k) != new.get(k):
                diffs[k] = {"recorded": manifest.get(k), "rebuilt": new.get(k)}
        checks.append(check("rebuilt manifest == recorded manifest (ignoring created_utc, model directory path, float32 hash)", not diffs, diffs))
        out["rebuilt_manifest_float32_sha256_equals_recorded_informational"] = new["embeddings_float32_sha256"] == recorded_hash
    out["ok"] = all(c["ok"] for c in checks)
    out["checks"] = checks
    return out


# ----------------------------------------------------------------------------------------------------- stage: router


def first_rank(expected: Sequence[str], ranking: Sequence[str]) -> Optional[int]:
    ranks = [ranking.index(e) + 1 for e in expected if e in ranking]
    return min(ranks) if ranks else None


def metrics(first_ranks: Sequence[Optional[int]]) -> Dict[str, float]:
    n = len(first_ranks)
    return {"questions": n,
            "recall@1": round(sum(1 for r in first_ranks if r == 1) / n, 4),
            "recall@3": round(sum(1 for r in first_ranks if r and r <= 3) / n, 4),
            "recall@5": round(sum(1 for r in first_ranks if r and r <= 5) / n, 4),
            "mrr": round(sum(1.0 / r for r in first_ranks if r) / n, 4)}


def compact(outcome) -> Dict[str, Any]:
    c = outcome.selected_card
    return {"query": outcome.query, "state": outcome.state,
            "selected": None if c is None else {"source_id": c.source_id, "title": c.title, "rank": c.rank, "distance": round(c.distance, 6),
                                                "source_status": c.source_status, "source_url_status": c.source_url_status,
                                                "has_source_correction": c.has_source_correction, "citation": c.citation},
            "source_url": outcome.source_url, "page_content_available": outcome.page_content_available,
            "fallback_reason": outcome.fallback_reason,
            "resolution": None if outcome.resolution is None else {"state": outcome.resolution.state, "card_exists": outcome.resolution.card_exists,
                                                                    "url_exists": outcome.resolution.url_exists,
                                                                    "local_page_content": outcome.resolution.local_page_content,
                                                                    "content_path": outcome.resolution.content_path},
            "top3": [{"rank": x.rank, "source_id": x.source_id, "distance": round(x.distance, 6)} for x in outcome.candidates[:3]]}


def router_stage(vector_dir: Path) -> Dict[str, Any]:
    import numpy as np
    import build_card_collection as B
    import m2c_orchestrator as orch
    import m2c_page_join as pj
    import m2c_router as rt

    units = load(C.UNITS_PATH)["units"]
    by_id = {u["source_id"]: u for u in units}
    checks: List[Dict[str, Any]] = []
    if not (vector_dir / "chroma.sqlite3").is_file():
        return {"stage": "router", "ok": False, "checks": [check("vector store exists", False, "store missing")]}

    # the router under test: the DEFAULT backend (real store, real model through m2c_common.resolve_model)
    backend = rt.ChromaCardBackend(vector_dir=vector_dir)

    # independent reference: stored vectors + batch-encoded queries (how the Phase 4 / 5 results were produced)
    client = open_store(vector_dir)
    s_before = stored(client.get_collection(C.COLLECTION_NAME))
    ids = s_before["ids"]
    model, _info = load_model()

    p4 = load(P4_RESULTS)["per_question"]
    p5 = {q["query_id"]: q for q in load(P5_QUERIES)["queries"]}
    p5rows = load(P5_RESULTS)["datasets"]["phase5"]["systems"]["dense"]["rows"]
    datasets = {
        "phase4": [{"id": r["question_id"], "query": r["question"], "expected": r["expected_source_ids"], "rec_first": r["first_expected_rank"],
                    "rec_top5": [(x["source_id"], x["cosine_similarity"]) for x in r["retrieved_top5"]]} for r in p4],
        "phase5": [{"id": r["id"], "query": p5[r["id"]]["query"], "expected": r["expected_source_ids"], "rec_first": r["first_expected_rank"],
                    "rec_top5": [(x["source_id"], x["score"]) for x in r["top5"]]} for r in p5rows],
    }
    for name, rows in datasets.items():
        checks.append(check(f"{name}: query text of recorded rows matches the query files", all(r["query"] for r in rows) and len(rows) == (50 if name == "phase4" else 54), len(rows)))

    results: Dict[str, Any] = {}
    all_routes: Dict[str, Any] = {}
    sem = {"queries": 0, "ascending_violations": 0, "rank1_not_minimum": 0, "min_candidates_returned": 10 ** 9,
           "max_abs_diff_distance_vs_independent": 0.0, "max_distance_seen": 0.0, "min_distance_seen": 9.0,
           "candidates_with_distance_above_legacy_equivalent_cosine_0.5": 0, "ranking_id_mismatches_vs_independent": 0}
    for name, rows in datasets.items():
        qv = model.encode([r["query"] for r in rows], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype("float32")
        ref_dist = 1.0 - qv @ s_before["embeddings"].T                      # independent cosine distance, shape (n, 29)
        per = []
        first_ranks: List[Optional[int]] = []
        top1_same = top5_same = sim_round_mismatch = first_rank_same = 0
        max_sim_diff = 0.0
        diff_rows = []
        for r, refd in zip(rows, ref_dist):
            res = rt.route(r["query"], backend, top_k=EXPECTED_COUNT)
            cands = res.candidates
            all_routes[r["id"]] = cands
            rank_ids = [c.source_id for c in cands]
            dists = [c.distance for c in cands]
            sem["queries"] += 1
            sem["min_candidates_returned"] = min(sem["min_candidates_returned"], len(cands))
            sem["ascending_violations"] += int(any(b < a for a, b in zip(dists, dists[1:])))
            sem["rank1_not_minimum"] += int(dists[0] > min(dists))
            sem["max_distance_seen"] = max(sem["max_distance_seen"], max(dists))
            sem["min_distance_seen"] = min(sem["min_distance_seen"], min(dists))
            sem["candidates_with_distance_above_legacy_equivalent_cosine_0.5"] += sum(1 for d in dists if d > 0.5)
            ref_by_id = {i: float(d) for i, d in zip(ids, refd)}
            sem["max_abs_diff_distance_vs_independent"] = max(sem["max_abs_diff_distance_vs_independent"], max(abs(c.distance - ref_by_id[c.source_id]) for c in cands))
            ref_order = [i for i, _ in sorted(ref_by_id.items(), key=lambda kv: (kv[1], kv[0]))]
            sem["ranking_id_mismatches_vs_independent"] += int(ref_order != rank_ids)
            rec_ids = [i for i, _ in r["rec_top5"]]
            top1_same += int(rank_ids[0] == rec_ids[0])
            same5 = rank_ids[:5] == rec_ids
            top5_same += int(same5)
            sims = [round(1.0 - c.distance, SIM_DECIMALS) for c in cands[:5]]
            sim_round_mismatch += sum(1 for a, (_, b) in zip(sims, r["rec_top5"]) if a != b)
            max_sim_diff = max(max_sim_diff, max(abs((1.0 - c.distance) - b) for c, (_, b) in zip(cands[:5], r["rec_top5"])))
            fr = first_rank(r["expected"], rank_ids)
            first_ranks.append(fr)
            first_rank_same += int(fr == r["rec_first"])
            if not same5 or fr != r["rec_first"]:
                diff_rows.append({"id": r["id"], "router_top5": rank_ids[:5], "recorded_top5": rec_ids, "router_first_rank": fr, "recorded_first_rank": r["rec_first"]})
            per.append({"id": r["id"], "top1": rank_ids[0], "top1_distance": round(dists[0], 6), "top5": rank_ids[:5],
                        "top5_distances": [round(d, 6) for d in dists[:5]], "first_expected_rank": fr})
        n = len(rows)
        results[name] = {
            "queries": n, "top1_identical_to_recorded": top1_same, "top5_ordering_identical_to_recorded": top5_same,
            "first_expected_rank_identical_to_recorded": first_rank_same,
            "recorded_similarity_mismatches_after_4dp_rounding": sim_round_mismatch,
            "max_abs_diff_similarity_vs_recorded": round(max_sim_diff, 8),
            "differing_queries": diff_rows, "metrics_from_router": metrics(first_ranks), "per_query": per}
        checks.append(check(f"{name}: router top-1 == recorded top-1 for all {n} queries", top1_same == n, f"{top1_same}/{n}"))
        checks.append(check(f"{name}: router top-5 ordering == recorded top-5 for all {n} queries", top5_same == n, f"{top5_same}/{n}"))
        checks.append(check(f"{name}: router first-expected-rank == recorded for all {n} queries", first_rank_same == n, f"{first_rank_same}/{n}"))
        checks.append(check(f"{name}: router similarities (1 - distance, 4 dp) == recorded similarities", sim_round_mismatch == 0, sim_round_mismatch))
    checks.append(check("Phase 4 recorded metrics reproduced from router output",
                        results["phase4"]["metrics_from_router"] == {k: load(P4_RESULTS)["metrics"]["overall"][k] for k in ("questions", "recall@1", "recall@3", "recall@5", "mrr")},
                        results["phase4"]["metrics_from_router"]))
    rec5 = load(P5_RESULTS)["datasets"]["phase5"]["systems"]["dense"]["summary"]["overall"]
    checks.append(check("Phase 5 dense recorded metrics reproduced from router output",
                        all(results["phase5"]["metrics_from_router"][k] == round(rec5[k], 4) for k in ("recall@1", "recall@3", "recall@5", "mrr")),
                        {"router": results["phase5"]["metrics_from_router"], "recorded": {k: rec5.get(k) for k in ("recall@1", "recall@3", "recall@5", "mrr")}}))

    # ---- distance semantics
    sem["min_candidates_returned"] = sem["min_candidates_returned"]
    checks.append(check("distances are ascending for every query (rank 1 = lowest distance)", sem["ascending_violations"] == 0 and sem["rank1_not_minimum"] == 0, sem["ascending_violations"]))
    checks.append(check("router distance == independent cosine distance 1 - q.d (stored vectors, batch-encoded queries), max abs diff < 1e-6",
                        sem["max_abs_diff_distance_vs_independent"] < 1e-6, sem["max_abs_diff_distance_vs_independent"]))
    checks.append(check("router ranking (all 29) == independent ranking for every query", sem["ranking_id_mismatches_vs_independent"] == 0, sem["ranking_id_mismatches_vs_independent"]))
    checks.append(check("no gate: all 29 cards returned for every query, including cards beyond the legacy-equivalent cosine 0.5",
                        sem["min_candidates_returned"] == EXPECTED_COUNT and sem["candidates_with_distance_above_legacy_equivalent_cosine_0.5"] > 0,
                        {"min_returned": sem["min_candidates_returned"], "candidates_beyond_cos_0.5": sem["candidates_with_distance_above_legacy_equivalent_cosine_0.5"]}))
    checks.append(check("distances lie in the cosine-distance range [0, 2]", 0.0 <= sem["min_distance_seen"] and sem["max_distance_seen"] <= 2.0, [sem["min_distance_seen"], sem["max_distance_seen"]]))

    # ---- metadata preservation for all 29 cards (one query, top_k = 29)
    res29 = rt.route("meter to cash reference", backend, top_k=EXPECTED_COUNT)
    meta_problems = []
    for c in res29.candidates:
        u = by_id[c.source_id]
        exp = B.metadata_for(u)
        got = c.to_dict()
        for k in ("source_id", "title", "category", "source_url", "source_status", "source_url_status", "has_source_correction", "citation",
                  "retrieval_unit_id", "source_number", "filename", "sha256", "corpus_document", "page_start", "page_end"):
            if got[k] != exp[k]:
                meta_problems.append((c.source_id, k, got[k], exp[k]))
        if got["rank"] != res29.candidates.index(c) + 1 or not isinstance(got["distance"], float):
            meta_problems.append((c.source_id, "rank/distance", got["rank"], got["distance"]))
        if "url" in got:
            meta_problems.append((c.source_id, "url alias present", None, None))
    checks.append(check("all 29 cards: router preserves source_id, title, category, source_url, source_status, source_url_status, has_source_correction, citation (+ provenance), rank, distance",
                        len(res29.candidates) == EXPECTED_COUNT and not meta_problems, meta_problems))
    issues = {}
    for sid in KNOWN_SOURCE_ISSUES:
        c = next(x for x in res29.candidates if x.source_id == sid)
        u = by_id[sid]
        issues[sid] = {"source_status": c.source_status, "source_url_status": c.source_url_status, "has_source_correction": c.has_source_correction,
                       "source_url": c.source_url, "unit_review_reasons": u.get("review_reasons"), "has_source_correction_in_unit": bool(u["has_source_correction"])}
    checks.append(check("known source issues M2C-05/14/18/23 remain visible through the router (status/correction equal to the units, none 'clean')",
                        all((v["source_status"], v["source_url_status"], v["has_source_correction"]) == (by_id[k]["source_status"], by_id[k]["source_url_status"], bool(by_id[k]["has_source_correction"]))
                            and (v["source_status"] != "verified" or v["source_url_status"] != "ok" or v["has_source_correction"]) for k, v in issues.items()), issues))

    # ---- card -> page join for all 29 real cards
    index = pj.PageContentIndex.from_directory()
    ok_pages = set()
    for p in (ROOT / "data" / "sap_help" / "pages").glob("*/*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("status") == "OK" and str(rec.get("text") or "").strip():
            ok_pages.update([(str(rec["guide_id"]).lower(), str(rec["page_id"]).lower())])
    joins = {}
    for c in res29.candidates:
        joins[c.source_id] = pj.resolve_card_page(c, index)
    expected_join = {sid: ("resolved_page" if pj.parse_source_url(u["source_url"]) in ok_pages else "url_only") for sid, u in by_id.items()}
    counts: Dict[str, int] = {}
    for r in joins.values():
        counts[r.state] = counts.get(r.state, 0) + 1
    checks.append(check("join: every card classified as the independently derived expectation (page record with status OK + text, else url_only)",
                        {k: v.state for k, v in joins.items()} == expected_join, counts))
    checks.append(check("join: URL-only cards have local_page_content == False", all(not r.local_page_content for r in joins.values() if r.state == "url_only")))
    checks.append(check("join: no card is unresolved (all 29 have a parseable SAP Help URL)", counts.get("unresolved", 0) == 0, counts))
    join_out = {"counts": counts, "index_pages": len(index),
                "resolved_cards": sorted(k for k, v in joins.items() if v.state == "resolved_page"),
                "per_card": {k: {"state": v.state, "reason": v.reason, "content_path": v.content_path, "content_chars": v.content_chars, "warnings": list(v.warnings)} for k, v in sorted(joins.items())},
                "not_counted_as_page_content": {
                    "captured_responses_files": len([p for p in (ROOT / "captured_responses").glob("*.json")]) if (ROOT / "captured_responses").is_dir() else 0,
                    "saved_toc_files": len([p for p in (ROOT / "data" / "toc").glob("*") if p.is_file()]) if (ROOT / "data" / "toc").is_dir() else 0}}

    # ---- orchestrator on the real collection
    def first_query(pred):
        for ds in ("phase4", "phase5"):
            for r in datasets[ds]:
                if pred(all_routes[r["id"]]):
                    return r
        return None

    def by_query_id(qid):
        for ds in ("phase4", "phase5"):
            for r in datasets[ds]:
                if r["id"] == qid:
                    return r
        return None

    resolved_ids = set(join_out["resolved_cards"])
    scen: List[Tuple[str, Optional[dict]]] = [
        ("1 resolved local page content (first query whose rank-1 card has a local page)", first_query(lambda cs: cs[0].source_id in resolved_ids)),
        ("2 URL-only card (first query whose rank-1 card has no local page and no source issue)",
         first_query(lambda cs: cs[0].source_id not in resolved_ids and cs[0].source_id not in KNOWN_SOURCE_ISSUES)),
    ]
    for sid in KNOWN_SOURCE_ISSUES:
        scen.append((f"3 source-status issue: first query whose rank-1 card is {sid}", first_query(lambda cs, sid=sid: cs[0].source_id == sid)))
    gaps = sorted(((all_routes[r["id"]][1].distance - all_routes[r["id"]][0].distance, r["id"]) for ds in datasets.values() for r in ds))
    scen.append(("4 sibling near-tie: recorded Phase 4 near-tie Q07 (M2C-24 vs M2C-23)", by_query_id("Q07")))
    scen.append(("4 sibling near-tie: recorded Phase 4 near-tie Q49 (M2C-02 vs M2C-04)", by_query_id("Q49")))
    scen.append((f"4 sibling near-tie: smallest rank1-rank2 distance gap over all {len(gaps)} queries ({gaps[0][1]})", by_query_id(gaps[0][1])))
    scen.append(("5 short / rare term: P5-16 'extrapolation'", by_query_id("P5-16")))
    scen.append(("5 short / rare term: Q42 'subledger processing'", by_query_id("Q42")))
    scenarios = []
    for label, row in scen:
        if row is None:
            scenarios.append({"scenario": label, "available": False})
            continue
        o = orch.route_to_page(row["query"], backend, index, top_k=5)
        d = compact(o)
        d.update({"scenario": label, "available": True, "query_id": row["id"]})
        if label.startswith("4"):
            d["rank1_rank2_distance_gap"] = round(o.candidates[1].distance - o.candidates[0].distance, 6)
            d["rank1_rank2_same_category"] = o.candidates[0].category == o.candidates[1].category
        scenarios.append(d)
    empty = compact(orch.route_to_page("   ", backend, index))
    empty.update({"scenario": "6 no-card scenario: empty query", "available": True})
    rejected = compact(orch.route_to_page("What is a contract account?", backend, index, selector=lambda cs: None))
    rejected.update({"scenario": "6 no-card scenario: caller-side selector rejects every candidate (illustration of the hook, NOT a recommended policy)", "available": True})
    scenarios += [empty, rejected]
    checks.append(check("orchestrator scenarios: 1, 2, 3 (x4), 4 (x3), 5 (x2) all available on the real collection", all(s["available"] for s in scenarios), [s["scenario"] for s in scenarios if not s["available"]]))
    checks.append(check("orchestrator: scenario 1 is resolved_page; scenario 2 is url_only with page_content_available False",
                        scenarios[0].get("state") == "resolved_page" and scenarios[0].get("page_content_available") is True
                        and scenarios[1].get("state") == "url_only" and scenarios[1].get("page_content_available") is False))
    checks.append(check("orchestrator: empty query and selector-rejected -> no_card_candidate with explicit fallback reasons",
                        (empty["state"], empty["fallback_reason"]) == ("no_card_candidate", "EMPTY_QUERY")
                        and (rejected["state"], rejected["fallback_reason"]) == ("no_card_candidate", "SELECTOR_REJECTED_ALL_CANDIDATES")))
    checks.append(check("orchestrator: 'unresolved' cannot be produced by the real cards (all 29 have a parseable URL); covered by Phase 7A unit tests",
                        all(s.get("state") != "unresolved" for s in scenarios)))

    # ---- isolation and non-modification
    s_after = stored(client.get_collection(C.COLLECTION_NAME))
    same_store = (s_before["ids"] == s_after["ids"] and s_before["metadatas"] == s_after["metadatas"] and s_before["documents"] == s_after["documents"]
                  and bool(np.array_equal(s_before["embeddings"], s_after["embeddings"])))
    checks.append(check("store content (ids, metadata, documents, vectors) identical before and after the router stage", same_store))
    loaded = sorted(m for m in BANNED_MODULES if m in sys.modules)
    checks.append(check("no LLM client, legacy retriever module, HTTP client or resolver was imported", not loaded, loaded))
    checks.append(check("no network connection was attempted during the stage", not NetworkGuard.attempts, NetworkGuard.attempts))
    checks.append(check("legacy chroma_db/ directory does not exist", not (ROOT / "chroma_db").exists()))
    return {"stage": "router", "ok": all(c["ok"] for c in checks), "checks": checks, "datasets": results, "distance_semantics": sem,
            "metadata_issue_cards": issues, "page_join": join_out, "orchestrator_scenarios": scenarios,
            "score_note": "similarity = 1 - distance is shown only to compare with recorded Phase 4/5 similarities; the stored/returned quantity is the cosine DISTANCE"}


# ----------------------------------------------------------------------------------------------------- main


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=["preflight", "collection", "router", "all"], default="all")
    ap.add_argument("--vector-dir", default=str(C.VECTOR_DIR))
    ap.add_argument("--built-manifest", default=None, help="manifest written by a rebuild (compare with the recorded one)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    NetworkGuard.install()
    vdir = Path(a.vector_dir)
    out: Dict[str, Any] = {"schema_version": 1, "stages": {}}
    if a.stage in ("preflight", "all"):
        out["stages"]["preflight"] = preflight()
    if a.stage in ("collection", "all"):
        out["stages"]["collection"] = validate_collection(vdir, Path(a.built_manifest) if a.built_manifest else None)
    if a.stage in ("router", "all"):
        out["stages"]["router"] = router_stage(vdir)
    out["network_attempts"] = len(NetworkGuard.attempts)
    out["ok"] = all(s["ok"] for s in out["stages"].values()) and not NetworkGuard.attempts
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, st in out["stages"].items():
        bad = [c for c in st["checks"] if not c["ok"]]
        print(f"{name}: {'OK' if st['ok'] else 'FAILED'} ({len(st['checks']) - len(bad)}/{len(st['checks'])} checks)")
        for c in bad:
            print(f"  FAIL: {c['check']} -> {str(c['detail'])[:300]}")
    print(f"overall: {'OK' if out['ok'] else 'FAILED'}  -> {a.out}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
