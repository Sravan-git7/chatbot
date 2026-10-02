#!/usr/bin/env python3
"""Phase 10 - DEV selection. Uses ONLY ``phase10_dev_queries.json`` (hash-checked). Applies the rules in ``data/phase10_contract.md`` section 5 and writes
``data/evaluation/phase10_selection.json`` (deterministic). Never reads the sealed TEST file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase10_lib as L  # noqa: E402
import rag_optimised as RO  # noqa: E402
import rag_pipeline as RP  # noqa: E402


def main() -> int:
    dev = L.load_set(L.DEV, "dev")
    qs = dev["queries"]
    base = RP.build_pipeline(generator="extractive")
    ans_ids = [q["id"] for q in qs if q["type"] == "answerable"]
    # ---- R: lambda grid (current generator)
    r_runs = {lam: L.evaluate(base, qs, lam, 0.34, False, with_oracle=False) for lam in RO.LAMBDA_GRID}
    r0 = r_runs[0.0]["metrics"]
    r_rows, best = [], None
    for lam in RO.LAMBDA_GRID:
        m = r_runs[lam]["metrics"]
        guard = m["wrong_topic_answered"]["count"] <= r0["wrong_topic_answered"]["count"]
        r_rows.append({"lam": lam, "answerable_r1": m["router_answerable"]["recall@1"], "answerable_mrr": m["router_answerable"]["mrr"], "router_mode_correct_answers": m["router_mode_correct_answers"],
                       "wrong_topic_answered": m["wrong_topic_answered"]["count"], "guard_passed": guard,
                       "paired_r1_vs_lam0": L.paired(r_runs[lam]["per_query"], r_runs[0.0]["per_query"], ans_ids, lambda r: r["gold_rank"] == 1)})
        if guard and (best is None or m["router_answerable"]["recall@1"]["k"] > best[1]):
            best = (lam, m["router_answerable"]["recall@1"]["k"])
    lam_star = best[0] if best else 0.0
    # ---- G: generator candidates (oracle routing, lam=0)
    g_runs = {name: L.evaluate(base, qs, 0.0, th, cue, with_oracle=True) for name, th, cue in L.G_CANDIDATES}
    g0 = g_runs["G0_current"]["metrics"]
    g_rows, g_best = [], None
    for idx, (name, th, cue) in enumerate(L.G_CANDIDATES):
        m = g_runs[name]["metrics"]
        lost = g0["oracle_correct_answers"]["k"] - m["oracle_correct_answers"]["k"]
        ok = lost <= L.ANSWERABLE_LOSS_ALLOWED_DEV
        g_rows.append({"name": name, "theta": th, "detail_cue_check": cue, "oracle_correct_answers": m["oracle_correct_answers"], "oracle_absent_detail_abstained": m["oracle_absent_detail_abstained"],
                       "answerable_correct_lost_vs_G0": lost, "constraint_passed": ok})
        if ok and (g_best is None or m["oracle_absent_detail_abstained"]["k"] > g_best[1]):
            g_best = (idx, m["oracle_absent_detail_abstained"]["k"])
    gi = g_best[0] if g_best else 0
    gname, gtheta, gcue = L.G_CANDIDATES[gi]
    # ---- informational (NOT a selection rule): fusion combined with the selected generator, wrong-topic answers split by type
    lam_exp = max(RO.LAMBDA_GRID, key=lambda l: (r_runs[l]["metrics"]["router_answerable"]["recall@1"]["k"], -l))
    comb = {}
    for lam in (0.0, lam_exp):
        r = L.evaluate(base, qs, lam, gtheta, gcue, with_oracle=False)
        by_type = {}
        for i in r["metrics"]["wrong_topic_answered"]["ids"]:
            t = r["per_query"][i]["type"]
            by_type[t] = by_type.get(t, 0) + 1
        comb[str(lam)] = {"answerable_r1": r["metrics"]["router_answerable"]["recall@1"]["k"], "router_mode_correct_answers": r["metrics"]["router_mode_correct_answers"]["k"],
                          "wrong_topic_answered": r["metrics"]["wrong_topic_answered"]["count"], "wrong_topic_answered_by_type": by_type}
    sel = {"schema_version": 1, "R_exploratory_lam": lam_exp, "R_with_selected_G_dev_informational": comb, "dev_sha256": L.sha(L.DEV), "rules": "data/phase10_contract.md section 5", "test_file_read": False,
           "R_grid": r_rows, "R_selected_lam": lam_star, "G_grid": g_rows, "G_selected": {"name": gname, "theta": gtheta, "detail_cue_check": gcue},
           "selected_configuration": {"lam": lam_star, "theta": gtheta, "detail_cue_check": gcue}}
    L.SELECTION.write_text(json.dumps(sel, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"R": [(r["lam"], r["answerable_r1"]["k"], r["wrong_topic_answered"], r["guard_passed"]) for r in r_rows], "lam*": lam_star,
                      "G": [(g["name"], g["oracle_correct_answers"]["k"], g["oracle_absent_detail_abstained"]["k"], g["constraint_passed"]) for g in g_rows], "G*": gname}, indent=None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
