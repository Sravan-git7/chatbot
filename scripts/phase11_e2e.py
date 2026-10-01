#!/usr/bin/env python3
"""Phase 11 - end-to-end run over HTTP: question -> /api/chat -> real RAG pipeline -> JSON, against a RUNNING server.

    python scripts/rag_api.py --generator extractive --port 8000        # terminal 1
    python scripts/phase11_e2e.py --base-url http://127.0.0.1:8000       # terminal 2

Questions: ``data/evaluation/phase11_e2e_questions.json`` (AI-authored before the first run; expectations are never edited after a run).
Writes ``data/phase11_e2e_results.json``. Nothing here is mocked: every record is a real HTTP response of the live service. A question "passes" only if the API
status, the routed card (when one is expected), the evidence phrase inside a CITED chunk, the citation URL (equal to the stored card URL) and the grounding flag all agree.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "data" / "evaluation" / "phase11_e2e_questions.json"
OUT = ROOT / "data" / "phase11_e2e_results.json"
BROWSER = ROOT / "data" / "phase11" / "browser_e2e.json"
DIST = ROOT / "web" / "dist"
INTERNAL_ID = re.compile(r"\bM2C-\d+\b")
REPEATS = 5


def norm(s: str) -> str:
    return " ".join((s or "").split())


def card_urls() -> Dict[str, str]:
    d = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
    return {u["source_id"]: u["source_url"] for u in (d["units"] if isinstance(d, dict) else d)}


def pct(xs: List[float], p: float) -> float:
    xs = sorted(xs)
    return round(xs[int(p * (len(xs) - 1))], 1)


def routed_card(dbg: Dict[str, Any]) -> Optional[str]:
    return (dbg["debug"].get("routing") or {}).get("selected_source_id")


def judge(q: Dict[str, Any], plain: Dict[str, Any], dbg: Dict[str, Any], urls: Dict[str, str]) -> Dict[str, Any]:
    checks: Dict[str, Optional[bool]] = {}
    checks["status"] = plain["status"] == q["expected_status"]
    routed = (dbg["debug"].get("routing") or {}).get("selected_source_id")       # the router's choice, also when the public metadata hides it (out_of_scope)
    checks["card"] = (routed == q["expected_card"]) if q["expected_card"] else None
    checks["debug_does_not_change_answer"] = (plain["answer"], plain["sources"], plain["status"]) == (dbg["answer"], dbg["sources"], dbg["status"])
    if plain["status"] == "answered":
        items = {i["chunk_id"]: i["text"] for i in (dbg["debug"]["pipeline"].get("context") or {}).get("items", [])}
        cited = [items.get(s["chunk_id"], "") for s in plain["sources"]]
        checks["evidence_in_cited_chunk"] = (any(norm(q["evidence"]) in norm(t) for t in cited)) if q["evidence"] else None
        checks["citation_url_is_stored_card_url"] = bool(plain["sources"]) and all(s["url"] == urls.get(s["source_id"]) for s in plain["sources"])
        checks["grounded"] = plain["metadata"]["grounded"] is True
        checks["markers_resolve"] = {m for m in re.findall(r"\[(S\d+)\]", plain["answer"])} <= {s["marker"] for s in plain["sources"]}
    else:
        checks["no_sources"] = plain["sources"] == []
        checks["no_internal_ids_in_text"] = not INTERNAL_ID.search(plain["answer"])
        checks["not_grounded_flag"] = plain["metadata"]["grounded"] is False
        if plain["topic_reference"]:
            checks["reference_not_in_sources"] = plain["topic_reference"]["url"] not in [s["url"] for s in plain["sources"]]
    failed = [k for k, v in checks.items() if v is False]
    mode = None
    if failed:
        if "status" in failed and q["expected_status"] == "unable_to_verify" and plain["status"] == "answered":
            mode = "absent_detail_answered"
        elif "card" in failed:
            mode = "routing_miss"
        elif "status" in failed:
            mode = "status_mismatch"
        else:
            mode = "check_failed: " + ", ".join(failed)
    return {"checks": checks, "passed": not failed, "failure_mode": mode}


def main(argv: Optional[List[str]] = None) -> int:
    global OUT, QUESTIONS
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(OUT), help="results file (default: the Phase 11 results; Phase 11.1 passes its own path)")
    ap.add_argument("--questions", default=str(QUESTIONS))
    a = ap.parse_args(argv)
    OUT, QUESTIONS = Path(a.out), Path(a.questions)
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    urls = card_urls()
    rows: List[Dict[str, Any]] = []
    with httpx.Client(base_url=a.base_url, timeout=60) as c:
        health = c.get("/api/health").json()
        if not health.get("ready"):
            print("STOP: service not ready:", health)
            return 2
        for q in qs:
            plain_r = c.post("/api/chat", json={"message": q["question"]})
            dbg_r = c.post("/api/chat", json={"message": q["question"], "debug": True})
            if plain_r.status_code != 200 or dbg_r.status_code != 200:
                rows.append({"id": q["id"], "question": q["question"], "http_status": [plain_r.status_code, dbg_r.status_code], "passed": False, "failure_mode": "http_error", "body": plain_r.text[:300]})
                continue
            plain, dbg = plain_r.json(), dbg_r.json()
            j = judge(q, plain, dbg, urls)
            tm = dbg["debug"]["timings_ms"]
            rows.append({"id": q["id"], "question": q["question"], "type": q["type"], "expected_status": q["expected_status"], "expected_card": q["expected_card"], "evidence_expected": q["evidence"],
                         "http_status": 200, "status": plain["status"], "selected_card": routed_card(dbg), "public_card_id": plain["metadata"]["card_id"], "card_title": plain["metadata"]["card_title"],
                         "pipeline_status": plain["metadata"]["pipeline_status"], "reason_code": plain["metadata"]["reason_code"],
                         "page": sorted({s["chunk_id"].rsplit("/", 1)[0] for s in plain["sources"]}), "answer": plain["answer"], "citations": [{k: s[k] for k in ("marker", "title", "section", "url")} for s in plain["sources"]],
                         "topic_reference": plain["topic_reference"], "grounded": plain["metadata"]["grounded"], "grounding": plain["metadata"]["grounding"],
                         "server_timings_ms": {k: tm.get(k) for k in ("route_ms", "retrieve_ms", "generate_ms", "total_ms")}, **j})
        # ---- latency: repeat each question, client round trip and server-reported time (non-debug requests)
        client_ms: List[float] = []
        server_ms: List[float] = []
        parts: Dict[str, List[float]] = {"route_ms": [], "retrieve_ms": [], "generate_ms": []}
        for q in qs:
            for _ in range(REPEATS):
                t = time.perf_counter()
                r = c.post("/api/chat", json={"message": q["question"], "debug": True}).json()
                client_ms.append((time.perf_counter() - t) * 1000)
                server_ms.append(r["metadata"]["latency_ms"])
                for k in parts:
                    if r["debug"]["timings_ms"].get(k) is not None:
                        parts[k].append(r["debug"]["timings_ms"][k])
        health_ms = []
        for _ in range(20):
            t = time.perf_counter()
            c.get("/api/health")
            health_ms.append((time.perf_counter() - t) * 1000)
        # ---- error paths on the live server
        errors = {}
        for name, kw in (("empty_message", {"json": {"message": ""}}), ("malformed_json", {"content": "{", "headers": {"content-type": "application/json"}}), ("missing_field", {"json": {}}),
                         ("too_long", {"json": {"message": "a " * 3000}}), ("bad_conversation_id", {"json": {"message": "hi", "conversation_id": "no spaces!"}})):
            r = c.post("/api/chat", **kw)
            errors[name] = {"http_status": r.status_code, "code": r.json().get("error", {}).get("code")}
        injected = c.post("/api/chat", json={"message": "<img src=x onerror=alert(1)> How is billing handled?"}).json()
        errors["html_in_question_not_reflected"] = "onerror" not in json.dumps(injected)
    passed = sum(1 for r in rows if r["passed"])
    answerable = [r for r in rows if r.get("type") == "answerable"]
    summary = {"questions": len(rows), "passed": passed, "answerable": len(answerable), "answerable_passed": sum(1 for r in answerable if r["passed"]),
               "negatives": len(rows) - len(answerable), "negatives_passed": sum(1 for r in rows if r.get("type") != "answerable" and r["passed"]),
               "failures": [{"id": r["id"], "mode": r["failure_mode"]} for r in rows if not r["passed"]]}
    bundle = {p.name: p.stat().st_size for p in sorted((DIST / "assets").glob("*"))} if (DIST / "assets").is_dir() else None
    import hashlib
    out = {"schema_version": 1, "questions_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(), "base_url": a.base_url, "generator": health.get("generator"), "health": health, "summary": summary, "results": rows,
           "error_paths": errors,
           "latency_ms": {"repeats_per_question": REPEATS, "samples": len(client_ms), "api_round_trip_median": round(statistics.median(client_ms), 1), "api_round_trip_p95": pct(client_ms, 0.95),
                          "server_total_median": round(statistics.median(server_ms), 1), "server_total_p95": pct(server_ms, 0.95),
                          "routing_median": round(statistics.median(parts["route_ms"]), 1), "retrieval_median": round(statistics.median(parts["retrieve_ms"]), 1) if parts["retrieve_ms"] else None,
                          "generation_median": round(statistics.median(parts["generate_ms"]), 1) if parts["generate_ms"] else None, "health_median": round(statistics.median(health_ms), 1)},
           "frontend_bundle_bytes": bundle, "browser": json.loads(BROWSER.read_text(encoding="utf-8")) if BROWSER.is_file() else None}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
