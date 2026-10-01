#!/usr/bin/env python3
"""Phase 12 - turn a results file of ``evaluate_phase12.py`` (e.g. the real-Ollama run) into a comparison + a human review sheet. Read-only; invents nothing.

    python scripts/phase12_compare_results.py --results data/evaluation/phase12_results_ollama.json

Writes ``data/phase12/ollama_comparison.json`` and ``.md`` (override with --out-prefix). Contents:
  1. provenance (model, digest, Ollama version, options, host, git head, question-set hash == frozen hash?)
  2. one table: baseline / evidence / ollama_raw / ollama, real routing and oracle routing (BLOCKED configurations are shown as BLOCKED)
  3. parity check: the extractive configurations of this run must equal the sealed ``phase12_results.json`` question by question (status/outcome/answer); a difference is reported, never hidden
  4. review sheet for every LLM configuration: each unsupported question that was answered, each answered-but-not-correct answerable question, each generator error and all answers
     with their text. IMPORTANT: ``correct`` is the repository's citation-evidence criterion (answered, cited a chunk of the gold page that contains the gold evidence phrase). It does
     NOT prove that the LLM's wording is right - the review sheet exists so that a human can judge that.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / "data" / "evaluation" / "phase12_results.json"
FREEZE = ROOT / "data" / "evaluation" / "phase12_freeze.json"
QUERIES = ROOT / "data" / "evaluation" / "phase12_queries.json"
CONFIGS = ("baseline", "evidence", "ollama_raw", "ollama")
LLM = ("ollama_raw", "ollama")


def rows(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if cfg.get("status") != "RUN":
        return None
    out: Dict[str, Any] = {}
    for mode, key in (("real", "answers_real_routing"), ("oracle", "answers_oracle_routing")):
        m = cfg[key]
        out[mode] = {"answerable_n": m["answerable"]["n"], "answerable_correct": m["answerable"]["answered_correct"], "answerable_abstained": m["answerable"]["incorrectly_abstained"],
                     "citation_evidence_failures": m["citation_evidence_failures"], "wrong_page": m["wrong_page_answers"], "unsupported_n": m["unsupported"]["n"],
                     "unsupported_answered": m["unsupported"]["incorrectly_answered"], "unsupported_abstained": m["unsupported"]["correctly_abstained"],
                     "absent_detail_answered": m["absent_detail"]["answered"], "absent_detail_n": m["absent_detail"]["n"], "grounding_failures": m["grounding_failures"],
                     "support_chain_failures": m["support_chain_failures"], "phantom_citations": m["phantom_citations"], "url_changes": m["url_changes"],
                     "generator_errors": m.get("generator_errors_total", 0), "non_answer_reasons": m.get("non_answer_reason_counts", {})}
    out["latency_ms_real"] = cfg["latency_ms_real_routing"]
    out["chunk_retrieval"] = cfg["page_retrieval"]
    return out


def parity(results: Dict[str, Any], sealed: Dict[str, Any]) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    for name in ("baseline", "evidence"):
        a, b = results["configs"].get(name, {}), sealed["configs"].get(name, {})
        if a.get("status") != "RUN" or b.get("status") != "RUN":
            rep[name] = {"compared": False}
            continue
        diffs = []
        for qid, rec in b["per_query"].items():
            for mode in ("real", "oracle"):
                if mode in rec:
                    x, y = rec[mode], a["per_query"].get(qid, {}).get(mode)
                    if y is None or any(x[k] != y[k] for k in ("status", "outcome", "answer", "selected", "reason")):
                        diffs.append({"id": qid, "mode": mode})
        rep[name] = {"compared": True, "differences": len(diffs), "examples": diffs[:10]}
    rep["router_identical"] = results["router"]["all_gold_card_questions"] == sealed["router"]["all_gold_card_questions"]
    return rep


def review(name: str, cfg: Dict[str, Any], queries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    flagged, answers = [], []
    for qid, rec in cfg["per_query"].items():
        q = queries[qid]
        for mode in ("real", "oracle"):
            r = rec.get(mode)
            if not r:
                continue
            entry = {"id": qid, "mode": mode, "type": q["type"], "category": q["category"], "query": q["query"], "status": r["status"], "reason": r["reason"], "correct_by_citation_evidence": r["correct"],
                     "outcome": r["outcome"], "evidence": q.get("evidence"), "absent_terms": q.get("absent_terms"), "answer": r["answer"], "error": r.get("error")}
            if r["status"] == "answered":
                answers.append(entry)
            reasons = []
            if r["status"] == "answered" and q["type"] in ("absent_detail", "not_ingested", "unresolved_identity", "out_of_domain"):
                reasons.append("unsupported_question_answered")
            if r["status"] == "answered" and q["type"] == "answerable" and not r["correct"]:
                reasons.append("answerable_answered_without_cited_evidence")
            if r["status"] == "generator_error":
                reasons.append("generator_error")
            if r["grounding_ok"] is False or r["chain_ok"] is False or r["phantom"]:
                reasons.append("grounding_or_chain_or_phantom_failure")
            if reasons:
                flagged.append(dict(entry, flags=reasons))
    return {"flagged": flagged, "all_answered": answers}


def build(results: Dict[str, Any], sealed: Dict[str, Any]) -> Dict[str, Any]:
    queries = {q["id"]: q for q in json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]}
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))["sha256"]
    out: Dict[str, Any] = {
        "schema_version": 1,
        "provenance": {"queries_sha256": results["queries_sha256"], "equals_frozen_hash": results["queries_sha256"] == frozen, "n_queries": results["n_queries"], "run": results.get("run"),
                       "ollama_ready": (results.get("ollama_environment") or {}).get("ready"), "ollama_model": results.get("ollama_model"),
                       "ollama_options": (results.get("ollama_environment") or {}).get("options"), "ollama_version": (((results.get("ollama_environment") or {}).get("checks") or {}).get("server") or {}).get("version"),
                       "ollama_python_package": (((results.get("ollama_environment") or {}).get("checks") or {}).get("python_package") or {}).get("version"),
                       "host": (results.get("ollama_environment") or {}).get("host"), "corpus": results.get("corpus"), "authorship": results.get("authorship")},
        "configs": {n: ({"status": "RUN", **rows(results["configs"][n])} if rows(results["configs"].get(n, {})) else {"status": results["configs"].get(n, {}).get("status", "NOT_RUN"), "blockers": results["configs"].get(n, {}).get("blocked")}) for n in CONFIGS},
        "router": results["router"]["all_gold_card_questions"],
        "parity_with_sealed_extractive_run": parity(results, sealed),
        "review": {n: review(n, results["configs"][n], queries) for n in LLM if results["configs"].get(n, {}).get("status") == "RUN"},
        "caveat": "'correct' = answered + cited a gold-page chunk containing the gold evidence phrase (citation-evidence criterion). It does not prove the LLM wording is right; see review sheet.",
    }
    return out


def markdown(c: Dict[str, Any]) -> str:
    L: List[str] = ["# Phase 12 - real-Ollama comparison (generated by `scripts/phase12_compare_results.py`)", ""]
    p = c["provenance"]
    L += [f"* question set sha256 `{p['queries_sha256']}` - equals the frozen hash: **{p['equals_frozen_hash']}**; questions: {p['n_queries']}",
          f"* Ollama ready: {p['ollama_ready']}; version {p['ollama_version']}; python package {p['ollama_python_package']}; options {p['ollama_options']}",
          f"* model: {json.dumps((p.get('ollama_model') or {}), default=str)}", f"* run: {json.dumps(p.get('run'), default=str)}", f"* host: {json.dumps(p.get('host'), default=str)}", ""]
    for mode, title in (("real", "Real routing (what a user gets)"), ("oracle", "Oracle routing (gold card forced: retrieval + generation in isolation)")):
        L += [f"## {title}", "", "| metric | " + " | ".join(CONFIGS) + " |", "|---|" + "---|" * len(CONFIGS)]
        keys = [("answerable_correct", "answerable correct (cited evidence)"), ("answerable_abstained", "answerable abstained"), ("citation_evidence_failures", "citation-evidence failures"), ("wrong_page", "wrong-page answers"),
                ("unsupported_answered", "unsupported answered"), ("unsupported_abstained", "unsupported abstained"), ("absent_detail_answered", "absent-detail answered"), ("grounding_failures", "grounding failures"),
                ("support_chain_failures", "support-chain failures"), ("phantom_citations", "phantom citations"), ("url_changes", "URL changes"), ("generator_errors", "generator errors")]
        for k, label in keys:
            cells = [("BLOCKED" if c["configs"][n]["status"] != "RUN" else str(c["configs"][n][mode][k])) for n in CONFIGS]
            L.append(f"| {label} | " + " | ".join(cells) + " |")
        L.append("")
    L += ["## Latency, real routing (ms)", "", "| config | total median | total p95 | generate median | generate p95 |", "|---|---|---|---|---|"]
    for n in CONFIGS:
        cfg = c["configs"][n]
        if cfg["status"] != "RUN":
            L.append(f"| {n} | BLOCKED | | | |")
        else:
            t, g = cfg["latency_ms_real"]["total_ms"], cfg["latency_ms_real"]["generate_ms"]
            L.append(f"| {n} | {t['median']} | {t['p95']} | {g['median']} | {g['p95']} |")
    L += ["", f"Router (all configurations): {json.dumps(c['router'])}", "", "## Parity of the extractive configurations with the sealed run", "", f"`{json.dumps(c['parity_with_sealed_extractive_run'])}`", "",
          f"> {c['caveat']}", ""]
    for n, rv in c["review"].items():
        L += [f"## Review sheet - {n}: {len(rv['flagged'])} flagged, {len(rv['all_answered'])} answers", ""]
        for f in rv["flagged"]:
            L.append(f"* **{f['id']} ({f['mode']}, {f['type']})** flags {f['flags']} - {f['query']}  \n  status `{f['status']}` / `{f['reason']}`; answer: {(f['answer'] or f['error'] or '')[:400]!r}")
        L.append("")
    return "\n".join(L) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--sealed", default=str(SEALED))
    ap.add_argument("--out-prefix", default=str(ROOT / "data" / "phase12" / "ollama_comparison"))
    a = ap.parse_args(argv)
    results = json.loads(Path(a.results).read_text(encoding="utf-8"))
    sealed = json.loads(Path(a.sealed).read_text(encoding="utf-8"))
    c = build(results, sealed)
    pre = Path(a.out_prefix)
    pre.parent.mkdir(parents=True, exist_ok=True)
    pre.with_suffix(".json").write_text(json.dumps(c, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    pre.with_suffix(".md").write_text(markdown(c), encoding="utf-8")
    llm_run = [n for n in LLM if c["configs"][n]["status"] == "RUN"]
    print(f"wrote {pre.with_suffix('.json').name} / .md; LLM configurations run: {llm_run or 'NONE (BLOCKED)'}; frozen hash equal: {c['provenance']['equals_frozen_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
