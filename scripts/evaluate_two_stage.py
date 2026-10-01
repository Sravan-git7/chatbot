#!/usr/bin/env python3
"""Phase 7E - router and regression evaluation (spec: data/phase6_next_phase_spec.md, section 5, step 7E).

Evaluation only. It never changes retrieval, never builds or writes a collection, never calls an LLM, never generates an answer,
never ingests or fetches a SAP page and makes no network request (sockets are blocked and attempts are counted and reported).

What it measures (the three 7E items of the specification)
  1. Router recall through the real Phase 7 router (``m2c_router.ChromaCardBackend``) on the Phase 4 (50) and Phase 5 (54) sets
     against the recorded results: top-1, top-5 ordering, expected-card rank, R@1/3/5, MRR, coverage - and the routing layers
     above the ranking (7A join, 7C identity, 7D citation) kept apart from the rank.
  2. Legacy regression: the 30 legacy retrieval questions. The legacy ``chroma_db`` and the legacy embedding model name are not
     available here and ``rag_core`` is protected, so ``legacy`` mode is NOT run live; the recorded legacy results are re-scored and
     the card route is overlaid on the same 30 questions. ``routed`` mode does not exist in this repository (the 7C orchestrator of
     the plan was realised as an identity layer; there is no soft boost), so it is reported as not implemented, not simulated.
  3. Answerable subset: topics with local page text are counted from the repository; if too few (today: one), the script says so
     and the ``routed`` mode stays off.

Distances are cosine distances. Rank 1 is a rank, not a confidence; the gap to rank 2 is reported and near-ties stay visible. No
threshold is applied or proposed (that is 7F).

    python scripts/evaluate_two_stage.py --out data/phase7E_evaluation.json
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_common as C  # noqa: E402
import m2c_citations as cit  # noqa: E402
import m2c_page_identity as pid  # noqa: E402
import m2c_router as rt  # noqa: E402
from m2c_orchestrator import route_to_page, select_top_ranked  # noqa: E402

ROOT = C.ROOT
EVAL = ROOT / "data" / "evaluation"
P4_RESULTS = EVAL / "card_retrieval_results.json"
P5_QUERIES = EVAL / "independent_queries.json"
P5_RESULTS = EVAL / "phase5_results.json"
LEGACY_QUESTIONS = ROOT / "data" / "evaluation_questions.json"
LEGACY_RESULTS = ROOT / "data" / "retrieval_results.json"
EXPECTED_COUNT = 29
SIM_DECIMALS = 4
DIST_DECIMALS = 6
NEAR_TIE_BINS = (0.01, 0.05)      # descriptive bins only (the ones Phase 7B used); not thresholds and not tuned
BANNED_MODULES = ("ollama", "rag_core", "rag_chat", "retrieve", "evaluate_retrieval", "create_embeddings", "requests", "sap_resolver")
OUT_DEFAULT = ROOT / "data" / "phase7E_evaluation.json"
LOCAL_PAGE_TOPICS_EXPECTED_MIN = 5   # a page-level comparison would need at least this many topics with page text; stated, not tuned

# ---------------------------------------------------------------------------------------------------- small helpers


class NetworkGuard:
    attempts: List[str] = []

    @classmethod
    def install(cls) -> None:
        def _blocked(*a, **k):
            cls.attempts.append(repr(a[:2]))
            raise OSError("network access is disabled in the Phase 7E evaluation")
        socket.socket.connect = _blocked          # type: ignore[assignment]
        socket.socket.connect_ex = _blocked       # type: ignore[assignment]
        socket.create_connection = _blocked       # type: ignore[assignment]
        socket.getaddrinfo = _blocked             # type: ignore[assignment]


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check(name: str, ok: bool, detail: Any = None) -> Dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail}


def first_rank(expected: Sequence[str], ranking: Sequence[str]) -> Optional[int]:
    ranks = [ranking.index(e) + 1 for e in expected if e in ranking]
    return min(ranks) if ranks else None


def expected_ranks(expected: Sequence[str], ranking: Sequence[str]) -> Dict[str, Optional[int]]:
    return {e: (ranking.index(e) + 1 if e in ranking else None) for e in expected}


def coverage_at(expected: Sequence[str], ranking: Sequence[str], k: int) -> float:
    return len(set(expected) & set(ranking[:k])) / len(expected)


def metrics_from(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """rows: {expected, ranking}. Same definitions as the recorded Phase 4 / Phase 5 summaries (4-decimal rounding)."""
    n = len(rows)
    frs = [first_rank(r["expected"], r["ranking"]) for r in rows]
    out: Dict[str, Any] = {"questions": n}
    for k in (1, 3, 5):
        out[f"recall@{k}"] = round(sum(1 for f in frs if f and f <= k) / n, 4)
        out[f"mean_expected_coverage@{k}"] = round(sum(coverage_at(r["expected"], r["ranking"], k) for r in rows) / n, 4)
    out["mrr"] = round(sum(1.0 / f for f in frs if f) / n, 4)
    out["hits@1"] = sum(1 for f in frs if f == 1)
    return out


def gap12(distances: Sequence[float]) -> Optional[float]:
    return round(distances[1] - distances[0], DIST_DECIMALS) if len(distances) > 1 else None


def tie_bin(gap: Optional[float]) -> str:
    if gap is None:
        return "no_rank2"
    for b in NEAR_TIE_BINS:
        if gap < b:
            return f"gap<{b}"
    return f"gap>={NEAR_TIE_BINS[-1]}"


def _first_row(cs: "cit.CitationSet") -> Dict[str, Any]:
    return cs.sources[0] if cs.sources else {}


# ---------------------------------------------------------------------------------------------------- recorded datasets


def recorded_datasets() -> Dict[str, Dict[str, Any]]:
    p4 = load(P4_RESULTS)
    p5q = {q["query_id"]: q for q in load(P5_QUERIES)["queries"]}
    p5 = load(P5_RESULTS)["datasets"]["phase5"]["systems"]["dense"]
    rows4 = [{"id": r["question_id"], "query": r["question"], "kind": r["question_type"], "expected": r["expected_source_ids"],
              "also": r.get("also_relevant_source_ids", []), "rec_first": r["first_expected_rank"], "rec_ranks": r["expected_ranks"],
              "rec_top5": [(x["source_id"], x["cosine_similarity"]) for x in r["retrieved_top5"]]} for r in p4["per_question"]]
    rows5 = [{"id": r["id"], "query": p5q[r["id"]]["query"], "kind": r["query_type"], "expected": r["expected_source_ids"],
              "also": r.get("also_relevant_source_ids", []), "rec_first": r["first_expected_rank"], "rec_ranks": r["expected_ranks"],
              "rec_top5": [(x["source_id"], x["score"]) for x in r["top5"]]} for r in p5["rows"]]
    return {
        "phase4": {"rows": rows4, "recorded_overall": p4["metrics"]["overall"], "recorded_by_type": p4["metrics"]["by_question_type"]},
        "phase5": {"rows": rows5, "recorded_overall": p5["summary"]["overall"], "recorded_by_type": p5["summary"]["by_query_type"]},
    }


# ---------------------------------------------------------------------------------------------------- item 1: router regression


def router_regression(name: str, data: Mapping[str, Any], backend: Any, ctx: "pid.IdentityContext") -> Dict[str, Any]:
    """Route every query through the real router twice: top_k = 29 (full ranking, for rank metrics) and the default path
    (``route_to_identity``, default top_k) for the routing layers. Compare with the recorded results; nothing is edited."""
    rows = data["rows"]
    per: List[Dict[str, Any]] = []
    scored: List[Dict[str, Any]] = []
    cmp = {"top1_identical": 0, "top5_ordering_identical": 0, "expected_rank_identical": 0, "first_expected_rank_identical": 0,
           "similarity_mismatches_after_4dp": 0, "default_path_equals_prefix_of_full_ranking": 0}
    max_sim_diff = 0.0
    diffs: List[Dict[str, Any]] = []
    for r in rows:
        full = rt.route(r["query"], backend, top_k=EXPECTED_COUNT).candidates
        ids = [c.source_id for c in full]
        dist = [c.distance for c in full]
        rec_ids = [i for i, _ in r["rec_top5"]]
        fr = first_rank(r["expected"], ids)
        er = expected_ranks(r["expected"], ids)
        cmp["top1_identical"] += int(ids[0] == rec_ids[0])
        same5 = ids[:5] == rec_ids
        cmp["top5_ordering_identical"] += int(same5)
        cmp["expected_rank_identical"] += int(er == r["rec_ranks"])
        cmp["first_expected_rank_identical"] += int(fr == r["rec_first"])
        sims = [round(1.0 - d, SIM_DECIMALS) for d in dist[:5]]
        cmp["similarity_mismatches_after_4dp"] += sum(1 for a, (_, b) in zip(sims, r["rec_top5"]) if a != b)
        max_sim_diff = max(max_sim_diff, max(abs((1.0 - d) - b) for d, (_, b) in zip(dist[:5], r["rec_top5"])))
        if not (same5 and fr == r["rec_first"] and er == r["rec_ranks"]):
            diffs.append({"id": r["id"], "router_top5": ids[:5], "recorded_top5": rec_ids, "router_first_rank": fr, "recorded_first_rank": r["rec_first"]})

        scored.append({"expected": r["expected"], "ranking": ids, "kind": r["kind"]})
        # default path: query -> router (default top_k) -> 7A join -> 7C identity -> 7D citation
        idr = pid.route_to_identity(r["query"], backend, ctx)
        default_ids = [c.source_id for c in route_to_page(r["query"], backend, ctx.page_index).candidates]
        cmp["default_path_equals_prefix_of_full_ranking"] += int(default_ids == ids[:len(default_ids)] and idr.selected_source_id == ids[0])
        selected = full[0]
        cs = cit.cite_card(selected, ctx, query=r["query"])
        e = _first_row(cs)
        g = gap12(dist)
        r2 = full[1]
        id1 = idr.identity
        id2 = pid.resolve_identity(r2, ctx)
        per.append({
            "id": r["id"], "kind": r["kind"], "expected": r["expected"],
            "rank1": ids[0], "rank1_is_expected": ids[0] in r["expected"], "rank1_is_also_relevant": ids[0] in r["also"],
            "first_expected_rank": fr, "recorded_first_expected_rank": r["rec_first"],
            "top5": ids[:5], "top5_distances": [round(d, DIST_DECIMALS) for d in dist[:5]],
            "rank1_distance": round(dist[0], DIST_DECIMALS), "gap_rank1_rank2": g, "near_tie_bin": tie_bin(g),
            "rank2": ids[1], "rank2_is_expected": ids[1] in r["expected"],
            "routing": {"route_state_7c": idr.route_state, "join_state_7a": idr.join_state_7a,
                        "page_content_available": idr.page_content_available, "fallback_reason": idr.fallback_reason,
                        "card_needs_review": bool(id1.card_needs_review) if id1 else None},
            "citation": {"origin": e.get("origin"), "url_present": bool(e.get("url")), "url_byte_identical_to_card": e.get("url") == selected.source_url,
                         "review_flag": e.get("review_flag"), "used_as_answer_text": e.get("used_as_answer_text"),
                         "provided_as_context": e.get("provided_as_context"), "verified_used": e.get("verified_used")},
            "rank2_routing": {"route_state_7c": id2.resolution_status, "page_content_available": id2.local_page_available,
                              "card_needs_review": bool(id2.card_needs_review)},
        })
    n = len(rows)
    overall = metrics_from(scored)
    rec = data["recorded_overall"]
    overall_equal = all(overall[k] == round(rec[k], 4) for k in overall)
    by_kind: Dict[str, Any] = {}
    by_kind_equal = True
    for kind, rec_k in sorted(data["recorded_by_type"].items()):
        mine = metrics_from([x for x in scored if x["kind"] == kind])
        same = all(mine[k] == round(rec_k[k], 4) for k in mine)
        by_kind_equal &= same
        by_kind[kind] = {"router": mine, "equals_recorded": same}
    return {"queries": n, "comparison_with_recorded": cmp, "max_abs_diff_similarity_vs_recorded": round(max_sim_diff, 8),
            "differing_queries": diffs, "router_metrics": overall, "recorded_metrics": {k: rec[k] for k in overall},
            "metrics_equal_to_recorded": overall_equal, "by_type": by_kind, "by_type_equal_to_recorded": by_kind_equal,
            "per_query": per}


def aggregate_layers(per: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Counts only. Keeps retrieval rank, routing decision, identity status, local page availability and citation apart."""
    n = len(per)
    by_state: Dict[str, Dict[str, int]] = {}
    for p in per:
        d = by_state.setdefault(p["routing"]["route_state_7c"], {"queries": 0, "rank1_is_expected": 0, "page_content_available": 0, "review_flag": 0})
        d["queries"] += 1
        d["rank1_is_expected"] += int(p["rank1_is_expected"])
        d["page_content_available"] += int(p["routing"]["page_content_available"])
        d["review_flag"] += int(bool(p["citation"]["review_flag"]))
    hits = [p for p in per if p["rank1_is_expected"]]
    ties: Dict[str, Dict[str, int]] = {}
    for b in [f"gap<{x}" for x in NEAR_TIE_BINS] + [f"gap>={NEAR_TIE_BINS[-1]}"]:
        sel = [p for p in per if p["near_tie_bin"] == b]
        ties[b] = {"queries": len(sel), "rank1_is_expected": sum(1 for p in sel if p["rank1_is_expected"]),
                   "rank1_not_expected": sum(1 for p in sel if not p["rank1_is_expected"]),
                   "rank1_not_expected_but_rank2_is": sum(1 for p in sel if not p["rank1_is_expected"] and p["rank2_is_expected"])}
    # cumulative view, as Phase 7B reported it (gap < 0.01 is contained in gap < 0.05)
    cum = {}
    for x in NEAR_TIE_BINS:
        sel = [p for p in per if p["gap_rank1_rank2"] is not None and p["gap_rank1_rank2"] < x]
        cum[f"gap<{x}"] = {"queries": len(sel), "rank1_not_expected": sum(1 for p in sel if not p["rank1_is_expected"])}
    sensitive = [p["id"] for p in per if p["gap_rank1_rank2"] is not None and p["gap_rank1_rank2"] < NEAR_TIE_BINS[0]
                 and (p["routing"]["route_state_7c"], p["routing"]["page_content_available"], p["routing"]["card_needs_review"])
                 != (p["rank2_routing"]["route_state_7c"], p["rank2_routing"]["page_content_available"], p["rank2_routing"]["card_needs_review"])]
    return {
        "queries": n,
        "rank1_is_expected": len(hits),
        "rank1_is_expected_and_local_page_available": sum(1 for p in hits if p["routing"]["page_content_available"]),
        "rank1_is_expected_but_no_local_page": sum(1 for p in hits if not p["routing"]["page_content_available"]),
        "rank1_is_expected_and_card_needs_review": sum(1 for p in hits if p["routing"]["card_needs_review"]),
        "routed_to_local_page": sum(1 for p in per if p["routing"]["page_content_available"]),
        "routed_to_card_needing_review": sum(1 for p in per if p["routing"]["card_needs_review"]),
        "by_route_state": dict(sorted(by_state.items())),
        "citation": {"every_selected_card_has_url": all(p["citation"]["url_present"] for p in per),
                     "urls_byte_identical_to_card": all(p["citation"]["url_byte_identical_to_card"] for p in per),
                     "card_route_never_used_text": all(p["citation"]["used_as_answer_text"] is False and p["citation"]["verified_used"] is False
                                                       and p["citation"]["provided_as_context"] is False for p in per),
                     "review_flag_equals_card_needs_review": all(bool(p["citation"]["review_flag"]) == bool(p["routing"]["card_needs_review"]) for p in per)},
        "near_ties_by_bin": ties, "near_ties_cumulative": cum,
        "near_ties_below_first_bin_where_rank1_and_rank2_differ_in_routing_status": sensitive,
        "rank1_distance_min_max": [min(p["rank1_distance"] for p in per), max(p["rank1_distance"] for p in per)],
    }


# ---------------------------------------------------------------------------------------------------- edge cases (real router, real identity, real citations)


def _forced(source_id: str):
    def sel(cands):
        return next((c for c in cands if c.source_id == source_id), None)
    return sel


EDGE_CARDS = {
    "M2C-05": "correction metadata",
    "M2C-14": "needs_review",
    "M2C-18": "conflicting_identity",
    "M2C-23": "needs_review",
    "M2C-01": "card_identity_only",
    "M2C-13": "card_identity_only",
    "M2C-16": "card_identity_only",
    "M2C-17": "resolved_local_page",
    "M2C-07": "identified_not_local (url_only in the 7A join)",
}


def edge_cases(datasets: Mapping[str, Mapping[str, Any]], regressions: Mapping[str, Mapping[str, Any]], backend: Any, ctx: "pid.IdentityContext") -> Dict[str, Any]:
    """For each known edge card: (a) the queries in which it is naturally rank 1, (b) a forced selection through the caller-side
    ``selector`` hook on a recorded query that expects the card (the card's real rank and distance are reported; the forcing is
    stated, it is not a routing decision by rank)."""
    out: Dict[str, Any] = {}
    for sid, label in EDGE_CARDS.items():
        natural = [(name, p["id"]) for name in regressions for p in regressions[name]["per_query"] if p["rank1"] == sid]
        q = next((r for name in datasets for r in datasets[name]["rows"] if sid in r["expected"]), None)
        entry: Dict[str, Any] = {"label": label, "natural_rank1_queries": [f"{a}:{b}" for a, b in natural], "natural_rank1_count": len(natural)}
        if q is not None:
            idr = pid.route_to_identity(q["query"], backend, ctx, top_k=EXPECTED_COUNT, selector=_forced(sid))
            full = rt.route(q["query"], backend, top_k=EXPECTED_COUNT).candidates
            card = next(c for c in full if c.source_id == sid)
            cs = cit.cite_card(card, ctx, query=q["query"])
            e = _first_row(cs)
            ident = idr.identity
            entry["forced_on_query"] = q["id"]
            entry["forced"] = {
                "rank_of_card": card.rank, "distance": round(card.distance, DIST_DECIMALS), "rank1_of_that_query": full[0].source_id,
                "route_state_7c": idr.route_state, "join_state_7a": idr.join_state_7a, "page_content_available": idr.page_content_available,
                "effective_guide_id": ident.effective_guide_id, "effective_page_id": ident.effective_page_id,
                "card_needs_review": ident.card_needs_review, "has_source_correction": card.has_source_correction,
                "source_status": card.source_status, "source_url_status": card.source_url_status,
                "citation": {"origin": e["origin"], "url": e["url"], "url_byte_identical_to_card": e["url"] == card.source_url,
                             "review_flag": e["review_flag"], "review_reasons": e["review_reasons"], "used_as_answer_text": e["used_as_answer_text"],
                             "verified_used": e["verified_used"], "flags": e["flags"], "citation": e["citation"],
                             "correction_present": bool(e["identity"]["correction"]), "conflict_present": bool(e["identity"]["conflict"]),
                             "probe_evidence_used_as_effective_guide": any(p.get("used_as_effective_guide") for p in e["identity"]["probe_evidence"]),
                             "local_content_is_legacy_copy": (e["identity"]["local_content"] or {}).get("is_legacy_local_copy"),
                             "fresh_network_fetch_claimed": (e["identity"]["local_content"] or {}).get("fresh_network_fetch_claimed")},
                "warnings": list(idr.warnings),
            }
        out[sid] = entry
    # no card candidate: empty query, and a caller selector that rejects everything (candidates stay visible)
    empty = pid.route_to_identity("", backend, ctx)
    rej = pid.route_to_identity("What is a contract account?", backend, ctx, selector=lambda cands: None)
    cs_empty = cit.cite_outcome(route_to_page("   ", backend, ctx.page_index), ctx)
    cs_rej = cit.cite_outcome(route_to_page("What is a contract account?", backend, ctx.page_index, selector=lambda cands: None), ctx)
    out["no_card_candidate"] = {
        "empty_query": {"route_state_7c": empty.route_state, "fallback_reason": empty.fallback_reason, "sources": len(cs_empty.sources)},
        "selector_rejects_all": {"route_state_7c": rej.route_state, "fallback_reason": rej.fallback_reason, "sources": len(cs_rej.sources)},
    }
    return out


# ---------------------------------------------------------------------------------------------------- item 2: legacy regression (recorded) + card overlay


def legacy_is_match(title: str, expected: Sequence[str]) -> bool:
    """The legacy loose rule (evaluate_retrieval.is_match): expected title is a case-insensitive substring of the retrieved title."""
    t = title.strip().lower()
    return bool(expected) and any(e.lower() in t for e in expected)


def legacy_is_strict(title: str, expected: Sequence[str]) -> bool:
    t = title.strip().lower()
    return any(e.strip().lower() == t for e in expected)


def legacy_rescore(questions: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Re-score the RECORDED legacy results (titles in rank order) with the legacy rules. Nothing is run live."""
    by_id = {r["id"]: r for r in results}
    scored = [q for q in questions if q["expected_titles"]]
    ood = [q for q in questions if not q["expected_titles"]]
    loose = {1: 0, 3: 0, 5: 0}
    strict = {1: 0, 3: 0, 5: 0}
    stored_match_ranks_agree = 0
    for q in scored:
        r = by_id[q["id"]]
        titles = r["retrieved_titles"]
        lm = [i + 1 for i, t in enumerate(titles) if legacy_is_match(t, q["expected_titles"])]
        sm = [i + 1 for i, t in enumerate(titles) if legacy_is_strict(t, q["expected_titles"])]
        stored_match_ranks_agree += int(lm == r["match_ranks"] and sm == r["strict_match_ranks"])
        for k in (1, 3, 5):
            loose[k] += int(any(x <= k for x in lm))
            strict[k] += int(any(x <= k for x in sm))
    return {"questions_total": len(questions), "scored_questions": len(scored), "out_of_domain_questions": len(ood),
            "loose_hits": {f"top{k}": v for k, v in loose.items()}, "strict_hits": {f"top{k}": v for k, v in strict.items()},
            "stored_match_ranks_agree_with_rescoring": stored_match_ranks_agree, "source": "recorded data/retrieval_results.json (not a live run)"}


def legacy_overlay(questions: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]], backend: Any, ctx: "pid.IdentityContext") -> Dict[str, Any]:
    """Route the 30 legacy questions through the card router and join to the RECORDED legacy top-5 page URLs by page id (7D rule).
    Descriptive counts only: the legacy labels are titles, so no card-level correctness is claimed."""
    by_id = {r["id"]: r for r in results}
    pairs = cit.recorded_numeric_pairs(ctx)
    rows: List[Dict[str, Any]] = []
    for q in questions:
        r = by_id[q["id"]]
        full = rt.route(q["question"], backend, top_k=EXPECTED_COUNT).candidates
        dist = [c.distance for c in full]
        idr = pid.route_to_identity(q["question"], backend, ctx)
        card = full[0]
        chunks = [{"metadata": {"title": t, "url": u}} for t, u in zip(r["retrieved_titles"], r["retrieved_urls"])]
        cs = cit.cite_card(card, ctx, chunks, query=q["question"])
        joined = [i + 1 for i, e in enumerate(cs.sources[1:]) if e["join"]["joined_to_card"]]
        rows.append({"id": q["id"], "category": q.get("category"), "in_domain": bool(q["expected_titles"]),
                     "rank1_card": card.source_id, "rank1_distance": round(dist[0], DIST_DECIMALS), "gap_rank1_rank2": gap12(dist),
                     "near_tie_bin": tie_bin(gap12(dist)), "route_state_7c": idr.route_state, "join_state_7a": idr.join_state_7a,
                     "page_content_available": idr.page_content_available, "card_needs_review": bool(idr.identity.card_needs_review),
                     "legacy_top5_joined_to_routed_card_at_ranks": joined,
                     "legacy_top5_page_ids": [(e["page_id"]) for e in cs.sources[1:]],
                     "legacy_chunk_urls_unmodified": all(e["url"] == u for e, u in zip(cs.sources[1:], r["retrieved_urls"])),
                     "card_route_used_as_text": cs.sources[0]["used_as_answer_text"]})
    n_join = sum(1 for x in rows if x["legacy_top5_joined_to_routed_card_at_ranks"])
    return {"questions": len(rows), "rank1_card_counts": dict(sorted(_count(x["rank1_card"] for x in rows).items())),
            "route_state_counts": dict(sorted(_count(x["route_state_7c"] for x in rows).items())),
            "routed_to_local_page": sum(1 for x in rows if x["page_content_available"]),
            "routed_to_review_card": sum(1 for x in rows if x["card_needs_review"]),
            "near_tie_counts": dict(sorted(_count(x["near_tie_bin"] for x in rows).items())),
            "questions_with_legacy_top5_page_joined_to_routed_card": n_join,
            "legacy_chunk_urls_unmodified_for_all": all(x["legacy_chunk_urls_unmodified"] for x in rows),
            "numeric_pairs_used_for_joins": {k: v for k, v in pairs.items()},
            "note": "legacy labels are titles, not cards or page ids; these counts describe agreement of two different retrieval stages, "
                    "not correctness. The recorded legacy results are the only legacy evidence; legacy mode was not run live.",
            "per_question": rows}


def _count(it) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


# ---------------------------------------------------------------------------------------------------- item 3: answerable subset


def answerable_subset(ctx: "pid.IdentityContext", regressions: Mapping[str, Mapping[str, Any]], legacy_rows: Sequence[Mapping[str, Any]],
                      cards: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    cards = pid.load_cards(ctx.root) if cards is None else cards
    ids = [pid.resolve_identity(c, ctx) for c in cards]
    with_text = [i.source_id for i in ids if i.local_page_available]
    sufficient = len(with_text) >= LOCAL_PAGE_TOPICS_EXPECTED_MIN
    router_hits = {name: {"rank1_is_local_topic": sum(1 for p in reg["per_query"] if p["rank1"] in with_text),
                          "expected_is_local_topic": sum(1 for p in reg["per_query"] if set(p["expected"]) & set(with_text))}
                   for name, reg in regressions.items()}
    return {
        "topics_with_local_page_text": with_text, "count": len(with_text), "of": len(ids),
        "minimum_topics_for_a_page_level_comparison": LOCAL_PAGE_TOPICS_EXPECTED_MIN,
        "subset_large_enough": sufficient, "routed_mode_implemented": False, "routed_mode_stays_off": True,
        "page_level_labels_available": False,
        "page_level_labels_note": "the 30 legacy questions are labelled by page title and the card sets by card id; there are no page-id labels, "
                                  "and titles are never used to join (spec 7B). A page-level hit rate for legacy vs routed cannot be formed without inventing labels.",
        "router_counts_on_phase_sets": router_hits,
        "legacy_questions_routed_to_local_topic": sum(1 for x in legacy_rows if x["page_content_available"]),
        "legacy_questions_with_recorded_top5_page_joined_to_local_topic_card": sum(
            1 for x in legacy_rows if x["page_content_available"] and x["legacy_top5_joined_to_routed_card_at_ranks"]),
        "conclusion": ("the subset is too small to conclude anything about routed vs legacy (one topic with page text); the comparison is not run, "
                       "and the routed mode stays off" if not sufficient else "subset size reached the stated minimum; a comparison would still need a routed mode"),
    }


# ---------------------------------------------------------------------------------------------------- store read-only identity


def store_logical_snapshot(vector_dir: Path) -> Dict[str, Any]:
    import chromadb
    import hashlib
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
    col = client.get_collection(C.COLLECTION_NAME)
    got = col.get(include=["documents", "metadatas", "embeddings"])
    order = sorted(range(len(got["ids"])), key=lambda i: got["ids"][i])
    h = hashlib.sha256()
    for i in order:
        h.update(json.dumps([got["ids"][i], got["documents"][i], got["metadatas"][i]], sort_keys=True).encode("utf-8"))
        h.update(b"".join(float(x).hex().encode("ascii") for x in got["embeddings"][i]))
    return {"collections": sorted(getattr(c, "name", c) for c in client.list_collections()), "count": col.count(),
            "space": (col.metadata or {}).get("hnsw:space"), "logical_content_sha256": h.hexdigest()}


# ---------------------------------------------------------------------------------------------------- evaluation


def evaluate(vector_dir: Path = C.VECTOR_DIR, backend: Any = None, ctx: Optional["pid.IdentityContext"] = None,
             snapshot: bool = True) -> Dict[str, Any]:
    ctx = ctx or pid.IdentityContext.from_root(ROOT)
    backend = backend or rt.ChromaCardBackend(vector_dir=vector_dir)
    before = store_logical_snapshot(vector_dir) if snapshot else None
    datasets = recorded_datasets()
    regs = {name: router_regression(name, data, backend, ctx) for name, data in datasets.items()}
    layers = {name: aggregate_layers(reg["per_query"]) for name, reg in regs.items()}
    edges = edge_cases(datasets, regs, backend, ctx)
    questions = load(LEGACY_QUESTIONS)
    results = load(LEGACY_RESULTS)
    legacy = {"mode_legacy": {"run_live": False, "reason": "legacy chroma_db and the legacy embedding model name are not available in this environment, "
                                                           "and rag_core is protected; the recorded results are re-scored instead (spec 0.4: user's machine)",
                              "recorded_rescore": legacy_rescore(questions, results)},
              "mode_routed": {"implemented": False, "run_live": False,
                              "reason": "no routed mode exists: the plan's orchestrator (soft boost) was realised as the 7C identity layer, which carries no page chunks. "
                                        "Spec 7E item 3: with one topic of page text the routed mode stays off."},
              "card_overlay": legacy_overlay(questions, results, backend, ctx)}
    subset = answerable_subset(ctx, regs, legacy["card_overlay"]["per_question"])
    after = store_logical_snapshot(vector_dir) if snapshot else None
    loaded = sorted(m for m in BANNED_MODULES if m in sys.modules)
    pc = {"phase4": regs["phase4"], "phase5": regs["phase5"]}
    checks = [
        check("phase4: router top-1 == recorded for all queries", pc["phase4"]["comparison_with_recorded"]["top1_identical"] == 50, pc["phase4"]["comparison_with_recorded"]["top1_identical"]),
        check("phase4: router top-5 ordering == recorded for all queries", pc["phase4"]["comparison_with_recorded"]["top5_ordering_identical"] == 50),
        check("phase4: expected-card ranks == recorded for all queries", pc["phase4"]["comparison_with_recorded"]["expected_rank_identical"] == 50),
        check("phase4: metrics (R@1/3/5, MRR, coverage, hits) == recorded, overall and by type", pc["phase4"]["metrics_equal_to_recorded"] and pc["phase4"]["by_type_equal_to_recorded"], pc["phase4"]["router_metrics"]),
        check("phase5: router top-1 == recorded for all queries", pc["phase5"]["comparison_with_recorded"]["top1_identical"] == 54, pc["phase5"]["comparison_with_recorded"]["top1_identical"]),
        check("phase5: router top-5 ordering == recorded for all queries", pc["phase5"]["comparison_with_recorded"]["top5_ordering_identical"] == 54),
        check("phase5: expected-card ranks == recorded for all queries", pc["phase5"]["comparison_with_recorded"]["expected_rank_identical"] == 54),
        check("phase5: metrics (R@1/3/5, MRR, coverage, hits) == recorded, overall and by type", pc["phase5"]["metrics_equal_to_recorded"] and pc["phase5"]["by_type_equal_to_recorded"], pc["phase5"]["router_metrics"]),
        check("recorded similarities reproduced (4 dp) for all 104 queries", all(pc[n]["comparison_with_recorded"]["similarity_mismatches_after_4dp"] == 0 for n in pc)),
        check("default router path (route_to_identity, default top_k) == prefix of the full ranking, rank-1 equal, for all 104 queries",
              pc["phase4"]["comparison_with_recorded"]["default_path_equals_prefix_of_full_ranking"] == 50
              and pc["phase5"]["comparison_with_recorded"]["default_path_equals_prefix_of_full_ranking"] == 54),
        check("no ranking difference to explain (0 differing queries)", not pc["phase4"]["differing_queries"] and not pc["phase5"]["differing_queries"]),
        check("citation layer: every selected card has its URL byte-identical, review flag == needs_review, card_route never used text",
              all(layers[n]["citation"][k] for n in layers for k in layers[n]["citation"])),
        check("edge cases: M2C-05 corrected, M2C-18 conflicting without effective guide, M2C-01/13/16 card_identity_only, M2C-17 resolved_local_page",
              edges["M2C-05"]["forced"]["route_state_7c"] == "corrected_identity" and edges["M2C-18"]["forced"]["route_state_7c"] == "conflicting_identity"
              and edges["M2C-18"]["forced"]["effective_guide_id"] is None
              and all(edges[s]["forced"]["route_state_7c"] == "card_identity_only" for s in ("M2C-01", "M2C-13", "M2C-16"))
              and edges["M2C-17"]["forced"]["route_state_7c"] == "resolved_local_page"),
        check("edge cases: M2C-14, 18, 23 carry the review flag; no other edge card does",
              all(edges[s]["forced"]["citation"]["review_flag"] for s in ("M2C-14", "M2C-18", "M2C-23"))
              and not any(edges[s]["forced"]["citation"]["review_flag"] for s in ("M2C-05", "M2C-01", "M2C-13", "M2C-16", "M2C-17", "M2C-07"))),
        check("no_card_candidate: empty query and rejecting selector give no sources", edges["no_card_candidate"]["empty_query"]["sources"] == 0
              and edges["no_card_candidate"]["selector_rejects_all"]["sources"] == 0),
        check("legacy: recorded results re-score to the recorded match ranks (25 scored questions)", legacy["mode_legacy"]["recorded_rescore"]["stored_match_ranks_agree_with_rescoring"] == 25),
        check("legacy overlay: recorded legacy chunk URLs are reported unmodified", legacy["card_overlay"]["legacy_chunk_urls_unmodified_for_all"]),
        check("answerable subset: counted from the repository, not inferred", subset["topics_with_local_page_text"] == ["M2C-17"], subset["topics_with_local_page_text"]),
        check("store: logical content (ids, documents, metadata, vectors) identical before and after the evaluation",
              before == after if snapshot else True, {"count": (after or {}).get("count"), "collections": (after or {}).get("collections")}),
        check("no network attempt", not NetworkGuard.attempts, len(NetworkGuard.attempts)),
        check("no LLM / legacy-pipeline module loaded", not loaded, loaded),
    ]
    return {
        "schema_version": 1, "spec": "data/phase6_next_phase_spec.md#7E",
        "scope": {"retrieval_changed": False, "threshold_applied": False, "answer_generated": False, "pages_fetched_or_ingested": False,
                  "rank1_is_not_confidence": True, "distance_metric": "cosine"},
        "inputs": {"collection_manifest_sha256": C.sha256_file(ROOT / "data" / "card_collection_manifest.json"),
                   "retrieval_units_sha256": C.sha256_file(C.UNITS_PATH), "phase4_results_sha256": C.sha256_file(P4_RESULTS),
                   "phase5_results_sha256": C.sha256_file(P5_RESULTS), "phase5_queries_sha256": C.sha256_file(P5_QUERIES),
                   "legacy_questions_sha256": C.sha256_file(LEGACY_QUESTIONS), "legacy_results_sha256": C.sha256_file(LEGACY_RESULTS)},
        "store": {"before": before, "after": after},
        "router_regression": {n: {k: v for k, v in reg.items() if k != "per_query"} for n, reg in regs.items()},
        "routing_layers": layers,
        "edge_cases": edges,
        "legacy_regression": {k: ({kk: vv for kk, vv in v.items() if kk != "per_question"} if k == "card_overlay" else v) for k, v in legacy.items()},
        "answerable_subset": subset,
        "per_query": {n: reg["per_query"] for n, reg in regs.items()},
        "legacy_per_question": legacy["card_overlay"]["per_question"],
        "isolation": {"network_attempts": len(NetworkGuard.attempts), "banned_modules_loaded": loaded},
        "checks": checks, "ok": all(c["ok"] for c in checks),
    }


def render_json(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7E: router and regression evaluation (read-only; needs the card store and the local model).")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--vector-dir", default=str(C.VECTOR_DIR))
    args = ap.parse_args(argv)
    NetworkGuard.install()
    doc = evaluate(Path(args.vector_dir))
    Path(args.out).write_text(render_json(doc), encoding="utf-8")
    bad = [c["check"] for c in doc["checks"] if not c["ok"]]
    print(f"checks: {len(doc['checks']) - len(bad)}/{len(doc['checks'])} ok" + (f"; FAILED: {bad}" if bad else ""))
    for n in ("phase4", "phase5"):
        print(n, doc["router_regression"][n]["router_metrics"])
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
