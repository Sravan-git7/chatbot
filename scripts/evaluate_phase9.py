#!/usr/bin/env python3
"""Phase 9B/9C/9D - fresh retrieval and end-to-end evaluation over the frozen query set ``data/evaluation/phase9_queries.json``.

Reports routing | identity | page retrieval | generation | citation SEPARATELY. Everything here runs offline. The generator measured is the
deterministic EXTRACTIVE baseline unless a real Ollama server with the configured model is detected; if it is not, the LLM section is written as
BLOCKED (no other model is substituted and no LLM metric is invented). Nothing is tuned: the query file is frozen (sha256 recorded in
``phase9_queries_freeze.json``; a different hash stops the run) and the pre-registered constants must equal the constants in the code.

Writes (deterministic):  data/evaluation/phase9_results.json, data/evaluation/phase9_failure_audit.json
Writes (timings):        data/evaluation/phase9_performance.json

    python scripts/evaluate_phase9.py
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_page_collection as BP  # noqa: E402
import evaluate_phase8 as EP8  # noqa: E402
import m2c_router as RT  # noqa: E402
import page_chunker as PK  # noqa: E402
import page_corpus as PC  # noqa: E402
import rag_context as RC  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_pipeline as RP  # noqa: E402
import rag_text as T  # noqa: E402

ROOT = PC.ROOT
QUERIES = ROOT / "data" / "evaluation" / "phase9_queries.json"
FREEZE = ROOT / "data" / "evaluation" / "phase9_queries_freeze.json"
RESULTS = ROOT / "data" / "evaluation" / "phase9_results.json"
AUDIT = ROOT / "data" / "evaluation" / "phase9_failure_audit.json"
PERF = ROOT / "data" / "evaluation" / "phase9_performance.json"
STATUS_JSON = ROOT / "data" / "phase9" / "corpus_status.json"
FETCH_LOG = ROOT / "data" / "phase9" / "fetch_attempt_log.json"
prop, has_evidence = EP8.prop, EP8.has_evidence
KS = (1, 3, 5)
ROUTER_DEPTH = 29                                           # rank the gold card over the whole card collection

PHASE4_RECORDED = {"recall@1": 0.92, "recall@3": 0.96, "recall@5": 1.0, "mrr": 0.95}
PHASE5_RECORDED = {"recall@1": 0.7222, "recall@3": 0.7963, "recall@5": 0.8704, "mrr": 0.7873}
PHASE8_RESULTS_SHA256_PREFIX = "735f706188d8154e"          # recorded at the end of Phase 8 (full hash is recomputed live)


def check_frozen(payload_bytes: bytes) -> Dict[str, Any]:
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    h = hashlib.sha256(payload_bytes).hexdigest()
    if h != fz["sha256"]:
        raise SystemExit(f"STOP: {QUERIES.name} differs from the frozen copy ({h[:12]} != {fz['sha256'][:12]}); the evaluation set must not change after freezing")
    return {"sha256": h, "frozen_on": fz["frozen_on"], "queries": fz["queries"]}


def check_preregistered(p: Dict[str, Any]) -> None:
    code = {"ood_min_coverage": RP.OOD_MIN_COVERAGE, "context_min_coverage": RP.CONTEXT_MIN_COVERAGE, "extractive_min_score": RG.EXTRACTIVE_MIN_SCORE,
            "min_sentence_support": RG.MIN_SENTENCE_SUPPORT, "context_budget_tokens": RC.DEFAULT_BUDGET_TOKENS, "max_context_chunks": RC.DEFAULT_MAX_CHUNKS}
    bad = {k: (p.get(k), v) for k, v in code.items() if p.get(k) != v}
    if not str(p.get("default_chunk_strategy", "")).startswith(PK.DEFAULT_STRATEGY):
        bad["default_chunk_strategy"] = (p.get("default_chunk_strategy"), PK.DEFAULT_STRATEGY)
    if bad:
        raise SystemExit(f"STOP: pre-registered constants differ from the code (no tuning on the evaluation set): {bad}")


# ---------------------------------------------------------------------------------------------------- Ollama detection (local only)

def detect_ollama(timeout: float = 1.0) -> Dict[str, Any]:
    import importlib.util
    import rag_core
    out: Dict[str, Any] = {"configured_model": rag_core.LLM_MODEL_NAME, "executable_on_path": shutil.which("ollama"), "python_package_importable": importlib.util.find_spec("ollama") is not None,
                           "server_reachable_127_0_0_1_11434": False, "configured_model_listed": None}
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=timeout):
            out["server_reachable_127_0_0_1_11434"] = True
    except OSError:
        pass
    if out["server_reachable_127_0_0_1_11434"] and out["python_package_importable"]:
        try:
            import ollama
            names = [m.get("model") or m.get("name") for m in ollama.list().get("models", [])]
            out["configured_model_listed"] = any(n and n.split(":")[0] == rag_core.LLM_MODEL_NAME.split(":")[0] and n == rag_core.LLM_MODEL_NAME for n in names)
        except Exception as e:                                                  # noqa: BLE001
            out["configured_model_listed"] = None
            out["list_error"] = f"{type(e).__name__}: {e}"
    out["available"] = bool(out["server_reachable_127_0_0_1_11434"] and out["python_package_importable"] and out["configured_model_listed"])
    out["status"] = "available" if out["available"] else "BLOCKED: local model unavailable (no Ollama executable/server/model reachable; nothing was downloaded or substituted)"
    return out


# ---------------------------------------------------------------------------------------------------- routing

def mean(xs: Sequence[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def route_all(pipe: RP.RagPipeline, queries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for q in queries:
        r = RT.route(q["query"], pipe.backend, top_k=ROUTER_DEPTH)
        out[q["id"]] = [{"rank": c.rank, "source_id": c.source_id, "distance": c.distance, "similarity": round(1.0 - c.distance, 4)} for c in r.candidates]
    return out


def auroc(pos: Sequence[float], neg: Sequence[float]) -> Optional[float]:
    """P(score_pos > score_neg) (ties 0.5): Mann-Whitney. Descriptive only."""
    if not pos or not neg:
        return None
    s = 0.0
    for a in pos:
        for b in neg:
            s += 1.0 if a > b else 0.5 if a == b else 0.0
    return round(s / (len(pos) * len(neg)), 4)


def router_metrics(queries: Sequence[Dict[str, Any]], routes: Dict[str, Any], units: Dict[str, Any], ingested: Sequence[str] = ()) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    gold = [q for q in queries if q.get("gold_source_id")]
    ranks: Dict[str, Optional[int]] = {}
    for q in gold:
        ranks[q["id"]] = next((c["rank"] for c in routes[q["id"]] if c["source_id"] == q["gold_source_id"]), None)

    def block(qs):
        rk = [ranks[q["id"]] for q in qs]
        n = len(qs)
        d = {f"recall@{k}": prop(sum(1 for r in rk if r and r <= k), n) for k in KS}
        d["mrr"] = round(sum(1 / r for r in rk if r) / n, 4) if n else None
        d["n"] = n
        return d

    res: Dict[str, Any] = {"depth_ranked": ROUTER_DEPTH, "all_gold_card_queries": block(gold), "answerable_only": block([q for q in gold if q["type"] == "answerable"])}
    res["by_type"] = {t: block([q for q in gold if q["type"] == t]) for t in sorted({q["type"] for q in gold})}
    res["by_facet_answerable"] = {f: block([q for q in gold if q["type"] == "answerable" and q["facet"] == f]) for f in sorted({q["facet"] for q in gold if q["type"] == "answerable"})}
    if ingested:
        # DIAGNOSTIC ONLY (not a system): rank of the gold card when the other 22 cards are removed from the router's list, i.e. the same 7-way choice that
        # corpus-wide page retrieval makes. It shows how much of the card-router loss is caused by the 22 cards that have no local page.
        ing = set(ingested)
        sub = [q for q in gold if q["type"] == "answerable"]
        rk = []
        for q in sub:
            kept = [c for c in routes[q["id"]] if c["source_id"] in ing]
            rk.append(next((i + 1 for i, c in enumerate(kept) if c["source_id"] == q["gold_source_id"]), None))
        res["diagnostic_answerable_rank_among_the_7_ingested_cards_only"] = {**{f"recall@{k}": prop(sum(1 for r in rk if r and r <= k), len(sub)) for k in (1, 3)},
                                                                              "mrr": round(sum(1 / r for r in rk if r) / len(sub), 4) if sub else None, "n": len(sub),
                                                                              "note": "diagnostic only; not a deployable routing mode"}
    per_card = {}
    for sid in sorted({q["gold_source_id"] for q in gold}):
        qs = [q for q in gold if q["gold_source_id"] == sid]
        per_card[sid] = {"n": len(qs), "top1": sum(1 for q in qs if ranks[q["id"]] == 1)}
    res["per_gold_card_top1"] = per_card
    lenient = [q for q in gold if ranks[q["id"]] == 1 or (routes[q["id"]][0]["source_id"] in q.get("acceptable_source_ids", []))]
    res["rank1_in_gold_or_acceptable_sibling"] = prop(len(lenient), len(gold))
    res["rank_distribution_of_gold_card"] = {str(k): sum(1 for r in ranks.values() if r == k) for k in sorted({r for r in ranks.values() if r})}
    # similarity / gap
    ok = [routes[q["id"]] for q in gold if ranks[q["id"]] == 1]
    bad = [routes[q["id"]] for q in gold if ranks[q["id"]] != 1]
    gap = lambda r: round(r[0]["similarity"] - r[1]["similarity"], 4)   # noqa: E731  rank-1 minus rank-2 similarity (>= 0)
    res["rank1_similarity"] = {"correct_mean": mean([r[0]["similarity"] for r in ok]), "wrong_mean": mean([r[0]["similarity"] for r in bad]),
                               "correct_median": round(statistics.median([r[0]["similarity"] for r in ok]), 4) if ok else None,
                               "wrong_median": round(statistics.median([r[0]["similarity"] for r in bad]), 4) if bad else None}
    res["rank1_rank2_similarity_gap"] = {"correct_mean": mean([gap(r) for r in ok]), "wrong_mean": mean([gap(r) for r in bad]),
                                         "auroc_gap_separates_correct_from_wrong": auroc([gap(r) for r in ok], [gap(r) for r in bad]),
                                         "note": "descriptive only; no threshold is derived or applied (Phase 7F: min_cosine stays None)"}
    # failures + heuristic classification
    cards = {sid: u for sid, u in units.items()}
    cterms = {sid: T.term_set(u["embedding_text"]) for sid, u in units.items()}
    failures: List[Dict[str, Any]] = []
    for q in gold:
        r1 = routes[q["id"]][0]
        if ranks[q["id"]] == 1:
            continue
        routed, g = r1["source_id"], q["gold_source_id"]
        qt = set(T.terms(q["query"]))
        if routed in q.get("acceptable_source_ids", []):
            cause = "sibling_card_ambiguity"
        elif q["facet"] == "sibling_ambiguous":
            cause = "query_ambiguity"
        elif q["facet"] == "terminology_mismatch":
            cause = "vocabulary_mismatch"
        elif cards[routed]["category"] == cards[g]["category"]:
            cause = "sibling_card_ambiguity"
        elif q["facet"] in ("entity", "rare_term"):
            cause = "rare_terminology"
        elif not (qt & cterms[g]):
            cause = "vocabulary_mismatch"
        elif q["type"] == "unresolved_identity":
            cause = "missing_page_card_identity"
        else:
            cause = "other_unexplained"
        failures.append({"id": q["id"], "query": q["query"], "type": q["type"], "facet": q["facet"], "gold": g, "routed": routed, "gold_rank": ranks[q["id"]],
                         "rank1_similarity": r1["similarity"], "gold_similarity": next((c["similarity"] for c in routes[q["id"]] if c["source_id"] == g), None),
                         "acceptable_sibling": routed in q.get("acceptable_source_ids", []), "cause_heuristic": cause})
    res["failure_count"] = len(failures)
    res["failure_causes_heuristic"] = {c: sum(1 for f in failures if f["cause_heuristic"] == c) for c in sorted({f["cause_heuristic"] for f in failures})}
    res["failure_classification_note"] = ("rule-based and ordered (acceptable sibling > ambiguous query > terminology facet > same category > entity/rare facet > zero term overlap > unresolved "
                                          "identity > other); a cause label is a hypothesis from the query/card text, NOT a proven root cause and NOT evidence about the tokenizer")
    res["failure_destination_card_counts"] = {c: sum(1 for f in failures if f["routed"] == c) for c in sorted({f["routed"] for f in failures})}
    return res, failures


def ood_observations(queries: Sequence[Dict[str, Any]], routes: Dict[str, Any], router_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ood = [q for q in queries if q["type"] == "out_of_domain"]
    ind = [q for q in queries if q["type"] != "out_of_domain"]
    s = lambda q: routes[q["id"]][0]["similarity"]                                           # noqa: E731
    status = {r["q"]["id"]: r["a"]["status"] for r in router_rows}
    return {"rank1_similarity_mean": {"out_of_domain": mean([s(q) for q in ood]), "in_domain": mean([s(q) for q in ind])},
            "auroc_rank1_similarity_in_domain_vs_ood": auroc([s(q) for q in ind], [s(q) for q in ood]),
            "gate_flagged_out_of_domain": prop(sum(1 for q in ood if status[q["id"]] == "out_of_domain"), len(ood)),
            "gate_answered_ood": [q["id"] for q in ood if status[q["id"]] == "answered"],
            "in_domain_wrongly_flagged_out_of_domain": prop(sum(1 for q in ind if status[q["id"]] == "out_of_domain"), len(ind)),
            "ood_queries_flagged_by": {q["id"]: status[q["id"]] for q in ood},
            "note": "descriptive only. The OOD gate is an uncalibrated lexical heuristic and n is small; no OOD threshold is proposed (7F verdict stands)"}


# ---------------------------------------------------------------------------------------------------- end-to-end failure audit

def audit_rows(rows: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        q, a = r["q"], r["a"]
        topic = a.get("topic") or {}
        dbg = a.get("debug", {})
        ctx_items = dbg.get("context", {}).get("items", [])
        selected = a["routing"]["selected_source_id"]
        routed_doc = f"{topic.get('effective_guide_id')}/{topic.get('effective_page_id')}" if topic else None
        srcs = a["citations"]["answer_sources"]
        texts = {i["chunk_id"]: i["text"] for i in ctx_items}
        category = None
        if q["type"] == "answerable":
            ok = a["status"] == "answered" and any(has_evidence(texts.get(s["chunk_id"], ""), q["evidence"]) for s in srcs) and all(f"{s['guide_id']}/{s['page_id']}" == q["gold_doc_id"] for s in srcs)
            if not ok:
                if selected != q["gold_source_id"]:
                    category = "wrong_route"
                elif a["status"] == "out_of_domain" or a["reason_code"] == "LOW_QUERY_TERM_COVERAGE_IN_CONTEXT":
                    category = "ood_or_context_gate_false_refusal"                      # stopped by a lexical gate before / after retrieval, even though the routed page is the gold page
                elif not any(has_evidence(i["text"], q["evidence"]) for i in ctx_items):
                    category = "insufficient_retrieval"
                elif a["status"] != "answered":
                    category = "correct_retrieval_incorrect_synthesis" if a["reason_code"] in ("GENERATOR_REFUSED", "GROUNDING_VERIFICATION_FAILED") else "ood_or_context_gate_false_refusal"
                else:
                    category = "citation_mismatch"
        elif q["type"] == "absent_detail":
            if a["status"] == "answered":
                category = "failure_to_abstain" if selected == q["gold_source_id"] else "wrong_route"
            elif a["status"] != q["expected_status"]:
                category = "wrong_route" if selected != q["gold_source_id"] else "other_status_mismatch"
        elif q["type"] in ("not_ingested", "unresolved_identity"):
            if a["status"] != q["expected_status"]:
                category = "failure_to_abstain" if a["status"] == "answered" else ("ood_gate_false_positive" if a["status"] == "out_of_domain" else "wrong_route")
        elif q["type"] == "out_of_domain":
            if a["status"] != "out_of_domain":
                category = "failure_to_abstain" if a["status"] == "answered" else "other_status_mismatch"
        if category is None:
            continue
        out.append({"mode": mode, "id": q["id"], "query": q["query"], "type": q["type"], "facet": q["facet"], "expected_status": q["expected_status"], "actual_status": a["status"],
                    "reason_code": a["reason_code"], "selected_card": selected, "gold_card": q.get("gold_source_id"), "identity_status": topic.get("identity_status"),
                    "effective_page": routed_doc, "retrieved_chunk_ids": [h["chunk_id"] for h in dbg.get("retrieved", [])], "context_chunk_ids": [i["chunk_id"] for i in ctx_items],
                    "answer": a["answer"], "cited_chunk_ids": [s["chunk_id"] for s in srcs], "expected_evidence": q.get("evidence", []), "failure_category": category})
    return out


def page_retrieval(pipe: RP.RagPipeline, queries: List[Dict[str, Any]], count: Any, records: List[Dict[str, Any]], routes: Dict[str, Any]) -> Dict[str, Any]:
    chunks = PK.chunk_corpus(records, PK.STRATEGIES[PK.DEFAULT_STRATEGY], count)
    r = EP8.retrieval_eval(pipe.retriever, queries, count, chunks)
    ranks = r.pop("_ranks_in_gold_page")
    ans = [q for q in queries if q["type"] == "answerable"]
    routed_ok = [q for q in ans if routes[q["id"]][0]["source_id"] == q["gold_source_id"]]
    n = len(routed_ok)
    r["given_card_router_rank1_is_gold"] = {"n": n, **{f"recall@{k}": prop(sum(1 for q in routed_ok if ranks[q["id"]] and ranks[q["id"]] <= k), n) for k in KS},
                                           "mrr": round(sum(1 / ranks[q["id"]] for q in routed_ok if ranks[q["id"]]) / n, 4) if n else None}
    r["by_facet_in_gold_page"] = {}
    for f in sorted({q["facet"] for q in ans}):
        qs = [q for q in ans if q["facet"] == f]
        r["by_facet_in_gold_page"][f] = {"n": len(qs), "recall@1": prop(sum(1 for q in qs if ranks[q["id"]] == 1), len(qs)), "recall@5": prop(sum(1 for q in qs if ranks[q["id"]] and ranks[q["id"]] <= 5), len(qs))}
    r["missed_at_5"] = [q["id"] for q in ans if not ranks[q["id"]]]
    r["rank_by_query"] = {q["id"]: ranks[q["id"]] for q in ans}
    r["chunk_stats"] = PK.chunk_stats(chunks)
    r["strategy"] = PK.DEFAULT_STRATEGY
    return r


def regression(pipe: RP.RagPipeline) -> Dict[str, Any]:
    """Re-run the card router on the Phase 4 and Phase 5 sets and compare with the recorded baselines (4 dp)."""
    out: Dict[str, Any] = {}
    for name, path, key, qkey, recorded in (("phase4", "data/evaluation/card_retrieval_questions.json", "questions", "question", PHASE4_RECORDED),
                                            ("phase5_independent", "data/evaluation/independent_queries.json", "queries", "query", PHASE5_RECORDED)):
        qs = json.loads((ROOT / path).read_text(encoding="utf-8"))[key]
        rk = []
        for q in qs:
            res = RT.route(q[qkey], pipe.backend, top_k=ROUTER_DEPTH)
            exp = set(q["expected_source_ids"])
            rk.append(next((c.rank for c in res.candidates if c.source_id in exp), None))
        live = {**{f"recall@{k}": round(sum(1 for r in rk if r and r <= k) / len(rk), 4) for k in KS}, "mrr": round(sum(1 / r for r in rk if r) / len(rk), 4)}
        out[name] = {"n": len(qs), "live": live, "recorded_baseline": recorded, "matches_recorded_4dp": all(abs(live[k] - v) <= 0.0051 for k, v in recorded.items()),
                     "note": "recorded Phase 4/5 figures were rounded to 2 dp (Phase 4) / 4 dp (Phase 5); the pinned per-query rankings are asserted by tests/test_phase7e.py"}
    p8 = ROOT / "data" / "evaluation" / "phase8_results.json"
    out["phase8_results_file_sha256"] = hashlib.sha256(p8.read_bytes()).hexdigest()
    out["phase8_results_unchanged_since_phase8"] = out["phase8_results_file_sha256"].startswith(PHASE8_RESULTS_SHA256_PREFIX)
    return out


def llm_summary(rows_router: List[Dict[str, Any]], rows_oracle: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"router_rank1": EP8.evaluate_rows(rows_router, oracle=False), "oracle_routing": EP8.evaluate_rows(rows_oracle, oracle=True)}


def run_llm_eval(pipe: RP.RagPipeline, queries: List[Dict[str, Any]], client: Any, count: Any, name: str = "ollama") -> Dict[str, Any]:
    """Same pipeline and metrics with an LLMGenerator over ``client``. Used with the real OllamaClient only when Ollama is detected (and, in tests, with a stub client).
    Failures of the model/runtime are recorded as ``model_runtime_failure`` and are never replaced by extractive output."""
    p = RP.RagPipeline(pipe.backend, pipe.retriever, pipe.ctx, pipe.corpus, RG.LLMGenerator(client, name=name), count)
    rows_r, rows_o, runtime_failures = [], [], []
    for oracle, sink in ((False, rows_r), (True, rows_o)):
        for q in queries:
            if oracle and not q.get("gold_source_id"):
                continue
            try:
                a = p.answer(q["query"], debug=True, oracle_source_id=q["gold_source_id"] if oracle else None)
            except Exception as e:                                                   # noqa: BLE001
                runtime_failures.append({"id": q["id"], "mode": "oracle" if oracle else "router", "error": f"{type(e).__name__}: {e}", "failure_category": "model_runtime_failure"})
                continue
            sink.append({"q": q, "a": a})
    ev = llm_summary(rows_r, rows_o)
    for e in ev.values():
        e["failures"] = e.pop("_failures")
        e.pop("_correct_ids", None)
    return {"generator": name, "runtime_failures": runtime_failures, **ev, "audit": audit_rows(rows_r, "router") + audit_rows(rows_o, "oracle"),
            "answer_correctness_note": "automated proxy only (answered AND a cited chunk contains the gold evidence AND the cited page is the gold page); no human judgement of fluency or semantic correctness"}


def main() -> int:
    raw = QUERIES.read_bytes()
    freeze = check_frozen(raw)
    payload = json.loads(raw.decode("utf-8"))
    check_preregistered(payload["preregistered"])
    manifest = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    if payload["corpus_sha256"] != manifest["corpus_sha256"]:
        raise SystemExit("STOP: the query file was verified against a different corpus")
    queries = payload["queries"]
    records = PC.load_records()
    units = {u["source_id"]: u for u in json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]}
    perf: Dict[str, Any] = {}
    t = time.perf_counter()
    embed, minfo = BP.load_embedder()
    count, tinfo = PK.make_token_counter(minfo["model_dir"])
    perf["embedder_load_s"] = round(time.perf_counter() - t, 3)
    pipe = RP.build_pipeline()

    t = time.perf_counter()
    routes = route_all(pipe, queries)
    perf["router_ms_per_query_mean"] = round((time.perf_counter() - t) * 1000 / len(queries), 2)
    router_rows = EP8.run_pipeline(pipe, queries, oracle=False)
    oracle_rows = EP8.run_pipeline(pipe, queries, oracle=True)
    rmet, rfail = router_metrics(queries, routes, units, [c["source_id"] for c in manifest["cards"] if c["corpus_status"] == "ingested"])
    e2e_router = EP8.evaluate_rows(router_rows, oracle=False)
    e2e_oracle = EP8.evaluate_rows(oracle_rows, oracle=True)
    page = page_retrieval(pipe, queries, count, records, routes)
    audit = audit_rows(router_rows, "router_rank1") + audit_rows(oracle_rows, "oracle")
    for e in (e2e_router, e2e_oracle):
        e["failures"] = e.pop("_failures")
        e.pop("_correct_ids", None)

    def factory(gen):
        return RP.RagPipeline(pipe.backend, pipe.retriever, pipe.ctx, pipe.corpus, gen, count)
    halluc = EP8.hallucination_eval(factory, queries)
    ollama = detect_ollama()
    if ollama["available"]:
        llm = run_llm_eval(pipe, queries, RG.OllamaClient(), count)
        llm_block = {"status": "executed", "detection": ollama, **{k: v for k, v in llm.items() if k != "audit"}}
        audit += llm["audit"]
    else:
        llm_block = {"status": ollama["status"], "detection": ollama, "executed": False,
                     "not_measured": ["answer correctness", "grounding rate with a real LLM", "citation correctness with a real LLM", "abstention of a real LLM", "unsupported-claim rate",
                                      "LLM latency", "LLM failure rate", "extractive-vs-LLM comparison"]}
    cat_counts: Dict[str, Dict[str, int]] = {}
    for a in audit:
        cat_counts.setdefault(a["mode"], {}).setdefault(a["failure_category"], 0)
        cat_counts[a["mode"]][a["failure_category"]] += 1
    reg = regression(pipe)
    status = json.loads(STATUS_JSON.read_text(encoding="utf-8"))["summary"]
    fetch = json.loads(FETCH_LOG.read_text(encoding="utf-8")) if FETCH_LOG.is_file() else []

    fingerprint = hashlib.sha256(json.dumps({"routes": {k: [c["source_id"] for c in v[:5]] for k, v in routes.items()}, "page_ranks": page["rank_by_query"]}, sort_keys=True).encode()).hexdigest()
    stages: Dict[str, List[float]] = {}
    for r in router_rows:
        for k, v in r["a"]["timings_ms"].items():
            stages.setdefault(k, []).append(v)
    pct = lambda xs, p: round(sorted(xs)[min(len(xs) - 1, int(round((len(xs) - 1) * p)))], 2)   # noqa: E731
    perf["per_query_ms_router_mode_extractive"] = {k: {"median": round(statistics.median(v), 2), "p95": pct(v, 0.95), "max": round(max(v), 2), "n": len(v)} for k, v in sorted(stages.items())}
    perf["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    perf["ollama_latency"] = "NOT MEASURED: local model unavailable" if not ollama["available"] else "see llm block timings in per-query rows (not stored in deterministic results)"
    PERF.write_text(json.dumps(perf, indent=2) + "\n", encoding="utf-8")

    results = {
        "schema_version": 1, "queries_file": str(QUERIES.relative_to(ROOT)), "freeze": freeze, "query_counts": payload["counts"], "facet_counts": payload["facet_counts"],
        "authorship": payload["authorship"], "preregistered": payload["preregistered"],
        "corpus": {"sha256": manifest["corpus_sha256"], "cards": status["cards"], "pages_available": status["pages_available"], "pages_missing": status["pages_missing"],
                   "by_corpus_status": status["by_corpus_status"], "by_identity_status_7c": status["by_identity_status_7c"], "fetched_in_phase9": status["fetched_in_phase9"],
                   "pending_external_retrieval": status["pending_external_retrieval"], "protected_unresolved": status["protected_unresolved"]},
        "official_page_fetch": {"attempts": sum(len(x.get("attempts", [])) for x in fetch), "pages_saved": sum(len(x.get("saved", [])) for x in fetch),
                                "stopped_reason": [x.get("stopped_reason") for x in fetch], "first_error": next((a.get("error") for x in fetch for a in x.get("attempts", []) if a.get("error")), None),
                                "status": "FAILED: help.sap.com unreachable from this environment; no page was fetched, guessed or fabricated"},
        "token_counter": tinfo, "chunking": {"strategy": PK.DEFAULT_STRATEGY, "stats": page["chunk_stats"]},
        "card_router": rmet, "router_failures": rfail, "page_retrieval": {k: v for k, v in page.items() if k != "chunk_stats"},
        "end_to_end_router_rank1_extractive": e2e_router, "end_to_end_oracle_routing_extractive": e2e_oracle,
        "ood_observations": ood_observations(queries, routes, router_rows), "hallucination_guard_stub_generators": halluc,
        "failure_audit_counts_by_mode": {m: dict(sorted(c.items())) for m, c in sorted(cat_counts.items())}, "failure_audit_file": str(AUDIT.relative_to(ROOT)),
        "ollama_evaluation": llm_block, "regression": reg, "retrieval_fingerprint_sha256": fingerprint,
        "baselines_for_comparison": {"phase4_card_router_recorded": PHASE4_RECORDED, "phase5_independent_recorded": PHASE5_RECORDED,
                                     "note": "Phase 4 scores are not representative of real-world queries; the Phase 9 set is the primary evidence"},
        "limitations": ["7 of 29 cards have page text; 22 pages are pending external retrieval (help.sap.com unreachable)", "queries are AI-authored with the page text in view; frozen before retrieval; per-page n 5-14",
                        "extractive generator only; real Ollama evaluation BLOCKED", "lexical OOD and context gates are uncalibrated heuristics", "failure-cause labels are heuristic hypotheses"]}
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    AUDIT.write_text(json.dumps({"schema_version": 1, "taxonomy": ["wrong_route", "wrong_page", "insufficient_retrieval", "unsupported_claim", "hallucinated_detail", "citation_mismatch",
                                                                   "failure_to_abstain", "correct_retrieval_incorrect_synthesis", "correct_answer_incomplete_citation", "model_runtime_failure",
                                                                   "ood_gate_false_positive", "ood_or_context_gate_false_refusal", "other_status_mismatch"],
                                 "note": "wrong_page is subsumed by wrong_route here (the page is always the routed card's page); unsupported_claim / hallucinated_detail / model_runtime_failure can only occur with a real LLM and are 0 by construction for the extractive generator",
                                 "rows": audit}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    c = rmet["all_gold_card_queries"]
    print("router R@1/3/5", [c[f"recall@{k}"]["rate"] for k in KS], "MRR", c["mrr"], "| answerable R@1", rmet["answerable_only"]["recall@1"]["rate"], "| failures", rmet["failure_count"], rmet["failure_causes_heuristic"])
    pg = page["in_gold_page"]
    print("page in-gold R@1/3/5", [pg[f"recall@{k}"]["rate"] for k in KS], "MRR", pg["mrr"], "| evidence in context", page["context"]["evidence_in_context"]["rate"])
    print("router-mode status match:", {k: v["rate"] for k, v in e2e_router["status_match_by_type"].items()})
    print("oracle-mode status match:", {k: v["rate"] for k, v in e2e_oracle["status_match_by_type"].items()})
    print("ollama:", ollama["status"])
    print("regression:", {k: v.get("matches_recorded_4dp") for k, v in reg.items() if isinstance(v, dict)}, reg["phase8_results_unchanged_since_phase8"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
