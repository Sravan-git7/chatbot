#!/usr/bin/env python3
"""Unit tests for Phase 3 Offline LLM Benchmark Harness."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval" / "phase3"))

import adapters
import metrics
import runner


class Phase3DatasetTests(unittest.TestCase):
    """Validate dataset structure, category counts, and field schema."""

    def setUp(self) -> None:
        self.dataset_path = ROOT / "eval" / "phase3" / "dataset.json"
        self.assertTrue(self.dataset_path.is_file(), "dataset.json must exist")
        self.data = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        self.cases = self.data["cases"]

    def test_total_case_count_is_70(self):
        self.assertEqual(len(self.cases), 70)
        self.assertEqual(self.data["total_cases"], 70)

    def test_category_distribution(self):
        from collections import Counter
        counts = Counter(c["category"] for c in self.cases)
        self.assertEqual(counts["factual_definition"], 10)
        self.assertEqual(counts["enumeration"], 6)
        self.assertEqual(counts["procedural_documented"], 8)
        self.assertEqual(counts["procedural_lacks_steps"], 6)
        self.assertEqual(counts["multi_step_or_multi_doc"], 8)
        self.assertEqual(counts["followup_and_transition"], 12)
        self.assertEqual(counts["ambiguous"], 6)
        self.assertEqual(counts["unsupported_or_out_of_scope"], 6)
        self.assertEqual(counts["unavailable_documentation"], 2)
        self.assertEqual(counts["adversarial_false_premise"], 6)

    def test_case_schema(self):
        required_fields = {
            "case_id", "question", "category", "conversation_context",
            "expected_behavior", "expected_source_id", "gold_evidence_spans",
            "key_facts", "prohibited_claims", "call_llm_proposed_policy"
        }
        valid_behaviors = {"answer", "partial_answer", "clarify", "abstain", "unavailable"}
        case_ids = set()

        for c in self.cases:
            self.assertTrue(required_fields.issubset(c.keys()), f"Missing fields in {c.get('case_id')}")
            self.assertIn(c["expected_behavior"], valid_behaviors)
            self.assertTrue(c["question"].strip(), "Question must not be empty")
            self.assertNotIn(c["case_id"], case_ids, f"Duplicate case_id {c['case_id']}")
            case_ids.add(c["case_id"])


class Phase3EvidenceCacheTests(unittest.TestCase):
    """Validate cached evidence snapshots."""

    def setUp(self) -> None:
        self.cache_path = ROOT / "eval" / "phase3" / "evidence_cache.json"
        self.assertTrue(self.cache_path.is_file(), "evidence_cache.json must exist")
        self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.snapshots = self.cache["snapshots"]

    def test_snapshot_coverage(self):
        self.assertEqual(len(self.snapshots), 70)
        for i in range(1, 71):
            cid = f"CASE-{i:03d}"
            self.assertIn(cid, self.snapshots)
            snap = self.snapshots[cid]
            self.assertEqual(snap["case_id"], cid)
            self.assertIn("retrieval_ms", snap)
            self.assertIn("context_items", snap)


class Phase3AdapterTests(unittest.TestCase):
    """Validate generator adapter behaviors and test fixture labelling."""

    def setUp(self) -> None:
        self.sample_items = [
            {
                "marker": "S1",
                "chunk_id": "c1",
                "text": "The budget billing plan is the basis for charging budget billing amounts.",
                "rendered_text": "The budget billing plan is the basis for charging budget billing amounts.",
                "title": "Budget Billing Plan",
                "heading_path": ["Utilities", "Billing"],
                "url": "https://help.sap.com/1",
                "source_id": "M2C-13",
            }
        ]
        self.ctx = adapters.build_context_block(self.sample_items)

    def test_a0_extractive_adapter_is_not_fixture(self):
        a0 = adapters.get_adapter("A0")
        self.assertFalse(a0.is_test_fixture)
        res = a0.generate("What is a budget billing plan?", self.ctx)
        self.assertEqual(res.adapter_id, "A0")
        self.assertFalse(res.is_test_fixture)
        self.assertIn("[S1]", res.text)
        self.assertGreater(res.latency_ms, 0.0)

    def test_a2_mock_adapter_is_labelled_test_fixture(self):
        a2 = adapters.get_adapter("A2_mock")
        self.assertTrue(a2.is_test_fixture)
        res = a2.generate("What is a budget billing plan?", self.ctx)
        self.assertEqual(res.adapter_id, "A2_mock")
        self.assertTrue(res.is_test_fixture)
        self.assertIn("[S1]", res.text)
        self.assertIn("TEST_FIXTURE_MOCK", res.telemetry.get("disclaimer", ""))

    def test_a3_mock_adapter_is_labelled_test_fixture(self):
        a3 = adapters.get_adapter("A3_mock")
        self.assertTrue(a3.is_test_fixture)
        res = a3.generate("What is a budget billing plan?", self.ctx)
        self.assertEqual(res.adapter_id, "A3_mock")
        self.assertTrue(res.is_test_fixture)
        self.assertTrue(res.telemetry.get("semantic_eval_required", False))


class Phase3MetricsTests(unittest.TestCase):
    """Validate deterministic scoring functions."""

    def test_key_facts_matching(self):
        text = "Business partner and contract account are key business master data objects in Utilities."
        facts = ["business partner", "contract account", "technical installation"]
        recalled, missing = metrics.check_key_facts(text, facts)
        self.assertEqual(recalled, 2)
        self.assertEqual(missing, ["technical installation"])

    def test_prohibited_claims_detection(self):
        text = "Execute transaction VA01 to create meter reading documents."
        claims = ["VA01 creates meter reading documents", "Automatic write-off"]
        detected = metrics.check_prohibited_claims(text, claims)
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0], "VA01 creates meter reading documents")

    def test_citation_checks(self):
        text = "This is item one. [S1]\nThis is item two. [S2]\nThis is uncited item."
        res = metrics.check_citations(text, valid_markers={"S1", "S2"})
        self.assertEqual(res["total_sentences"], 3)
        self.assertEqual(res["cited_sentences"], 2)
        self.assertEqual(res["citation_coverage"], 0.667)
        self.assertEqual(res["citation_precision"], 1.0)

    def test_substring_grounding(self):
        context_items = [
            {"marker": "S1", "text": "Utility companies bill for their services at the end of a supply period."}
        ]
        verbatim_text = "Utility companies bill for their services at the end of a supply period. [S1]"
        res = metrics.check_substring_grounding(verbatim_text, context_items)
        self.assertTrue(res["all_verbatim"])
        self.assertEqual(res["substring_support_ratio"], 1.0)

        paraphrased_text = "Power providers invoice customers after the billing cycle ends. [S1]"
        res2 = metrics.check_substring_grounding(paraphrased_text, context_items)
        self.assertFalse(res2["all_verbatim"])
        self.assertEqual(res2["substring_support_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
