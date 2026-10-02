#!/usr/bin/env python3
"""Phase 13-A: Multi-candidate router reranking evaluation against the frozen 113-question set.

Runs:
1. Baseline Configuration (extractive baseline + evidence, rerank_router=False)
2. Phase 13-A Configuration (extractive baseline + evidence, rerank_router=True)

Computes:
- Router metrics: R@1, R@3, R@5, MRR (overall and answerable)
- Answer metrics: real answer-correct, wrong-page, unsupported-answered, oracle answer-correct,
  absent-answered, citation-evidence failures, grounding/phantom/url failures, generator errors
- Latency / performance
- Per-question diff: question ID, baseline selected card, reranked selected card, gold card,
  baseline rank, reranked rank, selection changed, final answer changed, answer correctness changed.
Outputs to: data/phase13/
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
import phase13_reranker as PR13
import rag_evidence as RE
import rag_pipeline as RP
import rag_text as T

OUT_DIR = ROOT / "data" / "phase13"


def main():
    queries = E12.load_queries()
    freeze_data = json.loads((ROOT / "data" / "evaluation" / "phase12_freeze.json").read_text(encoding="utf-8"))
    queries_sha = L.sha(E12.QUERIES)
    assert queries_sha == freeze_data["sha256"], "Freeze hash mismatch"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
    card_url = {u["source_id"]: u["source_url"] for u in (units["units"] if isinstance(units, dict) else units)}

    # Build pipelines:
    # 1. Baseline
    base_pipe = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(rerank_router=False))
    ev_base_pipe = RE.build_evidence_pipeline(base_pipe, tau=RE.SHIPPED_TAU, widen=False, generator="extractive")

    # 2. Phase 13-A Reranker
    rerank_pipe = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(rerank_router=True))
    ev_rerank_pipe = RE.build_evidence_pipeline(rerank_pipe, tau=RE.SHIPPED_TAU, widen=False, generator="extractive")

    # Compute router orderings
    print("Computing router rankings for Baseline and Phase 13-A...")
    baseline_order_by_id: Dict[str, List[str]] = {}
    reranked_order_by_id: Dict[str, List[str]] = {}
    rerank_debug_by_id: Dict[str, Any] = {}

    for q in queries:
        raw = base_pipe.backend.query(q["query"], 29)
        base_order = [m["source_id"] for m in raw["metadatas"][0]]
        baseline_order_by_id[q["id"]] = base_order

        # Reranked order: top 5 reranked by page evidence, then remaining 24
        outcome = RP.route_to_page(q["query"], base_pipe.backend, base_pipe.ctx.page_index, top_k=5, selector=RP.select_top_ranked)
        selected, scored = PR13.rerank_candidates(q["query"], outcome.candidates, base_pipe.cards, base_pipe.retriever, base_pipe.ctx, base_pipe.corpus, top_k_evaluate=5)
        
        top5_reranked = [s.candidate.source_id for s in scored]
        remaining = [sid for sid in base_order if sid not in top5_reranked]
        reranked_order = top5_reranked + remaining
        reranked_order_by_id[q["id"]] = reranked_order
        rerank_debug_by_id[q["id"]] = [s.to_dict() for s in scored]

    router_metrics_baseline = E12.router_metrics(queries, baseline_order_by_id)
    router_metrics_reranked = E12.router_metrics(queries, reranked_order_by_id)

    print("\nRouter Metrics Summary:")
    print("  Baseline: R@1 = %.4f | R@3 = %.4f | R@5 = %.4f | MRR = %.4f" % (
        router_metrics_baseline["all_gold_card_questions"]["R@1"],
        router_metrics_baseline["all_gold_card_questions"]["R@3"],
        router_metrics_baseline["all_gold_card_questions"]["R@5"],
        router_metrics_baseline["all_gold_card_questions"]["MRR"],
    ))
    print("  Phase13:  R@1 = %.4f | R@3 = %.4f | R@5 = %.4f | MRR = %.4f" % (
        router_metrics_reranked["all_gold_card_questions"]["R@1"],
        router_metrics_reranked["all_gold_card_questions"]["R@3"],
        router_metrics_reranked["all_gold_card_questions"]["R@5"],
        router_metrics_reranked["all_gold_card_questions"]["MRR"],
    ))

    # Evaluate configurations
    eval_configs = {
        "baseline_extractive": (base_pipe, baseline_order_by_id),
        "baseline_evidence": (ev_base_pipe, baseline_order_by_id),
        "phase13_extractive": (rerank_pipe, reranked_order_by_id),
        "phase13_evidence": (ev_rerank_pipe, reranked_order_by_id),
    }

    eval_results = {}
    for name, (pipe, order_map) in eval_configs.items():
        print(f"\nEvaluating {name}...")
        res = E12.evaluate_config(pipe, queries, order_map, card_url, name=name, llm=False, log=sys.stdout)
        per = res["per_query"]
        entry = {
            "status": "RUN",
            "page_retrieval": E12.page_metrics(queries, per),
            "answers_real_routing": E12.answer_metrics(queries, per, "real"),
            "answers_oracle_routing": E12.answer_metrics(queries, per, "oracle"),
            "latency_ms_real_routing": E12.latency(per, "real"),
            "per_query": per,
        }
        eval_results[name] = entry
        r = entry["answers_real_routing"]
        o = entry["answers_oracle_routing"]
        print(f"  {name:20s} Real Correct: {r['answerable']['answered_correct']}/{r['answerable']['n']} "
              f"| Wrong-Page: {r['wrong_page_answers']} "
              f"| Unsupp-Answered: {r['unsupported']['incorrectly_answered']}/{r['unsupported']['n']} "
              f"| Oracle Correct: {o['answerable']['answered_correct']}/{o['answerable']['n']}")

    # Build per-question diff between baseline_evidence and phase13_evidence
    base_per = eval_results["baseline_evidence"]["per_query"]
    p13_per = eval_results["phase13_evidence"]["per_query"]

    per_question_diff = []
    changed_count = 0
    improved_count = 0
    regressed_count = 0

    for q in queries:
        qid = q["id"]
        b_rec = base_per[qid]["real"]
        p13_rec = p13_per[qid]["real"]

        b_sel = b_rec["selected"]
        p13_sel = p13_rec["selected"]
        gold = q.get("gold_source_id")

        b_order = baseline_order_by_id[qid]
        p13_order = reranked_order_by_id[qid]

        golds = [gold] if (gold and q["type"] != "ambiguous") else list(q.get("acceptable_source_ids") or [])
        b_ranks = [b_order.index(g) + 1 for g in golds if g in b_order]
        b_gold_rank = min(b_ranks) if b_ranks else None
        p13_ranks = [p13_order.index(g) + 1 for g in golds if g in p13_order]
        p13_gold_rank = min(p13_ranks) if p13_ranks else None

        sel_changed = (b_sel != p13_sel)
        ans_changed = (b_rec["answer"] != p13_rec["answer"]) or (b_rec["status"] != p13_rec["status"])
        correct_changed = (b_rec["correct"] != p13_rec["correct"])

        if sel_changed:
            changed_count += 1
        if p13_rec["correct"] and not b_rec["correct"]:
            improved_count += 1
        elif b_rec["correct"] and not p13_rec["correct"]:
            regressed_count += 1

        per_question_diff.append({
            "id": qid,
            "type": q["type"],
            "category": q["category"],
            "query": q["query"],
            "gold": gold,
            "baseline_selected": b_sel,
            "reranked_selected": p13_sel,
            "baseline_gold_rank": b_gold_rank,
            "reranked_gold_rank": p13_gold_rank,
            "selection_changed": sel_changed,
            "answer_changed": ans_changed,
            "correct_changed": correct_changed,
            "baseline_status": b_rec["status"],
            "reranked_status": p13_rec["status"],
            "baseline_outcome": b_rec["outcome"],
            "reranked_outcome": p13_rec["outcome"],
            "baseline_correct": b_rec["correct"],
            "reranked_correct": p13_rec["correct"],
            "baseline_answer": b_rec["answer"],
            "reranked_answer": p13_rec["answer"],
            "rerank_candidates_debug": rerank_debug_by_id.get(qid, []),
        })

    # Save artifacts
    results_payload = {
        "schema_version": 1,
        "phase": "13-A",
        "experiment": "multi_candidate_page_evidence_reranker",
        "queries_sha256": queries_sha,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "timestamp": int(time.time()),
        },
        "scoring_weights": {
            "w_card": PR13.W_CARD,
            "w_page": PR13.W_PAGE,
            "w_coverage": PR13.W_COVERAGE,
            "unresolved_penalty": PR13.UNRESOLVED_PENALTY,
            "not_ingested_penalty": PR13.NOT_INGESTED_PENALTY,
            "top_k_candidates_evaluated": 5,
        },
        "router": {
            "baseline": router_metrics_baseline,
            "reranked": router_metrics_reranked,
        },
        "configs": eval_results,
    }

    results_file = OUT_DIR / "phase13_results.json"
    results_file.write_text(json.dumps(results_payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    diff_file = OUT_DIR / "phase13_per_question_diff.json"
    diff_file.write_text(json.dumps(per_question_diff, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    # Generate comparison JSON and Markdown
    comp_json = {
        "queries_count": len(queries),
        "router_all": {
            "baseline_R@1": router_metrics_baseline["all_gold_card_questions"]["R@1"],
            "reranked_R@1": router_metrics_reranked["all_gold_card_questions"]["R@1"],
            "baseline_R@3": router_metrics_baseline["all_gold_card_questions"]["R@3"],
            "reranked_R@3": router_metrics_reranked["all_gold_card_questions"]["R@3"],
            "baseline_R@5": router_metrics_baseline["all_gold_card_questions"]["R@5"],
            "reranked_R@5": router_metrics_reranked["all_gold_card_questions"]["R@5"],
            "baseline_MRR": router_metrics_baseline["all_gold_card_questions"]["MRR"],
            "reranked_MRR": router_metrics_reranked["all_gold_card_questions"]["MRR"],
        },
        "router_answerable": {
            "baseline_R@1": router_metrics_baseline["answerable"]["R@1"],
            "reranked_R@1": router_metrics_reranked["answerable"]["R@1"],
            "baseline_R@3": router_metrics_baseline["answerable"]["R@3"],
            "reranked_R@3": router_metrics_reranked["answerable"]["R@3"],
            "baseline_MRR": router_metrics_baseline["answerable"]["MRR"],
            "reranked_MRR": router_metrics_reranked["answerable"]["MRR"],
        },
        "answer_metrics_evidence": {
            "baseline_real_correct": eval_results["baseline_evidence"]["answers_real_routing"]["answerable"]["answered_correct"],
            "reranked_real_correct": eval_results["phase13_evidence"]["answers_real_routing"]["answerable"]["answered_correct"],
            "delta_correct": eval_results["phase13_evidence"]["answers_real_routing"]["answerable"]["answered_correct"] - eval_results["baseline_evidence"]["answers_real_routing"]["answerable"]["answered_correct"],
            "baseline_wrong_page": eval_results["baseline_evidence"]["answers_real_routing"]["wrong_page_answers"],
            "reranked_wrong_page": eval_results["phase13_evidence"]["answers_real_routing"]["wrong_page_answers"],
            "baseline_unsupported_answered": eval_results["baseline_evidence"]["answers_real_routing"]["unsupported"]["incorrectly_answered"],
            "reranked_unsupported_answered": eval_results["phase13_evidence"]["answers_real_routing"]["unsupported"]["incorrectly_answered"],
            "oracle_correct": eval_results["phase13_evidence"]["answers_oracle_routing"]["answerable"]["answered_correct"],
        },
        "selection_changes": {
            "total_changed": changed_count,
            "improved_correctness": improved_count,
            "regressed_correctness": regressed_count,
            "net_gain": improved_count - regressed_count,
        }
    }
    (OUT_DIR / "phase13_comparison.json").write_text(json.dumps(comp_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Generate Markdown Report
    md_lines = [
        "# Phase 13-A Evaluation: Multi-Candidate Router Reranking",
        "",
        "## 1. Executive Summary",
        "",
        f"* **Evaluation Set**: Frozen Phase 12 113-question set (SHA-256 `{queries_sha}`)",
        f"* **Architecture**: Top-5 candidate retention + in-page chunk retrieval relevance + deterministic scoring formula",
        f"* **Scoring Formula**: `score = 0.50 * card_sim + 0.40 * page_sim + 0.10 * coverage` (with -0.20 penalty for unresolved identity cards like M2C-18)",
        "",
        "## 2. Router Metrics Comparison",
        "",
        "| Metric | Baseline (Dense Top-1) | Phase 13-A (Reranked Top-5) | Absolute Delta | Relative Gain |",
        "|---|---|---|---|---|",
        f"| **R@1 (All Gold, n=105)** | {comp_json['router_all']['baseline_R@1']:.4f} ({router_metrics_baseline['all_gold_card_questions']['counts']['top1']}/105) | **{comp_json['router_all']['reranked_R@1']:.4f}** ({router_metrics_reranked['all_gold_card_questions']['counts']['top1']}/105) | **+{comp_json['router_all']['reranked_R@1'] - comp_json['router_all']['baseline_R@1']:.4f}** | **+{(comp_json['router_all']['reranked_R@1'] - comp_json['router_all']['baseline_R@1'])/comp_json['router_all']['baseline_R@1']*100:.1f}%** |",
        f"| **R@1 (Answerable, n=65)** | {comp_json['router_answerable']['baseline_R@1']:.4f} ({router_metrics_baseline['answerable']['counts']['top1']}/65) | **{comp_json['router_answerable']['reranked_R@1']:.4f}** ({router_metrics_reranked['answerable']['counts']['top1']}/65) | **+{comp_json['router_answerable']['reranked_R@1'] - comp_json['router_answerable']['baseline_R@1']:.4f}** | **+{(comp_json['router_answerable']['reranked_R@1'] - comp_json['router_answerable']['baseline_R@1'])/comp_json['router_answerable']['baseline_R@1']*100:.1f}%** |",
        f"| **R@3 (All Gold)** | {comp_json['router_all']['baseline_R@3']:.4f} | {comp_json['router_all']['reranked_R@3']:.4f} | +{comp_json['router_all']['reranked_R@3'] - comp_json['router_all']['baseline_R@3']:.4f} | - |",
        f"| **R@5 (All Gold)** | {comp_json['router_all']['baseline_R@5']:.4f} | {comp_json['router_all']['reranked_R@5']:.4f} | 0.0000 | - |",
        f"| **MRR (All Gold)** | {comp_json['router_all']['baseline_MRR']:.4f} | **{comp_json['router_all']['reranked_MRR']:.4f}** | **+{comp_json['router_all']['reranked_MRR'] - comp_json['router_all']['baseline_MRR']:.4f}** | **+{(comp_json['router_all']['reranked_MRR'] - comp_json['router_all']['baseline_MRR'])/comp_json['router_all']['baseline_MRR']*100:.1f}%** |",
        "",
        "## 3. End-to-End Answer Quality (Evidence Pipeline)",
        "",
        "| Metric | Baseline | Phase 13-A Reranker | Delta |",
        "|---|---|---|---|",
        f"| **Answerable Correct (Cited Evidence)** | {comp_json['answer_metrics_evidence']['baseline_real_correct']} / 65 | **{comp_json['answer_metrics_evidence']['reranked_real_correct']} / 65** | **+{comp_json['answer_metrics_evidence']['delta_correct']} (+{comp_json['answer_metrics_evidence']['delta_correct']/65*100:.1f}%)** |",
        f"| **Wrong-Page Answers** | {comp_json['answer_metrics_evidence']['baseline_wrong_page']} | **{comp_json['answer_metrics_evidence']['reranked_wrong_page']}** | **{comp_json['answer_metrics_evidence']['reranked_wrong_page'] - comp_json['answer_metrics_evidence']['baseline_wrong_page']:+d}** |",
        f"| **Unsupported Answered (False Positives)** | {comp_json['answer_metrics_evidence']['baseline_unsupported_answered']} / 40 | {comp_json['answer_metrics_evidence']['reranked_unsupported_answered']} / 40 | {comp_json['answer_metrics_evidence']['reranked_unsupported_answered'] - comp_json['answer_metrics_evidence']['baseline_unsupported_answered']:+d} |",
        f"| **Oracle Answerable Correct** | {comp_json['answer_metrics_evidence']['oracle_correct']} / 65 | {comp_json['answer_metrics_evidence']['oracle_correct']} / 65 | 0 |",
        f"| **Real-vs-Oracle Gap** | {comp_json['answer_metrics_evidence']['oracle_correct'] - comp_json['answer_metrics_evidence']['baseline_real_correct']} | **{comp_json['answer_metrics_evidence']['oracle_correct'] - comp_json['answer_metrics_evidence']['reranked_real_correct']}** | **-{comp_json['answer_metrics_evidence']['baseline_real_correct'] - comp_json['answer_metrics_evidence']['reranked_real_correct']:d} (reduced by {(comp_json['answer_metrics_evidence']['delta_correct'])/(comp_json['answer_metrics_evidence']['oracle_correct'] - comp_json['answer_metrics_evidence']['baseline_real_correct'])*100:.1f}%)** |",
        "",
        "## 4. Latency Impact",
        "",
        f"* **Baseline Real Route Time (Median)**: {eval_results['baseline_evidence']['latency_ms_real_routing']['route_ms']['median']} ms",
        f"* **Phase 13-A Real Route Time (Median)**: {eval_results['phase13_evidence']['latency_ms_real_routing']['route_ms']['median']} ms",
        f"* **Total Pipeline Median Latency**: {eval_results['phase13_evidence']['latency_ms_real_routing']['total_ms']['median']} ms (vs Baseline {eval_results['baseline_evidence']['latency_ms_real_routing']['total_ms']['median']} ms)",
        "",
        "## 5. Selection Changes & Transitions",
        "",
        f"* **Total questions where card selection changed**: {changed_count} / 113",
        f"* **Questions improved from Incorrect/Abstained to Correct**: +{improved_count}",
        f"* **Questions regressed from Correct to Incorrect/Abstained**: -{regressed_count}",
        f"* **Net Correctness Gain**: **+{improved_count - regressed_count}**",
        "",
    ]

    (OUT_DIR / "phase13_comparison.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # Generate Per-Question Markdown Diff
    diff_md_lines = [
        "# Phase 13-A: Per-Question Comparison Diff",
        "",
        "| ID | Type | Gold Card | Baseline Top-1 (Rank) | Reranked Top-1 (Rank) | Sel Changed | Base Status -> Rerank Status | Base Correct -> Rerank Correct | Query |",
        "|---|---|---|---|---|:---:|---|:---:|---|",
    ]
    for d in per_question_diff:
        sel_c = "YES" if d["selection_changed"] else "-"
        cor_c = f"{d['baseline_correct']} -> **{d['reranked_correct']}**" if d["correct_changed"] else str(d["baseline_correct"])
        b_rk = d['baseline_gold_rank'] if d['baseline_gold_rank'] is not None else "N/A"
        r_rk = d['reranked_gold_rank'] if d['reranked_gold_rank'] is not None else "N/A"
        diff_md_lines.append(
            f"| {d['id']} | {d['type']} | {d['gold']} | {d['baseline_selected']} (#{b_rk}) | {d['reranked_selected']} (#{r_rk}) | {sel_c} | {d['baseline_status']} -> {d['reranked_status']} | {cor_c} | {d['query']} |"
        )
    (OUT_DIR / "phase13_per_question_diff.md").write_text("\n".join(diff_md_lines) + "\n", encoding="utf-8")
    print(f"\nPhase 13-A evaluation complete! Artifacts written to {OUT_DIR}")


if __name__ == "__main__":
    main()
