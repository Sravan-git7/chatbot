#!/usr/bin/env python3
"""Phase 19A - Regression tests for single query embedding + winning-page retrieval reuse
and production promotion of E1a-v2 (`tests/test_phase19a_latency.py`).

Covers all required Phase 19A invariants (Steps 4, 5, 6, 9, 12):
  1. single embedding per answer() (retriever.embed == 1, backend._embed == 0)
  2. q_emb propagation to route_to_page (and _inject_code_aware_candidates)
  3. reranker receives the exact same q_emb
  4. request-local cache eliminates redundant winning-page Chroma retrieval
  5. correct k handling (never mistakes k=3 cache entry for k=5; reuses only when k=5 is present)
  6. final evidence equivalence (page, guide, chunk IDs, order, content, metadata)
  7. candidate ranking & score equivalence (top_k=5 fetch + [:3] scoring slice)
  8. context equivalence (byte-for-byte identical ContextBlock & generator prompt input)
  9. citation & grounding equivalence
 10. concurrent request isolation (no cross-request state or embedding leakage)
 11. empty / no-result behavior + no accidental global cache
 12. unsupported behavior + production config & structural operation-count guard
"""
from __future__ import annotations

import concurrent.futures
import statistics
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import phase13_reranker as PR13  # noqa: E402
import rag_context as RC  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_pipeline as RP  # noqa: E402
import rag_service as S  # noqa: E402


def _has_real_stores() -> bool:
    return (
        (ROOT / "data" / "vector_store" / "chroma.sqlite3").is_file()
        and (ROOT / "data" / "vector_store" / "page_collection" / "chroma.sqlite3").is_file()
    )


@unittest.skipUnless(_has_real_stores(), "requires built card and page vector stores")
class TestPhase19ALatency(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = S.production_pipeline_config()
        cls.pipe = RP.build_pipeline(generator="extractive", config=cls.cfg)

    # 1. single embedding per answer()
    def test_01_single_embedding_per_answer(self) -> None:
        test_queries = [
            "What is the purpose of transaction EL43?",                     # triggers code_aware candidate logic
            "In which step do I enter an amount in the Installment Amount field?",  # triggers E1a-v2 phrase reranker
            "What does the Contract Accounts component let me create?",     # standard dense + rerank query
        ]
        orig_ret_embed = self.pipe.retriever.embed
        orig_back_embed = self.pipe.backend._embed

        for q in test_queries:
            ret_calls = []
            back_calls = []

            def spy_ret_embed(texts):
                ret_calls.append(list(texts))
                return orig_ret_embed(texts)

            def spy_back_embed(text):
                back_calls.append(text)
                return orig_back_embed(text)

            self.pipe.retriever.embed = spy_ret_embed
            self.pipe.backend._embed = spy_back_embed
            try:
                ans = self.pipe.answer(q, debug=True)
                self.assertEqual(ans["status"], "answered")
                self.assertEqual(len(ret_calls), 1, f"Expected 1 retriever.embed call for {q!r}, got {len(ret_calls)}")
                self.assertEqual(len(back_calls), 0, f"Expected 0 backend._embed calls for {q!r}, got {len(back_calls)}")
            finally:
                self.pipe.retriever.embed = orig_ret_embed
                self.pipe.backend._embed = orig_back_embed

    # 2. q_emb propagation to route_to_page
    def test_02_q_emb_propagation_to_route_to_page(self) -> None:
        orig_route_to_page = RP.route_to_page
        orig_ret_embed = self.pipe.retriever.embed
        captured: Dict[str, Any] = {}

        def spy_embed(texts):
            res = orig_ret_embed(texts)
            captured["emitted_emb"] = res
            return res

        def spy_route_to_page(*args, **kwargs):
            captured["route_query_embedding"] = kwargs.get("query_embedding")
            return orig_route_to_page(*args, **kwargs)

        self.pipe.retriever.embed = spy_embed
        RP.route_to_page = spy_route_to_page
        try:
            self.pipe.answer("What is the purpose of transaction EL43?", debug=True)
            self.assertIn("emitted_emb", captured)
            self.assertIsNotNone(captured.get("route_query_embedding"))
            self.assertEqual(captured["route_query_embedding"], captured["emitted_emb"])
        finally:
            self.pipe.retriever.embed = orig_ret_embed
            RP.route_to_page = orig_route_to_page

    # 3. reranker receives same q_emb
    def test_03_reranker_receives_same_q_emb(self) -> None:
        orig_route_to_page = RP.route_to_page
        orig_rerank = PR13.rerank_candidates
        captured: Dict[str, Any] = {}

        def spy_route(*args, **kwargs):
            captured["route_emb"] = kwargs.get("query_embedding")
            return orig_route_to_page(*args, **kwargs)

        def spy_rerank(*args, **kwargs):
            captured["rerank_emb"] = kwargs.get("query_embedding")
            return orig_rerank(*args, **kwargs)

        RP.route_to_page = spy_route
        PR13.rerank_candidates = spy_rerank
        try:
            self.pipe.answer("What does transaction ELDM display?", debug=True)
            self.assertIsNotNone(captured.get("route_emb"))
            self.assertIs(captured["rerank_emb"], captured["route_emb"])
        finally:
            RP.route_to_page = orig_route_to_page
            PR13.rerank_candidates = orig_rerank

    # 4. request-local cache eliminates redundant winning-page retrieval
    def test_04_request_local_cache_eliminates_winning_page_duplicate(self) -> None:
        orig_rip = self.pipe.retriever.retrieve_in_page
        calls_by_page: Dict[tuple, int] = {}

        def spy_rip(query, guide_id, page_id, top_k=5, query_embedding=None):
            key = (guide_id, page_id)
            calls_by_page[key] = calls_by_page.get(key, 0) + 1
            return orig_rip(query, guide_id, page_id, top_k=top_k, query_embedding=query_embedding)

        self.pipe.retriever.retrieve_in_page = spy_rip
        try:
            ans = self.pipe.answer("What is the purpose of transaction EL43?", debug=True)
            self.assertEqual(ans["status"], "answered")
            win_g = ans["topic"]["effective_guide_id"]
            win_p = ans["topic"]["effective_page_id"]
            self.assertEqual(calls_by_page.get((win_g, win_p)), 1)
            for page_key, count in calls_by_page.items():
                self.assertEqual(count, 1, f"Page {page_key} was queried {count} times in a single answer() call")
        finally:
            self.pipe.retriever.retrieve_in_page = orig_rip

    # 5. correct k handling (never pretends top_k=3 == top_k=5)
    def test_05_correct_k_handling_in_request_cache(self) -> None:
        # Verify that when rerank_candidates is called with k_chunks=5, it caches (guide_id, page_id, 5).
        # And if a caller/stub only populates (guide_id, page_id, 3) when k_chunks=5 is required,
        # Step 5 does NOT reuse the k=3 entry and instead calls retrieve_in_page(top_k=5).
        orig_rerank = PR13.rerank_candidates
        orig_rip = self.pipe.retriever.retrieve_in_page
        step5_top_ks: List[int] = []
        in_rerank = [False]

        def stub_rerank_k3_only(*args, **kwargs):
            in_rerank[0] = True
            try:
                # Force k_chunks=3 during reranking even though pipeline wants k_chunks=5
                kwargs["k_chunks"] = 3
                return orig_rerank(*args, **kwargs)
            finally:
                in_rerank[0] = False

        def spy_rip(query, guide_id, page_id, top_k=5, query_embedding=None):
            if not in_rerank[0]:
                step5_top_ks.append(top_k)
            return orig_rip(query, guide_id, page_id, top_k=top_k, query_embedding=query_embedding)

        PR13.rerank_candidates = stub_rerank_k3_only
        self.pipe.retriever.retrieve_in_page = spy_rip
        try:
            ans = self.pipe.answer("What is the purpose of transaction EL43?", debug=True)
            self.assertEqual(ans["status"], "answered")
            # Because rerank only cached k=3 while pipeline required k_chunks=5, Step 5 must fetch top_k=5
            self.assertEqual(step5_top_ks, [5])
        finally:
            PR13.rerank_candidates = orig_rerank
            self.pipe.retriever.retrieve_in_page = orig_rip

    # 6. final evidence equivalence (page, guide, chunk IDs, order, content, metadata)
    def test_06_final_evidence_equivalence(self) -> None:
        sample_queries = [
            "What is the purpose of transaction EL43?",
            "In which step do I enter an amount in the Installment Amount field?",
            "Which function releases bills that were outsorted?",
            "What does the Contract Accounts component let me create?",
            "Why is the billing period cut into pieces when a rate changes?",
        ]
        for q in sample_queries:
            ans = self.pipe.answer(q, debug=True)
            win_g = ans["topic"]["effective_guide_id"]
            win_p = ans["topic"]["effective_page_id"]
            q_emb = self.pipe.retriever.embed([q.strip()])
            direct_hits = self.pipe.retriever.retrieve_in_page(
                q, win_g, win_p, top_k=self.cfg.k_chunks, query_embedding=q_emb
            )
            reused_hits_dbg = ans["debug"]["retrieved"]
            self.assertEqual(
                reused_hits_dbg,
                [h.to_dict(with_text=False) for h in direct_hits],
                f"Winning-page evidence mismatch on {q!r}",
            )

    # 7. candidate ranking & score equivalence (k_chunks=5 vs k_chunks=3)
    def test_07_candidate_ranking_and_score_equivalence(self) -> None:
        q = "In which step do I enter an amount in the Installment Amount field?"
        q_emb = self.pipe.retriever.embed([q.strip()])
        outcome = RP.route_to_page(
            q, self.pipe.backend, self.pipe.ctx.page_index, top_k=10, query_embedding=q_emb
        )
        cands = self.pipe._inject_code_aware_candidates(q, list(outcome.candidates), query_embedding=q_emb)

        sel_3, scored_3 = PR13.rerank_candidates(
            q, cands, self.pipe.cards, self.pipe.retriever, self.pipe.ctx, self.pipe.corpus,
            top_k_evaluate=10, query_embedding=q_emb, code_aware=True,
            phrase_reranker=True, phrase_min_corroboration=2, k_chunks=3,
        )
        sel_5, scored_5 = PR13.rerank_candidates(
            q, cands, self.pipe.cards, self.pipe.retriever, self.pipe.ctx, self.pipe.corpus,
            top_k_evaluate=10, query_embedding=q_emb, code_aware=True,
            phrase_reranker=True, phrase_min_corroboration=2, k_chunks=5,
        )
        self.assertEqual(sel_3.source_id, sel_5.source_id)
        self.assertEqual([s.to_dict() for s in scored_3], [s.to_dict() for s in scored_5])

    # 8. context equivalence (byte-for-byte identical ContextBlock & generator input)
    def test_08_context_equivalence(self) -> None:
        sample_queries = [
            "What is the purpose of transaction EL43?",
            "In which step do I enter an amount in the Installment Amount field?",
            "What happens to interest and charges when the Distribute indicator is set?",
        ]
        for q in sample_queries:
            ans = self.pipe.answer(q, debug=True)
            win_g = ans["topic"]["effective_guide_id"]
            win_p = ans["topic"]["effective_page_id"]
            q_emb = self.pipe.retriever.embed([q.strip()])
            direct_hits = self.pipe.retriever.retrieve_in_page(
                q, win_g, win_p, top_k=self.cfg.k_chunks, query_embedding=q_emb
            )
            direct_ctx = RC.build_context(
                direct_hits,
                self.pipe.count_tokens,
                self.cfg.context_budget_tokens,
                self.cfg.max_context_chunks,
            )
            self.assertEqual(ans["debug"]["context"], direct_ctx.to_dict(with_text=True))

    # 9. citation & grounding equivalence
    def test_09_citation_and_grounding_equivalence(self) -> None:
        q = "What is the transaction code for creating an installment plan?"
        ans = self.pipe.answer(q, debug=True)
        self.assertEqual(ans["status"], "answered")
        self.assertEqual(ans["routing"]["selected_source_id"], "M2C-24")
        self.assertTrue(len(ans["citations"]["answer_sources"]) >= 1)
        for src in ans["citations"]["answer_sources"]:
            self.assertEqual(src["join"]["card_source_id"], "M2C-24")
            self.assertTrue(src["url"].startswith("https://help.sap.com/docs/"))
            self.assertIn("chunk_id", src)
            self.assertIn("content_hash", src)

        # Grounding rejection check
        class HallucinatingGenerator:
            def generate(self, question, context):
                return RG.GenerationResult(
                    text="Quantum flux capacitors require 500 gigawatts [S1].",
                    refused=False,
                    generator="fake_llm",
                    raw_text="Quantum flux capacitors require 500 gigawatts [S1].",
                    prompt="test",
                )

        bad_pipe = RP.RagPipeline(
            self.pipe.backend, self.pipe.retriever, self.pipe.ctx, self.pipe.corpus,
            HallucinatingGenerator(), self.pipe.count_tokens,
            cards=list(self.pipe.cards.values()), config=self.cfg,
        )
        bad_ans = bad_pipe.answer("What is the purpose of transaction EL43?", debug=True)
        self.assertEqual(bad_ans["status"], "insufficient_context")
        self.assertEqual(bad_ans["reason_code"], "GROUNDING_VERIFICATION_FAILED")
        self.assertIsNone(bad_ans["answer"])
        self.assertEqual(bad_ans["citations"]["answer_sources"], [])

    # 10. concurrent request isolation
    def test_10_concurrent_request_isolation(self) -> None:
        distinct_queries = [
            ("What is the purpose of transaction EL43?", "M2C-07"),
            ("What is the transaction code for creating an installment plan?", "M2C-24"),
            ("What does the Contract Accounts component let me create?", "M2C-17"),
            ("What is generated when invoicing with bill creation is run?", "M2C-14"),
            ("What do device, device category and device number correspond to in the standard system?", "M2C-05"),
            ("What is the weather in Hyderabad?", None),
        ]
        expected = {q: self.pipe.answer(q, debug=True) for q, _ in distinct_queries}

        def run_one(item):
            q, _ = item
            return q, self.pipe.answer(q, debug=True)

        work = distinct_queries * 3
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(run_one, work))

        for q, res in results:
            exp = expected[q]
            self.assertEqual(res["status"], exp["status"])
            self.assertEqual(res["routing"]["selected_source_id"], exp["routing"]["selected_source_id"])
            self.assertEqual(res["answer"], exp["answer"])
            self.assertEqual(res["citations"], exp["citations"])

    # 11. empty/no-result behavior + no accidental global cache
    def test_11_empty_query_and_no_global_cache(self) -> None:
        r_empty = self.pipe.answer("")
        self.assertEqual(r_empty["status"], "no_relevant_page")
        self.assertIsNone(r_empty["answer"])

        orig_ret_embed = self.pipe.retriever.embed
        call_count = 0

        def spy_embed(texts):
            nonlocal call_count
            call_count += 1
            return orig_ret_embed(texts)

        self.pipe.retriever.embed = spy_embed
        try:
            q = "What is the purpose of transaction EL43?"
            self.pipe.answer(q)
            self.pipe.answer(q)
            self.assertEqual(call_count, 2)
        finally:
            self.pipe.retriever.embed = orig_ret_embed

    # 12. unsupported behavior + production config & structural performance guard
    def test_12_unsupported_behavior_and_production_config_guard(self) -> None:
        # Out of domain
        r_ood = self.pipe.answer("What is the weather in Hyderabad?")
        self.assertEqual(r_ood["status"], "out_of_domain")
        self.assertIsNone(r_ood["answer"])
        self.assertEqual(r_ood["citations"]["answer_sources"], [])

        # Unresolved identity (M2C-18 conflict)
        r_unres = self.pipe.answer("What is the contract account business object?", oracle_source_id="M2C-18")
        self.assertEqual(r_unres["status"], "unresolved_identity")
        self.assertIsNone(r_unres["answer"])
        self.assertEqual(r_unres["citations"]["answer_sources"], [])

        # Production config verification
        cfg = S.production_pipeline_config()
        self.assertEqual(cfg.top_k_cards, 10)
        self.assertEqual(cfg.k_chunks, 5)
        self.assertEqual(cfg.context_budget_tokens, 700)
        self.assertEqual(cfg.max_context_chunks, 4)
        self.assertTrue(cfg.rerank_router)
        self.assertTrue(cfg.code_aware_router)
        self.assertTrue(cfg.in_page_grounding)
        self.assertTrue(cfg.citation_normalization)
        self.assertTrue(cfg.relaxed_context_gate)
        self.assertFalse(cfg.evidence_frame_normalization)
        self.assertTrue(cfg.phrase_reranker)
        self.assertEqual(cfg.phrase_min_corroboration, 2)
        self.assertFalse(cfg.full_page_coverage)
        self.assertFalse(cfg.citation_repair)

        # Structural operation-count regression guard
        batch = [
            "What is the purpose of transaction EL43?",
            "In which step do I enter an amount in the Installment Amount field?",
            "What does the Contract Accounts component let me create?",
        ]
        orig_ret_embed = self.pipe.retriever.embed
        orig_back_embed = self.pipe.backend._embed
        orig_rip = self.pipe.retriever.retrieve_in_page
        orig_rerank = PR13.rerank_candidates
        in_rerank = [False]

        def spy_rerank(*a, **kw):
            in_rerank[0] = True
            try:
                return orig_rerank(*a, **kw)
            finally:
                in_rerank[0] = False

        PR13.rerank_candidates = spy_rerank
        try:
            for q in batch:
                embed_calls = [0]
                step5_rip_calls = [0]

                def spy_ret_embed(texts):
                    embed_calls[0] += 1
                    return orig_ret_embed(texts)

                def spy_back_embed(text):
                    embed_calls[0] += 1
                    return orig_back_embed(text)

                def spy_rip(query, guide_id, page_id, top_k=5, query_embedding=None):
                    if not in_rerank[0]:
                        step5_rip_calls[0] += 1
                    return orig_rip(query, guide_id, page_id, top_k=top_k, query_embedding=query_embedding)

                self.pipe.retriever.embed = spy_ret_embed
                self.pipe.backend._embed = spy_back_embed
                self.pipe.retriever.retrieve_in_page = spy_rip

                ans = self.pipe.answer(q, debug=True)
                self.assertEqual(embed_calls[0], 1)
                self.assertEqual(step5_rip_calls[0], 0)
                self.assertLess(ans["timings_ms"]["retrieve_ms"], 1.0)
        finally:
            self.pipe.retriever.embed = orig_ret_embed
            self.pipe.backend._embed = orig_back_embed
            self.pipe.retriever.retrieve_in_page = orig_rip
            PR13.rerank_candidates = orig_rerank


if __name__ == "__main__":
    unittest.main()
