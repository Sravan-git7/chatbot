#!/usr/bin/env python3
"""Phase 5B-5E: robustness evaluation of the Phase-4 dense retriever on the independent query set, failure analysis,
a small controlled dense/BM25/hybrid experiment, and a tokenizer investigation. Evidence only: nothing is integrated.

Protected baseline (read-only): the collection `sap_m2c_card_v1` is queried through a COPY of its store, the Phase-4 files are
only read, and the result is compared with the recorded Phase-4 results (the baseline must reproduce exactly).

Pre-declared decision rule (written before any Phase-5 result existed; applied by `decide()`):
  hybrid (w_dense = PRIMARY_HYBRID_WEIGHT) provides a MEASURABLE benefit only if ALL hold versus dense-only:
   C1  MRR on the independent set improves by at least +0.03
   C2  Recall@3 and Recall@5 on the independent set do not decrease
   C3  more queries improve (first-expected rank) than worsen AND the exact two-sided sign test has p <= 0.10
   C4  the known-failure slices `very_short` (1-4 words) and `rare_term` do not lose MRR
   C5  harm bound on the Phase-4 set: MRR and Recall@1 each drop by no more than 0.02
   C6  MRR on the independent set improves for at least 2 of the 3 tested weights (not one lucky weight)
  Otherwise the evidence is NOT convincing and dense-only retrieval is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_common import COLLECTION_NAME, CORPUS_PATH, ROOT, UNITS_PATH, VECTOR_DIR, resolve_model, sha256_file  # noqa: E402
from evaluate_card_retrieval import metrics as _metrics, KS  # noqa: E402
from phase5_retrievers import BM25, HYBRID_WEIGHTS, PRIMARY_HYBRID_WEIGHT, hybrid, rank, tokenize  # noqa: E402

QUERIES = ROOT / "data" / "evaluation" / "independent_queries.json"
P4_QUESTIONS = ROOT / "data" / "evaluation" / "card_retrieval_questions.json"
P4_RESULTS = ROOT / "data" / "evaluation" / "card_retrieval_results.json"
P4_MANIFEST = ROOT / "data" / "card_collection_manifest.json"
OUT = ROOT / "data" / "evaluation" / "phase5_results.json"
FRAGMENT_PIECES = 3          # a term split into >= 3 word pieces counts as fragmented
RARE_DF_MAX = 2              # a query term found in at most 2 of the 29 cards counts as rare
SYSTEMS = ["dense", "bm25"] + [f"hybrid_{w}" for w in HYBRID_WEIGHTS]
PRIMARY = f"hybrid_{PRIMARY_HYBRID_WEIGHT}"
CRITERIA = {"C1_mrr_gain_min": 0.03, "C2_recall3_recall5_not_lower": True, "C3_sign_test_p_max": 0.10,
            "C4_slices_not_lower_mrr": ["very_short", "rare_term"], "C5_phase4_max_drop": 0.02, "C6_weights_improving_min": 2}


# ----------------------------------------------------------------------------- generic helpers
def tree_sha(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in path.rglob("*") if x.is_file()):
        h.update(str(p.relative_to(path)).encode())
        h.update(sha256_file(p).encode())
    return h.hexdigest()


def length_bucket(n: int) -> str:
    return "very_short" if n <= 4 else "short" if n <= 7 else "long" if n <= 20 else "very_long"


def sign_test_p(improved: int, worsened: int) -> float:
    n = improved + worsened
    if n == 0:
        return 1.0
    k = min(improved, worsened)
    return round(min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n), 4)


def rank_rows(items: Sequence[Dict[str, Any]], scores: Dict[str, Dict[str, float]], titles: Dict[str, str]) -> List[Dict[str, Any]]:
    rows = []
    for it in items:
        order = rank(scores[it["id"]])
        pos = {sid: i + 1 for i, (sid, _) in enumerate(order)}
        er = {sid: pos[sid] for sid in it["expected"]}
        first = min(er.values())
        rows.append({"id": it["id"], "query": it["query"], "query_type": it["query_type"], "difficulty": it.get("difficulty"),
                     "length_bucket": it["length_bucket"], "word_count": it["word_count"], "ambiguous": it["ambiguous"],
                     "expected_source_ids": it["expected"], "also_relevant_source_ids": it["also"], "expected_ranks": er,
                     "first_expected_rank": first, "pass": first == 1, "hit@3": first <= 3, "hit@5": first <= 5,
                     "top1_is_also_relevant": order[0][0] in it["also"],
                     "top5": [{"rank": i + 1, "source_id": s, "title": titles[s], "score": round(v, 4)} for i, (s, v) in enumerate(order[:5])]})
    return rows


def group(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, Any]:
    vals = sorted({r[key] for r in rows if r[key] is not None})
    return {v: _metrics([r for r in rows if r[key] == v]) for v in vals}


def summarise(rows: Sequence[Dict[str, Any]], slices: Dict[str, List[str]]) -> Dict[str, Any]:
    return {"overall": _metrics(rows), "by_query_type": group(rows, "query_type"), "by_length": group(rows, "length_bucket"),
            "by_difficulty": group(rows, "difficulty"),
            "slices": {n: _metrics([r for r in rows if r["id"] in set(ids)]) for n, ids in slices.items()}}


def paired(base: Sequence[Dict[str, Any]], other: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    imp = [b["id"] for b, o in zip(base, other) if o["first_expected_rank"] < b["first_expected_rank"]]
    wor = [b["id"] for b, o in zip(base, other) if o["first_expected_rank"] > b["first_expected_rank"]]
    return {"improved": len(imp), "worsened": len(wor), "unchanged": len(base) - len(imp) - len(wor), "improved_ids": imp, "worsened_ids": wor,
            "lost_rank1": [b["id"] for b, o in zip(base, other) if b["pass"] and not o["pass"]],
            "gained_rank1": [b["id"] for b, o in zip(base, other) if not b["pass"] and o["pass"]],
            "sign_test_p_two_sided": sign_test_p(len(imp), len(wor))}


# ----------------------------------------------------------------------------- inputs
def load_items(queries_path: Path, p4_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    p5 = json.loads(queries_path.read_text(encoding="utf-8"))["queries"]
    p4 = json.loads(p4_path.read_text(encoding="utf-8"))["questions"]
    a = [{"id": q["query_id"], "query": q["query"], "query_type": q["query_type"], "difficulty": q["difficulty"],
          "length_bucket": q["length_bucket"], "word_count": q["word_count"], "ambiguous": q["ambiguous"],
          "expected": q["expected_source_ids"], "also": q["also_relevant_source_ids"]} for q in p5]
    b = []
    for q in p4:
        n = len(q["question"].split())
        b.append({"id": q["question_id"], "query": q["question"], "query_type": q["question_type"], "difficulty": None,
                  "length_bucket": length_bucket(n), "word_count": n, "ambiguous": q["ambiguous"],
                  "expected": q["expected_source_ids"], "also": q["also_relevant_source_ids"]})
    return {"phase5": a, "phase4": b}


def dense_scores(vector_dir: Path, collection_name: str, model, items: Sequence[Dict[str, Any]]):
    """Query the EXISTING collection (through a temporary copy, so the protected store cannot change)."""
    import chromadb
    from chromadb.config import Settings
    with tempfile.TemporaryDirectory() as t:
        copy = Path(t) / "store"
        shutil.copytree(vector_dir, copy)
        client = chromadb.PersistentClient(path=str(copy), settings=Settings(anonymized_telemetry=False))
        col = client.get_collection(collection_name)
        n = col.count()
        qv = model.encode([i["query"] for i in items], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        res = col.query(query_embeddings=qv.tolist(), n_results=n, include=["distances"])
        stored = col.get(include=["embeddings"])
        stored_vecs = {i: v for i, v in zip(stored["ids"], stored["embeddings"])}
        meta = dict(col.metadata or {})
    scores = {it["id"]: {sid: 1.0 - d for sid, d in zip(ids, dists)} for it, ids, dists in zip(items, res["ids"], res["distances"])}
    return scores, stored_vecs, meta


# ----------------------------------------------------------------------------- analysis pieces
def cos(a, b) -> float:
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def wordpieces(tok, term: str) -> List[str]:
    return tok.tokenize(term)


def build_slices(items: Sequence[Dict[str, Any]], bm: BM25, doc_tokens: Dict[str, set], frag: Dict[str, List[str]]) -> Dict[str, List[str]]:
    very_short, rare, sib, fragmented = [], [], [], []
    for it in items:
        terms = set(tokenize(it["query"]))
        if it["length_bucket"] == "very_short":
            very_short.append(it["id"])
        if it["ambiguous"]:
            sib.append(it["id"])
        if any(0 < bm.df.get(t, 0) <= RARE_DF_MAX and any(t in doc_tokens[e] for e in it["expected"]) for t in terms):
            rare.append(it["id"])
        if any(t in frag and any(t in doc_tokens[e] for e in it["expected"]) for t in terms):
            fragmented.append(it["id"])
    return {"very_short": very_short, "rare_term": rare, "sibling_ambiguous": sib, "fragmented_term": fragmented}


def diagnose(it: Dict[str, Any], row: Dict[str, Any], *, bm: BM25, dense: Dict[str, float], bm_scores: Dict[str, float], sys_ranks: Dict[str, int],
             card_vecs: Dict[str, Any], sec_vecs: Dict[Tuple[str, str], Any], qvec, units: Dict[str, Dict[str, Any]],
             doc_tokens: Dict[str, set], tok, prose_rank: int) -> Dict[str, Any]:
    e = it["expected"][0] if len(it["expected"]) == 1 else min(it["expected"], key=lambda s: row["expected_ranks"][s])
    top1 = row["top5"][0]["source_id"]
    terms = sorted(set(tokenize(it["query"])))
    frag = {t: wordpieces(tok, t) for t in terms if len(wordpieces(tok, t)) >= FRAGMENT_PIECES}
    order = [s for s, _ in rank(dense)]
    sec = {}
    for label, sid in (("expected", e), ("top1", top1)):
        sims = {k: round(cos(qvec, v), 4) for (s, k), v in sec_vecs.items() if s == sid}
        best = max(sims, key=lambda k: (sims[k], k))
        sec[label] = {"card": sid, "whole_card_embedding_text": round(dense[sid], 4), "sections": sims, "best_section": best, "best_section_sim": sims[best]}
    return {
        "id": it["id"], "query": it["query"], "expected": e, "expected_title": units[e]["title"], "top1": top1, "top1_title": units[top1]["title"],
        "dense_rank_expected": row["first_expected_rank"], "dense_sim_expected": round(dense[e], 4), "dense_sim_top1": round(dense[top1], 4),
        "dense_gap_top1_minus_expected": round(dense[top1] - dense[e], 4),
        "content_terms": terms, "content_term_count": len(terms),
        "terms_in_expected_card": [t for t in terms if t in doc_tokens[e]], "terms_in_top1_card": [t for t in terms if t in doc_tokens[top1]],
        "terms_in_no_card": [t for t in terms if bm.df.get(t, 0) == 0],
        "fragmented_terms": frag,
        "bm25_rank_expected": sys_ranks["bm25"], "hybrid_primary_rank_expected": sys_ranks[PRIMARY],
        "same_category_expected_top1": units[e]["category"] == units[top1]["category"],
        "card_card_cosine_expected_top1": round(cos(card_vecs[e], card_vecs[top1]), 4),
        "section_level": sec, "prose_only_representation_rank_expected": prose_rank,
        "near_tie_gap_below_0.02": (dense[top1] - dense[e]) < 0.02,
        "failure_pattern": ("lexical_signal_present (BM25 ranks the expected card 1-2)" if sys_ranks["bm25"] <= 2 else
                            "no_lexical_path (BM25 ranks the expected card 4 or worse)" if sys_ranks["bm25"] >= 4 else "partial_lexical_signal (BM25 rank 3)"),
    }


def prose_text(unit: Dict[str, Any], doc: Dict[str, Any]) -> str:
    """Diagnostic representation: title, category line, What it covers, Meter-to-Cash relevance only (no reference line, no URL block)."""
    from build_retrieval_units import section_span
    secs = {s["key"]: s for s in doc["sections"]}
    parts = [secs["title"]["text"], secs["category"]["text"]]
    for k in ("what_it_covers", "meter_to_cash_relevance"):
        a, b = section_span(doc, secs[k])
        parts.append(doc["content"][a:b])
    return "\n".join(parts[:2]) + "\n\n" + "\n\n".join(parts[2:])


def decide(res: Dict[str, Any]) -> Dict[str, Any]:
    p5 = res["datasets"]["phase5"]
    d, h = p5["systems"]["dense"], p5["systems"][PRIMARY]
    dm, hm = d["summary"]["overall"], h["summary"]["overall"]
    pr = p5["paired_vs_dense"][PRIMARY]
    c = {}
    c["C1"] = {"rule": f"MRR gain >= {CRITERIA['C1_mrr_gain_min']}", "dense": dm["mrr"], "hybrid": hm["mrr"], "delta": round(hm["mrr"] - dm["mrr"], 4),
               "pass": hm["mrr"] - dm["mrr"] >= CRITERIA["C1_mrr_gain_min"] - 1e-9}
    c["C2"] = {"rule": "Recall@3 and Recall@5 not lower", "delta_recall@3": round(hm["recall@3"] - dm["recall@3"], 4),
               "delta_recall@5": round(hm["recall@5"] - dm["recall@5"], 4), "pass": hm["recall@3"] >= dm["recall@3"] and hm["recall@5"] >= dm["recall@5"]}
    c["C3"] = {"rule": "improved > worsened and sign-test p <= 0.10", "improved": pr["improved"], "worsened": pr["worsened"], "p": pr["sign_test_p_two_sided"],
               "pass": pr["improved"] > pr["worsened"] and pr["sign_test_p_two_sided"] <= CRITERIA["C3_sign_test_p_max"]}
    sl = {}
    for s in CRITERIA["C4_slices_not_lower_mrr"]:
        a, b = d["summary"]["slices"][s], h["summary"]["slices"][s]
        sl[s] = {"queries": a.get("questions", 0), "dense_mrr": a.get("mrr"), "hybrid_mrr": b.get("mrr"),
                 "ok": a.get("questions", 0) == 0 or b["mrr"] >= a["mrr"]}
    c["C4"] = {"rule": "very_short and rare_term slices do not lose MRR", "slices": sl, "pass": all(x["ok"] for x in sl.values())}
    p4 = res["datasets"]["phase4"]["systems"]
    a, b = p4["dense"]["summary"]["overall"], p4[PRIMARY]["summary"]["overall"]
    c["C5"] = {"rule": f"Phase-4 set: MRR and Recall@1 drop <= {CRITERIA['C5_phase4_max_drop']}", "delta_mrr": round(b["mrr"] - a["mrr"], 4),
               "delta_recall@1": round(b["recall@1"] - a["recall@1"], 4),
               "pass": (b["mrr"] - a["mrr"]) >= -CRITERIA["C5_phase4_max_drop"] - 1e-9 and (b["recall@1"] - a["recall@1"]) >= -CRITERIA["C5_phase4_max_drop"] - 1e-9}
    per_w = {w: round(p5["systems"][f"hybrid_{w}"]["summary"]["overall"]["mrr"] - dm["mrr"], 4) for w in HYBRID_WEIGHTS}
    c["C6"] = {"rule": f"MRR improves for >= {CRITERIA['C6_weights_improving_min']} of {len(HYBRID_WEIGHTS)} weights", "delta_mrr_by_w_dense": per_w,
               "pass": sum(1 for v in per_w.values() if v > 0) >= CRITERIA["C6_weights_improving_min"]}
    ok = all(v["pass"] for v in c.values())
    return {"primary_system": PRIMARY, "criteria": c, "all_pass": ok,
            "verdict": "Hybrid provides a measurable benefit under the pre-declared rule." if ok else
            "NOT convincing under the pre-declared rule: retain dense-only retrieval.", "failed_criteria": [k for k, v in c.items() if not v["pass"]]}


# ----------------------------------------------------------------------------- run
def run(units_path: Path, corpus_path: Path, queries_path: Path, p4_path: Path, p4_results_path: Path, vector_dir: Path, out: Path,
        model_path: Optional[str] = None, manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    if not vector_dir.is_dir():
        raise SystemExit(f"{vector_dir} not found: rebuild the protected collection first with "
                         "`python scripts/build_card_collection.py --manifest <tmp path>` (the Phase-4 manifest must not be overwritten)")
    units_payload = json.loads(units_path.read_text(encoding="utf-8"))
    units_list = units_payload["units"]
    units = {u["source_id"]: u for u in units_list}
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    docs = {d["source_id"]: d for d in corpus["documents"]}
    titles = {s: u["title"] for s, u in units.items()}
    items = load_items(queries_path, p4_path)
    all_items = items["phase5"] + items["phase4"]

    store_before = tree_sha(vector_dir)
    model_dir, model_info = resolve_model(model_path)
    model = SentenceTransformer(model_dir, device="cpu")
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    dense, stored_vecs, col_meta = dense_scores(vector_dir, COLLECTION_NAME, model, all_items)
    store_after = tree_sha(vector_dir)

    manifest_emb_sha = json.loads(Path(manifest_path or P4_MANIFEST).read_text(encoding="utf-8"))["embeddings_float32_sha256"]

    # the baseline must be reproduced exactly from the recorded Phase-4 results
    p4res = json.loads(p4_results_path.read_text(encoding="utf-8"))
    rec = {r["question_id"]: r for r in p4res["per_question"]}
    mism, maxdiff = [], 0.0
    for it in items["phase4"]:
        order = [s for s, _ in rank(dense[it["id"]])]
        if [t["source_id"] for t in rec[it["id"]]["retrieved_top5"]] != order[:5]:
            mism.append(it["id"])
        for t in rec[it["id"]]["retrieved_top5"]:
            maxdiff = max(maxdiff, abs(t["cosine_similarity"] - dense[it["id"]][t["source_id"]]))
    baseline = {"phase4_questions_checked": len(items["phase4"]), "top5_identical_to_recorded_phase4_results": not mism, "mismatching_questions": mism,
                "max_abs_similarity_difference_vs_recorded": round(maxdiff, 4), "phase4_recorded_metrics": p4res["metrics"]["overall"],
                # raw file hashes of a chroma store change whenever ANY process opens it (sqlite/index bookkeeping) and differ between rebuilds,
                # so they are compared within this run only and not recorded; the recorded identity is the logical content hash below
                "vector_store_unchanged_by_this_evaluation": store_before == store_after,
                "phase4_manifest_embeddings_float32_sha256": manifest_emb_sha}

    bm = BM25([u["source_id"] for u in units_list], [u["embedding_text"] for u in units_list])
    doc_tokens = {u["source_id"]: set(tokenize(u["embedding_text"])) for u in units_list}
    lex = {it["id"]: bm.scores(it["query"]) for it in all_items}
    scores: Dict[str, Dict[str, Dict[str, float]]] = {"dense": dense, "bm25": lex}
    for w in HYBRID_WEIGHTS:
        scores[f"hybrid_{w}"] = {it["id"]: hybrid(dense[it["id"]], lex[it["id"]], w) for it in all_items}

    # tokenizer investigation inputs
    # alphabetic words only: hexadecimal identifiers of the printed SAP URLs are reported separately (they are not terms a user can type)
    card_vocab = sorted({t for s in doc_tokens.values() for t in s if t.isalpha()})
    url_ids = sorted({t for s in doc_tokens.values() for t in s if not t.isalpha() and len(t) >= 8})
    url_share = []
    for u in units_list:
        n_url = len(tok.tokenize(u["source_url"]))
        n_all = len(tok.tokenize(u["embedding_text"]))
        url_share.append(n_url / n_all)
    pieces = {t: wordpieces(tok, t) for t in card_vocab}
    frag_terms = {t: p for t, p in pieces.items() if len(p) >= FRAGMENT_PIECES}
    query_terms = sorted({t for it in all_items for t in tokenize(it["query"])})
    qpieces = {t: wordpieces(tok, t) for t in query_terms}

    # in-memory diagnostics (nothing stored): card vectors, section vectors, prose-only ablation
    card_vecs = {s: v for s, v in stored_vecs.items()}
    recomputed = model.encode([u["embedding_text"] for u in units_list], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    card_vec_diff = max(abs(float(a) - float(b)) for u, r in zip(units_list, recomputed) for a, b in zip(card_vecs[u["source_id"]], r))
    # logical identity of the protected store: the vectors read back from it are the embeddings of the units' embedding_text (chroma returns them
    # with ~1e-7 float noise, so a bitwise hash of the read-back vectors is not used); the hash of the freshly encoded vectors is informational only
    # because it can differ across CPUs or library versions
    baseline["stored_vs_recomputed_embedding_max_abs_diff"] = round(card_vec_diff, 8)
    baseline["stored_embeddings_consistent_with_embedding_text"] = card_vec_diff < 1e-6
    baseline["recomputed_embeddings_float32_sha256"] = hashlib.sha256(np.asarray(recomputed, dtype="float32").tobytes()).hexdigest()
    baseline["recomputed_hash_equals_phase4_manifest_hash_informational"] = baseline["recomputed_embeddings_float32_sha256"] == manifest_emb_sha
    sec_keys = ("title", "category", "what_it_covers", "meter_to_cash_relevance", "authoritative_source")
    sec_texts = {(sid, k): next(s["text"] for s in d["sections"] if s["key"] == k) for sid, d in docs.items() for k in sec_keys}
    order_keys = sorted(sec_texts)
    sv = model.encode([sec_texts[k] for k in order_keys], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    sec_vecs = {k: v for k, v in zip(order_keys, sv)}
    prose_vecs = model.encode([prose_text(u, docs[u["source_id"]]) for u in units_list], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    qvecs = {it["id"]: v for it, v in zip(all_items, model.encode([i["query"] for i in all_items], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False))}
    prose_scores = {it["id"]: {u["source_id"]: float(qvecs[it["id"]] @ pv) for u, pv in zip(units_list, prose_vecs)} for it in all_items}
    cats = {s: u["category"] for s, u in units.items()}
    ids = sorted(units)
    same = [cos(card_vecs[a], card_vecs[b]) for i, a in enumerate(ids) for b in ids[i + 1:] if cats[a] == cats[b]]
    diff = [cos(card_vecs[a], card_vecs[b]) for i, a in enumerate(ids) for b in ids[i + 1:] if cats[a] != cats[b]]

    res: Dict[str, Any] = {"schema_version": 1, "protected_baseline": baseline,
                           "inputs": {"retrieval_units_sha256": sha256_file(units_path), "independent_queries_sha256": sha256_file(queries_path),
                                      "phase4_questions_sha256": sha256_file(p4_path), "phase4_results_sha256": sha256_file(p4_results_path),
                                      "source_corpus_sha256": sha256_file(corpus_path), "collection": COLLECTION_NAME,
                                      "collection_metadata": {k: col_meta.get(k) for k in ("embedding_model", "embedding_dimensions", "hnsw:space", "retrieval_units_file_sha256")},
                                      "model_files_sha256": model_info["files_sha256"]},
                           "settings": {"systems": SYSTEMS, "primary_hybrid": PRIMARY, "hybrid_weights_dense": list(HYBRID_WEIGHTS),
                                        "bm25": {"k1": 1.5, "b": 0.75, "text_indexed": "embedding_text (same text that is embedded)", "stemming": False,
                                                 "stopwords": "Lucene default English (33 words)"},
                                        "hybrid_normalisation": "min-max per query over the 29 cards", "fragment_pieces_threshold": FRAGMENT_PIECES,
                                        "rare_term_df_max": RARE_DF_MAX, "decision_criteria": CRITERIA},
                           "datasets": {}}
    diagnostics: Dict[str, List[Dict[str, Any]]] = {}
    for name, its in items.items():
        slices = build_slices(its, bm, doc_tokens, frag_terms)
        slices["no_lexical_overlap"] = [it["id"] for it in its if max(lex[it["id"]][e] for e in it["expected"]) == 0.0]
        ds: Dict[str, Any] = {"query_count": len(its), "slices": slices, "systems": {}, "paired_vs_dense": {}}
        comp = {"by_query_type": {t: sum(1 for i in its if i["query_type"] == t) for t in sorted({i["query_type"] for i in its})},
                "by_length": {t: sum(1 for i in its if i["length_bucket"] == t) for t in sorted({i["length_bucket"] for i in its})},
                "by_difficulty": {t: sum(1 for i in its if i["difficulty"] == t) for t in sorted({i["difficulty"] for i in its if i["difficulty"]})},
                "ambiguous": sum(1 for i in its if i["ambiguous"]), "multi_expected": sum(1 for i in its if len(i["expected"]) > 1)}
        ds["composition"] = comp
        for s in SYSTEMS:
            rows = rank_rows(its, scores[s], titles)
            ds["systems"][s] = {"summary": summarise(rows, slices), "rows": rows}
        for s in SYSTEMS[1:]:
            ds["paired_vs_dense"][s] = paired(ds["systems"]["dense"]["rows"], ds["systems"][s]["rows"])
        prose_rows = rank_rows(its, prose_scores, titles)
        ds["diagnostic_prose_only_dense"] = {"note": "DIAGNOSTIC ONLY, in memory, not stored as a collection: title + category + What it covers + Meter-to-Cash relevance embedded without the reference line and URL block",
                                             "summary": summarise(prose_rows, slices), "paired_vs_dense": paired(ds["systems"]["dense"]["rows"], prose_rows),
                                             "first_expected_rank": {r["id"]: r["first_expected_rank"] for r in prose_rows}}
        res["datasets"][name] = ds
        # failure diagnostics
        dr = {r["id"]: r for r in ds["systems"]["dense"]["rows"]}
        fail = [it for it in its if not dr[it["id"]]["pass"]] if name == "phase5" else [it for it in its if it["id"] in ("Q07", "Q39", "Q42", "Q49")]
        out_d = []
        for it in fail:
            sr = {s: next(r for r in ds["systems"][s]["rows"] if r["id"] == it["id"])["first_expected_rank"] for s in SYSTEMS}
            out_d.append(diagnose(it, dr[it["id"]], bm=bm, dense=dense[it["id"]], bm_scores=lex[it["id"]], sys_ranks=sr, card_vecs=card_vecs, sec_vecs=sec_vecs,
                                  qvec=qvecs[it["id"]], units=units, doc_tokens=doc_tokens, tok=tok, prose_rank=ds["diagnostic_prose_only_dense"]["first_expected_rank"][it["id"]]))
            out_d[-1]["ranks_all_systems"] = sr
        diagnostics[name] = out_d
    res["datasets"]["phase5"]["decision"] = decide(res)
    fp = diagnostics["phase5"]
    res["failure_pattern_counts_phase5"] = {"dense_not_rank1": len(fp), "dense_not_top3": sum(1 for d in fp if d["dense_rank_expected"] > 3),
                                            "patterns": {k: sum(1 for d in fp if d["failure_pattern"] == k) for k in sorted({d["failure_pattern"] for d in fp})},
                                            "near_ties": sum(1 for d in fp if d["near_tie_gap_below_0.02"]),
                                            "top1_same_category_as_expected": sum(1 for d in fp if d["same_category_expected_top1"]),
                                            "with_fragmented_query_terms": sum(1 for d in fp if d["fragmented_terms"]),
                                            "fixed_to_rank1_by_primary_hybrid": sum(1 for d in fp if d["hybrid_primary_rank_expected"] == 1),
                                            "fixed_to_rank1_by_bm25": sum(1 for d in fp if d["bm25_rank_expected"] == 1)}
    res["failure_diagnostics"] = {"phase5_dense_not_rank1": diagnostics["phase5"], "phase4_known_failures": diagnostics["phase4"]}
    res["card_similarity"] = {"mean_cosine_same_category_pairs": round(sum(same) / len(same), 4), "same_category_pairs": len(same),
                              "mean_cosine_cross_category_pairs": round(sum(diff) / len(diff), 4), "cross_category_pairs": len(diff),
                              "collection_vectors_vs_recomputed_max_abs_diff": round(card_vec_diff, 8)}

    # tokenizer investigation
    def frag_split(its, dname):
        rowsd = {r["id"]: r for r in res["datasets"][dname]["systems"]["dense"]["rows"]}
        yes = [i["id"] for i in its if any(t in frag_terms and any(t in doc_tokens[e] for e in i["expected"]) for t in set(tokenize(i["query"])))]
        no = [i["id"] for i in its if i["id"] not in set(yes)]
        out = {}
        for s in ("dense", "bm25", PRIMARY):
            rows = res["datasets"][dname]["systems"][s]["rows"]
            out[s] = {"with_fragmented_expected_term": _metrics([r for r in rows if r["id"] in set(yes)]),
                      "without": _metrics([r for r in rows if r["id"] in set(no)])}
        return {"with_fragmented_expected_term_ids": yes, "systems": out}
    known_terms = sorted({t for d in diagnostics["phase4"] + diagnostics["phase5"] for t in d["content_terms"]} | {"subledger", "clarification", "installment", "extrapolation", "interpolation", "dunning", "delinquency"})
    res["tokenization"] = {
        "tokenizer": type(tok).__name__, "vocab_size": tok.vocab_size, "model_max_seq_length": int(model.max_seq_length),
        "fragment_threshold_pieces": FRAGMENT_PIECES,
        "url_identifier_tokens": len(url_ids),
        "url_wordpiece_share_of_embedding_text": {"min": round(min(url_share), 3), "mean": round(sum(url_share) / len(url_share), 3), "max": round(max(url_share), 3)},
        "card_vocabulary_terms": len(card_vocab), "card_terms_fragmented": len(frag_terms),
        "card_terms_fragmented_share": round(len(frag_terms) / len(card_vocab), 4),
        "card_terms_fragmented": {t: frag_terms[t] for t in sorted(frag_terms)},
        "query_terms": len(query_terms), "query_terms_fragmented": sum(1 for p in qpieces.values() if len(p) >= FRAGMENT_PIECES),
        "term_pieces": {t: (pieces.get(t) or qpieces.get(t) or wordpieces(tok, t)) for t in known_terms},
        "term_card_document_frequency": {t: bm.df.get(t, 0) for t in known_terms},
        "fragmented_expected_term_effect": {"phase5": frag_split(items["phase5"], "phase5"), "phase4": frag_split(items["phase4"], "phase4")},
    }
    res["model"] = {"name": model_info["model_name"], "origin": model_info["origin"], "max_seq_length": int(model.max_seq_length)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--units", default=str(UNITS_PATH))
    ap.add_argument("--corpus", default=str(CORPUS_PATH))
    ap.add_argument("--queries", default=str(QUERIES))
    ap.add_argument("--phase4-questions", default=str(P4_QUESTIONS))
    ap.add_argument("--phase4-results", default=str(P4_RESULTS))
    ap.add_argument("--vector-dir", default=str(VECTOR_DIR))
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    r = run(Path(a.units), Path(a.corpus), Path(a.queries), Path(a.phase4_questions), Path(a.phase4_results), Path(a.vector_dir), Path(a.out), a.model_path)
    b = r["protected_baseline"]
    print(f"baseline reproduced: {b['top5_identical_to_recorded_phase4_results']}  vector store unchanged: {b['vector_store_unchanged_by_this_evaluation']}  "
          f"stored vectors consistent with embedding_text: {b['stored_embeddings_consistent_with_embedding_text']}")
    for name in ("phase5", "phase4"):
        print(f"--- {name} ({r['datasets'][name]['query_count']} queries)")
        for s in SYSTEMS:
            m = r["datasets"][name]["systems"][s]["summary"]["overall"]
            print(f"{s:14s} R@1={m['recall@1']:.4f} R@3={m['recall@3']:.4f} R@5={m['recall@5']:.4f} MRR={m['mrr']:.4f}")
    d = r["datasets"]["phase5"]["decision"]
    print(d["verdict"], d["failed_criteria"])
    return 0 if b["top5_identical_to_recorded_phase4_results"] and b["vector_store_unchanged_by_this_evaluation"] and b["stored_embeddings_consistent_with_embedding_text"] else 1


if __name__ == "__main__":
    sys.exit(main())
