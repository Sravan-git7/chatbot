"""Read-only reconciliation of historical quality artifacts; no inference or relabelling.

Run from the repository: python release/closure_v2/reconcile_provenance.py --out <new.json>
The historical shell argv/dirty producing tree cannot be recovered from summary metadata.
Git blob identities below are independently verifiable, not execution attestations.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "6eb9d9d25dda75bf9092838b813faa7a51cd8473"
RELEASE = "05ef5e7c99aca8a03ee05b61ba16128093c2e1b9"
SEALED = "9be6553473fa27abbf915c395d4204ca4beae123"
EVALUATORS = [
    "benchmarks/run_quality.py",
    "scripts/evaluate_phase12.py",
    "scripts/phase10_lib.py",
    "scripts/evaluate_phase11_1.py",
    "scripts/rag_pipeline.py",
    "scripts/rag_service.py",
    "scripts/rag_evidence.py",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact(path: str) -> dict:
    return {
        "path": path,
        "sha256": sha((ROOT / path).read_bytes()),
        "last_file_commit": git("log", "-1", "--format=%H", "--", path),
        "introduced_commit": git("log", "--diff-filter=A", "--format=%H", "--", path),
    }


def blob(commit: str, path: str) -> dict:
    spec = f"{commit}:{path}"
    raw = subprocess.check_output(["git", "-C", str(ROOT), "show", spec])
    return {"git_blob": git("rev-parse", spec), "sha256": sha(raw)}


def reconcile() -> dict:
    query_path = "data/evaluation/phase12_queries.json"
    queries = json.loads((ROOT / query_path).read_text())["queries"]
    phase_path = "data/evaluation/phase12_results.json"
    phase = json.loads((ROOT / phase_path).read_text())
    evidence = phase["configs"]["evidence"]
    baseline = json.loads(
        (ROOT / "benchmarks/results/v1_baseline_quality.json").read_text()
    )
    release = json.loads(
        (ROOT / "benchmarks/results/release_05ef5e7_quality.json").read_text()
    )
    query_hash = sha((ROOT / query_path).read_bytes())
    assert (
        query_hash
        == phase["queries_sha256"]
        == baseline["dataset_sha256"]
        == release["dataset_sha256"]
    )
    manifest = json.loads(
        (ROOT / "benchmarks/results/run_manifest_v2.json").read_text()
    )
    checks = {}
    for path, expected in manifest["artifact_sha256"].items():
        actual = sha((ROOT / path).read_bytes())
        assert actual == expected, path
        checks[path] = actual
    comparisons = {}
    for name, data in [
        ("baseline37_vs_context38", baseline),
        ("release37_vs_context38", release),
    ]:
        differences = []
        source_differences = []
        for row in data["per_query"]:
            if row["type"] != "answerable":
                continue
            other = evidence["per_query"][row["id"]]["real"]
            if row["strict_evidence_correct"] != other["correct"]:
                differences.append(
                    {
                        "id": row["id"],
                        "production_strict": row["strict_evidence_correct"],
                        "phase12_context_correct": other["correct"],
                        "production_status": row["status"],
                        "phase12_status": other["status"],
                    }
                )
            if row["selected"] != other["selected"]:
                source_differences.append(
                    {
                        "id": row["id"],
                        "production": row["selected"],
                        "phase12": other["selected"],
                    }
                )
        comparisons[name] = {
            "correctness_disagreements": differences,
            "selected_source_disagreements": source_differences,
        }
    runtimes = {}
    for commit in [phase["run"]["git_head"], SEALED, BASE, RELEASE]:
        paths = (
            EVALUATORS
            if commit == RELEASE
            else [p for p in EVALUATORS if p != "benchmarks/run_quality.py"]
        )
        runtimes[commit] = {path: blob(commit, path) for path in paths}
    return {
        "scope": "historical artifact/implementation reconciliation only; not current inference",
        "dataset": {
            **artifact(query_path),
            "n": len(queries),
            "types": dict(collections.Counter(q["type"] for q in queries)),
        },
        "historical37": [
            {
                **artifact(path),
                "claimed_runtime_commit": commit,
                "stored_source_commit": data["source_commit"],
                "stored_timestamp": data["started_utc"],
                "totals": data["totals"],
                "config": data["config"],
                "runtime_corpus_sha256": data["runtime_corpus_sha256"],
                "label_corpus_sha256": data["label_corpus_sha256"],
            }
            for path, commit, data in [
                ("benchmarks/results/v1_baseline_quality.json", BASE, baseline),
                ("benchmarks/results/release_05ef5e7_quality.json", RELEASE, release),
            ]
        ],
        "historical38": {
            **artifact(phase_path),
            "stored_run": phase["run"],
            "corpus": phase["corpus"],
            "config_name": "evidence",
            "routing": "real",
            "answer_metrics": evidence["answers_real_routing"],
            "page_metrics": evidence["page_retrieval"],
            "documented_historical_command": ".venv/bin/python scripts/evaluate_phase12.py",
            "command_evidence": "RELEASE_REPORT.md table row 9; shell argv/environment/dirty tree not independently attested",
        },
        "evaluators": {
            **artifact("benchmarks/run_quality.py"),
            "historical_git_blobs": runtimes,
            "strict37_definition": "answered, expected guide/page in BOTH cited source and its context item, and reference quote in BOTH answer and cited context",
            "context38_definition": "answered, expected guide/page in cited source and reference quote in cited source text or its debug context; no answer-quote requirement",
            "routing_difference": "37 uses rag_service.production_pipeline_config; 38 build_configs(evidence) wraps RP.build_pipeline defaults, not production config",
        },
        "comparisons": comparisons,
        "historical_manifest": {
            **artifact("benchmarks/results/run_manifest_v2.json"),
            "artifact_hashes_verified": checks,
            "contains_commands_key": "commands" in manifest,
        },
        "limitations": [
            "Same 113 frozen inputs and 65 answerable denominator; scores are not the same metric/pipeline.",
            "The 38 artifact reports HEAD c7527ed, but is published in a later corpus/evaluator commit 9be6553. HEAD does not identify uncommitted producing bytes.",
            "The committed evaluator blobs and report establish reproducible implementation references, not exact historical argv or a signed clean-tree execution record.",
            "The 37 evaluator was introduced at 05ef5e7 and can run against an older --source-root; its absence from 6eb9d9d is not a contradiction.",
            "Historical summaries do not retain full debug contexts; cannot recompute both predicates on identical historical raw outputs from these files alone.",
            "No meaningful one-case regression/improvement can be inferred from 37 versus 38.",
            "Labels are AI-authored frozen references, not independent SAP approval.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "dataset": result["dataset"]["sha256"],
                "answerable": result["dataset"]["types"]["answerable"],
                "historical37": [
                    r["totals"]["answerable_strict_correct"]
                    for r in result["historical37"]
                ],
                "historical38": result["historical38"]["answer_metrics"]["answerable"][
                    "answered_correct"
                ],
                "comparisons": {
                    k: {x: len(y) for x, y in v.items()}
                    for k, v in result["comparisons"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
