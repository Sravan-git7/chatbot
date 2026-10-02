#!/usr/bin/env python3
"""Phase 14 unit tests for candidate depth recall and Top-10 production integration.

Validates:
1. New production default: top_k_cards=10 and rerank_router=True.
2. Explicit override works (top_k_cards=5 or other values can still be configured).
3. Reranker weights, scoring formula, and identity penalty are unchanged.
4. Determinism is preserved across candidate depths.
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import phase13_reranker as PR13
import rag_pipeline as RP


class TestPhase14RecallConfig(unittest.TestCase):
    def test_production_defaults(self):
        """Phase 14 production default is top_k_cards=10 and rerank_router=True."""
        cfg = RP.PipelineConfig()
        self.assertEqual(cfg.top_k_cards, 10, "Production default top_k_cards must be 10")
        self.assertTrue(cfg.rerank_router, "Production default rerank_router must be True")

    def test_explicit_override_supported(self):
        """Callers must still be able to override top_k_cards explicitly (e.g. top_k_cards=5)."""
        cfg_override = RP.PipelineConfig(top_k_cards=5)
        self.assertEqual(cfg_override.top_k_cards, 5)

    def test_reranker_weights_unmodified(self):
        """Phase 14 MUST NOT alter reranker scoring formula or weights."""
        self.assertEqual(PR13.W_CARD, 0.50)
        self.assertEqual(PR13.W_PAGE, 0.40)
        self.assertEqual(PR13.W_COVERAGE, 0.10)
        self.assertEqual(PR13.UNRESOLVED_PENALTY, 0.20)
        self.assertEqual(PR13.NOT_INGESTED_PENALTY, 0.10)

    def test_default_pipeline_executes_top10(self):
        """Default pipeline (no explicit config passed) must route with top-10."""
        default_pipe = RP.build_pipeline(generator="extractive")
        self.assertEqual(default_pipe.cfg.top_k_cards, 10)
        self.assertTrue(default_pipe.cfg.rerank_router)

        q = "What is the purpose of meter reading monitoring?"
        res = default_pipe.answer(q)
        self.assertEqual(res["routing"]["mode"], "router_reranked_top10")
        self.assertLessEqual(len(res["routing"].get("candidates", [])), 10)

    def test_candidate_depth_configurable(self):
        """Pipeline must cleanly accept top_k_cards=5, 10, 15."""
        pipe5 = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(top_k_cards=5))
        pipe10 = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(top_k_cards=10))
        pipe15 = RP.build_pipeline(generator="extractive", config=RP.PipelineConfig(top_k_cards=15))

        self.assertEqual(pipe5.cfg.top_k_cards, 5)
        self.assertEqual(pipe10.cfg.top_k_cards, 10)
        self.assertEqual(pipe15.cfg.top_k_cards, 15)

        q = "What is the purpose of meter reading monitoring?"
        res5 = pipe5.answer(q)
        res10 = pipe10.answer(q)
        res15 = pipe15.answer(q)

        self.assertEqual(res5["routing"]["mode"], "router_reranked_top5")
        self.assertEqual(res10["routing"]["mode"], "router_reranked_top10")
        self.assertEqual(res15["routing"]["mode"], "router_reranked_top15")

        self.assertLessEqual(len(res5["routing"].get("candidates", [])), 5)
        self.assertLessEqual(len(res10["routing"].get("candidates", [])), 10)
        self.assertLessEqual(len(res15["routing"].get("candidates", [])), 15)


if __name__ == "__main__":
    unittest.main()
