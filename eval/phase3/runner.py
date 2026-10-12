#!/usr/bin/env python3
"""Phase 3 Offline Benchmark Runner.

Executes generator adapters against the frozen 70-case evaluation dataset and
cached evidence snapshots without calling any live external LLM APIs.

Usage:
    python eval/phase3/runner.py --adapter A0 --out eval/phase3/a0_baseline_results.json
    python eval/phase3/runner.py --adapter A2_mock --out eval/phase3/a2_mock_results.json
    python eval/phase3/runner.py --adapter A0 --oracle --out eval/phase3/a0_oracle_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval" / "phase3"))

import adapters
import metrics
import rag_context as RC


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    d = k - f
    return round(s[f] + d * (s[c] - s[f]), 2)


def run_benchmark(
    adapter_id: str = "A0",
    dataset_path: Optional[Path] = None,
    cache_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    oracle_mode: bool = False,
    repetitions: int = 1,
) -> Dict[str, Any]:
    dataset_file = dataset_path or (ROOT / "eval" / "phase3" / "dataset.json")
    cache_file = cache_path or (ROOT / "eval" / "phase3" / "evidence_cache.json")
    out_file = out_path or (ROOT / "eval" / "phase3" / f"{adapter_id.lower()}_baseline_results.json")

    dataset = json.loads(dataset_file.read_text(encoding="utf-8"))
    cache = json.loads(cache_file.read_text(encoding="utf-8"))

    cases = dataset["cases"]
    snapshots = cache["snapshots"]

    adapter = adapters.get_adapter(adapter_id)
    is_test_fixture = getattr(adapter, "is_test_fixture", False)

    print(f"\n=======================================================")
    print(f"SURA Phase 3 Offline Benchmark Runner")
    print(f"Adapter: {adapter_id} (Test fixture: {is_test_fixture})")
    print(f"Oracle Evidence Mode: {oracle_mode}")
    print(f"Cases: {len(cases)} | Repetitions: {repetitions}")
    print(f"=======================================================\n")

    case_results: List[Dict[str, Any]] = []
    latencies: List[float] = []
    retrieval_latencies: List[float] = []
    behavior_matches = 0
    total_key_fact_recall = 0.0
    total_citation_coverage = 0.0
    total_citation_precision = 0.0
    total_hallucinations = 0
    total_prohibited_claims = 0

    for idx, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        snapshot = snapshots.get(case_id) or {}
        question = case["question"]

        # Select items based on oracle mode
        if oracle_mode and snapshot.get("oracle_items"):
            context_items = snapshot["oracle_items"]
        else:
            context_items = snapshot.get("context_items") or []

        context_block = adapters.build_context_block(context_items)

        # Measure generation timing (cold on rep 1, warm on subsequent reps)
        rep_latencies: List[float] = []
        last_result: Optional[adapters.AdapterResult] = None

        for r in range(repetitions):
            res = adapter.generate(question, context_block, snapshot)
            rep_latencies.append(res.latency_ms)
            last_result = res

        assert last_result is not None
        gen_latency_ms = rep_latencies[0] if repetitions == 1 else round(statistics.mean(rep_latencies), 2)
        retrieval_ms = snapshot.get("retrieval_ms", 0.0)

        latencies.append(gen_latency_ms)
        retrieval_latencies.append(retrieval_ms)

        # Deterministic evaluation
        pipeline_status = snapshot.get("pipeline_status", "answered")
        eval_metrics = metrics.evaluate_case(
            case=case,
            answer_text=last_result.text,
            pipeline_status=pipeline_status,
            refused=last_result.refused,
            context_items=context_items,
            adapter_id=adapter_id,
        )

        if eval_metrics["behavior_match"]:
            behavior_matches += 1
        total_key_fact_recall += eval_metrics["key_fact_recall"]
        total_citation_coverage += eval_metrics["citation_coverage"]
        total_citation_precision += eval_metrics["citation_precision"]
        total_hallucinations += len(eval_metrics["hallucinated_tokens"])
        total_prohibited_claims += eval_metrics["prohibited_claims_count"]

        case_entry = {
            "case_id": case_id,
            "category": case["category"],
            "question": question,
            "expected_behavior": case["expected_behavior"],
            "actual_behavior": eval_metrics["actual_behavior"],
            "behavior_match": eval_metrics["behavior_match"],
            "answer": last_result.text,
            "refused": last_result.refused,
            "generation_latency_ms": gen_latency_ms,
            "retrieval_latency_ms": retrieval_ms,
            "metrics": eval_metrics,
            "telemetry": last_result.telemetry,
        }
        case_results.append(case_entry)

        status_flag = "[PASS]" if eval_metrics["behavior_match"] else "[DIFF]"
        print(f"[{idx:02d}/{len(cases):02d}] {status_flag} {case_id} ({case['category'][:22]}): {gen_latency_ms:.1f}ms")

    n = max(1, len(cases))
    summary = {
        "benchmark_schema_version": 1,
        "adapter_id": adapter_id,
        "is_test_fixture": is_test_fixture,
        "oracle_mode": oracle_mode,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(cases),
        "repetitions": repetitions,
        "metrics_summary": {
            "behavior_accuracy": round(behavior_matches / n, 3),
            "behavior_matches": behavior_matches,
            "mean_key_fact_recall": round(total_key_fact_recall / n, 3),
            "mean_citation_coverage": round(total_citation_coverage / n, 3),
            "mean_citation_precision": round(total_citation_precision / n, 3),
            "total_hallucinated_tokens": total_hallucinations,
            "total_prohibited_claims_detected": total_prohibited_claims,
        },
        "latency_summary": {
            "generation_p50_ms": percentile(latencies, 50),
            "generation_p95_ms": percentile(latencies, 95),
            "generation_mean_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "generation_min_ms": round(min(latencies), 2) if latencies else 0.0,
            "generation_max_ms": round(max(latencies), 2) if latencies else 0.0,
            "retrieval_p50_ms": percentile(retrieval_latencies, 50),
            "retrieval_p95_ms": percentile(retrieval_latencies, 95),
            "retrieval_mean_ms": round(statistics.mean(retrieval_latencies), 2) if retrieval_latencies else 0.0,
        },
        "cost_and_tokens": {
            "note": "Null until real hosted model usage and provider pricing are supplied. No fake cost fabricated.",
            "total_input_tokens": None,
            "total_output_tokens": None,
            "cost_per_1000_queries_usd": None,
        },
    }

    full_output = {
        "summary": summary,
        "results": case_results,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(full_output, indent=2), encoding="utf-8")
    print(f"\n=======================================================")
    print(f"Results Summary:")
    print(f"  Behavior Accuracy: {summary['metrics_summary']['behavior_accuracy'] * 100:.1f}% ({behavior_matches}/{len(cases)})")
    print(f"  Mean Key Fact Recall: {summary['metrics_summary']['mean_key_fact_recall'] * 100:.1f}%")
    print(f"  Mean Citation Coverage: {summary['metrics_summary']['mean_citation_coverage'] * 100:.1f}%")
    print(f"  Mean Citation Precision: {summary['metrics_summary']['mean_citation_precision'] * 100:.1f}%")
    print(f"  Generation Latency p50: {summary['latency_summary']['generation_p50_ms']} ms | p95: {summary['latency_summary']['generation_p95_ms']} ms")
    print(f"  Wrote results to: {out_file}")
    print(f"=======================================================\n")

    return full_output


def main():
    parser = argparse.ArgumentParser(description="SURA Phase 3 Offline Benchmark Runner")
    parser.add_argument("--adapter", default="A0", choices=["A0", "A2_mock", "A3_mock"], help="Generator adapter to evaluate")
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "phase3" / "dataset.json", help="Path to evaluation dataset")
    parser.add_argument("--cache", type=Path, default=ROOT / "eval" / "phase3" / "evidence_cache.json", help="Path to evidence cache")
    parser.add_argument("--out", type=Path, default=None, help="Path for results output JSON")
    parser.add_argument("--oracle", action="store_true", help="Run with gold oracle evidence subset where available")
    parser.add_argument("--repetitions", type=int, default=1, help="Number of repetitions per case for latency measurement")
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        prefix = f"{args.adapter.lower()}_oracle" if args.oracle else f"{args.adapter.lower()}_baseline"
        out_path = ROOT / "eval" / "phase3" / f"{prefix}_results.json"

    run_benchmark(
        adapter_id=args.adapter,
        dataset_path=args.dataset,
        cache_path=args.cache,
        out_path=out_path,
        oracle_mode=args.oracle,
        repetitions=args.repetitions,
    )


if __name__ == "__main__":
    main()
