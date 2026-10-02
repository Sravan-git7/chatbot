#!/usr/bin/env python3
"""Diagnostic probe: test multi-candidate reranking formulas on Phase 12 queries.
Evaluates router R@1, R@3, R@5, MRR and checks what happens to answerable questions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import m2c_common as C
import m2c_page_identity as pid
import page_corpus as PC
import rag_pipeline as RP
import rag_text as T


def run_probe():
    queries_path = ROOT / "data" / "evaluation" / "phase12_queries.json"
    queries = json.loads(queries_path.read_text(encoding="utf-8"))["queries"]

    pipe = RP.build_pipeline(generator="extractive")
    backend = pipe.backend
    retriever = pipe.retriever
    ctx = pipe.ctx
    corpus = pipe.corpus

    # Pre-fetch top 5 candidates and their page hits for all queries
    data = []
    for q in queries:
        raw = backend.query(q["query"], 29)
        ranked = [{"source_id": m["source_id"], "similarity": round(1.0 - d, 4), "distance": round(d, 4)}
                  for m, d in zip(raw["metadatas"][0], raw["distances"][0])]
        top5 = ranked[:5]

        # Fetch page evidence for top 5
        qterms = T.terms(q["query"])
        candidates_evidence = []
        for c in top5:
            sid = c["source_id"]
            card_obj = pipe.cards.get(sid, {})
            identity = pid.resolve_identity(card_obj, ctx)
            entry = corpus.entry(sid) or {}
            ingested = entry.get("corpus_status") == PC.S_INGESTED and identity.effective_guide_id and identity.effective_page_id

            top_chunk_sim = 0.0
            top_chunk_cov = 0.0
            if ingested:
                hits = retriever.retrieve_in_page(q["query"], identity.effective_guide_id, identity.effective_page_id, top_k=3)
                if hits:
                    top_chunk_sim = max(h.similarity for h in hits)
                    cov_text = " ".join(f"{h.title} {h.text}" for h in hits[:2])
                    top_chunk_cov = T.coverage(qterms, cov_text)

            candidates_evidence.append({
                "source_id": sid,
                "card_sim": c["similarity"],
                "ingested": bool(ingested),
                "has_identity": bool(identity.effective_page_id),
                "top_chunk_sim": top_chunk_sim,
                "coverage": top_chunk_cov,
            })

        golds = [q["gold_source_id"]] if q["type"] != "ambiguous" else list(q.get("acceptable_source_ids") or [])
        data.append({"q": q, "golds": golds, "full_order": [r["source_id"] for r in ranked], "candidates": candidates_evidence})

    ans_q = [d for d in data if d["q"]["type"] == "answerable"]
    all_gold_q = [d for d in data if d["golds"]]

    def eval_scoring(score_fn, name=""):
        r1, r3, r5, mrr = 0, 0, 0, 0.0
        r1_ans = 0
        for d in all_gold_q:
            # Score top 5
            scored = []
            for c in d["candidates"]:
                s = score_fn(c)
                scored.append((s, c["source_id"]))
            # Sort descending by score
            scored.sort(key=lambda x: x[0], reverse=True)
            reranked_order = [x[1] for x in scored] + [x for x in d["full_order"] if x not in [c["source_id"] for c in d["candidates"]]]
            
            ranks = [reranked_order.index(g) + 1 for g in d["golds"] if g in reranked_order]
            rank = min(ranks) if ranks else 999
            if rank == 1:
                r1 += 1
                if d["q"]["type"] == "answerable":
                    r1_ans += 1
            if rank <= 3:
                r3 += 1
            if rank <= 5:
                r5 += 1
            mrr += 1.0 / rank

        n = len(all_gold_q)
        n_ans = len(ans_q)
        print(f"[{name:40s}] R@1: {r1/n:.4f} ({r1}/{n}) | Ans R@1: {r1_ans/n_ans:.4f} ({r1_ans}/{n_ans}) | R@3: {r3/n:.4f} | R@5: {r5/n:.4f} | MRR: {mrr/n:.4f}")

    print("Baseline:")
    eval_scoring(lambda c: c["card_sim"], name="Baseline (card similarity only)")

    print("\nProbing combinations:")
    for w_card in (0.3, 0.4, 0.5, 0.6, 0.7):
        for w_page in (0.3, 0.4, 0.5, 0.6):
            for w_cov in (0.0, 0.1, 0.2):
                def score(c, wc=w_card, wp=w_page, wcv=w_cov):
                    if not c["ingested"]:
                        # penalty if uningested
                        return wc * c["card_sim"] - 0.2
                    return wc * c["card_sim"] + wp * c["top_chunk_sim"] + wcv * c["coverage"]
                eval_scoring(score, name=f"wc={w_card} wp={w_page} wcv={w_cov}")


if __name__ == "__main__":
    run_probe()
