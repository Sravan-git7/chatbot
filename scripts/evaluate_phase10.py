#!/usr/bin/env python3
"""Phase 10 - sealed TEST evaluation (run ONCE) + regression references. Writes ``data/evaluation/phase10_results.json`` (deterministic) and
``data/evaluation/phase10_performance.json`` (timings, measured on DEV queries only).

Order of checks: freeze record -> selection file (must reference the frozen DEV hash and say the TEST file was never read) -> TEST evaluation of four
PRE-DECLARED configurations -> rule verdicts (``phase10_lib.TEST_RULES``) -> regression references on the Phase 8 / Phase 9 sets -> determinism check.
Refuses to overwrite an existing results file (the TEST set is used once).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase10_lib as L  # noqa: E402
import rag_pipeline as RP  # noqa: E402

RESULTS = L.EVAL / "phase10_results.json"
PERF = L.EVAL / "phase10_performance.json"
BASELINE = (0.0, 0.34, False)


def compact(res):
    return {"metrics": res["metrics"], "per_query": {i: {k: v for k, v in r.items() if k in ("type", "status", "selected", "gold_rank", "correct_answer_router", "correct_answer_oracle", "oracle_status")} for i, r in res["per_query"].items()}}


def verdicts(sel_cfg, lam_exp, runs, qs):
    ans = [q["id"] for q in qs if q["type"] == "answerable"]
    ab = [q["id"] for q in qs if q["type"] == "absent_detail"]
    base, g = runs["baseline"], runs["selected"]
    bm, gm = base["metrics"], g["metrics"]
    # --- G rule (selected generator, oracle routing)
    nca = gm["oracle_absent_detail_abstained"]["k"] - bm["oracle_absent_detail_abstained"]["k"]
    lost = bm["oracle_correct_answers"]["k"] - gm["oracle_correct_answers"]["k"]
    rg = L.TEST_RULES["G"]
    G = {"net_correct_abstentions": nca, "answerable_correct_lost": lost, "grounding_failures": gm["oracle_grounding_failures"] + gm["router_mode_grounding_failures"], "phantom_citations": gm["oracle_phantom_citations"] + gm["router_mode_phantom_citations"],
         "paired_abstention": L.paired(g["per_query"], base["per_query"], ab, lambda r: r["oracle_status"] != "answered"),
         "paired_answerable_correct": L.paired(g["per_query"], base["per_query"], ans, lambda r: r["correct_answer_oracle"])}
    G["rule"] = rg
    G["supported"] = nca >= rg["min_net_correct_abstentions"] and lost <= rg["max_answerable_correct_lost"] and G["grounding_failures"] == 0 and G["phantom_citations"] == 0
    # --- R rule (INFORMATIONAL: lam_exp was not selected on DEV because the DEV guard failed)
    rr = L.TEST_RULES["R"]
    out = {"G": G}
    for name in ("R_exploratory", "R_exploratory+G"):
        r = runs[name]["metrics"]
        gain = (r["router_answerable"]["recall@1"]["k"] - bm["router_answerable"]["recall@1"]["k"]) / max(1, bm["n_answerable"])
        paired = L.paired(runs[name]["per_query"], base["per_query"], ans, lambda x: x["gold_rank"] == 1)
        wt_ref = bm["wrong_topic_answered"]["count"] if name == "R_exploratory" else gm["wrong_topic_answered"]["count"]
        ni = [r["router_top1_not_ingested"], r["router_top1_unresolved_identity"]]
        ni0 = [bm["router_top1_not_ingested"], bm["router_top1_unresolved_identity"]]
        routing_ok = all(a["k"] >= b["k"] for a, b in zip(ni, ni0))
        ok = gain >= rr["min_r1_gain"] and (paired["sign_test_p_two_sided"] or 1) < rr["sign_test_p_below"] and r["wrong_topic_answered"]["count"] <= wt_ref and routing_ok
        out[name] = {"lam": lam_exp, "r1_gain_absolute": round(gain, 4), "paired_r1": paired, "wrong_topic_answered": r["wrong_topic_answered"]["count"], "wrong_topic_answered_reference": wt_ref,
                     "wrong_topic_answered_ids": r["wrong_topic_answered"]["ids"], "routing_top1_not_worse_on_not_ingested_and_unresolved": routing_ok,
                     "would_pass_all_declared_R_criteria": ok, "adopted": False, "reason_not_adopted": "fusion failed the pre-declared DEV guard (wrong-topic answers increased), so it was not selected; TEST figures are informational"}
    out["R_rule"] = rr
    return out


def main() -> int:
    if RESULTS.exists():
        print(f"STOP: {RESULTS.name} exists - the sealed TEST set is evaluated once")
        return 2
    freeze = json.loads(L.FREEZE.read_text(encoding="utf-8"))
    sel = json.loads(L.SELECTION.read_text(encoding="utf-8"))
    if sel["dev_sha256"] != freeze["files"]["dev"]["sha256"] or sel["test_file_read"] is not False:
        print("STOP: selection file does not match the frozen DEV set")
        return 2
    test = L.load_set(L.TEST, "test")
    qs = test["queries"]
    sc = sel["selected_configuration"]
    lam_exp = sel["R_exploratory_lam"]
    cfgs = {"baseline": BASELINE, "selected": (sc["lam"], sc["theta"], sc["detail_cue_check"]), "R_exploratory": (lam_exp, 0.34, False), "R_exploratory+G": (lam_exp, sc["theta"], sc["detail_cue_check"])}
    base = RP.build_pipeline(generator="extractive")
    runs = {name: L.evaluate(base, qs, *c, with_oracle=True) for name, c in cfgs.items()}
    out = {"schema_version": 1, "test_sha256": L.sha(L.TEST), "dev_sha256": L.sha(L.DEV), "selection_sha256": L.sha(L.SELECTION), "n_test_queries": len(qs),
           "configs": {k: {"lam": c[0], "theta": c[1], "detail_cue_check": c[2]} for k, c in cfgs.items()}, "test": {k: compact(v) for k, v in runs.items()},
           "verdicts": verdicts(sc, lam_exp, runs, qs)}
    # ---- regression references on the earlier frozen sets (NOT unbiased: cue rules were written after the Phase 9 failures were seen)
    reg = {}
    for name, fn in (("phase8_queries", "phase8_queries.json"), ("phase9_queries", "phase9_queries.json")):
        rq = json.loads((L.EVAL / fn).read_text(encoding="utf-8"))["queries"]
        r = {k: L.evaluate(base, rq, *cfgs[k], with_oracle=True) for k in ("baseline", "selected", "R_exploratory+G")}
        reg[name] = {"n_queries": len(rq), "file_sha256": L.sha(L.EVAL / fn), **{k: v["metrics"] for k, v in r.items()},
                     "lam0_routing_identical_to_baseline": all(r["selected"]["per_query"][i].get("gold_rank") == r["baseline"]["per_query"][i].get("gold_rank") and r["selected"]["per_query"][i]["selected"] == r["baseline"]["per_query"][i]["selected"] for i in r["baseline"]["per_query"]) if cfgs["selected"][0] == 0.0 else None}
    out["regression_references"] = reg
    # ---- determinism (DEV, first 30 queries, selected config run twice)
    dq = L.load_set(L.DEV, "dev")["queries"][:30]
    a, b = L.evaluate(base, dq, *cfgs["selected"]), L.evaluate(base, dq, *cfgs["selected"])
    out["determinism"] = {"queries": len(dq), "identical": a == b}
    RESULTS.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    # ---- performance (separate, non-deterministic file; DEV queries only)
    perf = {"note": "median/p95 wall time per answer() call on the 73 DEV queries, extractive generator, one process, warm; not a benchmark of Ollama", "configs": {}}
    for name, c in cfgs.items():
        pipe = L.make_pipeline(base, *c)
        pipe.answer(dq[0]["query"])
        ts = []
        for q in L.load_set(L.DEV, "dev")["queries"]:
            t = time.perf_counter()
            pipe.answer(q["query"])
            ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        perf["configs"][name] = {"median_ms": round(statistics.median(ts), 1), "p95_ms": round(ts[int(0.95 * (len(ts) - 1))], 1)}
    PERF.write_text(json.dumps(perf, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    v = out["verdicts"]
    print(json.dumps({"G_supported": v["G"]["supported"], "G": {k: v["G"][k] for k in ("net_correct_abstentions", "answerable_correct_lost", "grounding_failures", "phantom_citations")},
                      "R": {k: {x: v[k][x] for x in ("r1_gain_absolute", "wrong_topic_answered", "wrong_topic_answered_reference", "would_pass_all_declared_R_criteria")} for k in ("R_exploratory", "R_exploratory+G")}, "determinism": out["determinism"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
