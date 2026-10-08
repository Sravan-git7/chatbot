"""Tests for Phase 3 Answer-Completeness Module:
- Feature flag controls: SURA_INTENT_AWARE, SURA_SECTION_SELECTION, SURA_ADDITIONAL_EVIDENCE
- Deterministic intent classification
- Retrieval-only query normalization
- Section tagging and complementary evidence selection
- Additional verified evidence extraction
- Verification that all flags default to OFF.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts import rag_completeness as RC
from scripts.rag_evidence import analyze_question, terms2, unit_score, Unit


class Phase3CompletenessTests(unittest.TestCase):
    def test_feature_flags_default_to_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(RC.is_intent_aware_enabled())
            self.assertFalse(RC.is_section_selection_enabled())
            self.assertFalse(RC.is_additional_evidence_enabled())

    def test_feature_flags_enabled_via_env(self):
        env = {
            "SURA_INTENT_AWARE": "1",
            "SURA_SECTION_SELECTION": "true",
            "SURA_ADDITIONAL_EVIDENCE": "yes",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(RC.is_intent_aware_enabled())
            self.assertTrue(RC.is_section_selection_enabled())
            self.assertTrue(RC.is_additional_evidence_enabled())

    def test_deterministic_intent_classification(self):
        # 1. Procedural query
        res1 = RC.classify_intent("How do I create an installment plan?")
        self.assertEqual(res1["primary_intent"], "procedural")
        self.assertTrue(res1["is_procedural"])

        # 2. Definition query
        res2 = RC.classify_intent("What is a contract account?")
        self.assertEqual(res2["primary_intent"], "definition")
        self.assertTrue(res2["is_definition"])

        # 3. Relationship query
        res3 = RC.classify_intent("How does a contract account relate to a business partner?")
        self.assertEqual(res3["primary_intent"], "relationship")
        self.assertTrue(res3["is_relationship"])

        # 4. Monitoring query
        res4 = RC.classify_intent("How is periodic billing monitored and tracked?")
        self.assertIn("status_monitoring", res4["intents"])

    def test_retrieval_only_query_normalization(self):
        raw = "Can you please explain how to create an installment plan?"
        # Flag OFF -> returns unmodified
        with patch.dict(os.environ, {"SURA_INTENT_AWARE": "0"}, clear=True):
            self.assertEqual(RC.normalize_retrieval_query(raw), raw)

        # Flag ON -> removes conversational fluff prefix
        with patch.dict(os.environ, {"SURA_INTENT_AWARE": "1"}, clear=True):
            normalized = RC.normalize_retrieval_query(raw)
            self.assertEqual(normalized, "how to create an installment plan?")

    def test_section_tagging_and_signature(self):
        u1 = Unit("S1", "chunk-01", 0, 1, "Installment plan text.", frozenset(), frozenset(), heading_labels=("Installment Plan", "Overview"))
        sig1 = RC.get_unit_section_signature(u1)
        self.assertEqual(sig1, "installment plan > overview")

        u2 = Unit("S2", "chunk-02", 0, 2, "Second text.", frozenset(), frozenset(), heading_labels=())
        sig2 = RC.get_unit_section_signature(u2)
        self.assertEqual(sig2, "chunk-02")

    def test_complementary_section_selection(self):
        # Create 3 units: u1 and u2 from same section, u3 from different section with valid score
        u1 = Unit("S1", "c1", 0, 1, "Sent 1", frozenset(), frozenset(), heading_labels=("Section A",))
        u2 = Unit("S1", "c1", 0, 2, "Sent 2", frozenset(), frozenset(), heading_labels=("Section A",))
        u3 = Unit("S2", "c2", 0, 3, "Sent 3", frozenset(), frozenset(), heading_labels=("Section B",))

        scored = [(0.85, u1), (0.80, u2), (0.75, u3)]

        # Flag OFF: selects top 2 directly (u1 and u2)
        with patch.dict(os.environ, {"SURA_SECTION_SELECTION": "0"}, clear=True):
            chosen_off = RC.select_complementary_units(scored, tau=0.5, keep_ratio=0.6, max_sentences=2)
            self.assertEqual([u.text for u in chosen_off], ["Sent 1", "Sent 2"])

        # Flag ON: selects u1 from Section A, then u3 from Section B to maximize section diversity
        with patch.dict(os.environ, {"SURA_SECTION_SELECTION": "1"}, clear=True):
            chosen_on = RC.select_complementary_units(scored, tau=0.5, keep_ratio=0.6, max_sentences=2)
            self.assertEqual([u.text for u in chosen_on], ["Sent 1", "Sent 3"])

    def test_additional_evidence_extraction(self):
        u1 = Unit("S1", "c1", 0, 1, "Primary sentence.", frozenset(), frozenset(), heading_labels=("Overview",))
        u2 = Unit("S1", "c1", 0, 2, "Secondary sentence providing extra fact.", frozenset(), frozenset(), heading_labels=("Details",))
        u3 = Unit("S2", "c2", 0, 3, "Uncited third sentence.", frozenset(), frozenset(), heading_labels=("Other",))

        needs = analyze_question("How do I create an installment plan?")
        weights = {"plan": 1.0}

        def mock_score(u, n, w):
            if u.text == "Secondary sentence providing extra fact.":
                return 0.65
            return 0.20

        # Flag OFF -> empty
        with patch.dict(os.environ, {"SURA_ADDITIONAL_EVIDENCE": "0"}, clear=True):
            res_off = RC.extract_additional_evidence([u1, u2, u3], [u1], needs, weights, mock_score)
            self.assertEqual(res_off, [])

        # Flag ON -> extracts u2 from cited marker S1
        with patch.dict(os.environ, {"SURA_ADDITIONAL_EVIDENCE": "1"}, clear=True):
            res_on = RC.extract_additional_evidence([u1, u2, u3], [u1], needs, weights, mock_score, min_score=0.5)
            self.assertEqual(len(res_on), 1)
            self.assertEqual(res_on[0]["sentence"], "Secondary sentence providing extra fact.")
            self.assertEqual(res_on[0]["marker"], "S1")


if __name__ == "__main__":
    unittest.main()
