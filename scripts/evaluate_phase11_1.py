#!/usr/bin/env python3
"""Phase 11.1 - baseline (B) vs evidence-checked candidates (C1, C2) on frozen question sets. Contract: ``data/phase11_1_contract.md``.

    python scripts/evaluate_phase11_1.py --set dev              # DEV: Phase 10 DEV + the 16 E2E questions, tau grid, prints per-query differences
    python scripts/evaluate_phase11_1.py --set holdout --tau 0.6    # sealed: refuses to overwrite its result file
    python scripts/evaluate_phase11_1.py --set test10 --tau 0.6     # Phase 10 TEST regression (once)
    python scripts/evaluate_phase11_1.py --set p9|p8 --tau 0.6      # regression sets

Per configuration: router rank / top-1 (identical across configurations: the router is untouched), router-mode and oracle-mode statuses, correctness (``phase10_lib.correct``),
grounding failures, phantom citations, support-chain failures (re-checked here, independently of the generator), citation-evidence failures, in-page chunk recall, latency.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate_phase8 as EP8  # noqa: E402
import phase10_lib as L  # noqa: E402
import rag_evidence as E  # noqa: E402
import rag_pipeline as RP  # noqa: E402

EVAL = ROOT / "data" / "evaluation"
OUTDIR = ROOT / "data" / "phase11_1"
HOLDOUT = EVAL / "phase11_1_holdout_questions.json"
HOLDOUT_FREEZE = EVAL / "phase11_1_holdout_freeze.json"
HOLDOUT2 = EVAL / "phase11_1_holdout2_questions.json"
HOLDOUT2_FREEZE = EVAL / "phase11_1_holdout2_freeze.json"
NON_ANSWERABLE = L.NON_ANSWERABLE
DOC = {"M2C-07": "2ac7fe29a0c94cdd88fb80c2cb9f7758/4d76765c1e012b8ae10000000a42189b", "M2C-05": "2ac7fe29a0c94cdd88fb80c2cb9f7758/8990d0533f8e4308e10000000a174cb4",
       "M2C-24": "9442486404b54071b4ebeab6a16628e7/790dc5536a51204be10000000a174cb4", "M2C-14": "a003b275c98148ee8a4c3fafe9588fe3/cc7bce53118d4308e10000000a174cb4",
       "M2C-17": "e52c8ee6197147ec97dfc2eb8c46a3ad/0bfcc5536a51204be10000000a174cb4", "M2C-11": "ed84b70c199d4470ae2e5ccb93b2e45b/147bce53118d4308e10000000a174cb4",
       "M2C-02": "f4a255a5de524e3992155767996fb1fd/8082ce53118d4308e10000000a174cb4"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def e2e16() -> List[Dict[str, Any]]:
    """The 16 Phase 11 E2E questions in the Phase 10 record schema (DEV only: they were inspected)."""
    out = []
    for q in json.loads((EVAL / "phase11_e2e_questions.json").read_text(encoding="utf-8"))["questions"]:
        typ = {"answerable": "answerable"}.get(q["type"])
        card, st = q.get("expected_card"), q["expected_status"]
        if q["type"] == "answerable":
            typ = "answerable"
        elif st == "documentation_unavailable":
            typ = "not_ingested"
        elif st == "out_of_scope":
            typ = "out_of_domain"
        elif card:
            typ = "absent_detail"
        else:
            typ = "unresolved_identity"
        if q["id"] == "E14":
            typ = "absent_detail"                  # the page (M2C-07) mentions EL31 but has no authorization object
        gold = card if typ != "out_of_domain" else None
        if q["id"] == "E15":
            gold = "M2C-18"
        out.append({"id": q["id"], "query": q["question"], "type": typ, "gold_source_id": gold, "gold_doc_id": DOC.get(card) if typ in ("answerable", "absent_detail") else None,
                    "acceptable_source_ids": [], "evidence": [q["evidence"]] if q.get("evidence") else [],
                    "expected_status": {"answerable": "answered", "absent_detail": "insufficient_context", "not_ingested": "page_not_ingested", "out_of_domain": "out_of_domain",
                                        "unresolved_identity": "unresolved_identity"}[typ]})
    return out


def load(name: str) -> List[Dict[str, Any]]:
    if name == "dev":
        return L.load_set(L.DEV, "dev")["queries"] + e2e16()
    if name == "holdout":
        fz = json.loads(HOLDOUT_FREEZE.read_text(encoding="utf-8"))
        if L.sha(HOLDOUT) != fz["sha256"]:
            raise SystemExit("STOP: the holdout differs from its frozen hash")
        return json.loads(HOLDOUT.read_text(encoding="utf-8"))["queries"]
    if name == "dev2":                                                    # iteration 2: DEV + the 16 E2E + holdout-1 (seen, therefore no longer unbiased)
        return load("dev") + load("holdout")
    if name == "holdout2":
        fz = json.loads(HOLDOUT2_FREEZE.read_text(encoding="utf-8"))
        if L.sha(HOLDOUT2) != fz["sha256"]:
            raise SystemExit("STOP: holdout-2 differs from its frozen hash")
        return json.loads(HOLDOUT2.read_text(encoding="utf-8"))["queries"]
    if name == "test10":
        return L.load_set(L.TEST, "test")["queries"]
    if name in ("p8", "p9"):
        return json.loads((EVAL / ("phase8_queries.json" if name == "p8" else "phase9_queries.json")).read_text(encoding="utf-8"))["queries"]
    raise SystemExit(f"unknown set {name}")


def chain_ok(answer: str, items: Sequence[Dict[str, Any]]) -> bool:
    """Independent support-chain check on the debug context: every answer line is a verbatim span of the chunk its marker names."""
    by = {i["marker"]: i for i in items}
    import rag_text as T
    seen = False
    for line in T.split_cited_sentences(answer or ""):
        body = norm(re.sub(r"\[S\d+\]", "", line))
        if not body:
            continue
        seen = True
        if not any(m in by and body in norm(by[m]["text"]) for m in re.findall(r"\[(S\d+)\]", line)):
            return False
    return seen


def evaluate(pipe: Any, queries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    per: Dict[str, Dict[str, Any]] = {}
    for q in queries:
        rec: Dict[str, Any] = {"type": q["type"], "expected_status": q["expected_status"]}
        if q.get("gold_source_id"):
            raw = pipe.backend.query(q["query"], 29)
            order = [m["source_id"] for m in raw["metadatas"][0]]
            rec["gold_rank"] = order.index(q["gold_source_id"]) + 1 if q["gold_source_id"] in order else None
            rec["top1"] = order[0]
        a = pipe.answer(q["query"], debug=True)
        d = a["debug"]
        rec.update(status=a["status"], selected=a["routing"]["selected_source_id"], total_ms=a["timings_ms"].get("total_ms"), reason=a["reason_code"],
                   correct_router=bool(q["type"] == "answerable" and L.correct(q, a)),
                   grounding_ok=(d.get("grounding") or {}).get("ok", True) if a["status"] == "answered" else None,
                   chain_ok=chain_ok(a["answer"], (d.get("context") or {}).get("items", [])) if a["status"] == "answered" else None,
                   phantom=sum(1 for s in a["citations"]["answer_sources"] if s["chunk_id"] not in {i["chunk_id"] for i in (d.get("context") or {}).get("items", [])}),
                   answer=a["answer"], evidence_rec=getattr(pipe.generator, "last", None) if a["status"] != "answered" or True else None)
        if q["type"] in ("answerable", "absent_detail") and q.get("gold_source_id"):
            o = pipe.answer(q["query"], debug=True, oracle_source_id=q["gold_source_id"])
            od = o["debug"]
            items = (od.get("context") or {}).get("items", [])
            rec.update(o_status=o["status"], o_correct=bool(q["type"] == "answerable" and L.correct(q, o)), o_answer=o["answer"], o_reason=o["reason_code"],
                       o_grounding_ok=(od.get("grounding") or {}).get("ok", True) if o["status"] == "answered" else None,
                       o_chain_ok=chain_ok(o["answer"], items) if o["status"] == "answered" else None,
                       o_phantom=sum(1 for s in o["citations"]["answer_sources"] if s["chunk_id"] not in {i["chunk_id"] for i in items}),
                       o_evidence_rec=getattr(pipe.generator, "last", None), o_total_ms=o["timings_ms"].get("total_ms"))
            if q["type"] == "answerable" and q.get("gold_doc_id"):
                g, p = q["gold_doc_id"].split("/")
                hits = pipe.retriever.retrieve_in_page(q["query"], g, p, top_k=5)
                ranks = [i + 1 for i, h in enumerate(hits) if EP8.has_evidence(h.text, q["evidence"])]
                rec["chunk_rank"] = ranks[0] if ranks else None
        per[q["id"]] = rec
    return {"per_query": per, "metrics": metrics(queries, per)}


def rate(k: int, n: int) -> str:
    return f"{k}/{n}"


def metrics(queries: Sequence[Dict[str, Any]], per: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ans = [q for q in queries if q["type"] == "answerable"]
    ab = [q for q in queries if q["type"] == "absent_detail"]
    m: Dict[str, Any] = {"n": len(queries), "n_answerable": len(ans), "n_absent_detail": len(ab)}
    ranks = [per[q["id"]]["gold_rank"] for q in ans]
    m["router_r1"] = rate(sum(1 for r in ranks if r == 1), len(ans))
    m["router_r3"] = rate(sum(1 for r in ranks if r and r <= 3), len(ans))
    m["router_r5"] = rate(sum(1 for r in ranks if r and r <= 5), len(ans))
    m["router_mrr"] = round(sum(1 / r for r in ranks if r) / max(1, len(ans)), 4)
    cr = [per[q["id"]].get("chunk_rank") for q in ans if q.get("gold_doc_id")]
    m["chunk_r1"], m["chunk_r3"], m["chunk_r5"] = (rate(sum(1 for r in cr if r and r <= k), len(cr)) for k in (1, 3, 5))
    m["answerable_answered_router"] = rate(sum(per[q["id"]]["status"] == "answered" for q in ans), len(ans))
    m["answerable_correct_router"] = rate(sum(per[q["id"]]["correct_router"] for q in ans), len(ans))
    m["answerable_answered_oracle"] = rate(sum(per[q["id"]]["o_status"] == "answered" for q in ans), len(ans))
    m["answerable_abstained_oracle"] = rate(sum(per[q["id"]]["o_status"] != "answered" for q in ans), len(ans))
    m["answerable_correct_oracle"] = rate(sum(per[q["id"]]["o_correct"] for q in ans), len(ans))
    m["citation_evidence_failures_oracle"] = sum(1 for q in ans if per[q["id"]]["o_status"] == "answered" and not per[q["id"]]["o_correct"])
    m["unsupported_answered_oracle"] = rate(sum(per[q["id"]]["o_status"] == "answered" for q in ab), len(ab))
    m["unsupported_abstained_oracle"] = rate(sum(per[q["id"]]["o_status"] != "answered" for q in ab), len(ab))
    wrong = [q["id"] for q in queries if q["type"] in NON_ANSWERABLE and per[q["id"]]["status"] == "answered"]
    m["wrong_topic_answered_router"] = {"count": len(wrong), "ids": wrong}
    m["status_match_router_by_type"] = {t: rate(sum(1 for q in queries if q["type"] == t and per[q["id"]]["status"] == q["expected_status"]), sum(1 for q in queries if q["type"] == t)) for t in sorted({q["type"] for q in queries})}
    allr = list(per.values())
    m["grounding_failures"] = sum(1 for r in allr if r["grounding_ok"] is False) + sum(1 for r in allr if r.get("o_grounding_ok") is False)
    m["support_chain_failures"] = sum(1 for r in allr if r["chain_ok"] is False) + sum(1 for r in allr if r.get("o_chain_ok") is False)
    m["phantom_citations"] = sum(r["phantom"] for r in allr) + sum(r.get("o_phantom", 0) for r in allr)
    ms = [r["total_ms"] for r in allr if r["total_ms"] is not None]
    m["latency_ms"] = {"median": round(statistics.median(ms), 1), "p95": round(sorted(ms)[max(0, int(len(ms) * 0.95) - 1)], 1)}
    return m


def make(base: Any, cfg: str, tau: float) -> Any:
    if cfg == "B":
        return base
    return E.build_evidence_pipeline(base, tau=tau, widen=(cfg == "C2"))


def slim(res: Dict[str, Any]) -> Dict[str, Any]:
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, choices=("dev", "dev2", "holdout", "holdout2", "test10", "p8", "p9"))
    ap.add_argument("--tau", type=float, default=None)
    ap.add_argument("--idf", action="store_true", help="iteration-2 ablation: IDF-weighted focus terms (rejected on DEV2; default off)")
    ap.add_argument("--configs", default="B,C1,C2")
    ap.add_argument("--show-diff", action="store_true", help="print per-query changes vs B (DEV only)")
    a = ap.parse_args(argv)
    E.USE_IDF = a.idf
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"eval_{a.set}{'_idf' if a.idf else ''}.json"
    if a.set not in ("dev", "dev2") and out.exists():
        raise SystemExit(f"STOP: {out.name} exists; sealed sets are evaluated once")
    queries = load(a.set)
    base = RP.build_pipeline(generator="extractive")
    grid = E.TAU_GRID if (a.set in ("dev", "dev2") and a.tau is None) else (a.tau if a.tau is not None else E.TAU,)
    results: Dict[str, Any] = {}
    for cfg in a.configs.split(","):
        for tau in ((None,) if cfg == "B" else grid):
            key = cfg if tau is None else f"{cfg}@{tau}"
            results[key] = evaluate(make(base, cfg, tau or E.TAU), queries)
            m = results[key]["metrics"]
            print(f"{key:8s} corrOracle {m['answerable_correct_oracle']} corrRouter {m['answerable_correct_router']} ansOracle {m['answerable_answered_oracle']} unsupAns {m['unsupported_answered_oracle']} "
                  f"citEvFail {m['citation_evidence_failures_oracle']} wrongTopic {m['wrong_topic_answered_router']['count']} chunkR1/3/5 {m['chunk_r1']},{m['chunk_r3']},{m['chunk_r5']} "
                  f"ground {m['grounding_failures']} chain {m['support_chain_failures']} phantom {m['phantom_citations']} routerR1 {m['router_r1']} lat {m['latency_ms']}")
            if a.show_diff and cfg != "B":
                b = results["B"]["per_query"]
                for q in queries:
                    x, y = b[q["id"]], results[key]["per_query"][q["id"]]
                    if (x.get("o_status"), x["status"], x.get("o_correct")) != (y.get("o_status"), y["status"], y.get("o_correct")):
                        print(f"   {q['id']} [{q['type']}] oracle {x.get('o_status')}/{x.get('o_correct')} -> {y.get('o_status')}/{y.get('o_correct')} | router {x['status']} -> {y['status']} | {q['query'][:70]}")
    payload = {"schema_version": 1, "set": a.set, "use_idf": a.idf, "tau_grid": list(grid), "configs": {k: {"metrics": v["metrics"], "per_query": {i: {kk: vv for kk, vv in r.items()} for i, r in v["per_query"].items()}} for k, v in results.items()},
               "queries_sha256": L.sha(HOLDOUT) if a.set == "holdout" else (L.sha(HOLDOUT2) if a.set == "holdout2" else None)}
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
