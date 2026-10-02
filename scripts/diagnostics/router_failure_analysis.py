#!/usr/bin/env python3
"""Phase 12 diagnostic script - in-depth router failure analysis and real-vs-oracle gap cross-reference.
Read-only analysis tool: does not modify router, stores, or question sets.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import m2c_common as C
import m2c_router as MR
import rag_pipeline as RP
import rag_text as T


def load_data():
    queries_path = ROOT / "data" / "evaluation" / "phase12_queries.json"
    results_path = ROOT / "data" / "evaluation" / "phase12_results_25pages.json"
    units_path = ROOT / "data" / "retrieval_units.json"
    identity_path = ROOT / "data" / "m2c_page_identity.json"

    queries_data = json.loads(queries_path.read_text(encoding="utf-8"))
    results_data = json.loads(results_path.read_text(encoding="utf-8"))
    units_data = json.loads(units_path.read_text(encoding="utf-8"))
    identity_data = json.loads(identity_path.read_text(encoding="utf-8"))

    queries = queries_data["queries"]
    units = {u["source_id"]: u for u in (units_data["units"] if isinstance(units_data, dict) else units_data)}
    cards_ident = {c["source_id"]: c for c in identity_data["cards"]}
    configs = results_data["configs"]

    return queries, results_data, units, cards_ident, configs


def analyze_router():
    queries, results_data, units, cards_ident, configs = load_data()

    # Load router backend
    pipe = RP.build_pipeline(generator="extractive")
    backend = pipe.backend

    categories = {sid: u["category"] for sid, u in units.items()}
    titles = {sid: u["title"] for sid, u in units.items()}
    card_terms = {sid: T.term_set(u["title"] + " " + u["full_text"]) for sid, u in units.items()}
    card_embed_terms = {sid: T.term_set(u["embedding_text"]) for sid, u in units.items()}

    sibling_groups = [
        {"M2C-02", "M2C-03", "M2C-04", "M2C-10"},  # Move-In / Move-Out / Meter Reading at Move-In
        {"M2C-05", "M2C-06", "M2C-07", "M2C-08", "M2C-09"},  # Device Management / Meter Reading / Estimation / Monitoring
        {"M2C-11", "M2C-12", "M2C-13", "M2C-14", "M2C-15", "M2C-16"},  # Billing / Invoicing / Budget Billing
        {"M2C-17", "M2C-18"},  # Contract Accounts Overview vs Business Object
        {"M2C-19", "M2C-20", "M2C-21", "M2C-22"},  # Incoming Payments / Clearing / Cash Desks
        {"M2C-23", "M2C-24", "M2C-25"},  # Installment Plans Overview / Create / Display
        {"M2C-26", "M2C-27", "M2C-28"},  # Dunning / Collection Agency
        {"M2C-29"},  # Disconnection / Reconnection
    ]
    card_to_group = {}
    for gid, group in enumerate(sibling_groups):
        for sid in group:
            card_to_group[sid] = gid

    all_gold_questions = [q for q in queries if q.get("gold_source_id") or q.get("acceptable_source_ids")]
    answerable_questions = [q for q in queries if q.get("type") == "answerable"]

    router_rankings = {}
    for q in queries:
        raw = backend.query(q["query"], 29)
        ranked = [{"source_id": m["source_id"], "similarity": round(1.0 - d, 4), "distance": round(d, 4)}
                  for m, d in zip(raw["metadatas"][0], raw["distances"][0])]
        order = [r["source_id"] for r in ranked]
        
        golds = [q["gold_source_id"]] if q["type"] != "ambiguous" else list(q.get("acceptable_source_ids") or [])
        ranks = {g: order.index(g) + 1 for g in golds if g in order}
        best_gold = min(ranks, key=ranks.get) if ranks else None
        best_rank = ranks[best_gold] if best_gold else None
        
        router_rankings[q["id"]] = {
            "ranked": ranked,
            "order": order,
            "best_gold": best_gold,
            "best_rank": best_rank,
            "top1": ranked[0]["source_id"],
            "top1_sim": ranked[0]["similarity"],
            "gold_sim": next((r["similarity"] for r in ranked if r["source_id"] == best_gold), None) if best_gold else None,
        }

    # Summary counts
    total_gold_q = len(all_gold_questions)
    r1_correct = sum(1 for q in all_gold_questions if router_rankings[q["id"]]["best_rank"] == 1)
    r3_correct = sum(1 for q in all_gold_questions if router_rankings[q["id"]]["best_rank"] is not None and router_rankings[q["id"]]["best_rank"] <= 3)
    r5_correct = sum(1 for q in all_gold_questions if router_rankings[q["id"]]["best_rank"] is not None and router_rankings[q["id"]]["best_rank"] <= 5)
    r1_failures = total_gold_q - r1_correct
    in_top3_not_top1 = r3_correct - r1_correct
    in_top5_not_top3 = r5_correct - r3_correct
    outside_top5 = total_gold_q - r5_correct

    print("=" * 80)
    print("ALL GOLD-CARD QUESTIONS (n = %d):" % total_gold_q)
    print("  R@1 correct: %d (%.2f%%)" % (r1_correct, r1_correct / total_gold_q * 100))
    print("  R@1 failures: %d (%.2f%%)" % (r1_failures, r1_failures / total_gold_q * 100))
    print("    - Gold in top 2-3: %d" % in_top3_not_top1)
    print("    - Gold in top 4-5: %d" % in_top5_not_top3)
    print("    - Gold outside top 5: %d" % outside_top5)

    # Now focus on ANSWERABLE questions (n = 65)
    ans_total = len(answerable_questions)
    ans_r1_correct = sum(1 for q in answerable_questions if router_rankings[q["id"]]["best_rank"] == 1)
    ans_r3_correct = sum(1 for q in answerable_questions if router_rankings[q["id"]]["best_rank"] is not None and router_rankings[q["id"]]["best_rank"] <= 3)
    ans_r5_correct = sum(1 for q in answerable_questions if router_rankings[q["id"]]["best_rank"] is not None and router_rankings[q["id"]]["best_rank"] <= 5)
    ans_r1_failures = ans_total - ans_r1_correct
    ans_in_top3_not_top1 = ans_r3_correct - ans_r1_correct
    ans_in_top5_not_top3 = ans_r5_correct - ans_r3_correct
    ans_outside_top5 = ans_total - ans_r5_correct

    print("\nANSWERABLE QUESTIONS (n = %d):" % ans_total)
    print("  R@1 correct: %d (%.2f%%)" % (ans_r1_correct, ans_r1_correct / ans_total * 100))
    print("  R@1 failures: %d (%.2f%%)" % (ans_r1_failures, ans_r1_failures / ans_total * 100))
    print("    - Gold in top 2-3: %d" % ans_in_top3_not_top1)
    print("    - Gold in top 4-5: %d" % ans_in_top5_not_top3)
    print("    - Gold outside top 5: %d" % ans_outside_top5)

    classification_counts = Counter()
    failed_details = []

    base_pq = configs["baseline"]["per_query"]
    ev_pq = configs["evidence"]["per_query"]
    oraw_pq = configs["ollama_raw"]["per_query"]
    ollama_pq = configs["ollama"]["per_query"]

    for q in answerable_questions:
        rinfo = router_rankings[q["id"]]
        if rinfo["best_rank"] == 1:
            continue

        gold = rinfo["best_gold"]
        top1 = rinfo["top1"]
        rank = rinfo["best_rank"]
        top1_sim = rinfo["top1_sim"]
        gold_sim = rinfo["gold_sim"]
        margin = round(top1_sim - gold_sim, 4)

        q_terms = set(T.terms(q["query"]))
        gold_c_terms = card_terms.get(gold, set())
        overlap = q_terms & gold_c_terms

        b_rec = base_pq.get(q["id"], {})
        e_rec = ev_pq.get(q["id"], {})
        oraw_rec = oraw_pq.get(q["id"], {})
        oll_rec = ollama_pq.get(q["id"], {})

        b_real = b_rec.get("real", {})
        b_oracle = b_rec.get("oracle", {})
        e_real = e_rec.get("real", {})
        e_oracle = e_rec.get("oracle", {})
        oll_real = oll_rec.get("real", {})
        oll_oracle = oll_rec.get("oracle", {})

        is_oracle_casualty_base = (b_oracle.get("correct") is True and b_real.get("correct") is not True)
        is_oracle_casualty_ev = (e_oracle.get("correct") is True and e_real.get("correct") is not True)
        is_oracle_casualty_oll = (oll_oracle.get("correct") is True and oll_real.get("correct") is not True)

        is_sibling = (categories.get(top1) == categories.get(gold)) or (card_to_group.get(top1) == card_to_group.get(gold))

        # Classify root cause
        # Check specific patterns
        if top1 == "M2C-18" and gold == "M2C-17":
            primary_diag = "near-duplicate/semantically competing card (M2C-17 vs M2C-18 Contract Accounts conflict hub)"
        elif is_sibling and rank <= 3:
            primary_diag = "near-duplicate/semantically competing card (functional sibling in same category/domain)"
        elif len(overlap) == 0:
            primary_diag = "query/card vocabulary mismatch (zero content-term overlap between query and card)"
        elif rank > 5:
            primary_diag = "gold card absent from top-k (ranked beyond #5)"
        elif margin <= 0.03:
            primary_diag = "near-tie dense embedding limitation (margin <= 0.03)"
        else:
            primary_diag = "card description weakness / subtopic omission (card lacks specific detail/transaction mentioned in query)"

        classification_counts[primary_diag] += 1

        failed_details.append({
            "id": q["id"],
            "query": q["query"],
            "category": q["category"],
            "gold": gold,
            "gold_title": titles.get(gold),
            "top1": top1,
            "top1_title": titles.get(top1),
            "rank": rank,
            "top1_sim": top1_sim,
            "gold_sim": gold_sim,
            "margin": margin,
            "primary_diag": primary_diag,
            "top3": rinfo["order"][:3],
            "top5": rinfo["order"][:5],
            "b_real_outcome": b_real.get("outcome"),
            "b_oracle_outcome": b_oracle.get("outcome"),
            "e_real_outcome": e_real.get("outcome"),
            "e_oracle_outcome": e_oracle.get("outcome"),
            "oll_real_outcome": oll_real.get("outcome"),
            "oll_oracle_outcome": oll_oracle.get("outcome"),
            "is_oracle_casualty_base": is_oracle_casualty_base,
            "is_oracle_casualty_ev": is_oracle_casualty_ev,
            "is_oracle_casualty_oll": is_oracle_casualty_oll,
            "overlap_terms": list(overlap),
        })

    print("\nPRIMARY DIAGNOSTIC BREAKDOWN FOR ANSWERABLE FAILURES (n = 35):")
    for diag, cnt in classification_counts.most_common():
        print("  %-75s : %2d (%5.1f%%)" % (diag, cnt, cnt / ans_r1_failures * 100))

    # Cross-reference against real-vs-oracle gap
    b_casualties = [f for f in failed_details if f["is_oracle_casualty_base"]]
    e_casualties = [f for f in failed_details if f["is_oracle_casualty_ev"]]
    oll_casualties = [f for f in failed_details if f["is_oracle_casualty_oll"]]

    print("\nREAL-VS-ORACLE CASUALTIES AMONG ANSWERABLE ROUTER MISSES:")
    print("  Baseline:  %d / 35 router misses were Oracle-correct answers (%.1f%%)" % (len(b_casualties), len(b_casualties) / ans_r1_failures * 100))
    print("  Evidence:  %d / 35 router misses were Oracle-correct answers (%.1f%%)" % (len(e_casualties), len(e_casualties) / ans_r1_failures * 100))
    print("  Ollama:    %d / 35 router misses were Oracle-correct answers (%.1f%%)" % (len(oll_casualties), len(oll_casualties) / ans_r1_failures * 100))

    # How many answerable questions overall suffered in the real-vs-oracle gap?
    # Total baseline: oracle=53, real=24 -> diff = 29
    # Check if all 29 lost answers come from router misses
    lost_q_base = [q["id"] for q in answerable_questions if base_pq[q["id"]]["oracle"].get("correct") is True and base_pq[q["id"]]["real"].get("correct") is not True]
    print("\nTotal Answerable questions where Oracle is Correct but Real is NOT:")
    print("  Baseline: %d questions" % len(lost_q_base))
    print("  Of which router missed R@1: %d / %d (%.1f%%)" % (len(b_casualties), len(lost_q_base), len(b_casualties) / len(lost_q_base) * 100))

    # Non-casualty failures
    non_casualties = [f for f in failed_details if not f["is_oracle_casualty_base"]]
    print("\nRouter misses where Oracle was ALSO NOT correct in Baseline (%d questions):" % len(non_casualties))
    for nc in non_casualties:
        b_or = base_pq[nc["id"]]["oracle"]
        print("  %s: oracle outcome = %s, reason = %s" % (nc["id"], b_or.get("outcome"), b_or.get("reason")))

    # Save complete diagnostic json
    diag_out = {
        "all_gold_n": total_gold_q,
        "all_r1_correct": r1_correct,
        "all_r1_failures": r1_failures,
        "all_in_top3_not_top1": in_top3_not_top1,
        "all_in_top5_not_top3": in_top5_not_top3,
        "all_outside_top5": outside_top5,
        "answerable_n": ans_total,
        "answerable_r1_correct": ans_r1_correct,
        "answerable_r1_failures": ans_r1_failures,
        "answerable_in_top3_not_top1": ans_in_top3_not_top1,
        "answerable_in_top5_not_top3": ans_in_top5_not_top3,
        "answerable_outside_top5": ans_outside_top5,
        "classification_counts": dict(classification_counts),
        "b_casualties_count": len(b_casualties),
        "e_casualties_count": len(e_casualties),
        "oll_casualties_count": len(oll_casualties),
        "failed_details": failed_details,
    }
    
    out_file = ROOT / "data" / "evaluation" / "phase12_diagnostic_router_gap.json"
    out_file.write_text(json.dumps(diag_out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nSaved full diagnostic json to:", out_file)

    return diag_out


if __name__ == "__main__":
    analyze_router()
