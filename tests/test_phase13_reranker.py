#!/usr/bin/env python3
"""Phase 13-A unit tests for multi-candidate router reranking.

Tests:
1. Top-k candidate retention (up to k candidates evaluated).
2. Invalid/unresolved candidate handling (e.g. M2C-18 does not automatically win over valid page evidence).
3. Deterministic reranking (identical inputs produce identical scores, ranks, and selections).
4. Baseline behavior unchanged when experiment disabled (rerank_router=False).
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT / "scripts"))

from m2c_router import CardCandidate
import phase13_reranker as PR13
import rag_pipeline as RP


class TestPhase13Reranker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_pipe = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(rerank_router=False))
        cls.rerank_pipe = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(rerank_router=True))

    def test_top_k_candidate_retention(self):
        """Verify that top-k (5) candidates are retained and scored."""
        query = "What is the purpose of meter reading monitoring?"
        raw = self.base_pipe.backend.query(query, 5)
        candidates = [
            CardCandidate(
                rank=i + 1,
                source_id=m["source_id"],
                title=m["title"],
                category=m["category"],
                source_url=m["source_url"],
                source_status=m["source_status"],
                source_url_status=m["source_url_status"],
                has_source_correction=m["has_source_correction"],
                citation=m["citation"],
                distance=float(d),
                distance_metric="cosine",
            )
            for i, (m, d) in enumerate(zip(raw["metadatas"][0], raw["distances"][0]))
        ]
        self.assertEqual(len(candidates), 5)
        selected, scored = PR13.rerank_candidates(
            query, candidates, self.base_pipe.cards, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus, top_k_evaluate=5
        )
        self.assertEqual(len(scored), 5)
        self.assertIn(selected.source_id, [c.source_id for c in candidates])
        self.assertEqual(scored[0].candidate.source_id, selected.source_id)
        # Rerank indices 1 to 5 are contiguous
        self.assertEqual([s.rerank for s in scored], [1, 2, 3, 4, 5])

    def test_invalid_unresolved_candidate_handling(self):
        """Verify that unresolved identity candidate (M2C-18) does not automatically beat verified page evidence (M2C-17)."""
        # Question P12-011: "What does the Contract Accounts component let me create?"
        query = "What does the Contract Accounts component let me create?"
        
        # Test directly with rerank_pipe
        ans_base = self.base_pipe.answer(query)
        ans_rerank = self.rerank_pipe.answer(query)

        # Baseline router selects M2C-18 (unresolved conflict hub)
        self.assertEqual(ans_base["routing"]["selected_source_id"], "M2C-18")
        self.assertEqual(ans_base["status"], "unresolved_identity")

        # Reranked router prefers M2C-17 because M2C-17 has verified page evidence while M2C-18 has none
        self.assertEqual(ans_rerank["routing"]["selected_source_id"], "M2C-17")
        self.assertEqual(ans_rerank["status"], "answered")

    def test_deterministic_reranking(self):
        """Verify that running reranker multiple times produces identical scores, ranks, and choices."""
        query = "How does the billing procedure cope with changes to master data?"
        ans1 = self.rerank_pipe.answer(query)
        ans2 = self.rerank_pipe.answer(query)

        self.assertEqual(ans1["routing"]["selected_source_id"], ans2["routing"]["selected_source_id"])
        self.assertEqual(ans1["status"], ans2["status"])
        self.assertEqual(ans1["answer"], ans2["answer"])
        
        cands1 = ans1["routing"]["candidates"]
        cands2 = ans2["routing"]["candidates"]
        self.assertEqual(len(cands1), len(cands2))
        for c1, c2 in zip(cands1, cands2):
            self.assertEqual(c1["source_id"], c2["source_id"])
            self.assertEqual(c1["final_score"], c2["final_score"])
            self.assertEqual(c1["rerank"], c2["rerank"])

    def test_baseline_behavior_unchanged_when_disabled(self):
        """Verify that when rerank_router=False, behavior is baseline rank-1, and default has reranking enabled."""
        test_queries = [
            "What is a billing procedure?",
            "How do I clear an incoming payment?",
            "What is the capital of France?",  # OOD
            "",  # empty query
        ]
        default_pipe = RP.build_pipeline(generator="extractive")
        explicit_true_pipe = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(rerank_router=True))
        explicit_false_pipe = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(rerank_router=False))

        # Default pipeline has reranking enabled
        self.assertTrue(default_pipe.cfg.rerank_router)

        for q in test_queries:
            r_def = default_pipe.answer(q)
            r_true = explicit_true_pipe.answer(q)
            r_false = explicit_false_pipe.answer(q)

            # Default matches explicit True
            self.assertEqual(r_def["status"], r_true["status"])
            self.assertEqual(r_def["routing"]["selected_source_id"], r_true["routing"]["selected_source_id"])
            self.assertEqual(r_def["answer"], r_true["answer"])
            if q and r_def["status"] != "empty_query":
                self.assertEqual(r_def["routing"]["mode"], f"router_reranked_top{default_pipe.cfg.top_k_cards}")

            # Explicit False strictly disables reranker to baseline router_rank1
            if q and r_false["status"] != "empty_query":
                self.assertEqual(r_false["routing"]["mode"], "router_rank1")


    def test_query_embedding_computed_once(self):
        """Verify that retriever.embed is called exactly once during rerank_candidates."""
        query = "How is an incoming payment cleared?"
        raw = self.base_pipe.backend.query(query, 5)
        candidates = [
            CardCandidate(
                rank=i + 1,
                source_id=m["source_id"],
                title=m["title"],
                category=m["category"],
                source_url=m["source_url"],
                source_status=m["source_status"],
                source_url_status=m["source_url_status"],
                has_source_correction=m["has_source_correction"],
                citation=m["citation"],
                distance=float(d),
                distance_metric="cosine",
            )
            for i, (m, d) in enumerate(zip(raw["metadatas"][0], raw["distances"][0]))
        ]

        original_embed = self.base_pipe.retriever.embed
        embed_call_count = 0

        def counting_embed(texts):
            nonlocal embed_call_count
            embed_call_count += 1
            return original_embed(texts)

        self.base_pipe.retriever.embed = counting_embed
        try:
            selected, scored = PR13.rerank_candidates(
                query,
                candidates,
                self.base_pipe.cards,
                self.base_pipe.retriever,
                self.base_pipe.ctx,
                self.base_pipe.corpus,
                top_k_evaluate=5,
            )
            self.assertEqual(embed_call_count, 1)
        finally:
            self.base_pipe.retriever.embed = original_embed

    def test_scores_identical_with_and_without_precomputed_embedding(self):
        """Verify that passing precomputed query_embedding produces mathematically identical scores and rankings."""
        test_queries = [
            "What is the purpose of meter reading monitoring?",
            "What does the Contract Accounts component let me create?",
            "How does the billing procedure cope with changes to master data?",
        ]
        for query in test_queries:
            raw = self.base_pipe.backend.query(query, 5)
            candidates = [
                CardCandidate(
                    rank=i + 1,
                    source_id=m["source_id"],
                    title=m["title"],
                    category=m["category"],
                    source_url=m["source_url"],
                    source_status=m["source_status"],
                    source_url_status=m["source_url_status"],
                    has_source_correction=m["has_source_correction"],
                    citation=m["citation"],
                    distance=float(d),
                    distance_metric="cosine",
                )
                for i, (m, d) in enumerate(zip(raw["metadatas"][0], raw["distances"][0]))
            ]
            sel1, scored1 = PR13.rerank_candidates(
                query, candidates, self.base_pipe.cards, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus, 5
            )
            emb = self.base_pipe.retriever.embed([query])
            sel2, scored2 = PR13.rerank_candidates(
                query, candidates, self.base_pipe.cards, self.base_pipe.retriever, self.base_pipe.ctx, self.base_pipe.corpus, 5, query_embedding=emb
            )
            self.assertEqual(sel1.source_id, sel2.source_id)
            for s1, s2 in zip(scored1, scored2):
                self.assertEqual(s1.candidate.source_id, s2.candidate.source_id)
                self.assertEqual(s1.final_score, s2.final_score)
                self.assertEqual(s1.card_similarity, s2.card_similarity)
                self.assertEqual(s1.page_similarity, s2.page_similarity)
                self.assertEqual(s1.coverage, s2.coverage)
                self.assertEqual(s1.rerank, s2.rerank)


if __name__ == "__main__":
    unittest.main()
