#!/usr/bin/env python3
"""Phase 17A - EvidenceGuard Structural / Frame Normalization Ablation Evaluation.

Evaluates 2 configurations across the frozen 113 questions with llama3.2:3b:
1. phase16_combined_ABC:   A=True, B=True, C=True, E=False (Phase 16 verified baseline)
2. phase17a_combined_ABCE: A=True, B=True, C=True, E=True  (Phase 17A structural frame normalization)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_phase12 as E12
import page_corpus as PC
import phase10_lib as L
import rag_evidence as RE
import rag_pipeline as RP
from rag_generate import GenerationResult


class CachedLLMGenerator:
    """Wraps an LLM generator with an in-memory cache keyed by (query, context_content_hash)."""
    def __init__(self, inner: Any):
        self.inner = inner
        self.name = getattr(inner, "name", "cached_ollama")
        self.cache: Dict[Tuple[str, str], GenerationResult] = {}

    def generate(self, query: str, context: Any) -> GenerationResult:
        ctx_hash = hashlib.sha256("\n".join(f"{it.marker}:{it.content_hash}" for it in context.items).encode("utf-8")).hexdigest()
        key = (query.strip(), ctx_hash)
        if key in self.cache:
            res = self.cache[key]
            return GenerationResult(res.text, res.refused, res.generator, res.raw_text, res.prompt)
        res = self.inner.generate(query, context)
        self.cache[key] = res
        return res


def run_evaluation() -> None:
    print("=" * 80)
    print("PHASE 17A: EVIDENCEGUARD STRUCTURAL / FRAME NORMALIZATION EVALUATION")
    print("=" * 80)

    queries_path = ROOT / "data" / "evaluation" / "phase12_queries.json"
    queries_payload = json.loads(queries_path.read_text(encoding="utf-8"))
    queries = queries_payload["queries"]
    queries_sha = hashlib.sha256(queries_path.read_bytes()).hexdigest()
    print(f"Loaded {len(queries)} frozen queries (SHA256: {queries_sha[:12]}...)")

    cards_manifest = json.loads((ROOT / "data" / "card_collection_manifest.json").read_text(encoding="utf-8"))
    card_url = {c["source_id"]: c.get("card_url", "") for c in cards_manifest.get("cards", [])}

    out_dir = ROOT / "data" / "phase17a"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "phase17a_ollama_ckpt.jsonl"
    ckpt_header = {
        "queries_sha256": queries_sha,
        "model": "llama3.2:3b",
        "phase": "17a",
    }
    ckpt = E12.Checkpoint(ckpt_path, ckpt_header)

    # Pre-populate from Phase 16 checkpoint if available
    p16_ckpt = ROOT / "data" / "phase16" / "phase16_ollama_ckpt.jsonl"
    if p16_ckpt.is_file():
        with open(p16_ckpt, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("config") == "phase16_combined_ABC":
                    if ckpt.get("phase16_combined_ABC", d["id"], d["mode"]) is None:
                        ckpt.put("phase16_combined_ABC", d["id"], d["mode"], d["record"])

    # Build shared underlying LLM generator with cache
    raw_ollama = RP.build_pipeline(generator="ollama").generator
    cached_llm = CachedLLMGenerator(raw_ollama)

    configs = [
        ("phase16_combined_ABC", True, True, True, False, "Phase 16 Combined Baseline (A=True, B=True, C=True, E=False)"),
        ("phase17a_combined_ABCE", True, True, True, True, "Phase 17A Combined (A=True, B=True, C=True, E=True)"),
    ]

    all_gold_q = [q for q in queries if q.get("gold_source_id") or q["type"] == "ambiguous"]
    ans_q = [q for q in queries if q["type"] == "answerable"]

    results_by_config: Dict[str, Any] = {}

    for eval_key, flag_a, flag_b, flag_c, flag_e, desc in configs:
        print(f"\n{'='*70}\nEVALUATING CONFIGURATION: {desc}\n{'='*70}")

        pipe_cfg = RP.PipelineConfig(
            top_k_cards=10,
            rerank_router=True,
            code_aware_router=True,
            in_page_grounding=flag_a,
            citation_normalization=flag_b,
            relaxed_context_gate=flag_c,
            evidence_frame_normalization=flag_e,
        )

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
            ans = base_pipe.answer(q["query"], debug=True)
            t_route_ms = (time.perf_counter() - t_route_start) * 1000
            route_latencies.append(t_route_ms)

            scored_cands = ans["routing"].get("candidates", [])
            topk_reranked = [c["source_id"] for c in scored_cands]

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

        # Build Guarded LLM pipeline sharing the cached generator
        pipe_llm = RP.RagPipeline(
            base_pipe.backend,
            base_pipe.retriever,
            base_pipe.ctx,
            base_pipe.corpus,
            cached_llm,
            base_pipe.count_tokens,
            config=pipe_cfg,
        )
        guard_llm_pipe = RE.build_evidence_pipeline(pipe_llm, tau=RE.SHIPPED_TAU, widen=False, generator="ollama")

        print(f"Running Guarded Ollama evaluation for {eval_key}...")
        res_guard = E12.evaluate_config(guard_llm_pipe, queries, order_by_id, card_url, name=eval_key, llm=True, ckpt=ckpt, log=sys.stdout)
        per_guard = res_guard["per_query"]

        ans_real = E12.answer_metrics(queries, per_guard, "real")
        ans_ora = E12.answer_metrics(queries, per_guard, "oracle")

        # Extractive baseline
        res_ext = E12.evaluate_config(base_pipe, queries, order_by_id, card_url, name=f"ext_{eval_key}", llm=False, log=None)
        ans_ext_real = E12.answer_metrics(queries, res_ext["per_query"], "real")

        real_corr = ans_real["answerable"]["answered_correct"]
        ora_corr = ans_ora["answerable"]["answered_correct"]
        gap = ora_corr - real_corr

        t_tots = [v["real"]["timings"]["total_ms"] for v in per_guard.values() if "real" in v and "timings" in v["real"] and "total_ms" in v["real"]["timings"]]
        tot_med = round(statistics.median(t_tots), 2) if t_tots else None
        tot_mean = round(statistics.mean(t_tots), 2) if t_tots else None

        print(f"\nGuarded Ollama ({eval_key}) Summary:")
        print(f"  Answerable Correct: {real_corr}/65 (Oracle: {ora_corr}/65, Gap: {gap})")
        print(f"  Extractive Correct: {ans_ext_real['answerable']['answered_correct']}/65")
        print(f"  Wrong-Page Answers: {ans_real['wrong_page_answers']}")
        print(f"  Unsupported Answered: {ans_real['unsupported']['incorrectly_answered']}/40")
        print(f"  Absent-Detail Answered: {ans_real['absent_detail']['answered']}/16")
        print(f"  Grounding Failures: {ans_real['grounding_failures']}")
        print(f"  Phantom Citations: {ans_real['phantom_citations']}")
        print(f"  Citation Evidence Failures: {ans_real['citation_evidence_failures']}")
        print(f"  Generator Errors: {ans_real['generator_errors_total']}")
        print(f"  Route Latency: median={round(statistics.median(route_latencies), 2)}ms, mean={round(statistics.mean(route_latencies), 2)}ms")
        print(f"  Total Pipeline Latency: median={tot_med}ms, mean={tot_mean}ms")

        results_by_config[eval_key] = {
            "key": eval_key,
            "description": desc,
            "flags": {
                "in_page_grounding": flag_a,
                "citation_normalization": flag_b,
                "relaxed_context_gate": flag_c,
                "evidence_frame_normalization": flag_e,
            },
            "router_metrics": {
                "all_gold_r1": ag["R@1"],
                "all_gold_r1_count": ag["counts"]["top1"],
                "all_gold_mrr": ag["MRR"],
                "all_gold_in_pool_rate": gold_in_pool_rate,
                "answerable_r1": ans_block["R@1"],
                "answerable_r1_count": ans_block["counts"]["top1"],
                "answerable_in_pool_rate": ans_gold_in_pool_rate,
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
                "total_pipeline_median_ms": tot_med,
                "total_pipeline_mean_ms": tot_mean,
            },
            "per_query": per_guard,
        }

    # Compare Phase 17A against Phase 16 baseline
    base_pq = results_by_config["phase16_combined_ABC"]["per_query"]
    p17_pq = results_by_config["phase17a_combined_ABCE"]["per_query"]
    recovered = []
    regressed = []
    for q in ans_q:
        qid = q["id"]
        b_corr = base_pq[qid]["real"]["correct"]
        c_corr = p17_pq[qid]["real"]["correct"]
        if not b_corr and c_corr:
            recovered.append({
                "id": qid,
                "query": q["query"],
                "gold": q["gold_source_id"],
                "answer": p17_pq[qid]["real"].get("answer"),
            })
        elif b_corr and not c_corr:
            regressed.append({
                "id": qid,
                "query": q["query"],
                "gold": q["gold_source_id"],
                "baseline_answer": base_pq[qid]["real"].get("answer"),
                "config_answer": p17_pq[qid]["real"].get("answer"),
            })

    diff_report = {
        "recovered_count": len(recovered),
        "recovered": recovered,
        "regressed_count": len(regressed),
        "regressed": regressed,
    }

    # Save full comparison JSON
    final_output = {
        "schema_version": 1,
        "phase": "17a",
        "experiment": "Phase 17A EvidenceGuard Frame Normalization Ablation",
        "queries_sha256": queries_sha,
        "model": "llama3.2:3b",
        "results": results_by_config,
        "diff_report": diff_report,
    }

    comparison_path = out_dir / "phase17a_comparison.json"
    comparison_path.write_text(json.dumps(final_output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved full Phase 17A comparison to: {comparison_path}")

    # Generate Markdown Report
    md_lines = [
        "# Phase 17A: EvidenceGuard Structural / Frame Normalization Report\n",
        f"* **Model**: `llama3.2:3b`",
        f"* **Evaluation Set**: Frozen Phase 12 113-question benchmark",
        f"* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards\n",
        "## 1. Comparative Metrics (Phase 16 vs Phase 17A)\n",
        "| Configuration | Guarded Ollama Correct / 65 | Oracle / 65 | Gap | Extractive / 65 | Absent-Detail / 16 | Wrong-Page | Grounding Failures | Median Route ms | Median Total ms |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for k in ["phase16_combined_ABC", "phase17a_combined_ABCE"]:
        c = results_by_config[k]
        g = c["guarded_ollama"]
        e = c["extractive"]
        lat = c["latency"]
        md_lines.append(f"| **{k}** | **{g['answerable_correct']} / 65** | {g['oracle_correct']} / 65 | {g['real_vs_oracle_gap']} | {e['answerable_correct']} / 65 | {g['absent_detail_answered']} / 16 | {g['wrong_page_answers']} | {g['grounding_failures']} | {lat['route_median_ms']} ms | {lat['total_pipeline_median_ms']} ms |")

    md_lines.append("\n## 2. Recovery & Regression Details\n")
    md_lines.append(f"* **Recovered ({diff_report['recovered_count']})**:")
    for r in diff_report["recovered"]:
        md_lines.append(f"  * **{r['id']}**: *{r['query']}*")
        md_lines.append(f"    *Answer*: {r['answer']}")
    md_lines.append(f"* **Regressed ({diff_report['regressed_count']})**:")
    for r in diff_report["regressed"]:
        md_lines.append(f"  * **{r['id']}**: *{r['query']}*")

    report_path = out_dir / "phase17a_report.md"
    report_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Saved Markdown report to: {report_path}")


if __name__ == "__main__":
    run_evaluation()
