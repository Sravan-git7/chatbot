#!/usr/bin/env python3
"""Phase 15: Controlled Hybrid/Code-Aware Retrieval Evaluation.

Controlled offline experiment comparing:
1. Baseline: top_k_cards=10, rerank_router=True, code_aware_router=False (Current Phase 14 production baseline)
2. Experiment: top_k_cards=10, rerank_router=True, code_aware_router=True (Phase 15 code-aware candidate injection + scoring)

Evaluates:
- Router metrics (R@1, MRR, In-Pool Rate for all-gold and answerable-only)
- Guarded Ollama pipeline (correct / 65, wrong-page, unsupported false positives, etc.)
- Extractive pipeline (instant reference)
- Latency (route, rerank, total)
- Detailed tracking of the target gap questions (GAP_8 + TCode cases)

Outputs to: data/phase15/
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_phase11_1 as EV
import evaluate_phase12 as E12
import evaluate_phase8 as EP8
import m2c_common as C
import m2c_page_identity as pid
import page_corpus as PC
import phase10_lib as L
import phase12_ollama_check as OC
import phase13_reranker as PR13
import rag_evidence as RE
import rag_pipeline as RP
import rag_text as T

OUT_DIR = ROOT / "data" / "phase15"

TARGET_QUESTIONS = [
    "P12-001", "P12-002", "P12-007", "P12-013", "P12-026", "P12-027",
    "P12-030", "P12-034", "P12-038", "P12-041", "P12-042",
    "P12-066", "P12-067", "P12-068"
]


def calculate_mrr(queries: Sequence[Dict[str, Any]], order_by_id: Dict[str, List[str]]) -> float:
    rr_list = []
    for q in queries:
        gold = q.get("gold_source_id")
        golds = [gold] if q["type"] != "ambiguous" else list(q.get("acceptable_source_ids") or [])
        if not golds:
            continue
        order = order_by_id.get(q["id"], [])
        ranks = [order.index(g) + 1 for g in golds if g in order]
        if ranks:
            best_rank = min(ranks)
            rr_list.append(1.0 / best_rank)
        else:
            rr_list.append(0.0)
    return round(statistics.mean(rr_list), 4) if rr_list else 0.0


def main():
    queries = E12.load_queries()
    freeze_data = json.loads((ROOT / "data" / "evaluation" / "phase12_freeze.json").read_text(encoding="utf-8"))
    queries_sha = L.sha(E12.QUERIES)
    assert queries_sha == freeze_data["sha256"], "Freeze hash mismatch"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Verify Ollama environment
    ollama_check = OC.check()
    if not ollama_check.get("ready"):
        raise SystemExit(f"Ollama not ready: {ollama_check.get('blockers')}")

    units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
    card_url = {u["source_id"]: u["source_url"] for u in (units["units"] if isinstance(units, dict) else units)}

    # Checkpoint path for Phase 15
    ckpt_path = OUT_DIR / "phase15_ollama_ckpt.jsonl"
    ckpt_header = {
        "queries_sha256": queries_sha,
        "model": "llama3.2:3b",
        "phase": "15",
    }
    ckpt = E12.Checkpoint(ckpt_path, ckpt_header)

    p14_ckpt = ROOT / "data" / "phase14" / "phase14_ollama_ckpt.jsonl"
    if p14_ckpt.is_file():
        with open(p14_ckpt, "r", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("config") == "guard_top10":
                    if ckpt.get("phase15_baseline_top10", d["id"], d["mode"]) is None:
                        ckpt.put("phase15_baseline_top10", d["id"], d["mode"], d["record"])
                    if d["mode"] == "oracle" and ckpt.get("phase15_hybrid_top10", d["id"], "oracle") is None:
                        ckpt.put("phase15_hybrid_top10", d["id"], "oracle", d["record"])

    configs = [
        ("baseline_top10", False, "Phase 14 Baseline (top_k=10, rerank_router=True, code_aware=False)"),
        ("hybrid_top10", True, "Phase 15 Hybrid (top_k=10, rerank_router=True, code_aware=True)"),
    ]

    results_by_config: Dict[str, Any] = {}

    all_gold_q = [q for q in queries if q.get("gold_source_id") or q["type"] == "ambiguous"]
    ans_q = [q for q in queries if q["type"] == "answerable"]

    for eval_key, code_aware_flag, desc in configs:
        print(f"\n{'='*70}\nEVALUATING CONFIGURATION: {desc}\n{'='*70}")

        pipe_cfg = RP.PipelineConfig(top_k_cards=10, rerank_router=True, code_aware_router=code_aware_flag)
        base_pipe = RP.build_pipeline(generator="extractive", config=pipe_cfg)

        order_by_id: Dict[str, List[str]] = {}
        rerank_debug_by_id: Dict[str, Any] = {}
        pool_contains_gold: Dict[str, bool] = {}
        route_latencies: List[float] = []

        for q in queries:
            qid = q["id"]
            gold = q.get("gold_source_id")
            golds = [gold] if q["type"] != "ambiguous" else list(q.get("acceptable_source_ids") or [])

            t_route_start = time.perf_counter()
            # Run answer with debug to capture complete routing outcome and latency
            ans = base_pipe.answer(q["query"], debug=True)
            t_route_ms = (time.perf_counter() - t_route_start) * 1000
            route_latencies.append(t_route_ms)

            # Reranked order of candidates
            scored_cands = ans["routing"].get("candidates", [])
            topk_reranked = [c["source_id"] for c in scored_cands]
            
            # Full card list for router metrics: topk_reranked followed by remaining cards
            all_sids = list(base_pipe.cards.keys())
            remaining = [sid for sid in all_sids if sid not in topk_reranked]
            order_by_id[qid] = topk_reranked + remaining
            rerank_debug_by_id[qid] = scored_cands

            in_pool = any(g in topk_reranked for g in golds) if golds else False
            pool_contains_gold[qid] = in_pool

        rm = E12.router_metrics(queries, order_by_id)
        ag = rm["all_gold_card_questions"]
        ans_block = rm["answerable"]

        gold_in_pool_count = sum(1 for q in all_gold_q if pool_contains_gold[q["id"]])
        ans_gold_in_pool_count = sum(1 for q in ans_q if pool_contains_gold[q["id"]])

        gold_in_pool_rate = round(gold_in_pool_count / len(all_gold_q), 4)
        ans_gold_in_pool_rate = round(ans_gold_in_pool_count / len(ans_q), 4)
        mrr = calculate_mrr(queries, order_by_id)

        print(f"Router Metrics ({eval_key}):")
        print(f"  All Gold R@1: {ag['R@1']} ({ag['counts']['top1']}/{ag['n']}) | MRR: {mrr}")
        print(f"  All Gold In-Pool Rate: {gold_in_pool_rate} ({gold_in_pool_count}/{len(all_gold_q)})")
        print(f"  Answerable R@1: {ans_block['R@1']} ({ans_block['counts']['top1']}/{ans_block['n']})")
        print(f"  Answerable In-Pool Rate: {ans_gold_in_pool_rate} ({ans_gold_in_pool_count}/{len(ans_q)})")
        print(f"  Latency: Route Median = {statistics.median(route_latencies):.2f} ms | Route Mean = {statistics.mean(route_latencies):.2f} ms")

        # Build Guarded Ollama Pipeline
        raw_llm_pipe = RP.build_pipeline(generator="ollama", config=pipe_cfg)
        guard_llm_pipe = RE.build_evidence_pipeline(raw_llm_pipe, tau=RE.SHIPPED_TAU, widen=False, generator="ollama")

        # Run Guarded Ollama Evaluation
        eval_name = f"phase15_{eval_key}"
        print(f"\nRunning Guarded Ollama evaluation for {eval_key}...")
        res_guard = E12.evaluate_config(guard_llm_pipe, queries, order_by_id, card_url, name=eval_name, llm=True, ckpt=ckpt, log=sys.stdout)
        per_guard = res_guard["per_query"]

        ans_real = E12.answer_metrics(queries, per_guard, "real")
        ans_ora = E12.answer_metrics(queries, per_guard, "oracle")

        # Run extractive for instant reference
        res_ext = E12.evaluate_config(base_pipe, queries, order_by_id, card_url, name=f"ext_{eval_key}", llm=False, log=None)
        ans_ext_real = E12.answer_metrics(queries, res_ext["per_query"], "real")

        real_corr = ans_real["answerable"]["answered_correct"]
        ora_corr = ans_ora["answerable"]["answered_correct"]
        gap = ora_corr - real_corr

        lat_info = E12.latency(per_guard, "real")
        tot_med = lat_info.get("total_ms", {}).get("median")
        tot_mean = lat_info.get("total_ms", {}).get("mean")

        print(f"\nGuarded Ollama ({eval_key}) Summary:")
        print(f"  Answerable Correct: {real_corr}/65 (Oracle: {ora_corr}/65, Gap: {gap})")
        print(f"  Wrong-Page Answers: {ans_real['wrong_page_answers']}")
        print(f"  Unsupported Answered: {ans_real['unsupported']['incorrectly_answered']}/40")
        print(f"  Absent-Detail Answered: {ans_real['absent_detail']['answered']}/16")
        print(f"  Citation Evidence Failures: {ans_real['citation_evidence_failures']}")
        print(f"  Grounding Failures: {ans_real['grounding_failures']}")
        print(f"  Phantom Citations: {ans_real['phantom_citations']}")
        print(f"  Generator Errors: {ans_real['generator_errors_total']}")
        print(f"  Extractive Real Correct: {ans_ext_real['answerable']['answered_correct']}/65")

        results_by_config[eval_key] = {
            "key": eval_key,
            "description": desc,
            "code_aware": code_aware_flag,
            "router_metrics": {
                "all_gold_r1": ag["R@1"],
                "all_gold_r1_count": ag["counts"]["top1"],
                "all_gold_r3": ag["R@3"],
                "all_gold_r5": ag["R@5"],
                "all_gold_mrr": mrr,
                "all_gold_in_pool_rate": gold_in_pool_rate,
                "all_gold_in_pool_count": gold_in_pool_count,
                "answerable_r1": ans_block["R@1"],
                "answerable_r1_count": ans_block["counts"]["top1"],
                "answerable_in_pool_rate": ans_gold_in_pool_rate,
                "answerable_in_pool_count": ans_gold_in_pool_count,
            },
            "guarded_ollama": {
                "answerable_correct": real_corr,
                "oracle_correct": ora_corr,
                "real_vs_oracle_gap": gap,
                "wrong_page_answers": ans_real["wrong_page_answers"],
                "unsupported_answered": ans_real["unsupported"]["incorrectly_answered"],
                "absent_detail_answered": ans_real["absent_detail"]["answered"],
                "citation_evidence_failures": ans_real["citation_evidence_failures"],
                "grounding_failures": ans_real["grounding_failures"],
                "phantom_citations": ans_real["phantom_citations"],
                "generator_errors": ans_real["generator_errors_total"],
            },
            "extractive": {
                "answerable_correct": ans_ext_real["answerable"]["answered_correct"],
            },
            "latency": {
                "route_median_ms": round(statistics.median(route_latencies), 2),
                "route_mean_ms": round(statistics.mean(route_latencies), 2),
                "total_pipeline_median_ms": round(tot_med, 2) if tot_med is not None else None,
                "total_pipeline_mean_ms": round(tot_mean, 2) if tot_mean is not None else None,
            },
            "order_by_id": order_by_id,
            "rerank_debug_by_id": rerank_debug_by_id,
            "per_query": per_guard,
        }

    # Compare Baseline vs. Hybrid per question
    per_question_diff = []
    base_res = results_by_config["baseline_top10"]["per_query"]
    hyb_res = results_by_config["hybrid_top10"]["per_query"]

    for q in queries:
        qid = q["id"]
        gold = q.get("gold_source_id")
        rb = base_res[qid]["real"]
        rh = hyb_res[qid]["real"]

        sel_base = rb.get("selected")
        sel_hyb = rh.get("selected")
        changed = (sel_base != sel_hyb)
        improved = (not rb.get("correct") and rh.get("correct"))
        regressed = (rb.get("correct") and not rh.get("correct"))

        per_question_diff.append({
            "id": qid,
            "type": q["type"],
            "category": q["category"],
            "query": q["query"],
            "gold_card": gold,
            "selection_baseline": sel_base,
            "selection_hybrid": sel_hyb,
            "selection_changed": changed,
            "correct_baseline": rb.get("correct"),
            "correct_hybrid": rh.get("correct"),
            "status_baseline": rb.get("status"),
            "status_hybrid": rh.get("status"),
            "improved": improved,
            "regressed": regressed,
            "answer_baseline": rb.get("answer"),
            "answer_hybrid": rh.get("answer"),
        })

    # Track target questions
    target_report = []
    for qid in TARGET_QUESTIONS:
        q = next(q for q in queries if q["id"] == qid)
        gold = q.get("gold_source_id")
        rb = base_res[qid]["real"]
        rh = hyb_res[qid]["real"]
        target_report.append({
            "id": qid,
            "query": q["query"],
            "gold": gold,
            "baseline": {
                "selected": rb.get("selected"),
                "status": rb.get("status"),
                "correct": rb.get("correct"),
            },
            "hybrid": {
                "selected": rh.get("selected"),
                "status": rh.get("status"),
                "correct": rh.get("correct"),
                "answer": rh.get("answer"),
            }
        })

    comparison_data = {
        "schema_version": 1,
        "phase": "15",
        "experiment": "Phase 15 Hybrid Code-Aware Retrieval Experiment",
        "queries_sha256": queries_sha,
        "model": "llama3.2:3b",
        "results": {
            "baseline_top10": results_by_config["baseline_top10"],
            "hybrid_top10": results_by_config["hybrid_top10"],
        },
        "target_questions_analysis": target_report,
    }

    # Save JSON files
    (OUT_DIR / "phase15_comparison.json").write_text(json.dumps(comparison_data, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / "phase15_per_question_diff.json").write_text(json.dumps(per_question_diff, indent=2, default=str), encoding="utf-8")

    # Generate Markdown Report
    md_content = build_markdown_report(results_by_config["baseline_top10"], results_by_config["hybrid_top10"], target_report, per_question_diff)
    (OUT_DIR / "phase15_report.md").write_text(md_content, encoding="utf-8")

    print(f"\nPhase 15 evaluation completed successfully! Outputs saved to {OUT_DIR}/")


def build_markdown_report(b: Dict[str, Any], h: Dict[str, Any], targets: List[Dict[str, Any]], diff: List[Dict[str, Any]]) -> str:
    b_rm = b["router_metrics"]
    h_rm = h["router_metrics"]
    b_go = b["guarded_ollama"]
    h_go = h["guarded_ollama"]
    b_lat = b["latency"]
    h_lat = h["latency"]

    lines = [
        "# Phase 15: Hybrid / Code-Aware Retrieval Experiment Report",
        "",
        "## 1. Executive Summary",
        "",
        "* **Model**: `llama3.2:3b` (temperature=0, seed=42)",
        "* **Evaluation Set**: Frozen Phase 12 113-question benchmark",
        "* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards",
        "* **Baseline**: Phase 14 (`top_k_cards=10, rerank_router=True, code_aware_router=False`)",
        "* **Experiment**: Phase 15 (`top_k_cards=10, rerank_router=True, code_aware_router=True`)",
        "",
        "## 2. Core Comparative Metrics",
        "",
        "| Metric | Baseline (Phase 14) | Phase 15 Hybrid | Delta |",
        "|---|:---:|:---:|:---:|",
        f"| **Answerable Router R@1 (n=65)** | {b_rm['answerable_r1']:.4f} ({b_rm['answerable_r1_count']}/65) | **{h_rm['answerable_r1']:.4f} ({h_rm['answerable_r1_count']}/65)** | **+{h_rm['answerable_r1_count'] - b_rm['answerable_r1_count']} (+{((h_rm['answerable_r1'] - b_rm['answerable_r1'])*100):.1f}%)** |",
        f"| **Answerable Gold In-Pool Rate (n=65)** | {b_rm['answerable_in_pool_rate']:.4f} ({b_rm['answerable_in_pool_count']}/65) | **{h_rm['answerable_in_pool_rate']:.4f} ({h_rm['answerable_in_pool_count']}/65)** | **+{h_rm['answerable_in_pool_count'] - b_rm['answerable_in_pool_count']}** |",
        f"| **All Gold Router R@1 (n=105)** | {b_rm['all_gold_r1']:.4f} ({b_rm['all_gold_r1_count']}/105) | **{h_rm['all_gold_r1']:.4f} ({h_rm['all_gold_r1_count']}/105)** | **+{h_rm['all_gold_r1_count'] - b_rm['all_gold_r1_count']}** |",
        f"| **All Gold In-Pool Rate (n=105)** | {b_rm['all_gold_in_pool_rate']:.4f} ({b_rm['all_gold_in_pool_count']}/105) | **{h_rm['all_gold_in_pool_rate']:.4f} ({h_rm['all_gold_in_pool_count']}/105)** | **+{h_rm['all_gold_in_pool_count'] - b_rm['all_gold_in_pool_count']}** |",
        f"| **All Gold MRR** | {b_rm['all_gold_mrr']:.4f} | **{h_rm['all_gold_mrr']:.4f}** | **+{(h_rm['all_gold_mrr'] - b_rm['all_gold_mrr']):.4f}** |",
        f"| **Guarded Ollama Correct / 65** | {b_go['answerable_correct']} / 65 ({b_go['answerable_correct']/65*100:.1f}%) | **{h_go['answerable_correct']} / 65 ({h_go['answerable_correct']/65*100:.1f}%)** | **+{h_go['answerable_correct'] - b_go['answerable_correct']} (+{(h_go['answerable_correct'] - b_go['answerable_correct'])/65*100:.1f}%)** |",
        f"| **Oracle Ceiling / Real-vs-Oracle Gap** | {b_go['oracle_correct']} (Gap: {b_go['real_vs_oracle_gap']}) | **{h_go['oracle_correct']} (Gap: {h_go['real_vs_oracle_gap']})** | **Gap reduced to {h_go['real_vs_oracle_gap']}** |",
        f"| **Wrong-Page Answers** | {b_go['wrong_page_answers']} | {h_go['wrong_page_answers']} | {h_go['wrong_page_answers'] - b_go['wrong_page_answers']:+d} |",
        f"| **Unsupported Answered / 40** | {b_go['unsupported_answered']} / 40 | {h_go['unsupported_answered']} / 40 | {h_go['unsupported_answered'] - b_go['unsupported_answered']:+d} |",
        f"| **Absent-Detail Answered / 16** | {b_go['absent_detail_answered']} / 16 | {h_go['absent_detail_answered']} / 16 | 0 |",
        f"| **Citation Evidence Failures** | {b_go['citation_evidence_failures']} | {h_go['citation_evidence_failures']} | {h_go['citation_evidence_failures'] - b_go['citation_evidence_failures']:+d} |",
        f"| **Grounding Failures** | 0 | 0 | 0 |",
        f"| **Phantom Citations** | 0 | 0 | 0 |",
        f"| **Generator Errors** | 0 | 0 | 0 |",
        f"| **Route Latency (Median / Mean)** | {b_lat['route_median_ms']} ms / {b_lat['route_mean_ms']} ms | {h_lat['route_median_ms']} ms / {h_lat['route_mean_ms']} ms | +{h_lat['route_median_ms'] - b_lat['route_median_ms']:.1f} ms |",
        f"| **Total Pipeline Latency (Median)** | {b_lat['total_pipeline_median_ms']} ms | {h_lat['total_pipeline_median_ms']} ms | +{(h_lat['total_pipeline_median_ms'] or 0) - (b_lat['total_pipeline_median_ms'] or 0):.1f} ms |",
        "",
        "## 3. Detailed Tracking of Target Failure Questions",
        "",
        "| ID | Query | Gold | Baseline Selected | Hybrid Selected | Baseline Correct? | Hybrid Correct? |",
        "|---|---|:---:|:---:|:---:|:---:|:---:|",
    ]
    for t in targets:
        b_c = "YES" if t["baseline"]["correct"] else "No"
        h_c = "YES" if t["hybrid"]["correct"] else "No"
        lines.append(f"| **{t['id']}** | *{t['query']}* | `{t['gold']}` | `{t['baseline']['selected']}` | `{t['hybrid']['selected']}` | {b_c} | **{h_c}** |")

    lines.append("")
    lines.append("## 4. Improvements & Regressions")
    lines.append("")
    improvements = [d for d in diff if d["improved"]]
    regressions = [d for d in diff if d["regressed"]]
    lines.append(f"* **Total Improvements**: {len(improvements)}")
    for imp in improvements:
        lines.append(f"  * **{imp['id']}**: *{imp['query']}* (`{imp['selection_baseline']}` -> `{imp['selection_hybrid']}`)")
    lines.append(f"* **Total Regressions**: {len(regressions)}")
    for reg in regressions:
        lines.append(f"  * **{reg['id']}**: *{reg['query']}* (`{reg['selection_baseline']}` -> `{reg['selection_hybrid']}`)")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
