#!/usr/bin/env python3
"""Phase 9 extras - chunking controlled comparison, gate distributions, per-query source chains and CLI evidence on the FROZEN Phase 9 query set.

Writes ``data/evaluation/phase9_extras.json`` (deterministic), ``phase9_source_chains.json`` (deterministic) and
``phase9_extras_performance.json`` (timings). Never modifies the frozen queries, the stores or any earlier artefact.

PRE-REGISTERED DECISION RULES (declared here before this script was first run; constants are asserted by tests/test_phase9.py):

* Chunking: candidate strategies ``A_legacy_1000c`` and ``C_heading_128`` are compared with the default ``B_heading_200`` on the Phase 9 set only.
  A candidate may be called *supported on this set* only if ALL of: in-gold-page MRR exceeds B's by >= 0.03; Recall@5 is not lower; the exact
  two-sided sign test on Recall@1 discordant pairs gives p < 0.05. Even then it is NOT adopted in Phase 9, because no held-out set exists
  (adoption would be tuning on the frozen evaluation set). B stays the default unless a later phase confirms a candidate on held-out queries.
* Gate: a lexical-coverage threshold is called *justified* only if the in-domain and out-of-domain coverage distributions do not overlap
  (max OOD coverage < min in-domain coverage) AND a held-out set exists. Phase 9 has no held-out set, so no threshold is proposed or changed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import build_page_collection as BP  # noqa: E402
import evaluate_phase8 as EP8  # noqa: E402
import evaluate_phase9 as E9  # noqa: E402
import page_chunker as PK  # noqa: E402
import page_corpus as PC  # noqa: E402
import page_retriever as PR  # noqa: E402
import rag_pipeline as RP  # noqa: E402

EVAL = ROOT / "data" / "evaluation"
OUT = EVAL / "phase9_extras.json"
CHAINS = EVAL / "phase9_source_chains.json"
PERF = EVAL / "phase9_extras_performance.json"
RULES = {"chunking": {"min_mrr_gain": 0.03, "recall@5_not_lower": True, "sign_test_p_below": 0.05, "adopt_without_held_out": False},
         "gate": {"requires_non_overlapping_distributions": True, "requires_held_out_set": True}}
IN_DOMAIN = ("answerable", "absent_detail", "not_ingested", "unresolved_identity")


def stats(xs: Sequence[float]) -> Dict[str, Any]:
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(xs[0], 3), "median": round(xs[len(xs) // 2], 3), "max": round(xs[-1], 3), "mean": round(sum(xs) / len(xs), 3)}


def chunking_comparison(records: List[Dict[str, Any]], queries: List[Dict[str, Any]], embed: Any, count: Any) -> Dict[str, Any]:
    import chromadb
    from chromadb.config import Settings
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))
    client.reset()
    ans = [q for q in queries if q["type"] == "answerable"]
    out: Dict[str, Any] = {"rules_preregistered": RULES["chunking"], "strategies": {}}
    ranks: Dict[str, Dict[str, Any]] = {}
    timings: Dict[str, float] = {}
    for name, cfg in PK.STRATEGIES.items():
        col, chunks, secs = EP8.build_strategy_collection(client, name, cfg, records, embed, count)
        timings[name] = round(secs, 3)
        retr = PR.PageRetriever(col, embed)
        r = EP8.retrieval_eval(retr, queries, count, chunks)
        ranks[name] = r.pop("_ranks_in_gold_page")
        by_id = {c["chunk_id"]: c for c in chunks}
        # section-level behaviour (only meaningful when a page has several chunks)
        sib = multi = multi_all = 0
        for q in ans:
            g, p = q["gold_doc_id"].split("/")
            hits = retr.retrieve_in_page(q["query"], g, p, top_k=5)
            gold = [c for c in chunks if c["page_id"] == p and EP8.has_evidence(c["text"], q["evidence"])]
            if ranks[name][q["id"]] != 1 and hits and gold:
                same_section = hits[0].section_title in {c["section_title"] for c in gold}
                sib += 0 if same_section else 1                                # rank-1 chunk comes from a different section than the evidence
            if len(q["evidence"]) > 1:
                multi += 1
                multi_all += 1 if all(any(EP8.has_evidence(h.text, [e]) for h in hits) for e in q["evidence"]) else 0
        out["strategies"][name] = {"config": cfg.to_dict(), "chunk_stats": PK.chunk_stats(chunks), "retrieval": r,
                                   "rank1_wrong_section_confusions": sib, "multi_evidence_queries": multi, "multi_evidence_all_pieces_in_top5": multi_all,
                                   "metadata_preserved": all(all(c.get(k) for k in ("chunk_id", "guide_id", "page_id", "source_url", "title", "content_hash")) and c.get("heading_path") for c in chunks)}
    base = "B_heading_200"
    out["paired_recall@1"] = {}
    out["verdicts"] = {}
    for other in ("A_legacy_1000c", "C_heading_128"):
        only_b = sum(1 for q, r in ranks[base].items() if r == 1 and ranks[other][q] != 1)
        only_o = sum(1 for q, r in ranks[other].items() if r == 1 and ranks[base][q] != 1)
        p = EP8.sign_test_p(only_o, only_b)
        out["paired_recall@1"][f"{other}_vs_{base}"] = {"only_default_right": only_b, "only_candidate_right": only_o, "sign_test_p_two_sided": p}
        b, o = out["strategies"][base]["retrieval"]["in_gold_page"], out["strategies"][other]["retrieval"]["in_gold_page"]
        supported = (o["mrr"] - b["mrr"] >= RULES["chunking"]["min_mrr_gain"] and o["recall@5"]["rate"] >= b["recall@5"]["rate"] and p is not None and p < RULES["chunking"]["sign_test_p_below"])
        out["verdicts"][other] = {"supported_on_this_set": bool(supported), "adopted": False,
                                  "reason": "no held-out set exists; adopting a candidate chosen on the frozen set would be tuning on the evaluation set" if supported
                                  else "preregistered rule not met; the default is kept"}
    out["default_kept"] = base
    return out, timings


def gate_distribution(router_rows: List[Dict[str, Any]], oracle_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def collect(rows, group):
        cov, ctx = [], []
        for r in rows:
            if r["q"]["type"] not in group:
                continue
            d = r["a"]["debug"]
            if "gate_topic" in d:
                cov.append(d["gate_topic"]["coverage"])
            if "gate_context" in d:
                ctx.append(d["gate_context"]["coverage"])
        return cov, ctx
    res: Dict[str, Any] = {"rules_preregistered": RULES["gate"], "ood_min_coverage_in_force": RP.OOD_MIN_COVERAGE, "context_min_coverage_in_force": RP.CONTEXT_MIN_COVERAGE}
    for mode, rows in (("router_rank1", router_rows), ("oracle", oracle_rows)):
        in_cov, in_ctx = collect(rows, IN_DOMAIN)
        ood_cov, _ = collect(rows, ("out_of_domain",))
        in_rows = [r for r in rows if r["q"]["type"] in IN_DOMAIN]
        ood_rows = [r for r in rows if r["q"]["type"] == "out_of_domain"]
        false_refusal_topic = [r["q"]["id"] for r in in_rows if r["a"]["status"] == "out_of_domain"]
        answerable = [r for r in rows if r["q"]["type"] == "answerable"]
        ctx_refusal = [r["q"]["id"] for r in answerable if r["a"]["reason_code"] == "LOW_QUERY_TERM_COVERAGE_IN_CONTEXT"]
        topic_refusal_answerable = [r["q"]["id"] for r in answerable if r["a"]["status"] == "out_of_domain"]
        mx_ood = max(ood_cov) if ood_cov else None
        mn_in = min(in_cov) if in_cov else None
        res[mode] = {
            "topic_gate_coverage_in_domain": stats(in_cov), "topic_gate_coverage_out_of_domain": stats(ood_cov), "context_gate_coverage_in_domain": stats(in_ctx),
            "distributions_overlap": (bool(mx_ood >= mn_in) if mx_ood is not None and mn_in is not None else None),   # None = no OOD queries in this mode (oracle routing needs a gold card)
            "in_domain_queries": len(in_rows), "in_domain_refused_by_topic_gate_false_refusals": E9.EP8.prop(len(false_refusal_topic), len(in_rows)),
            "answerable_refused_by_topic_gate": E9.EP8.prop(len(topic_refusal_answerable), len(answerable)),
            "answerable_refused_by_context_gate": E9.EP8.prop(len(ctx_refusal), len(answerable)),
            "out_of_domain_queries": len(ood_rows),
            "out_of_domain_accepted_past_topic_gate_false_accepts": E9.EP8.prop(sum(1 for r in ood_rows if r["a"]["status"] != "out_of_domain"), len(ood_rows)),
            "out_of_domain_answered": sum(1 for r in ood_rows if r["a"]["status"] == "answered"),
            "false_refusal_query_ids": false_refusal_topic}
    ov = bool(res["router_rank1"]["distributions_overlap"])
    res["threshold_justified"] = False
    res["threshold_verdict"] = ("NOT justified: the in-domain and out-of-domain coverage distributions overlap and no held-out set exists; the gate constants are unchanged"
                                if ov else "NOT justified: the distributions do not overlap on this set, but no held-out set exists, so no threshold is proposed or changed")
    return res


def source_chains(router_rows: List[Dict[str, Any]], oracle_rows: List[Dict[str, Any]], units: Dict[str, Any]) -> Dict[str, Any]:
    def chain(r: Dict[str, Any], mode: str) -> Dict[str, Any]:
        q, a = r["q"], r["a"]
        d = a["debug"]
        ident = d.get("identity", {})
        ctx_items = (d.get("context") or {}).get("items", [])
        ctx_ids = [i["chunk_id"] for i in ctx_items]
        srcs = a["citations"]["answer_sources"]
        sid = a["routing"].get("selected_source_id")
        card_url = units[sid]["source_url"] if sid in units else None
        tp = a["citations"]["topic_pointer"]
        eff = (ident.get("effective_guide_id"), ident.get("effective_page_id"))
        checks = {
            "answer_urls_equal_card_source_url": all(s["url"] == card_url for s in srcs),
            "topic_pointer_url_equals_card_source_url": tp.get("url") == card_url,
            "cited_chunks_were_in_the_generator_context": all(s["chunk_id"] in ctx_ids for s in srcs),
            "cited_chunks_belong_to_the_effective_identity_page": all((s["guide_id"], s["page_id"]) == eff for s in srcs),
            "card_not_used_as_answer_text": tp.get("used_as_answer_text") is False and tp.get("verified_used") is False,
            "no_sources_unless_answered": a["status"] == "answered" or srcs == []}
        return {"id": q["id"], "mode": mode, "query": q["query"], "type": q["type"], "expected_status": q["expected_status"], "card": sid,
                "card_rank": next((c["rank"] for c in a["routing"].get("candidates", []) if c["source_id"] == sid), None), "identity_status": ident.get("status"),
                "effective_guide_id": eff[0], "effective_page_id": eff[1], "status": a["status"], "reason_code": a["reason_code"],
                "context_chunk_ids": ctx_ids, "cited_chunk_ids": [s["chunk_id"] for s in srcs], "answer": a["answer"],
                "citation_urls": sorted({s["url"] for s in srcs}), "topic_pointer_url": tp.get("url"), "checks": checks}
    rows = [chain(r, "router_rank1") for r in router_rows] + [chain(r, "oracle") for r in oracle_rows]
    keys = list(rows[0]["checks"])
    return {"rows": rows, "summary": {"chains": len(rows), "answered": sum(1 for r in rows if r["status"] == "answered"),
                                      **{k: {"passed": sum(1 for r in rows if r["checks"][k]), "of": len(rows)} for k in keys}}}


def cli_evidence(question: str) -> Dict[str, Any]:
    """Runs the real CLI in a subprocess: extractive on two questions, and ollama (expected to fail loudly, never to fall back)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    out: Dict[str, Any] = {}
    cases = [("extractive_answerable", ["--generator", "extractive", "--json", "--question", question]),
             ("extractive_out_of_domain", ["--generator", "extractive", "--json", "--question", "What is the capital of France?"]),
             ("ollama_requested", ["--generator", "ollama", "--json", "--question", question])]
    for name, args in cases:
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "rag_answer.py"), *args], capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=300)
        rec: Dict[str, Any] = {"args": args, "exit_code": p.returncode}
        if p.returncode == 0:
            ans = json.loads(p.stdout)
            rec.update(status=ans["status"], selected=ans["routing"].get("selected_source_id"), answer_sources=len(ans["citations"]["answer_sources"]))
        else:
            rec.update(stdout_empty=p.stdout.strip() == "", stderr_last_line=[ln for ln in p.stderr.strip().splitlines() if ln.strip()][-1] if p.stderr.strip() else "")
        out[name] = rec
    return out


def main() -> int:
    raw = E9.QUERIES.read_bytes()
    E9.check_frozen(raw)
    payload = json.loads(raw.decode("utf-8"))
    queries = payload["queries"]
    records = PC.load_records()
    units = {u["source_id"]: u for u in json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))["units"]}
    embed, minfo = BP.load_embedder()
    count, _ = PK.make_token_counter(minfo["model_dir"])
    pipe = RP.build_pipeline()
    router_rows = EP8.run_pipeline(pipe, queries, oracle=False)
    oracle_rows = EP8.run_pipeline(pipe, queries, oracle=True)
    chunk, secs = chunking_comparison(records, queries, embed, count)
    gate = gate_distribution(router_rows, oracle_rows)
    chains = source_chains(router_rows, oracle_rows, units)
    t = time.perf_counter()
    question = next(r["q"]["query"] for r in router_rows if r["q"]["type"] == "answerable" and r["a"]["status"] == "answered")     # first query the real router answers (so generation is reached)
    cli = cli_evidence(question)
    cli_s = round(time.perf_counter() - t, 2)
    CHAINS.write_text(json.dumps(chains, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    res = {"schema_version": 1, "cli_question": question, "queries_sha256": json.loads(E9.FREEZE.read_text(encoding="utf-8"))["sha256"], "preregistered_rules": RULES, "chunking_comparison": chunk,
           "gate_distribution": gate, "source_chain_summary": chains["summary"], "source_chains_file": str(CHAINS.relative_to(ROOT)), "cli_evidence": cli,
           "router_change_experiment": {"run": False, "reason": "no router change was proposed or needed to complete Phase 9; no held-out set exists; the card router is unchanged"}}
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    PERF.write_text(json.dumps({"chunk_and_embed_seconds_by_strategy": secs, "cli_three_subprocess_runs_seconds": cli_s}, indent=2) + "\n", encoding="utf-8")
    print("chunking verdicts:", chunk["verdicts"])
    print("gate:", gate["threshold_verdict"])
    print("chains:", chains["summary"])
    print("cli:", json.dumps(cli, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
