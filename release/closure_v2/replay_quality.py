"""Replay unchanged cached contexts, never label this as current full-RAG inference.

python release/closure_v2/replay_quality.py --out <new-summary.json>
Writes separately named raw normal/oracle results and a detailed stage trace for every
case with a prohibited-claim flag, plus the targeted list/follow-up/payment cases.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "eval/phase3")]
import adapters
import rag_evidence as EV
import runner


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    targets = [
        args.out,
        *[
            args.out.with_name(f"{args.out.stem}-{mode}{suffix}")
            for mode in ["a0", "oracle"]
            for suffix in ["-raw.json", ".log"]
        ],
    ]
    if any(path.exists() for path in targets):
        raise SystemExit(
            "STOP: use new output filenames; existing evidence must not be overwritten"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "scope": "cached-context generation only; retrieval latency/status/source IDs are historical snapshot data, not a fresh retrieval run",
        "source_head": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        "runtime_source_sha256": {
            p: file_sha(ROOT / p)
            for p in [
                "scripts/rag_evidence.py",
                "scripts/rag_pipeline.py",
                "scripts/rag_service.py",
                "scripts/owned_retrieval.py",
            ]
        },
        "inputs_sha256": {
            p: file_sha(ROOT / p)
            for p in [
                "eval/phase3/dataset.json",
                "eval/phase3/evidence_cache.json",
                "eval/phase3/runner.py",
                "eval/phase3/adapters.py",
                "eval/phase3/metrics.py",
            ]
        },
        "modes": {},
    }
    snapshots = json.loads((ROOT / "eval/phase3/evidence_cache.json").read_text())[
        "snapshots"
    ]
    for mode in ["a0", "oracle"]:
        raw_path = args.out.with_name(f"{args.out.stem}-{mode}-raw.json")
        log_path = args.out.with_name(f"{args.out.stem}-{mode}.log")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            raw = runner.run_benchmark(
                adapter_id="A0", oracle_mode=mode == "oracle", out_path=raw_path
            )
        log_path.write_text(stdout.getvalue(), encoding="utf-8")
        targeted = {"CASE-012", "CASE-040", "CASE-052"}
        targeted |= {
            c["case_id"]
            for c in raw["results"]
            if c["metrics"]["prohibited_claims_count"]
        }
        traces = []
        for row in raw["results"]:
            if row["case_id"] not in targeted:
                continue
            snapshot = snapshots[row["case_id"]]
            items = (
                snapshot.get("oracle_items")
                if mode == "oracle" and snapshot.get("oracle_items")
                else snapshot.get("context_items", [])
            )
            context = adapters.build_context_block(items)
            generated = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(
                row["question"], context
            )
            needs = EV.analyze_question(row["question"])
            units = EV.build_units(context.items)
            weights = EV.focus_weights(needs, units)
            traces.append(
                {
                    "case_id": row["case_id"],
                    "question": row["question"],
                    "retrieval_snapshot": {
                        k: snapshot.get(k)
                        for k in [
                            "routed_source_id",
                            "pipeline_status",
                            "reason_code",
                            "retrieval_ms",
                        ]
                    },
                    "identity_limit": "chunk IDs/labels are copied from immutable snapshots; null URL/source_id is not filled in or treated as authoritative version proof",
                    "context_items": items,
                    "sentence_candidates": [
                        {
                            "marker": u.marker,
                            "chunk_id": u.chunk_id,
                            "order": u.order,
                            "source_line_index": u.source_line_index,
                            "text": u.text,
                            "list_items": list(u.list_items),
                            "coverage": EV.unit_score(u, needs, weights),
                        }
                        for u in units
                    ],
                    "construction": {
                        "refused": generated.refused,
                        "answer": generated.text,
                        "evidence": generated.evidence,
                    },
                    "unchanged_metric_result": row["metrics"],
                }
            )
        result["modes"][mode] = {
            "metrics_summary": raw["summary"]["metrics_summary"],
            "total_cases": raw["summary"]["total_cases"],
            "raw_file": raw_path.name,
            "raw_sha256": file_sha(raw_path),
            "log_file": log_path.name,
            "log_sha256": file_sha(log_path),
            "traces": traces,
        }
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {mode: value["metrics_summary"] for mode, value in result["modes"].items()},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
