#!/usr/bin/env python3
"""Phase 12 (G) - read-only router failure audit over the Phase 12 set and the older question sets. NO router change is made or evaluated here.

Implements the pre-declared first-match-wins rules of ``data/phase12_contract.md`` section G:
  identity_hub -> sibling_ambiguity -> vocabulary_mismatch -> query_underspecified -> near_tie_embedding -> other_ranking
plus the separate flags ``gold_page_not_available`` and (for answerable questions whose top-1 is right) ``ood_gate``.
Output: ``data/evaluation/phase12_failure_audit.json``.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "evaluation" / "phase12_failure_audit.json"
SETS = {
    "phase12": "phase12_queries.json", "phase8": "phase8_queries.json", "phase9": "phase9_queries.json", "phase10_dev": "phase10_dev_queries.json", "phase10_test": "phase10_test_queries.json",
    "phase11_1_holdout": "phase11_1_holdout_questions.json", "phase11_1_holdout2": "phase11_1_holdout2_questions.json", "phase11_e2e": "phase11_e2e_questions.json",
}
HUB_STATUSES = ("conflicting_identity", "card_identity_only")
RULES = ("identity_hub", "sibling_ambiguity", "vocabulary_mismatch", "query_underspecified", "near_tie_embedding", "other_ranking")
NEAR_TIE = 0.05


def load_set(name: str) -> List[Dict[str, Any]]:
    d = json.loads((ROOT / "data" / "evaluation" / SETS[name]).read_text(encoding="utf-8"))
    out = []
    for q in d.get("queries") or d.get("questions"):
        out.append({"id": q["id"], "query": q.get("query") or q.get("question"), "type": q.get("type"),
                    "gold": q.get("gold_source_id") or q.get("expected_card"), "acceptable": list(q.get("acceptable_source_ids") or []), "category": q.get("category") or q.get("facet"),
                    "expected_status": q.get("expected_status")})
    return out


def gold_ids(q: Dict[str, Any]) -> List[str]:
    return [g for g in ([q["gold"]] if q["gold"] and q["type"] != "ambiguous" else q["acceptable"]) if g]


def classify_miss(q: Dict[str, Any], ranked: Sequence[Dict[str, Any]], card_terms: Dict[str, set], card_category: Dict[str, str], identity: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """``ranked`` = [{source_id, similarity}] best first. Returns None when the best gold/acceptable card is top-1; else the first-match rule."""
    import rag_text as T
    golds = gold_ids(q)
    order = [r["source_id"] for r in ranked]
    ranks = {g: order.index(g) + 1 for g in golds if g in order}
    if not ranks or min(ranks.values()) == 1:
        return None
    gold = min(ranks, key=ranks.get)
    gold_rank = ranks[gold]
    top1 = ranked[0]
    q_terms = set(T.terms(q["query"]))
    margin = round(top1["similarity"] - next(r["similarity"] for r in ranked if r["source_id"] == gold), 4)
    if identity.get(top1["source_id"]) in HUB_STATUSES:
        rule = "identity_hub"
    elif card_category.get(top1["source_id"]) == card_category.get(gold) and gold_rank <= 3:
        rule = "sibling_ambiguity"
    elif not (q_terms & card_terms[gold]):
        rule = "vocabulary_mismatch"
    elif len(q_terms) < 3 or q["type"] == "ambiguous":
        rule = "query_underspecified"
    elif margin <= NEAR_TIE:
        rule = "near_tie_embedding"
    else:
        rule = "other_ranking"
    return {"id": q["id"], "rule": rule, "gold": gold, "gold_rank": gold_rank, "top1": top1["source_id"], "margin": margin, "type": q["type"], "category": q["category"]}


def main() -> int:
    import rag_pipeline as RP
    import rag_text as T
    units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
    units = units["units"] if isinstance(units, dict) else units
    card_terms = {u["source_id"]: T.term_set(u["title"] + " " + u["full_text"]) for u in units}
    card_category = {u["source_id"]: u["category"] for u in units}
    ident = {c["source_id"]: c for c in json.loads((ROOT / "data" / "m2c_page_identity.json").read_text(encoding="utf-8"))["cards"]}
    identity = {k: v["resolution_status"] for k, v in ident.items()}
    local = {k: bool(v.get("local_page_available")) for k, v in ident.items()}
    pipe = RP.build_pipeline(generator="extractive")
    result: Dict[str, Any] = {"schema_version": 1, "rules": list(RULES), "near_tie_margin": NEAR_TIE, "note": "read-only audit; no router change evaluated or adopted (contract G)", "sets": {}}
    total = Counter()
    for name in SETS:
        qs = [q for q in load_set(name) if gold_ids(q)]
        misses, gate = [], []
        for q in qs:
            raw = pipe.backend.query(q["query"], 29)
            ranked = [{"source_id": m["source_id"], "similarity": round(1.0 - d, 4)} for m, d in zip(raw["metadatas"][0], raw["distances"][0])]
            m = classify_miss(q, ranked, card_terms, card_category, identity)
            if m:
                m["gold_page_not_available"] = not local.get(m["gold"], False)
                misses.append(m)
            elif q["type"] == "answerable":
                a = pipe.answer(q["query"])
                if a["status"] in ("out_of_domain", "no_relevant_page"):
                    gate.append({"id": q["id"], "status": a["status"], "reason": a["reason_code"], "selected": a["routing"]["selected_source_id"]})
        counts = Counter(m["rule"] for m in misses)
        result["sets"][name] = {"n_with_gold_card": len(qs), "router_top1_misses": len(misses), "rule_counts": dict(counts), "gold_page_not_available": sum(1 for m in misses if m["gold_page_not_available"]),
                                "ood_gate_on_correct_top1": gate, "misses": misses}
        total.update(counts)
        print(f"{name:20s} n={len(qs):3d} misses={len(misses):3d} {dict(counts)} ood_gate={len(gate)}")
    result["total_rule_counts"] = dict(total)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("total", dict(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
