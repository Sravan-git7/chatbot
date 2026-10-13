#!/usr/bin/env python3
"""Versioned current-production quality run, separate from latency and sealed historical outputs.

Uses the frozen 113-case Phase-12 labels (AI-authored, not expert/blind gold), without changing
labels or outputs. Current corpus is larger than the label authors' corpus, so negative-label
drift is reported rather than relabelled. Strict evidence correctness requires BOTH the
expected guide/page identity in a cited context item AND the evidence quote in the answer.
Lexical grounding is reported separately; it is not a semantic truth judgement.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def normalize(text):
    return " ".join(re.sub(r"\[S\d+\]", "", text or "").lower().split())


def strict_evidence_correct(query, raw):
    if raw.get("status") != "answered" or not query.get("gold_doc_id") or not query.get("evidence"):
        return False
    guide, page = query["gold_doc_id"].split("/")
    debug = raw.get("debug") or {}
    items = {i["chunk_id"]: i for i in (debug.get("context") or {}).get("items", [])}
    quotes = [normalize(q) for q in query["evidence"]]
    answer = normalize(raw.get("answer"))
    for citation in (raw.get("citations") or {}).get("answer_sources", []):
        item = items.get(citation.get("chunk_id"))
        if not item:
            continue
        if (citation.get("guide_id"), citation.get("page_id")) != (guide, page):
            continue
        if (item.get("guide_id"), item.get("page_id")) != (guide, page):
            continue
        if any(q and q in normalize(item.get("text")) and q in answer for q in quotes):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve() / "scripts"))
    import rag_service as S
    import rag_evidence as E
    import evaluate_phase8 as EP
    import subprocess
    queries_path = ROOT / "data/evaluation/phase12_queries.json"
    dataset = json.loads(queries_path.read_bytes())
    svc = S.build_service("extractive")
    records = []
    totals = {"n": 0, "answerable_n": 0, "answerable_strict_correct": 0,
              "answerable_answered": 0, "wrong_page_answered": 0, "negative_n": 0,
              "negative_abstained": 0, "negative_answered": 0, "grounded_answers": 0,
              "answered": 0, "phantom_citations": 0, "source_identity_violations": 0,
              "supported_sentences_lexical": 0, "sentences_checked": 0,
              "gold_evidence_in_context": 0, "recall_at_1_hits": 0, "recall_at_5_hits": 0,
              "recall_at_10_hits": 0, "reciprocal_rank_sum_truncated_10": 0.0}
    for query in dataset["queries"]:
        raw, evidence = svc._run_pipeline_request(query["query"])
        debug = raw.get("debug") or {}
        selected = raw.get("routing", {}).get("selected_source_id")
        candidates = [c.get("source_id") for c in raw.get("routing", {}).get("candidates", [])]
        allowed = set(query.get("acceptable_source_ids") or []) | {query.get("gold_source_id")}
        rank = next((i for i, c in enumerate(candidates, 1) if c in allowed), None)
        answered = raw["status"] == "answered"
        items = {i["chunk_id"]: i for i in (debug.get("context") or {}).get("items", [])}
        cited = (raw.get("citations") or {}).get("answer_sources", [])
        phantom = sum(c.get("chunk_id") not in items for c in cited)
        identity_bad = sum(c.get("chunk_id") in items and
                           (c.get("guide_id"), c.get("page_id")) !=
                           (items[c["chunk_id"]].get("guide_id"), items[c["chunk_id"]].get("page_id")) for c in cited)
        ground = debug.get("grounding") or {}
        sentence_reports = ground.get("sentences") or []
        sentence_bad = sum(not x.get("markers") or x.get("support", 0) < 0.6 or bool(x.get("unsupported_tokens"))
                           for x in sentence_reports if isinstance(x, dict))
        strict = strict_evidence_correct(query, raw)
        gold_evidence = any(query.get("gold_doc_id") == f"{i.get('guide_id')}/{i.get('page_id')}" and
                            EP.has_evidence(i.get("text") or "", query.get("evidence") or []) for i in items.values())
        totals["n"] += 1
        if query["type"] == "answerable":
            totals["answerable_n"] += 1
            totals["answerable_strict_correct"] += strict
            totals["answerable_answered"] += answered
            totals["wrong_page_answered"] += answered and selected not in allowed
            totals["gold_evidence_in_context"] += gold_evidence
            for k in (1, 5, 10):
                totals[f"recall_at_{k}_hits"] += rank is not None and rank <= k
            totals["reciprocal_rank_sum_truncated_10"] += 1 / rank if rank else 0
        elif query["type"] != "ambiguous":
            totals["negative_n"] += 1
            totals["negative_answered"] += answered
            totals["negative_abstained"] += not answered
        totals["answered"] += answered
        totals["grounded_answers"] += answered and bool(ground.get("ok")) and not phantom and not identity_bad
        totals["phantom_citations"] += phantom
        totals["source_identity_violations"] += identity_bad
        totals["sentences_checked"] += len(sentence_reports) if answered else 0
        totals["supported_sentences_lexical"] += (len(sentence_reports) - sentence_bad) if answered else 0
        records.append({"id": query["id"], "type": query["type"], "status": raw["status"],
                        "reason": raw.get("reason_code"), "selected": selected, "rank_gold": rank,
                        "strict_evidence_correct": strict, "gold_evidence_in_context": gold_evidence,
                        "grounding_ok": ground.get("ok"), "phantom_citations": phantom,
                        "identity_violations": identity_bad, "answer": raw.get("answer"),
                        "sources": [{k: c.get(k) for k in ("chunk_id", "guide_id", "page_id", "url")} for c in cited]})
    a = totals["answerable_n"]
    metrics = {f"recall_at_{k}": totals[f"recall_at_{k}_hits"] / a for k in (1, 5, 10)}
    metrics.update({"precision_at_1_known_gold": metrics["recall_at_1"],
                    "mrr_truncated_10": totals["reciprocal_rank_sum_truncated_10"] / a,
                    "strict_evidence_answer_accuracy": totals["answerable_strict_correct"] / a,
                    "gold_evidence_context_coverage": totals["gold_evidence_in_context"] / a,
                    "appropriate_abstention_frozen_negative_labels": totals["negative_abstained"] / totals["negative_n"],
                    "unsupported_answer_rate_frozen_negative_labels": totals["negative_answered"] / totals["negative_n"],
                    "grounded_answer_rate_lexical": totals["grounded_answers"] / totals["answered"] if totals["answered"] else None,
                    "supported_sentence_rate_lexical": totals["supported_sentences_lexical"] / totals["sentences_checked"] if totals["sentences_checked"] else None})
    result = {"quality_version": "v1", "started_utc": datetime.now(timezone.utc).isoformat(),
              "source_commit": args.source_commit, "generator": "extractive", "real_llm": False,
              "dataset_sha256": hashlib.sha256(queries_path.read_bytes()).hexdigest(),
              "label_authorship": dataset.get("authorship"), "label_corpus_sha256": dataset.get("corpus_sha256"),
              "runtime_corpus_sha256": svc.pipeline.corpus.corpus_sha256,
              "config": svc.pipeline.cfg.to_dict(), "totals": totals, "metrics": metrics,
              "limits": ["Labels are frozen AI-authored reference-evidence labels, not blind human gold.",
                         "Negative labels may drift as the admitted corpus expands; they are not relabelled.",
                         "Grounding and sentence support are lexical, not semantic truth judgements.",
                         "Precision@k beyond 1 is not reported: complete relevance judgements are unavailable.",
                         "Follow-up/topic isolation is evaluated by the fixed multi-turn workload and regression suite."],
              "per_query": records}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({"totals": totals, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
