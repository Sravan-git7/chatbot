"""Phase 10 - shared evaluation code for the DEV selection (``phase10_select.py``) and the sealed TEST evaluation (``evaluate_phase10.py``).

Metrics are deterministic (no timings). Definitions (declared in ``data/phase10_contract.md``):

* router rank of the gold card = position in the FULL 29-card order produced by the router (fused order for candidate R);
* ``correct_answer`` = status ``answered`` AND a cited chunk contains an evidence quote AND the cited page is the gold page;
* ``abstained`` (absent-detail queries) = status other than ``answered``;
* ``wrong_topic_answered`` = non-answerable queries (absent_detail, not_ingested, unresolved_identity, out_of_domain) that end ``answered`` in router mode.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import evaluate_phase8 as EP8  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_optimised as RO  # noqa: E402
import rag_pipeline as RP  # noqa: E402

EVAL = ROOT / "data" / "evaluation"
FREEZE = EVAL / "phase10_queries_freeze.json"
DEV = EVAL / "phase10_dev_queries.json"
TEST = EVAL / "phase10_test_queries.json"
SELECTION = EVAL / "phase10_selection.json"
NON_ANSWERABLE = ("absent_detail", "not_ingested", "unresolved_identity", "out_of_domain")
G_CANDIDATES: Tuple[Tuple[str, float, bool], ...] = (("G0_current", 0.34, False), ("G1_theta_0.5", 0.5, False), ("G1_theta_0.67", 0.67, False), ("G2_detail_cue", 0.34, True), ("G2_detail_cue+theta_0.5", 0.5, True))
ANSWERABLE_LOSS_ALLOWED_DEV = 2          # 5 % of 41 answerable queries, rounded down
TEST_RULES = {"R": {"min_r1_gain": 0.05, "sign_test_p_below": 0.05, "wrong_topic_answered_must_not_increase": True, "unresolved_and_not_ingested_routing_must_not_worsen": True},
              "G": {"min_net_correct_abstentions": 4, "max_answerable_correct_lost": 2, "grounding_all_pass": True, "phantom_citations": 0}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_set(path: Path, key: Optional[str] = None) -> Dict[str, Any]:
    """Load a frozen query file after checking its sha256 against the freeze record (a changed file stops the run)."""
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if key:
        if sha(path) != freeze["files"][key]["sha256"]:
            raise SystemExit(f"STOP: {path.name} differs from its frozen hash")
    return json.loads(path.read_text(encoding="utf-8"))


def sign_test_p(only_candidate: int, only_baseline: int) -> Optional[float]:
    n = only_candidate + only_baseline
    if n == 0:
        return None
    k = min(only_candidate, only_baseline)
    return round(min(1.0, sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n * 2), 4)


def rate(k: int, n: int) -> Dict[str, Any]:
    return EP8.prop(k, n)


def make_pipeline(base: RP.RagPipeline, lam: float, theta: float, cue: bool) -> RP.RagPipeline:
    return RO.build_optimised_pipeline(lam, theta, cue, "extractive", base=base)


def correct(q: Dict[str, Any], a: Dict[str, Any]) -> bool:
    if a["status"] != "answered" or not q.get("evidence"):
        return False
    g, p = (q["gold_doc_id"] or "/").split("/")
    cited = a["citations"]["answer_sources"]
    return any(s["guide_id"] == g and s["page_id"] == p and EP8.has_evidence(s.get("text") or "", q["evidence"]) for s in cited) if cited and "text" in cited[0] else _correct_by_context(q, a)


def _correct_by_context(q: Dict[str, Any], a: Dict[str, Any]) -> bool:
    """Evidence check through the context items of the debug block (answer_sources carry ids, not text)."""
    g, p = q["gold_doc_id"].split("/")
    items = {i["chunk_id"]: i for i in (a.get("debug", {}).get("context") or {}).get("items", [])}
    for s in a["citations"]["answer_sources"]:
        it = items.get(s["chunk_id"])
        if it and s["guide_id"] == g and s["page_id"] == p and EP8.has_evidence(it["text"], q["evidence"]):
            return True
    return False


def evaluate(base: RP.RagPipeline, queries: Sequence[Dict[str, Any]], lam: float, theta: float, cue: bool, with_oracle: bool = True) -> Dict[str, Any]:
    """Run one configuration over a query set. Returns metrics plus per-query outcomes (``per_query``) for paired tests."""
    pipe = make_pipeline(base, lam, theta, cue)
    per: Dict[str, Dict[str, Any]] = {}
    for q in queries:
        rec: Dict[str, Any] = {"type": q["type"]}
        if q.get("gold_source_id"):
            raw = pipe.backend.query(q["query"], 29)
            order = [m["source_id"] for m in raw["metadatas"][0]]
            rec["gold_rank"] = order.index(q["gold_source_id"]) + 1 if q["gold_source_id"] in order else None
            rec["top1"] = order[0]
            rec["top1_acceptable"] = order[0] == q["gold_source_id"] or order[0] in (q.get("acceptable_source_ids") or [])
        a = pipe.answer(q["query"], debug=True)
        rec["status"] = a["status"]
        rec["selected"] = a["routing"].get("selected_source_id")
        rec["correct_answer_router"] = bool(q["type"] == "answerable" and correct(q, a))
        rec["grounding_ok"] = (a["debug"].get("grounding") or {}).get("ok", True) if a["status"] == "answered" else None
        ctx_ids = {i["chunk_id"] for i in (a["debug"].get("context") or {}).get("items", [])}
        rec["phantom"] = sum(1 for s in a["citations"]["answer_sources"] if s["chunk_id"] not in ctx_ids)
        if with_oracle and q["type"] in ("answerable", "absent_detail"):
            o = pipe.answer(q["query"], debug=True, oracle_source_id=q["gold_source_id"])
            rec["oracle_status"] = o["status"]
            rec["correct_answer_oracle"] = bool(q["type"] == "answerable" and correct(q, o))
            rec["oracle_grounding_ok"] = (o["debug"].get("grounding") or {}).get("ok", True) if o["status"] == "answered" else None
            rec["oracle_phantom"] = sum(1 for s in o["citations"]["answer_sources"] if s["chunk_id"] not in {i["chunk_id"] for i in (o["debug"].get("context") or {}).get("items", [])})
        per[q["id"]] = rec
    ans = [q["id"] for q in queries if q["type"] == "answerable"]
    gold = [q["id"] for q in queries if q.get("gold_source_id")]
    ranks = [per[i]["gold_rank"] for i in ans]
    n = len(ans)
    m: Dict[str, Any] = {"config": {"lam": lam, "theta": theta, "detail_cue_check": cue}, "n_answerable": n}
    m["router_answerable"] = {**{f"recall@{k}": rate(sum(1 for r in ranks if r and r <= k), n) for k in (1, 3, 5)}, "mrr": round(sum(1 / r for r in ranks if r) / n, 4) if n else None}
    gr = [per[i]["gold_rank"] for i in gold]
    m["router_all_gold_card_queries"] = {"recall@1": rate(sum(1 for r in gr if r == 1), len(gold)), "n": len(gold)}
    for t in ("not_ingested", "unresolved_identity"):
        ids = [q["id"] for q in queries if q["type"] == t]
        m[f"router_top1_{t}"] = rate(sum(1 for i in ids if per[i]["top1_acceptable"]), len(ids)) if ids else None
    by_type: Dict[str, Any] = {}
    for t in sorted({q["type"] for q in queries}):
        ids = [q for q in queries if q["type"] == t]
        by_type[t] = rate(sum(1 for q in ids if per[q["id"]]["status"] == q["expected_status"]), len(ids))
    m["router_mode_status_match_by_type"] = by_type
    m["router_mode_correct_answers"] = rate(sum(per[i]["correct_answer_router"] for i in ans), n)
    wrong = [q["id"] for q in queries if q["type"] in NON_ANSWERABLE and per[q["id"]]["status"] == "answered"]
    m["wrong_topic_answered"] = {"count": len(wrong), "ids": wrong}
    if with_oracle:
        ab = [q["id"] for q in queries if q["type"] == "absent_detail"]
        m["oracle_correct_answers"] = rate(sum(per[i]["correct_answer_oracle"] for i in ans), n)
        m["oracle_absent_detail_abstained"] = rate(sum(1 for i in ab if per[i]["oracle_status"] != "answered"), len(ab))
        m["oracle_grounding_failures"] = sum(1 for i in ans + ab if per[i].get("oracle_grounding_ok") is False)
        m["oracle_phantom_citations"] = sum(per[i].get("oracle_phantom", 0) for i in ans + ab)
    m["router_mode_grounding_failures"] = sum(1 for r in per.values() if r["grounding_ok"] is False)
    m["router_mode_phantom_citations"] = sum(r["phantom"] for r in per.values())
    return {"metrics": m, "per_query": per}


def paired(a: Dict[str, Any], b: Dict[str, Any], ids: Sequence[str], fn) -> Dict[str, Any]:
    """Paired comparison candidate ``a`` vs baseline ``b`` for a boolean outcome ``fn(per_query_record)`` over ``ids``."""
    only_a = sum(1 for i in ids if fn(a[i]) and not fn(b[i]))
    only_b = sum(1 for i in ids if fn(b[i]) and not fn(a[i]))
    return {"only_candidate": only_a, "only_baseline": only_b, "sign_test_p_two_sided": sign_test_p(only_a, only_b)}
