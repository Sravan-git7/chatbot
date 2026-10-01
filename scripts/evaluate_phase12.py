#!/usr/bin/env python3
"""Phase 12 (E) - evaluate the COMPLETE product pipeline on the frozen Phase 12 question set. Contract: ``data/phase12_contract.md``.

    python scripts/evaluate_phase12.py                                  # baseline + evidence (+ ollama configs: run only if a real Ollama is ready, else recorded as BLOCKED)
    python scripts/evaluate_phase12.py --configs baseline,evidence,ollama_raw,ollama --require-ollama --out data/evaluation/phase12_results_ollama.json     # machine with Ollama + llama3.2:3b

Configurations: ``baseline`` = extractive generator of Phases 8-10; ``evidence`` = shipped Phase 11.1 configuration; ``ollama_raw`` = real LLM without the evidence guard;
``ollama`` = real LLM + ``EvidenceGuard``. An ``ollama*`` configuration is NEVER replaced by another generator: when the environment check (``phase12_ollama_check``) fails it is
recorded as ``BLOCKED`` with the exact blockers and contributes no metrics. The result file of a sealed evaluation is not overwritten (use ``--out`` for a new file).

An LLM call that raises (server stopped, timeout) is recorded as ``generator_error`` for that question - it is never counted as a correct answer or as a correct abstention, never retried
with another generator, and 5 consecutive errors stop the run without writing results. ``--checkpoint`` (default ``<out>.partial.jsonl``) stores every finished (configuration, mode, question)
so that an interrupted run resumes instead of restarting; a checkpoint written for another question set or another model is refused.

Routing is measured separately from generation: router ranks come from the card collection for every question that has a gold card (ambiguous: best acceptable rank); generation
metrics are produced twice - with the real router (what a user gets) and with the gold card forced (the generator and retriever in isolation).
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

QUERIES = ROOT / "data" / "evaluation" / "phase12_queries.json"
FREEZE = ROOT / "data" / "evaluation" / "phase12_freeze.json"
RESULTS = ROOT / "data" / "evaluation" / "phase12_results.json"
PERF = ROOT / "data" / "evaluation" / "phase12_performance.json"
UNSUPPORTED_TYPES = ("absent_detail", "not_ingested", "unresolved_identity", "out_of_domain")
ALL_CONFIGS = ("baseline", "evidence", "ollama_raw", "ollama")
GENERATOR_ERROR = "generator_error"
MAX_CONSECUTIVE_ERRORS = 5


def load_queries(path: Path = QUERIES, freeze: Path = FREEZE) -> List[Dict[str, Any]]:
    import phase10_lib as L
    fz = json.loads(freeze.read_text(encoding="utf-8"))
    if L.sha(path) != fz["sha256"]:
        raise SystemExit("STOP: the Phase 12 question set differs from its frozen hash")
    return json.loads(path.read_text(encoding="utf-8"))["queries"]


def pct(xs: Sequence[float], p: float) -> Optional[float]:
    xs = sorted(xs)
    return round(xs[max(0, int(len(xs) * p) - 1)], 1) if xs else None


def router_rank(q: Dict[str, Any], order: Sequence[str]) -> Optional[int]:
    """Rank of the gold card (ambiguous: best rank among the acceptable cards); None for questions without a gold card."""
    gold = [q["gold_source_id"]] if q["type"] != "ambiguous" else list(q.get("acceptable_source_ids") or [])
    ranks = [order.index(g) + 1 for g in gold if g in order]
    return min(ranks) if ranks else None


def outcome(q: Dict[str, Any], a: Dict[str, Any], correct: bool, selected_ok: bool) -> str:
    """One label per (question, answer). ``selected_ok`` = the card/page the answer came from is the gold (or an acceptable) one."""
    answered = a["status"] == "answered"
    t = q["type"]
    if a["status"] == GENERATOR_ERROR:
        return f"{t}_generator_error"
    if t == "answerable":
        if not answered:
            return "answerable_abstained"
        if correct:
            return "answerable_answered_correct"
        return "answerable_answered_wrong_page" if not selected_ok else "answerable_answered_citation_evidence_failure"
    if t == "ambiguous":
        if not answered:
            return "ambiguous_abstained"
        return "ambiguous_answered_acceptable" if selected_ok else "ambiguous_answered_wrong_page"
    return f"{t}_incorrectly_answered" if answered else f"{t}_correctly_abstained"


def error_record(q: Dict[str, Any], mode: str, selected: Optional[str], exc: BaseException) -> Dict[str, Any]:
    """A generator that raised: recorded as such. Not an answer, not a correct abstention, never retried with another generator."""
    a = {"status": GENERATOR_ERROR}
    return {"status": GENERATOR_ERROR, "selected": selected, "reason": "GENERATOR_EXCEPTION", "correct": False, "outcome": outcome(q, a, False, False), "grounding_ok": None, "chain_ok": None, "phantom": 0,
            "url_changed": 0, "evidence_in_context": False, "answer": None, "timings": {}, "status_match": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def answer_record(pipe: Any, q: Dict[str, Any], mode: str, oracle: Optional[str], card_url: Dict[str, str]) -> Dict[str, Any]:
    import evaluate_phase8 as EP8
    import evaluate_phase11_1 as EV
    import phase10_lib as L
    a = pipe.answer(q["query"], debug=True, oracle_source_id=oracle)
    d = a["debug"] or {}
    items = (d.get("context") or {}).get("items", [])
    srcs = a["citations"]["answer_sources"]
    gold_page = (q.get("gold_doc_id") or "/").split("/")
    ok_cards = set(q.get("acceptable_source_ids") or []) | ({q["gold_source_id"]} if q.get("gold_source_id") else set())
    selected = a["routing"]["selected_source_id"] if mode == "real" else oracle
    correct = bool(q["type"] == "answerable" and L.correct(q, a))
    selected_ok = selected in ok_cards
    cited_urls = [(s.get("url"), (s.get("join") or {}).get("card_source_id")) for s in srcs]
    return {"status": a["status"], "selected": selected, "reason": a["reason_code"], "correct": correct, "outcome": outcome(q, a, correct, selected_ok),
            "grounding_ok": (d.get("grounding") or {}).get("ok", True) if a["status"] == "answered" else None,
            "chain_ok": EV.chain_ok(a["answer"], items) if a["status"] == "answered" else None,
            "phantom": sum(1 for s in srcs if s["chunk_id"] not in {i["chunk_id"] for i in items}),
            "url_changed": sum(1 for u, c in cited_urls if c in card_url and u != card_url[c]),
            "evidence_in_context": bool(q.get("evidence")) and any(EP8.has_evidence(i["text"], q["evidence"]) and i["guide_id"] == gold_page[0] and i["page_id"] == gold_page[-1] for i in items),
            "answer": a["answer"], "timings": a["timings_ms"], "status_match": a["status"] == q["expected_status"]}


class Checkpoint:
    """Append-only JSONL of finished (configuration, mode, question) records. The header pins the question-set hash and the model."""

    def __init__(self, path: Optional[Path], header: Dict[str, Any]) -> None:
        self.path, self.header, self.done = path, header, {}
        if path is None:
            return
        if path.exists():
            lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            if not lines or lines[0].get("header") != header:
                raise SystemExit(f"STOP: {path.name} was written for a different question set / model / configuration list; delete it to start over")
            for r in lines[1:]:
                self.done[(r["config"], r["id"], r["mode"])] = r["record"]
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"header": header}) + "\n", encoding="utf-8")

    def get(self, config: str, qid: str, mode: str) -> Optional[Dict[str, Any]]:
        return self.done.get((config, qid, mode))

    def put(self, config: str, qid: str, mode: str, record: Dict[str, Any]) -> None:
        self.done[(config, qid, mode)] = record
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"config": config, "id": qid, "mode": mode, "record": record}, ensure_ascii=False, default=str) + "\n")


def evaluate_config(pipe: Any, queries: Sequence[Dict[str, Any]], order_by_id: Dict[str, List[str]], card_url: Dict[str, str], name: str = "", llm: bool = False,
                    ckpt: Optional[Checkpoint] = None, log: Any = None) -> Dict[str, Any]:
    """``llm=True``: a raising generator is recorded per question (``generator_error``); 5 consecutive errors stop the run. For the extractive configurations exceptions propagate."""
    import evaluate_phase8 as EP8
    ckpt = ckpt or Checkpoint(None, {})
    per: Dict[str, Dict[str, Any]] = {}
    consecutive, t0 = 0, time.time()
    for n, q in enumerate(queries, 1):
        rec: Dict[str, Any] = {"type": q["type"], "category": q["category"]}
        for mode, oracle in (("real", None), ("oracle", q["gold_source_id"] if q["type"] in ("answerable", "absent_detail") else None)):
            if mode == "oracle" and oracle is None:
                continue
            r = ckpt.get(name, q["id"], mode)
            if r is None:
                try:
                    r = answer_record(pipe, q, mode, oracle, card_url)
                    if r["timings"].get("generate_ms") is not None:      # only a call that reached the generator proves the generator works
                        consecutive = 0
                except Exception as e:                                           # noqa: BLE001
                    if not llm:
                        raise
                    r = error_record(q, mode, oracle, e)
                    consecutive += 1
                    if consecutive >= MAX_CONSECUTIVE_ERRORS:
                        raise SystemExit(f"STOP: {consecutive} consecutive generator errors for '{name}' (last: {r['error']}); nothing was written; fix the Ollama service and re-run (finished questions are kept in the checkpoint)") from e
                ckpt.put(name, q["id"], mode, r)
            rec[mode] = r
        if q["type"] == "answerable" and q.get("gold_doc_id"):
            g, p = q["gold_doc_id"].split("/")
            hits = pipe.retriever.retrieve_in_page(q["query"], g, p, top_k=5)
            ranks = [i + 1 for i, h in enumerate(hits) if EP8.has_evidence(h.text, q["evidence"])]
            rec["chunk_rank"] = ranks[0] if ranks else None
        per[q["id"]] = rec
        if log is not None and (n % 10 == 0 or n == len(queries)):
            print(f"  [{name}] {n}/{len(queries)} questions, {time.time() - t0:.0f}s elapsed", file=log, flush=True)
    return {"per_query": per}


def router_metrics(queries: Sequence[Dict[str, Any]], order_by_id: Dict[str, List[str]]) -> Dict[str, Any]:
    def block(qs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        ranks = [router_rank(q, order_by_id[q["id"]]) for q in qs]
        n = len(ranks)
        f = lambda k: round(sum(1 for r in ranks if r and r <= k) / n, 4) if n else None  # noqa: E731
        return {"n": n, "R@1": f(1), "R@3": f(3), "R@5": f(5), "MRR": round(sum(1 / r for r in ranks if r) / n, 4) if n else None,
                "counts": {"top1": sum(1 for r in ranks if r == 1), "top3": sum(1 for r in ranks if r and r <= 3), "top5": sum(1 for r in ranks if r and r <= 5)}}
    gold = [q for q in queries if q.get("gold_source_id") or q["type"] == "ambiguous"]
    out = {"all_gold_card_questions": block(gold), "answerable": block([q for q in queries if q["type"] == "answerable"]),
           "by_category": {c: block([q for q in gold if q["category"] == c]) for c in sorted({q["category"] for q in gold})},
           "by_type": {t: block([q for q in gold if q["type"] == t]) for t in sorted({q["type"] for q in gold})}}
    return out


def page_metrics(queries: Sequence[Dict[str, Any]], per: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ans = [q for q in queries if q["type"] == "answerable" and q.get("gold_doc_id")]
    ranks = [per[q["id"]].get("chunk_rank") for q in ans]
    n = len(ranks)
    f = lambda k: round(sum(1 for r in ranks if r and r <= k) / n, 4) if n else None  # noqa: E731
    return {"n": n, "chunk_R@1": f(1), "chunk_R@3": f(3), "chunk_R@5": f(5), "chunk_MRR": round(sum(1 / r for r in ranks if r) / n, 4) if n else None,
            "counts": {"top1": sum(1 for r in ranks if r == 1), "top3": sum(1 for r in ranks if r and r <= 3), "top5": sum(1 for r in ranks if r and r <= 5)},
            "evidence_in_context_real_routing": sum(1 for q in ans if per[q["id"]]["real"]["evidence_in_context"]), "evidence_in_context_oracle_routing": sum(1 for q in ans if per[q["id"]]["oracle"]["evidence_in_context"])}


def answer_metrics(queries: Sequence[Dict[str, Any]], per: Dict[str, Dict[str, Any]], mode: str) -> Dict[str, Any]:
    recs = [(q, per[q["id"]][mode]) for q in queries if mode in per[q["id"]]]
    count = lambda o: sum(1 for _, r in recs if r["outcome"] == o)  # noqa: E731
    ans = [(q, r) for q, r in recs if q["type"] == "answerable"]
    uns = [(q, r) for q, r in recs if q["type"] in UNSUPPORTED_TYPES]
    ab = [(q, r) for q, r in recs if q["type"] == "absent_detail"]
    amb = [(q, r) for q, r in recs if q["type"] == "ambiguous"]
    m = {"answerable": {"n": len(ans), "answered_correct": count("answerable_answered_correct"), "answered_wrong_page": count("answerable_answered_wrong_page"),
                        "answered_citation_evidence_failure": count("answerable_answered_citation_evidence_failure"), "incorrectly_abstained": count("answerable_abstained"), "generator_errors": count("answerable_generator_error")},
         "unsupported": {"n": len(uns), "correctly_abstained": sum(1 for _, r in uns if r["status"] not in ("answered", GENERATOR_ERROR)), "generator_errors": sum(1 for _, r in uns if r["status"] == GENERATOR_ERROR), "incorrectly_answered": sum(1 for _, r in uns if r["status"] == "answered"),
                         "status_match": sum(1 for _, r in uns if r["status_match"])},
         "absent_detail": {"n": len(ab), "abstained": sum(1 for _, r in ab if r["status"] not in ("answered", GENERATOR_ERROR)), "answered": sum(1 for _, r in ab if r["status"] == "answered")},
         "ambiguous": {"n": len(amb), "answered_acceptable": count("ambiguous_answered_acceptable"), "answered_wrong_page": count("ambiguous_answered_wrong_page"), "abstained": count("ambiguous_abstained")},
         "generator_errors_total": sum(1 for _, r in recs if r["status"] == GENERATOR_ERROR),
         "non_answer_reason_counts": dict(sorted(Counter(r["reason"] for _, r in recs if r["status"] != "answered").items())),
         "wrong_page_answers": count("answerable_answered_wrong_page") + count("ambiguous_answered_wrong_page"),
         "wrong_topic_answers": sum(1 for _, r in uns if r["status"] == "answered"),
         "grounding_failures": sum(1 for _, r in recs if r["grounding_ok"] is False), "support_chain_failures": sum(1 for _, r in recs if r["chain_ok"] is False),
         "citation_evidence_failures": count("answerable_answered_citation_evidence_failure"), "phantom_citations": sum(r["phantom"] for _, r in recs), "url_changes": sum(r["url_changed"] for _, r in recs)}
    cats: Dict[str, Dict[str, int]] = {}
    for q, r in recs:
        cats.setdefault(q["category"], {})
        cats[q["category"]][r["outcome"]] = cats[q["category"]].get(r["outcome"], 0) + 1
    m["by_category_outcomes"] = cats
    return m


def latency(per: Dict[str, Dict[str, Any]], mode: str = "real") -> Dict[str, Any]:
    out = {}
    for stage in ("route_ms", "retrieve_ms", "generate_ms", "total_ms"):
        xs = [r[mode]["timings"].get(stage) for r in per.values() if mode in r and r[mode]["timings"].get(stage) is not None]
        out[stage] = {"median": round(statistics.median(xs), 1) if xs else None, "p95": pct(xs, 0.95), "n": len(xs)}
    return out


def build_configs(requested: Sequence[str], ollama_env: Dict[str, Any]) -> Dict[str, Any]:
    """name -> pipeline, or {"blocked": reason}. An ollama configuration is only built when the environment check passed."""
    import rag_evidence as E
    import rag_pipeline as RP
    out: Dict[str, Any] = {}
    base = None
    for name in requested:
        if name in ("baseline", "evidence"):
            base = base or RP.build_pipeline(generator="extractive")
            out[name] = base if name == "baseline" else E.build_evidence_pipeline(base, tau=E.SHIPPED_TAU, widen=False, generator="extractive")
        elif name in ("ollama_raw", "ollama"):
            if not ollama_env.get("ready"):
                out[name] = {"blocked": ollama_env.get("blockers") or ["OLLAMA_NOT_READY"], "statement": ollama_env.get("statement")}
                continue
            llm = RP.build_pipeline(generator="ollama")
            out[name] = llm if name == "ollama_raw" else E.build_evidence_pipeline(llm, tau=E.SHIPPED_TAU, widen=False, generator="ollama")
        else:
            raise SystemExit(f"unknown configuration {name}")
    return out


def model_details(model: Optional[str], http_get: Any = None) -> Optional[Dict[str, Any]]:
    """Digest/size/family of the configured model as reported by the local Ollama server (``/api/tags``); None when unavailable."""
    import phase12_ollama_check as OC
    status, body, _ = (http_get or OC.loopback_get)("/api/tags", 5.0)
    if status != 200:
        return None
    try:
        for m in json.loads(body).get("models") or []:
            if (m.get("name") or m.get("model")) == model:
                return {"name": m.get("name"), "digest": m.get("digest"), "size_bytes": m.get("size"), "modified_at": m.get("modified_at"), "details": m.get("details")}
    except ValueError:
        return None
    return None


def run_info() -> Dict[str, Any]:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        head = None
    return {"git_head": head, "python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(), "started_at_unix": int(time.time())}


def corpus_info() -> Dict[str, Any]:
    pm = json.loads((ROOT / "data" / "page_collection_manifest.json").read_text(encoding="utf-8"))
    n = len(pm.get("page_doc_ids") or [])
    return {"local_pages": n, "cards": 29, "complete": n == 29}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import phase12_ollama_check as OC
    import phase10_lib as L
    import rag_pipeline as RP
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="baseline,evidence,ollama_raw,ollama")
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--perf-out", default=None, help="default: phase12_performance.json for the default --out, else <out>_performance.json")
    ap.add_argument("--checkpoint", default=None, help="default: <out>.partial.jsonl (resume an interrupted run)")
    ap.add_argument("--require-ollama", action="store_true", help="exit 3 before doing anything if a real Ollama + model is not ready (instead of recording BLOCKED)")
    a = ap.parse_args(argv)
    out_path = Path(a.out)
    perf_path = Path(a.perf_out) if a.perf_out else (PERF if out_path.resolve() == RESULTS.resolve() else out_path.with_name(out_path.stem + "_performance.json"))
    for target in (out_path, perf_path):
        if target.exists():
            raise SystemExit(f"STOP: {target.name} exists; a sealed evaluation is not overwritten (use --out for a new file)")
    queries = load_queries()
    requested = [c for c in a.configs.split(",") if c]
    ollama_env = OC.check() if any(c.startswith("ollama") for c in requested) else {"ready": False, "blockers": ["NOT_REQUESTED"]}
    if a.require_ollama and any(c.startswith("ollama") for c in requested) and not ollama_env.get("ready"):
        print(f"STOP: real Ollama is not ready: {ollama_env.get('blockers')}", file=sys.stderr)
        return 3
    configs = build_configs(requested, ollama_env)
    model = ollama_env.get("configured_model")
    info = run_info()
    ckpt_path = Path(a.checkpoint) if a.checkpoint else out_path.with_name(out_path.name + ".partial.jsonl")
    ckpt = Checkpoint(ckpt_path if any(c.startswith("ollama") and not isinstance(configs[c], dict) for c in requested) else None,
                      {"queries_sha256": L.sha(QUERIES), "model": model, "configs": requested})
    units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
    card_url = {u["source_id"]: u["source_url"] for u in (units["units"] if isinstance(units, dict) else units)}
    base = RP.build_pipeline(generator="extractive")
    order_by_id: Dict[str, List[str]] = {}
    for q in queries:
        raw = base.backend.query(q["query"], 29)
        order_by_id[q["id"]] = [m["source_id"] for m in raw["metadatas"][0]]
    results: Dict[str, Any] = {"schema_version": 1, "queries_sha256": L.sha(QUERIES), "n_queries": len(queries), "authorship": json.loads(QUERIES.read_text(encoding="utf-8"))["authorship"],
                               "corpus": corpus_info(), "run": info,
                               "ollama_environment": {k: ollama_env.get(k) for k in ("ready", "blockers", "statement", "configured_model", "options", "host", "checks")},
                               "ollama_model": model_details(model) if ollama_env.get("ready") else None,
                               "router": router_metrics(queries, order_by_id), "configs": {}}
    perf: Dict[str, Any] = {"schema_version": 1, "note": "latency in ms of the process/host that ran the evaluation (see results.run / ollama_environment.host)", "configs": {}}
    for name in requested:
        cfg = configs[name]
        if isinstance(cfg, dict) and "blocked" in cfg:
            results["configs"][name] = {"status": "BLOCKED", **cfg}
            perf["configs"][name] = {"status": "BLOCKED"}
            print(f"{name:11s} BLOCKED {cfg['blocked']}")
            continue
        res = evaluate_config(cfg, queries, order_by_id, card_url, name=name, llm=name.startswith("ollama"), ckpt=ckpt, log=sys.stdout)
        per = res["per_query"]
        entry = {"status": "RUN", "page_retrieval": page_metrics(queries, per), "answers_real_routing": answer_metrics(queries, per, "real"), "answers_oracle_routing": answer_metrics(queries, per, "oracle"),
                 "latency_ms_real_routing": latency(per, "real"), "per_query": per}
        results["configs"][name] = entry
        perf["configs"][name] = {"status": "RUN", "latency_ms_real_routing": entry["latency_ms_real_routing"], "latency_ms_oracle_routing": latency(per, "oracle")}
        r, o = entry["answers_real_routing"], entry["answers_oracle_routing"]
        print(f"{name:11s} real: ans-correct {r['answerable']['answered_correct']}/{r['answerable']['n']} wrong-page {r['wrong_page_answers']} unsupp-answered {r['unsupported']['incorrectly_answered']}/{r['unsupported']['n']} "
              f"| oracle: ans-correct {o['answerable']['answered_correct']}/{o['answerable']['n']} absent-answered {o['absent_detail']['answered']}/{o['absent_detail']['n']} cit-ev-fail {o['citation_evidence_failures']} "
              f"| gen-errors {r['generator_errors_total']+o['generator_errors_total']} | ground {r['grounding_failures']+o['grounding_failures']} phantom {r['phantom_citations']+o['phantom_citations']} url {r['url_changes']+o['url_changes']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    perf_path.write_text(json.dumps(perf, indent=1) + "\n", encoding="utf-8")
    rt = results["router"]["all_gold_card_questions"]
    print(f"router (n={rt['n']}): R@1 {rt['R@1']} R@3 {rt['R@3']} R@5 {rt['R@5']} MRR {rt['MRR']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
