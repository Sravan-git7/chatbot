"""Versioned API observation package, NOT an independent SAP semantic oracle.

No downloads, no store creation, no output overwrites. Without --url, run offline
resource preflight. Even a complete API observation run needs independent review;
identity/quote matches are candidates, not substantive semantic certification.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def validate_inputs(dataset, root=ROOT):
    failures = []
    for name, digest in dataset["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            failures.append(name)
    return failures


def observe(case, status_code, body):
    if status_code != 200:
        return {
            "http_status": status_code,
            "machine_status": "FAIL",
            "reason": "API did not complete case",
        }
    if case["category"] == "positive":
        identities = {
            f"{s.get('guide_id')}/{s.get('page_id')}" for s in body.get("sources", [])
        }
        answer = " ".join(body.get("answer", "").lower().split())
        quote = any(
            " ".join(q.lower().split()) in answer for q in case["reference_quotes"]
        )
        candidate = (
            body.get("status") == "answered"
            and case["reference_doc_id"] in identities
            and quote
        )
        return {
            "http_status": status_code,
            "machine_status": "CANDIDATE" if candidate else "FAIL",
            "substantive_semantic_correctness": None,
            "independent_review_required": True,
        }
    # This only detects conspicuous failures. A non-answered response is NOT a
    # substantively correct answer and cannot prove semantic safety by itself.
    obvious_failure = body.get("status") == "answered"
    return {
        "http_status": status_code,
        "machine_status": "FAIL" if obvious_failure else "REVIEW_REQUIRED",
        "substantive_semantic_correctness": None,
        "independent_review_required": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", help="Explicit existing private API; never starts/deploys a server"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; choose a new versioned path")
    dataset_path = Path(__file__).with_name("cases.json")
    dataset = json.loads(dataset_path.read_bytes())
    drift = validate_inputs(dataset)
    report = {
        "schema_version": 1,
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "status": "BLOCKED",
        "semantic_certification": False,
        "input_drift": drift,
        "observations": [],
    }
    code = 2
    if drift:
        report.update(
            status="FAIL",
            reason="Frozen reference input drift; no evaluation permitted",
        )
        code = 1
    elif not args.url:
        probe = subprocess.run(
            [sys.executable, str(ROOT / "scripts/preflight_verification.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        report["preflight"] = json.loads(probe.stdout)
        report["preflight_exit"] = probe.returncode
        report["reason"] = (
            "Full API and independent authoritative adjudication required; offline checks are not quality passes"
        )
    else:
        import httpx

        token = os.environ.get("SURA_API_TOKEN", "")
        headers = {"Authorization": "Bearer " + token} if token else {}
        # Never include request headers, token, or environment dumps in evidence.
        with httpx.Client(
            base_url=args.url.rstrip("/"), headers=headers, timeout=90, trust_env=False
        ) as client:
            for case in dataset["cases"]:
                try:
                    response = client.post(
                        "/api/chat", json={"message": case["question"]}
                    )
                    body = response.json()
                    row = observe(case, response.status_code, body)
                    row["response"] = body
                except (httpx.HTTPError, ValueError) as exc:
                    row = {"machine_status": "FAIL", "error_type": type(exc).__name__}
                row["id"] = case["id"]
                report["observations"].append(row)
        if any(r["machine_status"] == "FAIL" for r in report["observations"]):
            report.update(
                status="FAIL",
                reason="API observation failures; no relabeling permitted",
            )
            code = 1
        else:
            report["reason"] = (
                "Independent SAP source/version/claim adjudication still required; observations are not semantic gold"
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2)
        target.write("\n")
    print(json.dumps({"status": report["status"], "semantic_certification": False}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
