"""Deterministic golden evaluation suite for SURA RAG pipeline.

Evaluates:
- Answerability and route correctness on canonical queries
- Citation validity and grounding status on answered queries
- Abstention behavior and topic_reference suppression on out-of-scope/unrelated queries
- Near-miss unanswerable query safety
"""
from __future__ import annotations

import json
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_api
import rag_service


class GoldenEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_path = ROOT / "tests" / "fixtures" / "golden_evaluation_set.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            cls.test_cases = json.load(f)

        # Build service using standard factory
        cls.service = rag_service.build_service("extractive")

    def test_golden_eval_suite(self):
        results = []
        metrics = {
            "total": len(self.test_cases),
            "status_matches": 0,
            "topic_matches": 0,
            "citations_valid": 0,
            "oos_suppression_correct": 0,
        }

        for tc in self.test_cases:
            query = tc["query"]
            expected_status = tc.get("expected_status")
            expected_topic_id = tc.get("expected_topic_id")
            allow_topic_ref = tc.get("allow_topic_reference", True)

            raw = self.service.ask(question=query, conversation_id="eval-session", debug=True)

            status = raw.get("status")
            status_ok = status == expected_status if expected_status else True
            if status_ok:
                metrics["status_matches"] += 1

            topic_id = raw.get("metadata", {}).get("card_id")
            topic_ok = True
            if expected_topic_id:
                topic_ok = topic_id == expected_topic_id
                if topic_ok:
                    metrics["topic_matches"] += 1

            citations_ok = True
            if status == "answered":
                sources = raw.get("sources", [])
                citations_ok = len(sources) > 0 and all(s.get("marker") for s in sources)
                if citations_ok:
                    metrics["citations_valid"] += 1

            topic_ref = raw.get("topic_reference")
            topic_ref_ok = True
            if not allow_topic_ref:
                topic_ref_ok = topic_ref is None
                if topic_ref_ok:
                    metrics["oos_suppression_correct"] += 1

            results.append({
                "id": tc["id"],
                "query": query,
                "category": tc["category"],
                "status": status,
                "expected_status": expected_status,
                "status_ok": status_ok,
                "topic_id": topic_id,
                "expected_topic_id": expected_topic_id,
                "topic_ok": topic_ok,
                "citations_ok": citations_ok,
                "topic_ref": topic_ref,
                "topic_ref_ok": topic_ref_ok,
            })

            # Assertions for individual test cases
            if not allow_topic_ref:
                self.assertIsNone(
                    topic_ref,
                    f"Query '{query}' must NOT have topic_reference, got {topic_ref}",
                )

            if status == "answered":
                self.assertTrue(raw.get("metadata", {}).get("grounded", False))
                self.assertIsNotNone(raw.get("structured_answer"))

        print("\n--- Golden Evaluation Baseline Summary ---")
        print(f"Total test cases: {metrics['total']}")
        print(f"Status matches: {metrics['status_matches']} / {metrics['total']} ({metrics['status_matches']/metrics['total']:.1%})")
        print(f"Citation validity on answered: {metrics['citations_valid']}")
        print(f"Irrelevant topic_reference suppressed: {metrics['oos_suppression_correct']}")


if __name__ == "__main__":
    unittest.main()
