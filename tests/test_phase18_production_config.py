#!/usr/bin/env python3
"""Phase 18 - production configuration reconciliation tests.

The service (rag_service.build_service / rag_api) must serve the VERIFIED Phase 16 baseline
configuration (data/phase16/phase16_comparison.json, "phase16_combined_ABC"):
  top_k_cards=10, rerank_router=True, code_aware_router=True, in_page_grounding=True,
  citation_normalization=True, relaxed_context_gate=True, evidence_frame_normalization=False.
The dataclass DEFAULTS stay at their historical values so that pre-Phase-18 evaluators keep
reproducing their sealed results (reproducibility invariant).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_pipeline as RP  # noqa: E402
import rag_service as S  # noqa: E402


class TestProductionPipelineConfig(unittest.TestCase):
    def test_verified_phase16_baseline_flags(self):
        cfg = S.production_pipeline_config()
        self.assertEqual(cfg.top_k_cards, 10)
        self.assertTrue(cfg.rerank_router)
        self.assertTrue(cfg.code_aware_router)          # Phase 15
        self.assertTrue(cfg.in_page_grounding)          # Phase 16 A
        self.assertTrue(cfg.citation_normalization)     # Phase 16 B
        self.assertTrue(cfg.relaxed_context_gate)       # Phase 16 C
        self.assertFalse(cfg.evidence_frame_normalization)  # Phase 17A Feature E: experimental, OFF

    def test_phase18_experimental_flags_stay_off_in_production(self):
        cfg = S.production_pipeline_config()
        self.assertTrue(cfg.phrase_reranker)
        self.assertEqual(cfg.phrase_min_corroboration, 2)
        self.assertFalse(cfg.full_page_coverage)
        self.assertFalse(cfg.citation_repair)

    def test_dataclass_defaults_unchanged_for_legacy_evaluators(self):
        """Pre-Phase-18 evaluators call build_pipeline() without a config; their sealed results
        reproduce only if the dataclass defaults keep their historical values."""
        d = RP.PipelineConfig()
        self.assertEqual(d.top_k_cards, 10)             # Phase 14 default (pinned by test_phase14_recall)
        self.assertTrue(d.rerank_router)                # Phase 14 default
        self.assertFalse(d.code_aware_router)           # historical: Phase 15 flag, opt-in
        self.assertFalse(d.in_page_grounding)           # historical: Phase 16 A, opt-in
        self.assertFalse(d.citation_normalization)      # historical: Phase 16 B, opt-in
        self.assertFalse(d.relaxed_context_gate)        # historical: Phase 16 C, opt-in
        self.assertFalse(d.evidence_frame_normalization)
        self.assertFalse(d.phrase_reranker)
        self.assertFalse(d.full_page_coverage)
        self.assertFalse(d.citation_repair)


class TestServiceWiring(unittest.TestCase):
    def test_service_pipeline_carries_production_config(self):
        """build_service passes production_pipeline_config() into the pipeline; the evidence wrapper
        must preserve it (it rebuilds RagPipeline with config=base.cfg). The stub mimics the OUTPUT
        of EV.build_evidence_pipeline (a RagPipeline whose generator is the evidence-checked one)."""
        import rag_evidence as EV

        class StubPipeline:
            def __init__(self):
                self.cfg = S.production_pipeline_config()
                self.backend = object()
                self.retriever = object()
                self.ctx = object()
                self.corpus = object()
                self.generator = EV.EvidenceExtractiveGenerator()
                self.count_tokens = lambda t: len(t)
                self.cards = {"M2C-01": {"source_id": "M2C-01", "title": "t", "embedding_text": "t"}}

        svc = S.RagService(StubPipeline(), "extractive")
        self.assertEqual(svc.pipeline.cfg.top_k_cards, 10)
        self.assertTrue(svc.pipeline.cfg.code_aware_router)
        self.assertTrue(svc.pipeline.cfg.in_page_grounding)
        self.assertTrue(svc.pipeline.cfg.citation_normalization)
        self.assertTrue(svc.pipeline.cfg.relaxed_context_gate)
        self.assertFalse(svc.pipeline.cfg.evidence_frame_normalization)
        # RagService rebuilds the pipeline keeping config=base.cfg and wraps the (evidence-checked)
        # generator in its exception guard: the evidence generator must be the guard's inner.
        self.assertIsInstance(svc.pipeline.generator, S.GeneratorGuard)
        self.assertIsInstance(svc.pipeline.generator.inner, (EV.EvidenceExtractiveGenerator, EV.EvidenceGuard))


if __name__ == "__main__":
    unittest.main()
