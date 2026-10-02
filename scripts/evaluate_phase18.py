#!/usr/bin/env python3
"""Phase 18 - Reranker page-evidence deepening (E1) + deterministic citation repair (E2) + production config reconciliation.

Evaluates 6 configurations across the frozen 113-question benchmark, all on top of the verified
Phase 16 production baseline (top_k_cards=10, rerank_router=True, code_aware_router=True,
in_page_grounding=True, citation_normalization=True, relaxed_context_gate=True,
evidence_frame_normalization=False):

  phase16_baseline        : Phase 18 flags OFF (must equal the committed Phase 16 baseline)
  e1a_phrase_reranker     : + phrase_reranker=True
  e1b_full_page_coverage  : + full_page_coverage=True
  e1ab_phrase_and_page    : + phrase_reranker=True, full_page_coverage=True
  e2_citation_repair      : + citation_repair=True
  e1e2_combined           : + phrase_reranker=True, full_page_coverage=True, citation_repair=True

Sandbox-measurable (no Ollama required): routing metrics (R@1 / in-pool), EXTRACTIVE answer
metrics, per-question route latency. The guarded Ollama part (llama3.2:3b) runs when the Ollama
server is reachable; otherwise it is recorded as BLOCKED with the Windows runbook (project
precedent since Phase 12).

Pre-declared adoption rules - a configuration PASSES only if every applicable rule holds:
  R1 (router):      answerable R@1 >= 58/65 AND all-gold R@1 >= 87/105 AND gold-in-pool 100% (105/105).
  R2 (extractive):  zero per-question regressions vs phase16_baseline (every question correct in the
                    baseline must stay correct in the candidate).
  R3 (guarded):     only evaluated when Ollama ran - wrong-page answers <= 1, unsupported answered
                    <= 6 with no new non-stale, absent-detail answered = 0, grounding failures = 0,
                    phantom citations = 0, URL changes = 0, citation-evidence failures <= 2,
                    generator errors = 0.
  R4 (latency):     median route latency <= baseline median + 15 ms.
Best passing config: most (guarded correct, extractive correct); ties break toward fewer new flags.

Contract: no hardcoded question / gold / source IDs - all label logic comes from the frozen query file.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_phase12 as E12
import page_corpus as PC
import rag_evidence as RE
import rag_pipeline as RP
from rag_generate import GenerationResult


class CachedLLMGenerator:
    """Wraps an LLM generator with an in-memory cache keyed by (query, context_content_hash)."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.name = getattr(inner, "name", "cached_ollama")
        self.cache: Dict[Tuple[str, str], GenerationResult] = {}

    def generate(self, query: str, context: Any) -> GenerationResult:
        ctx_hash = hashlib.sha256("\n".join(f"{it.marker}:{it.content_hash}" for it in context.items).encode("utf-8")).hexdigest()
        key = (query.strip(), ctx_hash)
        if key in self.cache:
            res = self.cache[key]
            return GenerationResult(res.text, res.refused, res.generator, res.raw_text, res.prompt)
        res = self.inner.generate(query, context)
        self.cache[key] = res
        return res


def ollama_available(timeout_s: float = 2.0) -> bool:
    """Cheap reachability probe for the local Ollama server (never blocks a router/extractive run)."""
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=timeout_s)
        return r.status_code == 200
    except Exception:                                  # noqa: BLE001
        return False


# (config key, phrase_reranker, phrase_min_corroboration, full_page_coverage, citation_repair, description)
CONFIGS: Sequence[Tuple[str, bool, int, bool, bool, str]] = (
    ("phase16_baseline", False, 1, False, False, "Verified Phase 16 production baseline (Phase 18 flags OFF)"),
    ("e1a_phrase_reranker", True, 1, False, False, "E1a (corr=1): unique-phrase channel in the Phase 13 reranker"),
    ("e1a_v2_corroborated", True, 2, False, False, "E1a-v2 (corr=2): phrase channel requiring >= 2 distinct unique query phrases per page"),
    ("e1b_full_page_coverage", False, 1, True, False, "E1b: reranker coverage over the full page text"),
    ("e1ab_phrase_and_page", True, 1, True, False, "E1 (corr=1): phrase channel + full-page coverage"),
    ("e1ab_v2_corroborated", True, 2, True, False, "E1-v2 (corr=2): corroborated phrase channel + full-page coverage"),
    ("e2_citation_repair", False, 1, False, True, "E2: deterministic in-page citation repair after grounding"),
    ("e1e2_combined", True, 1, True, True, "Combined (corr=1): E1a + E1b + E2"),
    ("e1e2_v2_combined", True, 2, True, True, "Combined-v2 (corr=2): E1a-v2 + E1b + E2"),
)

FLAG_COUNT = {
    "phase16_baseline": 0,
    "e1a_phrase_reranker": 1, "e1a_v2_corroborated": 1,
    "e1b_full_page_coverage": 1,
    "e1ab_phrase_and_page": 2, "e1ab_v2_corroborated": 2,
    "e2_citation_repair": 1,
    "e1e2_combined": 3, "e1e2_v2_combined": 3,
}

R1_ANS_R1_MIN = 58        # answerable R@1 floor (Phase 16 baseline: 58/65)
R1_GOLD_R1_MIN = 87       # all-gold R@1 floor (Phase 16 baseline: 87/105)
R4_LATENCY_SLACK_MS = 15.0
R3_WRONG_PAGE_MAX = 1
R3_UNSUPPORTED_MAX = 6
R3_CITE_EVIDENCE_MAX = 2


def make_config(phrase: bool, corr: int, pagecov: bool, repair: bool) -> "RP.PipelineConfig":
    """The verified Phase 16 production baseline with the named Phase 18 flags toggled."""
    return RP.PipelineConfig(
        top_k_cards=10,
        rerank_router=True,
        code_aware_router=True,
        in_page_grounding=True,
        citation_normalization=True,
        relaxed_context_gate=True,
        evidence_frame_normalization=False,
        phrase_reranker=phrase,
        phrase_min_corroboration=corr,
        full_page_coverage=pagecov,
        citation_repair=repair,
    )


def routing_pass(pipe: "RP.RagPipeline", queries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Real-mode routing for every question: per-question candidate order, gold-in-pool, route latency."""
    order_by_id: Dict[str, List[str]] = {}
    pool_contains_gold: Dict[str, bool] = {}
    route_latencies: List[float] = []
    all_sids = list(pipe.cards.keys())
    for q in queries:
        qid = q["id"]
        golds = list(q.get("acceptable_source_ids") or []) if q["type"] == "ambiguous" else ([q["gold_source_id"]] if q.get("gold_source_id") else [])
        t0 = time.perf_counter()
        ans = pipe.answer(q["query"], debug=True)
        route_ms = (ans.get("timings_ms") or {}).get("route_ms")
        route_latencies.append(float(route_ms) if route_ms is not None else (time.perf_counter() - t0) * 1000)
        topk = [c["source_id"] for c in ans["routing"].get("candidates", [])]
        order_by_id[qid] = topk + [sid for sid in all_sids if sid not in topk]
        pool_contains_gold[qid] = bool(golds) and any(g in topk for g in golds)
    return {"order_by_id": order_by_id, "pool_contains_gold": pool_contains_gold, "route_latencies": route_latencies}


def adoption_check(key: str, base: Dict[str, Any], cand: Dict[str, Any], guarded_ran: bool,
                   stale_unsupported: set) -> Dict[str, Any]:
    """Evaluate the pre-declared adoption rules for one candidate against the baseline."""
    checks: Dict[str, Any] = {}
    rm_c = cand["router_metrics"]
    checks["R1_router"] = {
        "pass": bool(rm_c["answerable_r1_count"] >= R1_ANS_R1_MIN
                     and rm_c["all_gold_r1_count"] >= R1_GOLD_R1_MIN
                     and rm_c["all_gold_in_pool_count"] == rm_c["all_gold_in_pool_total"]),
        "answerable_r1": f"{rm_c['answerable_r1_count']}/65",
        "all_gold_r1": f"{rm_c['all_gold_r1_count']}/{rm_c['all_gold_in_pool_total']}",
        "gold_in_pool": f"{rm_c['all_gold_in_pool_count']}/{rm_c['all_gold_in_pool_total']}",
    }
    ext_b = base["extractive_per_correct"]
    ext_c = cand["extractive_per_correct"]
    regressed = sorted(qid for qid in ext_b if ext_b[qid] and not ext_c[qid])
    recovered = sorted(qid for qid in ext_c if ext_c[qid] and not ext_b[qid])
    checks["R2_extractive"] = {"pass": not regressed, "regressed": regressed, "recovered": recovered}
    if guarded_ran:
        g_b, g_c = base["guarded"], cand["guarded"]
        new_unsupported = sorted(set(g_c["unsupported_answered_ids"]) - set(g_b["unsupported_answered_ids"]) - stale_unsupported)
        checks["R3_guarded"] = {
            "pass": bool(g_c["wrong_page_answers"] <= R3_WRONG_PAGE_MAX
                         and g_c["unsupported_answered"] <= R3_UNSUPPORTED_MAX and not new_unsupported
                         and g_c["absent_detail_answered"] == 0
                         and g_c["grounding_failures"] == 0
                         and g_c["phantom_citations"] == 0
                         and g_c["url_changed_total"] == 0
                         and g_c["citation_evidence_failures"] <= R3_CITE_EVIDENCE_MAX
                         and g_c["generator_errors"] == 0),
            "wrong_page_answers": g_c["wrong_page_answers"],
            "unsupported_answered": f"{g_c['unsupported_answered']}/40",
            "new_non_stale_unsupported": new_unsupported,
            "absent_detail_answered": g_c["absent_detail_answered"],
            "grounding_failures": g_c["grounding_failures"],
            "phantom_citations": g_c["phantom_citations"],
            "url_changed_total": g_c["url_changed_total"],
            "citation_evidence_failures": g_c["citation_evidence_failures"],
            "generator_errors": g_c["generator_errors"],
        }
    else:
        checks["R3_guarded"] = {"pass": None, "note": "BLOCKED - Ollama server not reachable; run the Windows runbook for guarded metrics"}
    checks["R4_latency"] = {
        "pass": bool(cand["latency"]["route_median_ms"] <= base["latency"]["route_median_ms"] + R4_LATENCY_SLACK_MS),
        "baseline_median_ms": base["latency"]["route_median_ms"],
        "candidate_median_ms": cand["latency"]["route_median_ms"],
    }
    checks["overall"] = bool(checks["R1_router"]["pass"] and checks["R2_extractive"]["pass"]
                             and checks["R4_latency"]["pass"]
                             and (checks["R3_guarded"]["pass"] in (None, True)))
    return checks


def run_evaluation() -> None:
    print("=" * 80)
    print("PHASE 18: E1 RERANKER DEEPENING + E2 CITATION REPAIR + CONFIG RECONCILIATION EVALUATION")
    print("=" * 80)

    queries_path = ROOT / "data" / "evaluation" / "phase12_queries.json"
    queries_payload = json.loads(queries_path.read_text(encoding="utf-8"))
    queries = queries_payload["queries"]
    queries_sha = hashlib.sha256(queries_path.read_bytes()).hexdigest()
    print(f"Loaded {len(queries)} frozen queries (SHA256: {queries_sha[:12]}...)")

    cards_manifest = json.loads((ROOT / "data" / "card_collection_manifest.json").read_text(encoding="utf-8"))
    card_url = {c["source_id"]: c.get("card_url", "") for c in cards_manifest.get("cards", [])}

    out_dir = ROOT / "data" / "phase18"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "phase18_ollama_ckpt.jsonl"
    ckpt_header = {"queries_sha256": queries_sha, "model": "llama3.2:3b", "phase": "18"}
    ckpt = E12.Checkpoint(ckpt_path, ckpt_header)

    # Pre-populate the baseline config from the sealed Phase 16 checkpoint (identical pipeline =>
    # identical (query, context) pairs) so the user's guarded re-run reuses finished LLM rows.
    p16_ckpt = ROOT / "data" / "phase16" / "phase16_ollama_ckpt.jsonl"
    if p16_ckpt.is_file():
        with open(p16_ckpt, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("config") == "phase16_combined_ABC":
                    if ckpt.get("phase16_baseline", d["id"], d["mode"]) is None:
                        ckpt.put("phase16_baseline", d["id"], d["mode"], d["record"])
        print(f"Pre-populated baseline checkpoint rows from {p16_ckpt.name}")

    ollama_ok = ollama_available()
    print(f"Ollama server reachable: {ollama_ok}" + ("" if ollama_ok else " -> guarded part BLOCKED (Windows runbook recorded in the report)"))

    all_gold_q = [q for q in queries if q.get("gold_source_id") or q["type"] == "ambiguous"]
    ans_q = [q for q in queries if q["type"] == "answerable"]

    def stale_unsupported_ids(pipe: "RP.RagPipeline") -> set:
        """Not-ingested-labeled questions whose gold card in fact has ingested local content: their
        'not_ingested' label is a stale corpus_status artifact (the G1 governance item). Data-driven -
        no question or card IDs are hardcoded."""
        out = set()
        for q in queries:
            if q["type"] != "not_ingested":
                continue
            gold = q.get("gold_source_id")
            if not gold:
                continue
            entry = pipe.corpus.entry(gold) or {}
            if entry.get("corpus_status") == PC.S_INGESTED:
                out.add(q["id"])
        return out

    cached_llm: Optional[CachedLLMGenerator] = None
    if ollama_ok:
        raw_ollama = RP.build_pipeline(generator="ollama").generator
        cached_llm = CachedLLMGenerator(raw_ollama)

    results_by_config: Dict[str, Any] = {}
    # Build the shared embedding/store/corpus components ONCE so later configurations are not penalized
    # by accumulating multiple SentenceTransformer models + Chroma clients in the same process.
    shared_pipe = RP.build_pipeline(generator="extractive", config=make_config(False, 1, False, False))
    baseline_pipe_ref: Optional["RP.RagPipeline"] = shared_pipe

    for key, flag_p, flag_corr, flag_pc, flag_r, desc in CONFIGS:
        print(f"\n{'=' * 70}\nEVALUATING CONFIGURATION: {desc} ({key})\n{'=' * 70}")
        pipe_cfg = make_config(flag_p, flag_corr, flag_pc, flag_r)
        base_pipe = RP.RagPipeline(
            shared_pipe.backend, shared_pipe.retriever, shared_pipe.ctx, shared_pipe.corpus,
            shared_pipe.generator, shared_pipe.count_tokens, config=pipe_cfg,
        )

        rpass = routing_pass(base_pipe, queries)
        order_by_id, pool_contains_gold = rpass["order_by_id"], rpass["pool_contains_gold"]
        route_latencies = rpass["route_latencies"]

        rm = E12.router_metrics(queries, order_by_id)
        ag = rm["all_gold_card_questions"]
        ans_block = rm["answerable"]
        all_gold_total = len(all_gold_q)
        gold_in_pool_count = sum(1 for q in all_gold_q if pool_contains_gold[q["id"]])

        # Extractive answers (deterministic, always measured)
        res_ext = E12.evaluate_config(base_pipe, queries, order_by_id, card_url, name=f"ext_{key}", llm=False, log=sys.stdout)
        per_ext = res_ext["per_query"]
        ext_real = E12.answer_metrics(queries, per_ext, "real")
        ext_per_correct = {qid: bool(v["real"]["correct"]) for qid, v in per_ext.items() if qid in {q["id"] for q in ans_q}}

        guarded: Optional[Dict[str, Any]] = None
        per_guard: Optional[Dict[str, Any]] = None
        if ollama_ok:
            pipe_llm = RP.RagPipeline(
                base_pipe.backend, base_pipe.retriever, base_pipe.ctx, base_pipe.corpus,
                cached_llm, base_pipe.count_tokens, config=pipe_cfg,
            )
            guard_llm_pipe = RE.build_evidence_pipeline(pipe_llm, tau=RE.SHIPPED_TAU, widen=False, generator="ollama")
            res_guard = E12.evaluate_config(guard_llm_pipe, queries, order_by_id, card_url, name=key, llm=True, ckpt=ckpt, log=sys.stdout)
            per_guard = res_guard["per_query"]
            g_real = E12.answer_metrics(queries, per_guard, "real")
            g_ora = E12.answer_metrics(queries, per_guard, "oracle")
            t_tots = [v["real"]["timings"]["total_ms"] for v in per_guard.values() if "real" in v and "timings" in v["real"] and "total_ms" in v["real"]["timings"]]
            url_changed_total = sum(v["real"].get("url_changed", 0) for v in per_guard.values() if "real" in v)
            guarded = {
                "answerable_correct": g_real["answerable"]["answered_correct"],
                "oracle_correct": g_ora["answerable"]["answered_correct"],
                "real_vs_oracle_gap": g_ora["answerable"]["answered_correct"] - g_real["answerable"]["answered_correct"],
                "wrong_page_answers": g_real["wrong_page_answers"],
                "unsupported_answered": g_real["unsupported"]["incorrectly_answered"],
                "unsupported_answered_ids": sorted(q["id"] for q in queries if q["type"] in E12.UNSUPPORTED_TYPES and per_guard[q["id"]]["real"]["status"] == "answered"),
                "absent_detail_answered": g_real["absent_detail"]["answered"],
                "citation_evidence_failures": g_real["citation_evidence_failures"],
                "grounding_failures": g_real["grounding_failures"],
                "phantom_citations": g_real["phantom_citations"],
                "url_changed_total": url_changed_total,
                "generator_errors": g_real["generator_errors_total"],
                "total_pipeline_median_ms": round(statistics.median(t_tots), 2) if t_tots else None,
            }

        lat = {
            "route_median_ms": round(statistics.median(route_latencies), 2),
            "route_mean_ms": round(statistics.mean(route_latencies), 2),
        }

        print(f"\nExtractive ({key}): answerable correct = {ext_real['answerable']['answered_correct']}/65 | "
              f"wrong-page = {ext_real['wrong_page_answers']} | absent-detail = {ext_real['absent_detail']['answered']}/16 | "
              f"grounding failures = {ext_real['grounding_failures']} | phantom = {ext_real['phantom_citations']}")
        print(f"Router ({key}): answerable R@1 = {ans_block['counts']['top1']}/65 | all-gold R@1 = {ag['counts']['top1']}/{all_gold_total} | "
              f"gold-in-pool = {gold_in_pool_count}/{all_gold_total} | route median = {lat['route_median_ms']} ms")
        if guarded is not None:
            print(f"Guarded Ollama ({key}): answerable correct = {guarded['answerable_correct']}/65 (oracle {guarded['oracle_correct']}/65)")

        results_by_config[key] = {
            "key": key,
            "description": desc,
            "flags": {"phrase_reranker": flag_p, "phrase_min_corroboration": flag_corr,
                      "full_page_coverage": flag_pc, "citation_repair": flag_r},
            "router_metrics": {
                "all_gold_r1": ag["R@1"],
                "all_gold_r1_count": ag["counts"]["top1"],
                "all_gold_mrr": ag["MRR"],
                "all_gold_in_pool_count": gold_in_pool_count,
                "all_gold_in_pool_total": all_gold_total,
                "answerable_r1": ans_block["R@1"],
                "answerable_r1_count": ans_block["counts"]["top1"],
                "answerable_in_pool_rate": round(sum(1 for q in ans_q if pool_contains_gold[q["id"]]) / len(ans_q), 4),
            },
            "extractive": {
                "answerable_correct": ext_real["answerable"]["answered_correct"],
                "wrong_page_answers": ext_real["wrong_page_answers"],
                "absent_detail_answered": ext_real["absent_detail"]["answered"],
                "grounding_failures": ext_real["grounding_failures"],
                "phantom_citations": ext_real["phantom_citations"],
                "citation_evidence_failures": ext_real["citation_evidence_failures"],
                "generator_errors": ext_real["generator_errors_total"],
            },
            "extractive_per_correct": ext_per_correct,
            "guarded": guarded,
            "latency": lat,
            "per_query_extractive": per_ext,
            "per_query_guarded": per_guard,
        }

    base = results_by_config["phase16_baseline"]
    stale_unsupported = stale_unsupported_ids(baseline_pipe_ref) if baseline_pipe_ref is not None else set()
    print(f"\nStale-labeled unsupported questions (gold card actually ingested; G1 governance): {sorted(stale_unsupported) or 'none'}")

    print(f"\n{'=' * 70}\nADOPTION DECISIONS (pre-declared rules)\n{'=' * 70}")
    decisions: Dict[str, Any] = {}
    for key, _, _, _, _, _ in CONFIGS:
        if key == "phase16_baseline":
            decisions[key] = {"role": "baseline", "overall": None}
            continue
        d = adoption_check(key, base, results_by_config[key], ollama_ok, stale_unsupported)
        decisions[key] = d
        print(f"\n{key}: OVERALL {'PASS' if d['overall'] else 'FAIL'}")
        for rule, body in d.items():
            if rule == "overall":
                continue
            if isinstance(body, dict) and "pass" in body:
                print(f"  {rule}: {'PASS' if body['pass'] is True else ('BLOCKED' if body['pass'] is None else 'FAIL')}")

    passing = [k for k, v in decisions.items() if v.get("overall") is True]
    best = None
    if passing:
        def rank(k: str) -> Tuple:
            r = results_by_config[k]
            guarded_corr = (r["guarded"]["answerable_correct"] if r["guarded"] else 0)
            rm_k = r["router_metrics"]
            return (-guarded_corr, -r["extractive"]["answerable_correct"],
                    -rm_k["answerable_r1_count"], -rm_k["all_gold_r1_count"], FLAG_COUNT[k])
        best = sorted(passing, key=rank)[0]
    print(f"\nPassing configurations: {passing or 'none'}")
    print(f"Best passing configuration: {best or 'none'}")

    # Persist (drop the bulky per_query_extractive lists from the JSON; keep the guarded per-query detail
    # only when measured, mirroring phase17a_comparison.json's structure)
    slim = {}
    for k, r in results_by_config.items():
        s = {kk: vv for kk, vv in r.items() if kk != "per_query_extractive"}
        s["per_query"] = r["per_query_guarded"] if r["per_query_guarded"] is not None else None
        slim[k] = s
    final_output = {
        "schema_version": 1,
        "phase": "18",
        "experiment": "Phase 18 reranker page-evidence deepening (E1) + deterministic citation repair (E2) + production config reconciliation",
        "queries_sha256": queries_sha,
        "model": "llama3.2:3b (guarded part)" if ollama_ok else "extractive only (Ollama BLOCKED)",
        "ollama_available": ollama_ok,
        "results": slim,
        "adoption": {
            "rules": {
                "R1": f"answerable R@1 >= {R1_ANS_R1_MIN}/65 AND all-gold R@1 >= {R1_GOLD_R1_MIN}/{len(all_gold_q)} AND gold-in-pool 100%",
                "R2": "zero per-question extractive regressions vs phase16_baseline",
                "R3": "guarded: wrong-page <= 1, unsupported answered <= 6 (no new non-stale), absent-detail = 0, grounding = 0, phantom = 0, URL changes = 0, cite-evidence <= 2, generator errors = 0 (only when Ollama ran)",
                "R4": f"median route latency <= baseline median + {R4_LATENCY_SLACK_MS:.0f} ms",
            },
            "decisions": decisions,
            "passing": passing,
            "best": best,
        },
        "blocked": None if ollama_ok else {
            "part": "guarded_ollama",
            "reason": "Ollama server not reachable in this environment (no local server; outbound TLS to the model registry is blocked - sandbox precedent since Phase 12)",
            "runbook_windows": [
                "1. Start Ollama on the Windows machine and pull the model:  ollama pull llama3.2:3b",
                "2. Keep the ORIGINAL (Windows) vector stores - do not use the sandbox-rebuilt stores.",
                "3. Run:  python scripts/evaluate_phase18.py",
                "4. Baseline guarded rows are pre-populated from data/phase16/phase16_ollama_ckpt.jsonl; only the new-flag configurations need fresh LLM calls.",
                "5. Compare data/phase18/phase18_comparison.json adoption section against the sealed Phase 16 numbers.",
            ],
        },
    }
    comparison_path = out_dir / "phase18_comparison.json"
    comparison_path.write_text(json.dumps(final_output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved full Phase 18 comparison to: {comparison_path}")

    # Markdown report
    md: List[str] = []
    md.append("# Phase 18: Reranker Page-Evidence Deepening (E1) + Deterministic Citation Repair (E2) Report\n")
    md.append(f"* **Frozen set**: Phase 12 113-question benchmark (SHA256 {queries_sha[:16]}...)")
    md.append("* **Corpus**: 25 ingested SAP Help pages, 29 M2C cards")
    md.append("* **Guarded model**: `llama3.2:3b`" if ollama_ok else "* **Guarded part**: BLOCKED in this environment (Ollama unreachable) - Windows runbook below")
    md.append("\n## 1. Comparative Metrics\n")
    md.append("| Configuration | Answerable R@1 /65 | All-gold R@1 /105 | Gold-in-pool | Extractive /65 | Guarded /65 (Oracle) | Absent /16 | Wrong-page | Route median ms |")
    md.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    for key, _, _, _, _, _ in CONFIGS:
        r = results_by_config[key]
        rm = r["router_metrics"]
        ext = r["extractive"]
        lat = r["latency"]
        g = r["guarded"]
        guarded_s = f"{g['answerable_correct']} / 65 ({g['oracle_correct']})" if g else "BLOCKED"
        md.append(f"| **{key}** | {rm['answerable_r1_count']} / 65 | {rm['all_gold_r1_count']} / {rm['all_gold_in_pool_total']} | "
                  f"{rm['all_gold_in_pool_count']}/{rm['all_gold_in_pool_total']} | {ext['answerable_correct']} / 65 | {guarded_s} | "
                  f"{ext['absent_detail_answered']} / 16 | {ext['wrong_page_answers']} | {lat['route_median_ms']} ms |")
    md.append("\n## 2. Adoption Decisions (pre-declared rules)\n")
    md.append(f"* **R1** router: {final_output['adoption']['rules']['R1']}")
    md.append(f"* **R2** extractive: {final_output['adoption']['rules']['R2']}")
    md.append(f"* **R3** guarded: {final_output['adoption']['rules']['R3']}")
    md.append(f"* **R4** latency: {final_output['adoption']['rules']['R4']}\n")
    for key, _, _, _, _, _ in CONFIGS:
        d = decisions[key]
        if key == "phase16_baseline":
            md.append(f"* **{key}**: baseline (reference)")
            continue
        md.append(f"* **{key}**: **{'PASS' if d['overall'] else 'FAIL'}**")
        for rule, body in d.items():
            if rule == "overall" or not isinstance(body, dict) or "pass" not in body:
                continue
            md.append(f"    * {rule}: {'PASS' if body['pass'] is True else ('BLOCKED' if body['pass'] is None else 'FAIL')}")
        r2 = d.get("R2_extractive", {})
        if r2.get("recovered"):
            md.append(f"    * extractive recovered: {', '.join(r2['recovered'])}")
        if r2.get("regressed"):
            md.append(f"    * extractive regressed: {', '.join(r2['regressed'])}")
    md.append(f"\n* **Passing configurations**: {', '.join(passing) if passing else 'none'}")
    md.append(f"* **Best passing configuration**: {best if best else 'none'}")
    if not ollama_ok:
        md.append("\n## 3. BLOCKED: Guarded Ollama Metrics (Windows runbook)\n")
        for line in final_output["blocked"]["runbook_windows"]:
            md.append(line)
    report_path = out_dir / "phase18_report.md"
    report_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Saved Markdown report to: {report_path}")


if __name__ == "__main__":
    run_evaluation()
