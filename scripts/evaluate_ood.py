#!/usr/bin/env python3
"""Phase 7F - out-of-domain behaviour of the card router (spec: data/phase6_next_phase_spec.md, section 5, step 7F).

Evidence only. This script does not change retrieval, does not add a threshold to the router, does not build or write a
collection, calls no LLM, generates no answer, fetches no SAP page and makes no network request (sockets are blocked and
attempts are counted).

Question: do the rank-1 scores of in-domain queries separate from those of out-of-domain queries well enough to justify a
refusal threshold (``min_cosine``)? The decision rule is declared in ``data/evaluation/phase7F_ood_queries.json`` BEFORE any of
its queries was routed; this script applies it as written. The default is ``min_cosine = None`` and stays so unless every
criterion of the rule holds.

Units
-----
The router returns cosine DISTANCE (``1 - cosine``, 0 = identical direction). This module reports similarity
(``cosine = 1 - distance``) for the decision and keeps both numbers apart in every row (``..._cosine_similarity`` and
``..._cosine_distance``). A threshold means ``similarity >= min_cosine`` is accepted. It is never a distance, and it is not the
legacy squared-L2 ``MAX_DISTANCE = 1.0`` of the page store.

    python scripts/evaluate_ood.py --out data/evaluation/phase7F_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_common as C  # noqa: E402
import m2c_router as rt  # noqa: E402
import evaluate_two_stage as ev  # noqa: E402  (7E helpers: recorded Phase 4/5 data, metrics, store snapshot, NetworkGuard)
from m2c_orchestrator import select_top_ranked  # noqa: E402

ROOT = C.ROOT
QUERIES_PATH = ROOT / "data" / "evaluation" / "phase7F_ood_queries.json"
RESULTS_DEFAULT = ROOT / "data" / "evaluation" / "phase7F_results.json"
E7_PATH = ROOT / "data" / "phase7E_evaluation.json"
LEGACY_QUESTIONS = ROOT / "data" / "evaluation_questions.json"
DEFAULT_MIN_COSINE: Optional[float] = None      # explicit default: no card refusal threshold
EXPECTED_COUNT = 29
GRID = tuple(round(0.10 + 0.05 * i, 2) for i in range(13))       # 0.10 ... 0.70; fixed in advance, descriptive only
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)

# the decision-rule constants (they mirror the rule written in the queries file; a test compares them)
RULE = {"min_in_domain": 100, "min_ood": 50, "min_ood_per_split": 25, "auroc_min": 0.90, "pooled_max_fn": 0.05, "pooled_max_fp": 0.20,
        "dev_max_fn": 0.05, "test_max_fn": 0.10, "test_max_fp": 0.25}


# ------------------------------------------------------------------------------------------------------ units and selector


def similarity(distance: float) -> float:
    """cosine similarity from the router's cosine distance."""
    return 1.0 - float(distance)


def validate_min_cosine(min_cosine: Optional[float]) -> Optional[float]:
    if min_cosine is None:
        return None
    if isinstance(min_cosine, bool) or not isinstance(min_cosine, (int, float)) or not math.isfinite(float(min_cosine)):
        raise ValueError(f"min_cosine must be None or a finite number, got {min_cosine!r}")
    if not -1.0 <= float(min_cosine) <= 1.0:
        raise ValueError(f"min_cosine is a cosine SIMILARITY in [-1, 1], got {min_cosine!r} (was a distance or a squared-L2 value passed?)")
    return float(min_cosine)


def make_selector(min_cosine: Optional[float] = DEFAULT_MIN_COSINE):
    """Caller-side selector for ``m2c_orchestrator.route_to_page`` (the hook 7A provides; the router itself is unchanged).

    ``None`` -> the default rank-1 selector (no refusal). Otherwise the rank-1 card is selected only when its cosine similarity
    (``1 - distance``) is ``>= min_cosine`` (inclusive); else ``None`` (the orchestrator then reports ``no_card_candidate`` with
    ``SELECTOR_REJECTED_ALL_CANDIDATES``). It never reorders or removes candidates.
    """
    t = validate_min_cosine(min_cosine)
    if t is None:
        return select_top_ranked

    def select(candidates):
        if not candidates:
            return None
        top = candidates[0]
        return top if similarity(top.distance) >= t else None
    return select


# ------------------------------------------------------------------------------------------------------ statistics (stdlib only)


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Linear interpolation between closest ranks (the usual 'inclusive' definition)."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("no values")
    if n == 1:
        return sorted_values[0]
    pos = (n - 1) * p / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def describe(values: Sequence[float]) -> Dict[str, Any]:
    v = sorted(values)
    n = len(v)
    if n == 0:
        return {"n": 0}
    mean = sum(v) / n
    out: Dict[str, Any] = {"n": n, "min": round(v[0], 6), "max": round(v[-1], 6), "mean": round(mean, 6), "median": round(percentile(v, 50), 6),
                           "stdev": round(math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1)), 6) if n > 1 else 0.0}
    out["percentiles"] = {f"p{p}": round(percentile(v, p), 6) for p in PERCENTILES}
    return out


def auroc(positive: Sequence[float], negative: Sequence[float]) -> Optional[float]:
    """P(random positive score > random negative score), ties count 0.5 (Mann-Whitney U / (n1*n2))."""
    if not positive or not negative:
        return None
    wins = 0.0
    for p in positive:
        for q in negative:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(positive) * len(negative))


def wilson(k: int, n: int, z: float = 1.959964) -> Optional[List[float]]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def rates_at(t: float, in_scores: Sequence[float], ood_scores: Sequence[float]) -> Dict[str, Any]:
    """Accept when similarity >= t. FN = in-domain refused; FP = out-of-domain accepted."""
    fn = sum(1 for s in in_scores if s < t)
    fp = sum(1 for s in ood_scores if s >= t)
    n_in, n_ood = len(in_scores), len(ood_scores)
    return {"t": round(t, 6), "in_domain_refused": fn, "in_domain_n": n_in, "in_domain_refusal_rate": round(fn / n_in, 4) if n_in else None,
            "in_domain_refusal_ci95": wilson(fn, n_in), "ood_accepted": fp, "ood_n": n_ood,
            "ood_acceptance_rate": round(fp / n_ood, 4) if n_ood else None, "ood_acceptance_ci95": wilson(fp, n_ood)}


def candidate_thresholds(scores: Sequence[float]) -> List[float]:
    """Midpoints between adjacent distinct observed scores (the only places where the counts change)."""
    d = sorted(set(round(s, 9) for s in scores))
    return [(a + b) / 2 for a, b in zip(d, d[1:])]


def select_on_dev(dev_in: Sequence[float], dev_ood: Sequence[float]) -> Optional[Dict[str, Any]]:
    """Rule C3: among midpoints with DEV in-domain refusal rate <= 0.05, the one with the lowest DEV out-of-domain acceptance rate
    (ties: the lowest t). None if no midpoint satisfies the refusal limit."""
    best = None
    for t in candidate_thresholds(list(dev_in) + list(dev_ood)):
        r = rates_at(t, dev_in, dev_ood)
        if r["in_domain_refusal_rate"] <= RULE["dev_max_fn"]:
            key = (r["ood_acceptance_rate"], t)
            if best is None or key < best[0]:
                best = (key, r)
    return best[1] if best else None


def pooled_feasible(in_scores: Sequence[float], ood_scores: Sequence[float]) -> Dict[str, Any]:
    """Rule C2 second half: is there ANY threshold with refusal <= 0.05 and acceptance <= 0.20? Reports the best acceptance rate
    reachable at refusal <= 0.05 (a ceiling on what any threshold could do)."""
    best = None
    for t in candidate_thresholds(list(in_scores) + list(ood_scores)):
        r = rates_at(t, in_scores, ood_scores)
        if r["in_domain_refusal_rate"] <= RULE["pooled_max_fn"]:
            if best is None or (r["ood_acceptance_rate"], t) < (best["ood_acceptance_rate"], best["t"]):
                best = r
    return {"exists": bool(best and best["ood_acceptance_rate"] <= RULE["pooled_max_fp"]), "best_at_refusal_limit": best}


def candidate_ranges(in_scores: Sequence[float], ood_scores: Sequence[float]) -> Dict[str, Any]:
    """Descriptive threshold ranges. 'clean gap' exists only when every OOD score is below every in-domain score."""
    min_in, max_in = min(in_scores), max(in_scores)
    min_ood, max_ood = min(ood_scores), max(ood_scores)
    clean = max_ood < min_in
    below = sum(1 for s in in_scores if s <= max_ood)
    above = sum(1 for s in ood_scores if s >= min_in)
    return {
        "clean_gap_exists": clean,
        "clean_gap_interval": [round(max_ood, 6), round(min_in, 6)] if clean else None,
        "overlap_interval": None if clean else [round(max(min_in, min_ood), 6), round(min(max_in, max_ood), 6)],
        "in_domain_scores_at_or_below_max_ood": below, "in_domain_n": len(in_scores),
        "ood_scores_at_or_above_min_in_domain": above, "ood_n": len(ood_scores),
        "zero_in_domain_refusal_range": {"t_at_most": round(min_in, 6), "ood_accepted_at_that_t": sum(1 for s in ood_scores if s >= min_in)},
        "zero_ood_acceptance_range": {"t_greater_than": round(max_ood, 6), "in_domain_refused_at_that_t": sum(1 for s in in_scores if s <= max_ood)},
    }


# ------------------------------------------------------------------------------------------------------ data


def file_sha(path: Path) -> str:
    return C.sha256_file(path)


def load_groups(queries_doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """All queries to route, as plain rows (labels exactly as recorded; nothing is relabelled here)."""
    rec = ev.recorded_datasets()
    rows: List[Dict[str, Any]] = []
    for r in rec["phase4"]["rows"]:
        rows.append({"id": r["id"], "group": "phase4", "label": "in_domain", "category": r["kind"], "query": r["query"], "expected": list(r["expected"])})
    for r in rec["phase5"]["rows"]:
        rows.append({"id": r["id"], "group": "phase5", "label": "in_domain", "category": r["kind"], "query": r["query"], "expected": list(r["expected"])})
    group_of = {"in_domain": "7f_in_domain", "out_of_domain": "7f_ood", "ambiguous_excluded": "7f_ambiguous"}
    for q in queries_doc["queries"]:
        rows.append({"id": q["id"], "group": group_of[q["label"]], "label": q["label"], "category": q["category"], "query": q["query"],
                     "expected": list(q["expected_source_ids"])})
    for q in json.loads(LEGACY_QUESTIONS.read_text(encoding="utf-8")):
        if not q["expected_titles"]:
            rows.append({"id": q["id"], "group": "legacy_ood", "label": "out_of_domain_legacy", "category": q.get("category", "out_of_domain"),
                         "query": q["question"], "expected": []})
    return rows


def assign_splits(rows: Sequence[Dict[str, Any]]) -> None:
    """The pre-declared split rule: per label group, pooled order (phase4, phase5, 7f), even position -> dev, odd -> test."""
    order = {"phase4": 0, "phase5": 1, "7f_in_domain": 2, "7f_ood": 2}
    counters = {"in_domain": 0, "out_of_domain": 0}
    for r in sorted((r for r in rows if r["label"] in counters), key=lambda r: (order[r["group"]], r["id"])):
        r["split"] = "dev" if counters[r["label"]] % 2 == 0 else "test"
        counters[r["label"]] += 1
    for r in rows:
        r.setdefault("split", None)


def route_rows(rows: Sequence[Dict[str, Any]], backend: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        cands = rt.route(r["query"], backend, top_k=EXPECTED_COUNT).candidates
        ids = [c.source_id for c in cands]
        c1, c2 = cands[0], cands[1]
        row = {k: r[k] for k in ("id", "group", "label", "category", "split", "query")}
        row.update({
            "expected_source_ids": r["expected"],
            "rank1_source_id": c1.source_id, "rank1_cosine_distance": round(c1.distance, 6), "rank1_cosine_similarity": round(similarity(c1.distance), 6),
            "rank2_source_id": c2.source_id, "rank2_cosine_distance": round(c2.distance, 6), "rank2_cosine_similarity": round(similarity(c2.distance), 6),
            "gap_cosine_distance_rank1_rank2": round(c2.distance - c1.distance, 6),
            "rank1_is_correct": (c1.source_id in r["expected"]) if r["expected"] else None,
            "first_expected_rank": ev.first_rank(r["expected"], ids) if r["expected"] else None,
            "_ranking": ids,
        })
        out.append(row)
    return out


def sims(rows: Sequence[Mapping[str, Any]], **where) -> List[float]:
    return [r["rank1_cosine_similarity"] for r in rows if all(r.get(k) == v for k, v in where.items())]


# ------------------------------------------------------------------------------------------------------ analysis


def decide(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Apply the pre-declared rule (C1, C2, C3) exactly. No criterion is added, relaxed or tuned here."""
    in_all = [r for r in rows if r["label"] == "in_domain"]
    ood_all = [r for r in rows if r["label"] == "out_of_domain"]
    s_in = [r["rank1_cosine_similarity"] for r in in_all]
    s_ood = [r["rank1_cosine_similarity"] for r in ood_all]
    ood_dev = [r for r in ood_all if r["split"] == "dev"]
    ood_test = [r for r in ood_all if r["split"] == "test"]
    c1 = {"n_in_domain": len(s_in), "n_out_of_domain": len(s_ood), "n_ood_dev": len(ood_dev), "n_ood_test": len(ood_test),
          "pass": len(s_in) >= RULE["min_in_domain"] and len(s_ood) >= RULE["min_ood"] and min(len(ood_dev), len(ood_test)) >= RULE["min_ood_per_split"]}
    a = auroc(s_in, s_ood)
    feas = pooled_feasible(s_in, s_ood)
    c2 = {"auroc": None if a is None else round(a, 4), "auroc_min": RULE["auroc_min"], "pooled_feasible": feas,
          "pass": a is not None and a >= RULE["auroc_min"] and feas["exists"]}
    dev_in = [r["rank1_cosine_similarity"] for r in in_all if r["split"] == "dev"]
    dev_ood = [r["rank1_cosine_similarity"] for r in ood_dev]
    test_in = [r["rank1_cosine_similarity"] for r in in_all if r["split"] == "test"]
    test_ood = [r["rank1_cosine_similarity"] for r in ood_test]
    sel = select_on_dev(dev_in, dev_ood)
    if sel is None:
        c3 = {"t_star": None, "dev": None, "test": None, "pass": False, "reason": "no DEV threshold keeps the in-domain refusal rate <= 0.05"}
    else:
        test = rates_at(sel["t"], test_in, test_ood)
        ok = test["in_domain_refusal_rate"] <= RULE["test_max_fn"] and test["ood_acceptance_rate"] <= RULE["test_max_fp"]
        c3 = {"t_star": sel["t"], "dev": sel, "test": test, "pass": ok,
              "limits": {"test_max_in_domain_refusal": RULE["test_max_fn"], "test_max_ood_acceptance": RULE["test_max_fp"]}}
    justified = c1["pass"] and c2["pass"] and c3["pass"]
    return {"C1_sample_adequacy": c1, "C2_separation_pooled": c2, "C3_held_out": c3,
            "threshold_justified": justified, "proposed_min_cosine": c3["t_star"] if justified else None,
            "min_cosine": c3["t_star"] if justified else DEFAULT_MIN_COSINE}


def distributions(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    in_rows = [r for r in rows if r["label"] == "in_domain"]
    ood_rows = [r for r in rows if r["label"] == "out_of_domain"]
    s_in = sims(in_rows)
    s_ood = sims(ood_rows)
    out: Dict[str, Any] = {
        "similarity_definition": "rank-1 cosine similarity = 1 - cosine distance",
        "in_domain_all": describe(s_in), "out_of_domain_all": describe(s_ood),
        "in_domain_by_group": {g: describe(sims(in_rows, group=g)) for g in ("phase4", "phase5", "7f_in_domain")},
        "in_domain_rank1_correct": describe([r["rank1_cosine_similarity"] for r in in_rows if r["rank1_is_correct"]]),
        "in_domain_rank1_wrong": describe([r["rank1_cosine_similarity"] for r in in_rows if r["rank1_is_correct"] is False]),
        "in_domain_by_split": {s: describe(sims(in_rows, split=s)) for s in ("dev", "test")},
        "out_of_domain_by_split": {s: describe(sims(ood_rows, split=s)) for s in ("dev", "test")},
        "out_of_domain_by_category": {c: describe(sims(ood_rows, category=c)) for c in sorted({r["category"] for r in ood_rows})},
        "legacy_ood_q26_q30": describe(sims([r for r in rows if r["group"] == "legacy_ood"])),
        "ambiguous_excluded": describe(sims([r for r in rows if r["group"] == "7f_ambiguous"])),
        "overlap": candidate_ranges(s_in, s_ood),
        "auroc_in_vs_ood_rank1_similarity": round(auroc(s_in, s_ood), 4),
        "auroc_by_in_domain_group": {g: round(auroc(sims(in_rows, group=g), s_ood), 4) for g in ("phase4", "phase5", "7f_in_domain")},
        "auroc_by_ood_category": {c: round(auroc(s_in, sims(ood_rows, category=c)), 4) for c in sorted({r["category"] for r in ood_rows})},
        "auroc_gap_signal_descriptive_only": round(auroc([r["gap_cosine_distance_rank1_rank2"] for r in in_rows], [r["gap_cosine_distance_rank1_rank2"] for r in ood_rows]), 4),
        "auroc_correct_vs_wrong_rank1_among_in_domain": round(auroc([r["rank1_cosine_similarity"] for r in in_rows if r["rank1_is_correct"]],
                                                                    [r["rank1_cosine_similarity"] for r in in_rows if r["rank1_is_correct"] is False]), 4),
        "ood_above_in_domain_median": sum(1 for s in s_ood if s >= percentile(sorted(s_in), 50)),
        "ood_above_in_domain_p5": sum(1 for s in s_ood if s >= percentile(sorted(s_in), 5)),
        "ood_n": len(s_ood), "in_domain_n": len(s_in),
        "post_hoc_descriptive_mentions_sap": mentions_sap(in_rows, ood_rows),
    }
    return out


def has_word_sap(query: str) -> bool:
    import re
    return re.search(r"\bSAP\b", query, re.I) is not None


def mentions_sap(in_rows: Sequence[Mapping[str, Any]], ood_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """POST-HOC observation (added after the first run, which already showed SAP-flavoured OOD queries scoring highest). Descriptive
    only: not a gate, not used for labels, the verdict or any threshold."""
    out: Dict[str, Any] = {"note": "post hoc; descriptive only; does not enter the decision rule"}
    for name, rows in (("in_domain", in_rows), ("out_of_domain", ood_rows)):
        out[name] = {"with_word_SAP": describe(sims([r for r in rows if has_word_sap(r["query"])])),
                     "without_word_SAP": describe(sims([r for r in rows if not has_word_sap(r["query"])]))}
    a = auroc(sims([r for r in in_rows if not has_word_sap(r["query"])]), sims([r for r in ood_rows if not has_word_sap(r["query"])]))
    out["auroc_in_vs_ood_both_without_word_SAP"] = None if a is None else round(a, 4)
    return out


def grid_table(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """What-if counts on a FIXED grid (descriptive; the grid is not tuned and none of these rows is a proposal)."""
    groups = {g: sims([r for r in rows if r["group"] == g]) for g in ("phase4", "phase5", "7f_in_domain", "7f_ood", "7f_ambiguous", "legacy_ood")}
    table = []
    for t in GRID:
        row: Dict[str, Any] = {"t": t}
        for g, s in groups.items():
            refused = sum(1 for x in s if x < t)
            row[g] = {"refused": refused, "n": len(s)}
        table.append(row)
    return table


def metrics_for(rows: Sequence[Mapping[str, Any]], group: str) -> Dict[str, Any]:
    sel = [r for r in rows if r["group"] == group]
    return ev.metrics_from([{"expected": r["expected_source_ids"], "ranking": r["_ranking"]} for r in sel])


def regression(rows: Sequence[Mapping[str, Any]], proposed: Optional[float]) -> Dict[str, Any]:
    """Phase 4/5 (and 7E) behaviour with the default (no threshold) selector, and with the proposed threshold if there is one."""
    e7 = json.loads(E7_PATH.read_text(encoding="utf-8"))
    out: Dict[str, Any] = {"default_min_cosine": DEFAULT_MIN_COSINE}
    for g in ("phase4", "phase5"):
        sel = [r for r in rows if r["group"] == g]
        e7rows = {p["id"]: p for p in e7["per_query"][g]}
        out[g] = {
            "queries": len(sel),
            "rank1_equals_7e": sum(1 for r in sel if r["rank1_source_id"] == e7rows[r["id"]]["rank1"]),
            "top5_equals_7e": sum(1 for r in sel if r["_ranking"][:5] == e7rows[r["id"]]["top5"]),
            "rank1_distance_equals_7e_to_6dp": sum(1 for r in sel if abs(r["rank1_cosine_distance"] - e7rows[r["id"]]["rank1_distance"]) < 1e-5),
            "first_expected_rank_equals_7e": sum(1 for r in sel if r["first_expected_rank"] == e7rows[r["id"]]["first_expected_rank"]),
            "metrics": metrics_for(rows, g),
            "metrics_equal_7e": metrics_for(rows, g) == {k: v for k, v in e7["router_regression"][g]["router_metrics"].items()},
            "refused_with_default_selector": 0,
        }
    if proposed is not None:
        for g in ("phase4", "phase5"):
            sel = [r for r in rows if r["group"] == g]
            refused = [r["id"] for r in sel if r["rank1_cosine_similarity"] < proposed]
            out[g]["with_proposed_threshold"] = {"min_cosine": proposed, "refused": len(refused), "refused_ids": refused,
                                                 "rankings_changed": 0, "note": "a threshold only decides acceptance of rank 1; it never reorders candidates"}
    return out


# ------------------------------------------------------------------------------------------------------ evaluation


def evaluate(vector_dir: Path = C.VECTOR_DIR, backend: Any = None, snapshot: bool = True) -> Dict[str, Any]:
    backend = backend or rt.ChromaCardBackend(vector_dir=vector_dir)
    before = ev.store_logical_snapshot(vector_dir) if snapshot else None
    qdoc = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    groups = load_groups(qdoc)
    assign_splits(groups)
    rows = route_rows(groups, backend)
    after = ev.store_logical_snapshot(vector_dir) if snapshot else None
    verdict = decide(rows)
    dist = distributions(rows)
    reg = regression(rows, verdict["proposed_min_cosine"])
    counts = {g: sum(1 for r in rows if r["group"] == g) for g in ("phase4", "phase5", "7f_in_domain", "7f_ood", "7f_ambiguous", "legacy_ood")}
    loaded = sorted(m for m in ev.BANNED_MODULES if m in sys.modules)
    checks = [
        ev.check("query file sha256 recorded and counts match the file's own header",
                 counts["7f_in_domain"] == qdoc["counts"]["in_domain"] and counts["7f_ood"] == qdoc["counts"]["out_of_domain"] and counts["7f_ambiguous"] == qdoc["counts"]["ambiguous_excluded"], counts),
        ev.check("every query routed with 29 candidates; rank-1 similarity == 1 - rank-1 distance (to 6 dp)",
                 all(abs(r["rank1_cosine_similarity"] - (1 - r["rank1_cosine_distance"])) < 2e-6 for r in rows)),
        ev.check("Phase 4 and Phase 5 rankings, expected ranks and metrics equal the Phase 7E results (which equal the recorded ones)",
                 all(reg[g]["rank1_equals_7e"] == reg[g]["queries"] and reg[g]["top5_equals_7e"] == reg[g]["queries"]
                     and reg[g]["first_expected_rank_equals_7e"] == reg[g]["queries"] and reg[g]["metrics_equal_7e"] for g in ("phase4", "phase5"))),
        ev.check("default min_cosine is None (and the verdict sets a value only if the rule is satisfied)", DEFAULT_MIN_COSINE is None and (verdict["min_cosine"] is None) == (not verdict["threshold_justified"])),
        ev.check("store: logical content identical before and after", before == after if snapshot else True),
        ev.check("no network attempt", not ev.NetworkGuard.attempts, len(ev.NetworkGuard.attempts)),
        ev.check("no LLM / legacy-pipeline module loaded", not loaded, loaded),
    ]
    return {
        "schema_version": 1, "spec": "data/phase6_next_phase_spec.md#7F",
        "scope": {"retrieval_changed": False, "router_modified": False, "answer_generated": False, "pages_fetched_or_ingested": False,
                  "threshold_enabled_in_router": False, "default_min_cosine": DEFAULT_MIN_COSINE,
                  "score": "rank-1 cosine similarity (1 - cosine distance); distance is reported separately in every row"},
        "inputs": {"queries_file_sha256": file_sha(QUERIES_PATH), "collection_manifest_sha256": file_sha(ROOT / "data" / "card_collection_manifest.json"),
                   "phase7e_evaluation_sha256": file_sha(E7_PATH), "phase4_results_sha256": file_sha(ev.P4_RESULTS),
                   "phase5_results_sha256": file_sha(ev.P5_RESULTS), "legacy_questions_sha256": file_sha(LEGACY_QUESTIONS)},
        "counts": counts,
        "store": {"before": before, "after": after},
        "rule": {"constants": RULE, "text": qdoc["decision_rule"]},
        "verdict": verdict,
        "distributions": dist,
        "grid_what_if_refused_counts": grid_table(rows),
        "regression": reg,
        "per_query": [{k: v for k, v in r.items() if k != "_ranking"} for r in rows],
        "isolation": {"network_attempts": len(ev.NetworkGuard.attempts), "banned_modules_loaded": loaded},
        "checks": checks, "ok": all(c["ok"] for c in checks),
    }


def render_json(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7F: OOD evidence for the card router (read-only; needs the card store and the local model).")
    ap.add_argument("--out", default=str(RESULTS_DEFAULT))
    ap.add_argument("--vector-dir", default=str(C.VECTOR_DIR))
    args = ap.parse_args(argv)
    ev.NetworkGuard.install()
    doc = evaluate(Path(args.vector_dir))
    Path(args.out).write_text(render_json(doc), encoding="utf-8")
    v = doc["verdict"]
    bad = [c["check"] for c in doc["checks"] if not c["ok"]]
    print(f"checks: {len(doc['checks']) - len(bad)}/{len(doc['checks'])} ok" + (f"; FAILED: {bad}" if bad else ""))
    print(f"counts: {doc['counts']}")
    print(f"C1 {v['C1_sample_adequacy']['pass']}  C2 {v['C2_separation_pooled']['pass']} (AUROC {v['C2_separation_pooled']['auroc']})  C3 {v['C3_held_out']['pass']}"
          f"  -> threshold_justified={v['threshold_justified']} min_cosine={v['min_cosine']}")
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
