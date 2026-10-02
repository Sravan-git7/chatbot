#!/usr/bin/env python3
"""Phase 15 unit tests: code-aware candidate injection and hybrid reranking.

Tests:
A. Exact code match causes candidate injection.
B. Candidate pool never exceeds 10.
C. No code token => Phase 13 score is unchanged.
D. Exact code match produces code_match=1.
E. Non-matching candidate produces code_match=0.
F. Generic words do not trigger injection.
G. Unresolved-card penalty remains active.
H. EvidenceGuard behavior remains unchanged.
I. Existing Phase 13 tests still pass.
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
import rag_evidence as EV


class TestPhase15Hybrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Baseline pipeline: top-10, rerank_router=True, code_aware_router=False
        cls.pipe_baseline = RP.build_pipeline(
            generator="extractive",
            config=RP.PipelineConfig(top_k_cards=10, rerank_router=True, code_aware_router=False),
        )
        # Experimental pipeline: top-10, rerank_router=True, code_aware_router=True
        cls.pipe_hybrid = RP.build_pipeline(
            generator="extractive",
            config=RP.PipelineConfig(top_k_cards=10, rerank_router=True, code_aware_router=True),
        )

    def test_a_exact_code_match_causes_candidate_injection(self):
        """A. Query with ELDM (absent from dense top-10) causes M2C-07 to be injected into candidate pool."""
        query = "What does transaction ELDM display?"
        
        # Under baseline, M2C-07 is at dense rank 21, so it is NOT in candidates
        ans_base = self.pipe_baseline.answer(query)
        base_cands = [c["source_id"] for c in ans_base["routing"]["candidates"]]
        self.assertNotIn("M2C-07", base_cands)
        
        # Under code-aware router, M2C-07 is detected and injected
        ans_hybrid = self.pipe_hybrid.answer(query)
        hybrid_cands = [c["source_id"] for c in ans_hybrid["routing"]["candidates"]]
        self.assertIn("M2C-07", hybrid_cands)
        # And M2C-07 wins reranking!
        self.assertEqual(ans_hybrid["routing"]["selected_source_id"], "M2C-07")

    def test_b_candidate_pool_never_exceeds_10(self):
        """B. Injected candidates replace lowest-ranked candidates; pool length is strictly <= 10."""
        queries = [
            "What does transaction ELDM display?",
            "What is the business function ISU_AMI_1 required for?",
            "What is the purpose of transaction EL43?",
            "Where in Customizing is the clearing priority indicator made available?",
        ]
        for q in queries:
            ans = self.pipe_hybrid.answer(q)
            cands = ans["routing"]["candidates"]
            self.assertLessEqual(len(cands), 10)
            self.assertGreater(len(cands), 0)

    def test_c_no_code_token_phase13_score_unchanged(self):
        """C. When query has no code tokens, scoring formula produces identical results to Phase 13 baseline."""
        query = "What happens to interest and charges when the Distribute indicator is set?"
        ans_base = self.pipe_baseline.answer(query)
        ans_hybrid = self.pipe_hybrid.answer(query)

        self.assertEqual(ans_base["routing"]["selected_source_id"], ans_hybrid["routing"]["selected_source_id"])
        base_scores = {c["source_id"]: c["final_score"] for c in ans_base["routing"]["candidates"]}
        hybrid_scores = {c["source_id"]: c["final_score"] for c in ans_hybrid["routing"]["candidates"]}
        
        # Common candidates must have identical scores
        for sid in base_scores:
            if sid in hybrid_scores:
                self.assertAlmostEqual(base_scores[sid], hybrid_scores[sid], places=4)

    def test_d_exact_code_match_produces_code_match_1(self):
        """D. Exact normalized code token in page produces code_match=1.0."""
        query = "What does transaction ELDM display?"
        cand_7 = CardCandidate(
            rank=21, source_id="M2C-07", title="Monitoring Meter Reading Results",
            category="Device Management", source_url="https://help.sap.com", source_status="verified",
            source_url_status="ok", has_source_correction=False, citation="", distance=0.7118, distance_metric="cosine"
        )
        sc = PR13.score_candidate(
            query, cand_7, self.pipe_hybrid.cards["M2C-07"], self.pipe_hybrid.retriever,
            self.pipe_hybrid.ctx, self.pipe_hybrid.corpus, query_code_tokens={"ELDM"}, code_aware=True
        )
        self.assertEqual(sc.code_match, 1.0)

    def test_e_non_matching_candidate_produces_code_match_0(self):
        """E. Candidate without code token in page produces code_match=0.0."""
        query = "What does transaction ELDM display?"
        cand_25 = CardCandidate(
            rank=1, source_id="M2C-25", title="Displaying and Changing Installment Plans",
            category="Contract Accounts", source_url="https://help.sap.com", source_status="verified",
            source_url_status="ok", has_source_correction=False, citation="", distance=0.6045, distance_metric="cosine"
        )
        sc = PR13.score_candidate(
            query, cand_25, self.pipe_hybrid.cards["M2C-25"], self.pipe_hybrid.retriever,
            self.pipe_hybrid.ctx, self.pipe_hybrid.corpus, query_code_tokens={"ELDM"}, code_aware=True
        )
        self.assertEqual(sc.code_match, 0.0)

    def test_f_generic_words_do_not_trigger_injection(self):
        """F. Generic words (transaction, billing, customer, process) do not trigger candidate injection."""
        query = "How is a customer billing process handled in the standard system?"
        ans_base = self.pipe_baseline.answer(query)
        ans_hybrid = self.pipe_hybrid.answer(query)
        
        # Dense candidate pool should not have arbitrary replacements
        base_sids = [c["source_id"] for c in ans_base["routing"]["candidates"]]
        hybrid_sids = [c["source_id"] for c in ans_hybrid["routing"]["candidates"]]
        self.assertEqual(base_sids, hybrid_sids)

    def test_g_unresolved_card_penalty_remains_active(self):
        """G. Unresolved card (M2C-18) continues to receive unresolved penalty."""
        cand_18 = CardCandidate(
            rank=1, source_id="M2C-18", title="Contract Account Business Object",
            category="Contract Accounts", source_url="https://help.sap.com", source_status="needs_review",
            source_url_status="ok", has_source_correction=False, citation="", distance=0.40, distance_metric="cosine"
        )
        sc = PR13.score_candidate(
            "What is a contract account?", cand_18, self.pipe_hybrid.cards["M2C-18"],
            self.pipe_hybrid.retriever, self.pipe_hybrid.ctx, self.pipe_hybrid.corpus, code_aware=True
        )
        # Score must reflect the 0.20 unresolved penalty
        card_sim = round(1.0 - cand_18.distance, 4)
        expected_score = round(PR13.W_CARD * card_sim - PR13.UNRESOLVED_PENALTY, 4)
        self.assertEqual(sc.final_score, expected_score)

    def test_h_evidence_guard_behavior_remains_unchanged(self):
        """H. EvidenceGuard thresholds and abstention rules function identically with hybrid routing."""
        # Wrap hybrid pipeline in EvidenceGuard, exactly like production / evaluation
        guarded_pipe = EV.build_evidence_pipeline(self.pipe_hybrid, tau=EV.SHIPPED_TAU, widen=False, generator="extractive")
        query = "What is the maximum number of meter reading orders that transaction EL31 can display?"
        ans = guarded_pipe.answer(query)
        self.assertEqual(ans["status"], "insufficient_context")
        self.assertIsNone(ans["answer"])


if __name__ == "__main__":
    unittest.main()
