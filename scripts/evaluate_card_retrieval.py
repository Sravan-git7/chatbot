#!/usr/bin/env python3
"""Phase 4 / stage 7: evaluate retrieval against the NEW collection `sap_m2c_card_v1` with the card-level question set.

Measurable metrics only (no subjective score, no LLM): Recall@1/3/5 (a question is a hit if ANY expected source is in the
top k), MRR (reciprocal rank of the first expected source), plus the mean share of expected sources found (for questions
with several expected cards). Every question's top-5 (source id, title, cosine similarity) is recorded, and the rank of
each expected source over the whole collection (29 cards) is kept.

Failed cases are reported exactly as they came out; nothing is re-tuned, re-worded or re-labelled after the fact.

CONTROL (clearly separated, in memory only, nothing stored): the same questions ranked against embeddings of the
cards' `full_text` (boilerplate included) to show whether excluding the boilerplate from the embedded text mattered.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import COLLECTION_NAME, ROOT, UNITS_PATH, VECTOR_DIR, resolve_model, sha256_file  # noqa: E402

QUESTIONS = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"
RESULTS = ROOT / "data" / "evaluation" / "card_retrieval_results.json"
MANIFEST = ROOT / "data" / "card_collection_manifest.json"
KS = (1, 3, 5)


def metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    out: Dict[str, Any] = {"questions": n}
    if not n:
        return out
    for k in KS:
        out[f"recall@{k}"] = round(sum(1 for r in rows if r["first_expected_rank"] is not None and r["first_expected_rank"] <= k) / n, 4)
        out[f"mean_expected_coverage@{k}"] = round(sum(sum(1 for x in r["expected_ranks"].values() if x <= k) / len(r["expected_ranks"])
                                                       for r in rows) / n, 4)
    out["mrr"] = round(sum(1.0 / r["first_expected_rank"] for r in rows) / n, 4)
    out["hits@1"] = sum(1 for r in rows if r["first_expected_rank"] == 1)
    return out


def rank_questions(questions: Sequence[Dict[str, Any]], ranked: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows = []
    for q in questions:
        order = ranked[q["question_id"]]
        pos = {o["source_id"]: i + 1 for i, o in enumerate(order)}
        er = {sid: pos[sid] for sid in q["expected_source_ids"]}
        first = min(er.values())
        rows.append({
            "question_id": q["question_id"], "question": q["question"], "question_type": q["question_type"], "ambiguous": q["ambiguous"],
            "expected_source_ids": q["expected_source_ids"], "also_relevant_source_ids": q["also_relevant_source_ids"],
            "expected_ranks": er, "first_expected_rank": first,
            "hit@1": first <= 1, "hit@3": first <= 3, "hit@5": first <= 5,
            "top1_is_also_relevant": order[0]["source_id"] in q["also_relevant_source_ids"],
            "retrieved_top5": [{"rank": i + 1, "source_id": o["source_id"], "title": o["title"], "cosine_similarity": o["cosine_similarity"]}
                               for i, o in enumerate(order[:5])],
        })
    return rows


def summarise(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    types = sorted({r["question_type"] for r in rows})
    return {"overall": metrics(rows), "by_question_type": {t: metrics([r for r in rows if r["question_type"] == t]) for t in types},
            "ambiguous_questions_only": metrics([r for r in rows if r["ambiguous"]]),
            "unambiguous_questions_only": metrics([r for r in rows if not r["ambiguous"]])}


def query_collection(collection, model, questions: Sequence[Dict[str, Any]], n_total: int) -> Dict[str, List[Dict[str, Any]]]:
    qv = model.encode([q["question"] for q in questions], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    res = collection.query(query_embeddings=qv.tolist(), n_results=n_total, include=["metadatas", "distances"])
    ranked = {}
    for q, ids, metas, dists in zip(questions, res["ids"], res["metadatas"], res["distances"]):
        ranked[q["question_id"]] = [{"source_id": i, "title": m["title"], "cosine_similarity": round(1.0 - d, 4)}
                                    for i, m, d in zip(ids, metas, dists)]
    return ranked


def control_ranking(model, questions, units, field: str) -> Dict[str, List[Dict[str, Any]]]:
    import numpy as np
    dv = model.encode([u[field] for u in units], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    qv = model.encode([q["question"] for q in questions], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    sims = qv @ dv.T
    ranked = {}
    for q, row in zip(questions, sims):
        order = sorted(range(len(units)), key=lambda i: (-float(row[i]), units[i]["source_id"]))
        ranked[q["question_id"]] = [{"source_id": units[i]["source_id"], "title": units[i]["title"], "cosine_similarity": round(float(row[i]), 4)} for i in order]
    return ranked


def run(units_path: Path, questions_path: Path, vector_dir: Path, collection_name: str, model_path: Optional[str], out: Path,
        manifest_path: Path, control: bool = True) -> Dict[str, Any]:
    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer

    payload = json.loads(units_path.read_text(encoding="utf-8"))
    units = payload["units"]
    qs = json.loads(questions_path.read_text(encoding="utf-8"))["questions"]
    client = chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
    col = client.get_collection(collection_name)
    cm = col.metadata or {}
    units_sha = sha256_file(units_path)
    problems = []
    if cm.get("retrieval_units_file_sha256") != units_sha:
        problems.append("collection was built from a different retrieval_units.json")
    stored = col.get(include=["documents", "metadatas"])
    if sorted(stored["ids"]) != sorted(u["retrieval_unit_id"] for u in units):
        problems.append("collection ids differ from the retrieval units")
    by_doc = dict(zip(stored["ids"], stored["documents"]))
    for u in units:
        if by_doc.get(u["retrieval_unit_id"]) != u["embedding_text"]:
            problems.append(f"{u['retrieval_unit_id']}: stored document differs from embedding_text")
    if problems:
        raise SystemExit("collection is not reproducible from the dataset: " + "; ".join(problems))
    model_dir, model_info = resolve_model(model_path)
    model = SentenceTransformer(model_dir, device="cpu")
    ranked = query_collection(col, model, qs, col.count())
    rows = rank_questions(qs, ranked)
    res: Dict[str, Any] = {
        "collection": collection_name, "vector_count": col.count(), "embedding_model": cm.get("embedding_model"),
        "embedding_dimensions": cm.get("embedding_dimensions"), "distance_space": cm.get("hnsw:space"),
        "retrieval_units_file_sha256": units_sha, "questions_file_sha256": sha256_file(questions_path),
        "collection_manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
        "question_count": len(qs), "metrics": summarise(rows),
        "failed_at_1": [r["question_id"] for r in rows if not r["hit@1"]],
        "failed_at_3": [r["question_id"] for r in rows if not r["hit@3"]],
        "failed_at_5": [r["question_id"] for r in rows if not r["hit@5"]],
        "ambiguous_question_ids": [r["question_id"] for r in rows if r["ambiguous"]],
        "per_question": rows,
    }
    if control:
        crows = rank_questions(qs, control_ranking(model, qs, units, "full_text"))
        res["control_full_text_in_memory"] = {
            "note": "CONTROL ONLY: same model and questions ranked against embeddings of full_text (boilerplate included); nothing stored, not the evaluated collection",
            "metrics": summarise(crows), "failed_at_1": [r["question_id"] for r in crows if not r["hit@1"]],
            "failed_at_3": [r["question_id"] for r in crows if not r["hit@3"]],
            "failed_at_5": [r["question_id"] for r in crows if not r["hit@5"]],
            "first_expected_rank_by_question": {r["question_id"]: r["first_expected_rank"] for r in crows}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--units", default=str(UNITS_PATH))
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--vector-dir", default=str(VECTOR_DIR))
    ap.add_argument("--collection", default=COLLECTION_NAME)
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--no-control", action="store_true")
    a = ap.parse_args(argv)
    r = run(Path(a.units), Path(a.questions), Path(a.vector_dir), a.collection, a.model_path, Path(a.out), Path(a.manifest), not a.no_control)
    m = r["metrics"]["overall"]
    print(f"{r['collection']}: {r['question_count']} questions   Recall@1={m['recall@1']} Recall@3={m['recall@3']} Recall@5={m['recall@5']} MRR={m['mrr']}")
    print(f"failed@1: {r['failed_at_1']}\nfailed@3: {r['failed_at_3']}\nfailed@5: {r['failed_at_5']}")
    if "control_full_text_in_memory" in r:
        c = r["control_full_text_in_memory"]["metrics"]["overall"]
        print(f"control (full_text, in memory): Recall@1={c['recall@1']} Recall@3={c['recall@3']} Recall@5={c['recall@5']} MRR={c['mrr']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
