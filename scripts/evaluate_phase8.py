#!/usr/bin/env python3
"""Phase 8I - evaluation of the page corpus, chunking strategies, retrieval, the end-to-end pipeline and the grounding guard.

Stages are reported SEPARATELY (never one blended score): routing | identity | retrieval | generation | citation | end-to-end status.
Everything runs offline with the extractive (non-LLM) generator. The real LLM path (``OllamaClient``) is NOT exercised here: no Ollama
and no model weights exist in this environment. Metrics therefore describe retrieval, routing, gating, citation and the grounding
verifier - not the answer quality of llama3.2:3b.

Writes ``data/evaluation/phase8_results.json`` (deterministic) and ``data/evaluation/phase8_performance.json`` (timings; vary per run).
The query file is ``data/evaluation/phase8_queries.json`` (AI-authored; see its ``authorship`` block). Its ``preregistered`` constants
must equal the constants in the code or the run stops (no tuning on this set).

    python scripts/evaluate_phase8.py
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import resource
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
import page_chunker as PK  # noqa: E402
import page_corpus as PC  # noqa: E402
import page_retriever as PR  # noqa: E402
import rag_context as RC  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_pipeline as RP  # noqa: E402
import rag_text as T  # noqa: E402

ROOT = PC.ROOT
QUERIES = ROOT / "data" / "evaluation" / "phase8_queries.json"
RESULTS = ROOT / "data" / "evaluation" / "phase8_results.json"
PERF = ROOT / "data" / "evaluation" / "phase8_performance.json"
KS = (1, 3, 5)
PERF_NOTES: Dict[str, float] = {}


def norm(t: str) -> str:
    return " ".join((t or "").replace("\xa0", " ").split())


def wilson(k: int, n: int, z: float = 1.96) -> List[Optional[float]]:
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def prop(k: int, n: int) -> Dict[str, Any]:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": wilson(k, n)}


def sign_test_p(b: int, c: int) -> Optional[float]:
    """Two-sided exact sign test on discordant pairs (b: only A right, c: only B right)."""
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return round(min(1.0, p), 4)


def has_evidence(text: str, quotes: Sequence[str]) -> bool:
    t = norm(text)
    return any(norm(q) in t for q in quotes)


def check_preregistered(payload: Dict[str, Any]) -> None:
    p = payload["preregistered"]
    code = {"ood_min_coverage": RP.OOD_MIN_COVERAGE, "context_min_coverage": RP.CONTEXT_MIN_COVERAGE, "extractive_min_score": RG.EXTRACTIVE_MIN_SCORE,
            "min_sentence_support": RG.MIN_SENTENCE_SUPPORT, "default_chunk_strategy": PK.DEFAULT_STRATEGY, "context_budget_tokens": RC.DEFAULT_BUDGET_TOKENS,
            "max_context_chunks": RC.DEFAULT_MAX_CHUNKS}
    bad = {k: (p.get(k), v) for k, v in code.items() if p.get(k) != v}
    if bad:
        raise SystemExit(f"STOP: pre-registered constants differ from the code (no tuning on the evaluation set): {bad}")


# ---------------------------------------------------------------------------------------------------- chunking / retrieval


def build_strategy_collection(client: Any, name: str, cfg: PK.ChunkConfig, records: List[Dict[str, Any]], embed: Any, count: Any) -> Tuple[Any, List[Dict[str, Any]], float]:
    t = time.perf_counter()
    chunks = PK.chunk_corpus(records, cfg, count)
    col = client.create_collection(name=f"eval_{name.lower()}", metadata={"hnsw:space": "cosine"})
    BP.fill_collection(col, chunks, records, embed)
    return col, chunks, time.perf_counter() - t


def retrieval_eval(retriever: Any, queries: Sequence[Dict[str, Any]], count: Any, chunks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ans = [q for q in queries if q["type"] == "answerable"]
    gold_chunks = {q["id"]: [c for c in chunks if c["page_id"] == q["gold_doc_id"].split("/")[1] and has_evidence(c["text"], q["evidence"])] for q in ans}
    res: Dict[str, Any] = {"queries": len(ans), "queries_with_gold_chunk": sum(1 for v in gold_chunks.values() if v)}
    ranks_in, ranks_all, page_top1 = {}, {}, 0
    for q in ans:
        g, p = q["gold_doc_id"].split("/")
        hits = retriever.retrieve_in_page(q["query"], g, p, top_k=5)
        ranks_in[q["id"]] = next((h.rank for h in hits if has_evidence(h.text, q["evidence"])), None)
        hits_all = retriever.retrieve_corpus(q["query"], top_k=5)
        ranks_all[q["id"]] = next((h.rank for h in hits_all if h.page_id == p and has_evidence(h.text, q["evidence"])), None)
        page_top1 += 1 if hits_all and hits_all[0].page_id == p else 0
    n = len(ans)
    for label, ranks in (("in_gold_page", ranks_in), ("corpus_wide_no_card_stage", ranks_all)):
        res[label] = {**{f"recall@{k}": prop(sum(1 for r in ranks.values() if r is not None and r <= k), n) for k in KS},
                      "mrr": round(sum(1 / r for r in ranks.values() if r) / n, 4)}
    res["corpus_wide_no_card_stage"]["page_hit@1"] = prop(page_top1, n)
    res["_ranks_in_gold_page"] = ranks_in
    # context assembly quality (gold page, k=5)
    precisions, red, toks, ev_in = [], [], [], 0
    for q in ans:
        g, p = q["gold_doc_id"].split("/")
        ctx = RC.build_context(retriever.retrieve_in_page(q["query"], g, p, top_k=5), count)
        items = ctx.items
        flags = [has_evidence(i.text, q["evidence"]) for i in items]
        ev_in += 1 if any(flags) else 0
        precisions.append(sum(flags) / len(flags) if flags else 0.0)
        words = [w for i in items for w in i.rendered_text.lower().split()]
        red.append(1 - len(set(words)) / len(words) if words else 0.0)
        toks.append(ctx.total_tokens)
    res["context"] = {"evidence_in_context": prop(ev_in, n), "context_precision_mean": round(statistics.mean(precisions), 4),
                      "redundancy_mean": round(statistics.mean(red), 4), "context_tokens_mean": round(statistics.mean(toks), 1), "context_tokens_max": max(toks)}
    return res


def chunking_comparison(records: List[Dict[str, Any]], queries: List[Dict[str, Any]], embed: Any, count: Any) -> Dict[str, Any]:
    import chromadb
    from chromadb.config import Settings
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))
    client.reset()
    out: Dict[str, Any] = {"strategies": {}, "paired_recall@1_in_gold_page": {}}
    ranks: Dict[str, Dict[str, Any]] = {}
    for name, cfg in PK.STRATEGIES.items():
        col, chunks, secs = build_strategy_collection(client, name, cfg, records, embed, count)
        r = retrieval_eval(PR.PageRetriever(col, embed), queries, count, chunks)
        ranks[name] = r.pop("_ranks_in_gold_page")
        out["strategies"][name] = {"config": cfg.to_dict(), "chunk_stats": PK.chunk_stats(chunks), "retrieval": r}
        PERF_NOTES[f"chunk_and_embed_seconds_{name}"] = round(secs, 3)
    for other in ("A_legacy_1000c", "C_heading_128"):
        b = sum(1 for q, r in ranks["B_heading_200"].items() if r == 1 and ranks[other][q] != 1)
        a = sum(1 for q, r in ranks[other].items() if r == 1 and ranks["B_heading_200"][q] != 1)
        out["paired_recall@1_in_gold_page"][f"B_vs_{other}"] = {"only_B_right": b, "only_other_right": a, "sign_test_p_two_sided": sign_test_p(a, b)}
    client.reset()
    return out


# ---------------------------------------------------------------------------------------------------- end to end


def run_pipeline(pipe: RP.RagPipeline, queries: Sequence[Dict[str, Any]], oracle: bool) -> List[Dict[str, Any]]:
    rows = []
    for q in queries:
        if oracle and not q.get("gold_source_id"):
            continue
        a = pipe.answer(q["query"], debug=True, oracle_source_id=q["gold_source_id"] if oracle else None)
        rows.append({"q": q, "a": a})
    return rows


def evaluate_rows(rows: List[Dict[str, Any]], oracle: bool) -> Dict[str, Any]:
    res: Dict[str, Any] = {"queries": len(rows)}
    # ---- end-to-end status vs expected
    conf: Dict[str, Dict[str, int]] = {}
    for r in rows:
        conf.setdefault(r["q"]["expected_status"], {}).setdefault(r["a"]["status"], 0)
        conf[r["q"]["expected_status"]][r["a"]["status"]] += 1
    res["status_confusion_expected_to_actual"] = {k: dict(sorted(v.items())) for k, v in sorted(conf.items())}
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_type.setdefault(r["q"]["type"], []).append(r)
    res["status_match_by_type"] = {t: prop(sum(1 for r in rs if r["a"]["status"] == r["q"]["expected_status"]), len(rs)) for t, rs in sorted(by_type.items())}
    # ---- routing (router mode only)
    if not oracle:
        gold = [r for r in rows if r["q"].get("gold_source_id")]
        def rank_of(r):
            for c in r["a"]["routing"]["candidates"]:
                if c["source_id"] == r["q"]["gold_source_id"]:
                    return c["rank"]
            return None
        rk = [rank_of(r) for r in gold]
        res["routing"] = {**{f"top{k}": prop(sum(1 for x in rk if x and x <= k), len(gold)) for k in (1, 3, 5)},
                          "mrr": round(sum(1 / x for x in rk if x) / len(gold), 4) if gold else None, "queries_with_gold_card": len(gold)}
        res["routing"]["top1_by_type"] = {t: prop(sum(1 for r in rs if rank_of(r) == 1), len(rs)) for t, rs in sorted(by_type.items()) if t != "out_of_domain"}
        # ---- identity
        ans_rows = by_type.get("answerable", [])
        routed_ok = [r for r in ans_rows if rank_of(r) == 1]
        res["identity"] = {
            "gold_ingested_pages_routed_top1": prop(len(routed_ok), len(ans_rows)),
            "effective_page_equals_gold_doc_when_routed": prop(sum(1 for r in routed_ok if f"{r['a']['topic']['effective_guide_id']}/{r['a']['topic']['effective_page_id']}" == r["q"]["gold_doc_id"]), len(routed_ok)),
            "m2c05_correction_preserved": prop(sum(1 for r in rows if r["a"]["routing"]["selected_source_id"] == "M2C-05" and r["a"]["topic"]["corrected_identity"]),
                                              sum(1 for r in rows if r["a"]["routing"]["selected_source_id"] == "M2C-05")),
            "unresolved_card_routed_but_never_answered": {"routed_to_conflict_or_identity_only": sum(1 for r in rows if r["a"]["topic"] and r["a"]["topic"]["identity_status"] in ("conflicting_identity", "card_identity_only") ),
                                                          "of_those_answered": sum(1 for r in rows if r["a"]["topic"] and r["a"]["topic"]["identity_status"] in ("conflicting_identity", "card_identity_only") and r["a"]["status"] == "answered")},
            "m2c18_never_answered": sum(1 for r in rows if r["a"]["routing"]["selected_source_id"] == "M2C-18" and r["a"]["status"] == "answered") == 0,
        }
    # ---- retrieval inside the routed/oracle page, generation, citation (answerable)
    ans_rows = [r for r in by_type.get("answerable", [])]
    in_page = [r for r in ans_rows if r["a"]["topic"] and f"{r['a']['topic']['effective_guide_id']}/{r['a']['topic']['effective_page_id']}" == r["q"]["gold_doc_id"]]
    def ctx_items(r):
        return r["a"].get("debug", {}).get("context", {}).get("items", [])
    ret_ranks = []
    for r in in_page:
        hits = r["a"]["debug"].get("retrieved", [])
        chunk_text = {i["chunk_id"]: i["text"] for i in ctx_items(r)}
        # rank over the retrieved list; chunk texts of non-context hits are not stored, so evidence is looked up in the stored page chunks below
        ret_ranks.append(hits)
    res["pages_matching_gold"] = prop(len(in_page), len(ans_rows))
    ev_ctx = sum(1 for r in in_page if any(has_evidence(i["text"], r["q"]["evidence"]) for i in ctx_items(r)))
    res["retrieval"] = {"evidence_in_assembled_context_given_gold_page": prop(ev_ctx, len(in_page))}
    answered = [r for r in ans_rows if r["a"]["status"] == "answered"]
    correct = []
    for r in answered:
        texts = {i["chunk_id"]: i["text"] for i in ctx_items(r)}
        srcs = r["a"]["citations"]["answer_sources"]
        ok = any(has_evidence(texts.get(s["chunk_id"], ""), r["q"]["evidence"]) for s in srcs) and all(f"{s['guide_id']}/{s['page_id']}" == r["q"]["gold_doc_id"] for s in srcs)
        correct.append(ok)
    res["_correct_ids"] = [r["q"]["id"] for r, ok in zip(answered, correct) if ok]
    res["generation"] = {
        "answered_given_answerable": prop(len(answered), len(ans_rows)),
        "answered_and_cites_evidence_chunk_on_gold_page": prop(sum(correct), len(ans_rows)),
        "grounding_verifier_passed_among_answered": prop(sum(1 for r in answered if r["a"]["debug"]["grounding"]["ok"]), len(answered)),
        "withheld_by_grounding_check": sum(1 for r in ans_rows if r["a"]["reason_code"] == "GROUNDING_VERIFICATION_FAILED"),
        "refused_low_context_coverage": sum(1 for r in ans_rows if r["a"]["reason_code"] == "LOW_QUERY_TERM_COVERAGE_IN_CONTEXT"),
        "refused_by_generator": sum(1 for r in ans_rows if r["a"]["reason_code"] == "GENERATOR_REFUSED"),
        "generator": "extractive (non-LLM baseline); LLM path not validated here"}
    absent = by_type.get("absent_detail", [])
    res["abstention_on_absent_detail"] = {"insufficient_context": prop(sum(1 for r in absent if r["a"]["status"] == "insufficient_context"), len(absent)),
                                          "answered_anyway": prop(sum(1 for r in absent if r["a"]["status"] == "answered"), len(absent))}
    # ---- citations
    all_answered = [r for r in rows if r["a"]["status"] == "answered"]
    phantom = 0
    pointer_misuse = 0
    url_changed = 0
    srcs_total = 0
    srcs_with_evidence = 0
    for r in rows:
        cit = r["a"]["citations"]
        items = {i["chunk_id"] for i in ctx_items(r)}
        if cit.get("topic_pointer"):
            pointer_misuse += 1 if cit["topic_pointer"]["used_as_answer_text"] or cit["topic_pointer"]["verified_used"] else 0
        for s in cit["answer_sources"]:
            srcs_total += 1
            phantom += 1 if s["chunk_id"] not in items else 0
            url_changed += 1 if s["url"] != r["a"]["topic"]["card_url"] else 0
            if r["q"]["type"] == "answerable":
                txt = next((i["text"] for i in ctx_items(r) if i["chunk_id"] == s["chunk_id"]), "")
                srcs_with_evidence += 1 if has_evidence(txt, r["q"]["evidence"]) else 0
        if r["a"]["status"] != "answered" and cit["answer_sources"]:
            phantom += len(cit["answer_sources"])
    res["citation"] = {"answered_total": len(all_answered), "answer_sources_total": srcs_total, "phantom_citations": phantom, "topic_pointer_counted_as_evidence": pointer_misuse,
                       "answer_source_url_differs_from_card_url": url_changed,
                       "answer_sources_containing_gold_evidence_among_answerable": prop(srcs_with_evidence, sum(1 for r in ans_rows for _ in r["a"]["citations"]["answer_sources"]))}
    # ---- gates on non-answerable populations
    ood = by_type.get("out_of_domain", [])
    in_domain_rows = [r for r in rows if r["q"]["type"] in ("answerable", "absent_detail", "not_ingested", "unresolved_identity")]
    res["ood_gate"] = {"ood_flagged_out_of_domain": prop(sum(1 for r in ood if r["a"]["status"] == "out_of_domain"), len(ood)),
                       "in_domain_wrongly_flagged_out_of_domain": prop(sum(1 for r in in_domain_rows if r["a"]["status"] == "out_of_domain"), len(in_domain_rows)),
                       "ood_answered": sum(1 for r in ood if r["a"]["status"] == "answered"), "note": "lexical heuristic; not calibrated; small n; not a reliable OOD detector"}
    # ---- per page (answerable)
    pages: Dict[str, Any] = {}
    for r in ans_rows:
        d = pages.setdefault(r["q"]["gold_source_id"], {"n": 0, "answered": 0, "answered_correct": 0})
        d["n"] += 1
        d["answered"] += 1 if r["a"]["status"] == "answered" else 0
    for r, ok in zip(answered, correct):
        pages[r["q"]["gold_source_id"]]["answered_correct"] += 1 if ok else 0
    res["per_page_answerable"] = dict(sorted(pages.items()))
    res["_failures"] = [{"id": r["q"]["id"], "query": r["q"]["query"], "expected": r["q"]["expected_status"], "actual": r["a"]["status"], "reason": r["a"]["reason_code"],
                         "routed": r["a"]["routing"]["selected_source_id"], "gold": r["q"].get("gold_source_id")}
                        for r in rows if r["a"]["status"] != r["q"]["expected_status"]]
    return res


# ---------------------------------------------------------------------------------------------------- hallucination guard


class _Stub:
    def __init__(self, fn):
        self.fn = fn

    def generate(self, prompt: str) -> str:
        return self.fn(prompt)


def _first_context(prompt: str) -> Tuple[str, str]:
    """(marker, first sentence) of the first excerpt in a grounded prompt."""
    body = prompt.split("DOCUMENTATION EXCERPTS:")[1].split("QUESTION:")[0]
    m = re.search(r"\[(S\d+)\][^\n]*\n(.+)", body)
    if not m:
        return "S1", ""
    sents = [x for x in T.split_sentences(m.group(2)) if len(x.split()) >= 5 and not re.match(r"^\d+\.\s*$", x)]
    return m.group(1), (sents[0] if sents else m.group(2))


FABRICATIONS = {
    "faithful_control": lambda p: "{} [{}]".format(_first_context(p)[1], _first_context(p)[0]),
    "invented_url": lambda p: "{} [{}] See https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/0000000000000000000000000000dead/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.html.".format(_first_context(p)[1], _first_context(p)[0]),
    "invented_transaction_code": lambda p: "{} [{}] Use transaction ZQ99 to do this.".format(_first_context(p)[1], _first_context(p)[0]),
    "phantom_citation": lambda p: "{} [S9]".format(_first_context(p)[1]),
    "uncited_claim": lambda p: _first_context(p)[1],
    "off_context_claim": lambda p: "The moon orbits the earth every month and sea levels are rising. [{}]".format(_first_context(p)[0]),
    "invented_number": lambda p: "{} [{}] The limit is 4711 days.".format(_first_context(p)[1], _first_context(p)[0]),
}


def hallucination_eval(pipe_factory: Any, queries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ans = [q for q in queries if q["type"] == "answerable"]
    out: Dict[str, Any] = {"note": "scripted stub LLMs that fabricate in one specific way; measures whether the verifier withholds each type. It does not measure llama3.2:3b behaviour.", "cases": {}}
    for name, fn in FABRICATIONS.items():
        pipe = pipe_factory(RG.LLMGenerator(_Stub(fn), name=name))
        answered = withheld = refused = 0
        for q in ans:
            a = pipe.answer(q["query"], oracle_source_id=q["gold_source_id"])
            answered += a["status"] == "answered"
            withheld += a["reason_code"] == "GROUNDING_VERIFICATION_FAILED"
            refused += a["reason_code"] in ("GENERATOR_REFUSED", "LOW_QUERY_TERM_COVERAGE_IN_CONTEXT")
        out["cases"][name] = {"queries": len(ans), "fabricated_answer_shown": answered, "withheld_by_verifier": withheld, "other_refusal": refused}
    return out


# ---------------------------------------------------------------------------------------------------- main


def main() -> int:
    payload = json.loads(QUERIES.read_text(encoding="utf-8"))
    check_preregistered(payload)
    manifest = json.loads((PC.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    if payload["corpus_sha256"] != manifest["corpus_sha256"]:
        raise SystemExit("STOP: the query file was verified against a different corpus (re-run scripts/build_phase8_queries.py)")
    queries = payload["queries"]
    records = PC.load_records()
    perf: Dict[str, Any] = {}
    t = time.perf_counter()
    embed, minfo = BP.load_embedder()
    count, tinfo = PK.make_token_counter(minfo["model_dir"])
    perf["embedder_load_s"] = round(time.perf_counter() - t, 3)
    t = time.perf_counter()
    comparison = chunking_comparison(records, queries, embed, count)
    perf["chunking_comparison_total_s"] = round(time.perf_counter() - t, 3)

    t = time.perf_counter()
    pipe = RP.build_pipeline()
    perf["pipeline_build_s"] = round(time.perf_counter() - t, 3)
    router_rows = run_pipeline(pipe, queries, oracle=False)
    oracle_rows = run_pipeline(pipe, queries, oracle=True)
    e2e_router = evaluate_rows(router_rows, oracle=False)
    e2e_oracle = evaluate_rows(oracle_rows, oracle=True)

    # end-to-end per chunking strategy with oracle routing (same pipeline code, other collection)
    import chromadb
    from chromadb.config import Settings
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))
    client.reset()
    strat_e2e: Dict[str, Any] = {}
    correct_by: Dict[str, set] = {}
    for name, cfg in PK.STRATEGIES.items():
        col, chunks, _ = build_strategy_collection(client, "e2e_" + name, cfg, records, embed, count)
        p2 = RP.RagPipeline(pipe.backend, PR.PageRetriever(col, embed), pipe.ctx, pipe.corpus, RG.ExtractiveGenerator(), count)
        ev = evaluate_rows(run_pipeline(p2, queries, oracle=True), oracle=True)
        correct_by[name] = set(ev.pop("_correct_ids"))
        strat_e2e[name] = {"answered_and_cites_evidence_chunk_on_gold_page": ev["generation"]["answered_and_cites_evidence_chunk_on_gold_page"],
                           "answered_given_answerable": ev["generation"]["answered_given_answerable"],
                           "abstention_on_absent_detail": ev["abstention_on_absent_detail"]["insufficient_context"]}
    client.reset()
    ids = [q["id"] for q in queries if q["type"] == "answerable"]
    for other in ("A_legacy_1000c", "C_heading_128"):
        only_b = sum(1 for i in ids if i in correct_by["B_heading_200"] and i not in correct_by[other])
        only_o = sum(1 for i in ids if i in correct_by[other] and i not in correct_by["B_heading_200"])
        strat_e2e[f"paired_B_vs_{other}"] = {"only_B_correct": only_b, "only_other_correct": only_o, "sign_test_p_two_sided": sign_test_p(only_o, only_b)}

    def factory(gen):
        return RP.RagPipeline(pipe.backend, pipe.retriever, pipe.ctx, pipe.corpus, gen, count)
    halluc = hallucination_eval(factory, queries)

    # performance (router mode, per stage)
    stages: Dict[str, List[float]] = {}
    for r in router_rows:
        for k, v in r["a"]["timings_ms"].items():
            stages.setdefault(k, []).append(v)
    def pct(xs, p):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(round((len(xs) - 1) * p)))], 2)
    perf["per_query_ms_router_mode"] = {k: {"median": round(statistics.median(v), 2), "p95": pct(v, 0.95), "max": round(max(v), 2), "n": len(v)} for k, v in sorted(stages.items())}
    perf.update(PERF_NOTES)
    perf["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    perf["note"] = "CPU, no GPU, extractive generator; LLM generation latency is NOT measured (no LLM available)"
    PERF.write_text(json.dumps(perf, indent=2) + "\n", encoding="utf-8")

    for e in (e2e_router, e2e_oracle):
        e["failures"] = e.pop("_failures")
        e.pop("_correct_ids", None)
    results = {
        "schema_version": 1, "queries_file": str(QUERIES.relative_to(ROOT)), "queries_file_sha256": hashlib.sha256(QUERIES.read_bytes()).hexdigest(),
        "query_counts": payload["counts"], "authorship": payload["authorship"], "preregistered": payload["preregistered"],
        "corpus": {"sha256": manifest["corpus_sha256"], "pages": manifest["totals"]["pages_ingested"], "cards": manifest["totals"]["cards"], "status_counts": manifest["totals"]["status_counts"]},
        "token_counter": tinfo, "chunking_comparison": comparison, "end_to_end_by_chunk_strategy_oracle_routing": strat_e2e,
        "end_to_end_router_rank1": e2e_router, "end_to_end_oracle_routing": e2e_oracle, "hallucination_guard": halluc,
        "llm_generation": {"validated": False, "reason": "no Ollama server and no model weights are reachable from this environment (network blocked); OllamaClient is implemented and unit-tested with stubs only"},
        "limitations": ["7 of 29 cards have page text; 22 can only be answered with page_not_ingested / unresolved_identity",
                        "queries are AI-authored with the page text in view; n per page is 6-10; every rate has a wide Wilson interval",
                        "the extractive generator is not an LLM; answer fluency and paraphrase quality are not measured",
                        "lexical gates are uncalibrated heuristics"],
    }
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS.relative_to(ROOT)} and {PERF.relative_to(ROOT)}")
    for name, s in comparison["strategies"].items():
        r = s["retrieval"]
        print(name, s["chunk_stats"]["chunks"], "chunks | gold-page R@1/3/5", [r["in_gold_page"][f"recall@{k}"]["rate"] for k in KS], "MRR", r["in_gold_page"]["mrr"],
              "| corpus-wide R@1", r["corpus_wide_no_card_stage"]["recall@1"]["rate"])
    print("router-mode status match:", {k: v["rate"] for k, v in e2e_router["status_match_by_type"].items()})
    print("oracle-mode status match:", {k: v["rate"] for k, v in e2e_oracle["status_match_by_type"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
