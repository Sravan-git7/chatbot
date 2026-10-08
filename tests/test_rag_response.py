"""Tests for deterministic response composer (scripts/rag_response.py)."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rag_response as RR


class RagResponseTests(unittest.TestCase):
    def setUp(self):
        self.sample_answer = (
            "SAP Utilities installment plans allow customers to pay outstanding amounts in installments [S1].\n"
            "To configure an installment plan, use transaction code FPR1 [S2].\n"
            "A prerequisite is that the items must be open and not in a dunning lock [S1]."
        )
        self.sample_sources = [
            {"marker": "S1", "title": "Installment Plan Overview", "section": "Basics", "url": "https://help.sap.com/1"},
            {"marker": "S2", "title": "Installment Plan Creation", "section": "Configuration", "url": "https://help.sap.com/2"},
        ]
        self.sample_meta = {"card_title": "Installment Plans", "pipeline_status": "answered"}

    def test_compose_response_answered(self):
        result = RR.compose_response(self.sample_answer, self.sample_sources, "answered", self.sample_meta)
        self.assertIn("structured_answer", result)
        self.assertIn("documentation_coverage", result)

        sa = result["structured_answer"]
        self.assertIsNotNone(sa)
        self.assertTrue(len(sa["sections"]) > 0)
        self.assertEqual(sa["citations"], ["S1", "S2"])

        for sec in sa["sections"]:
            self.assertIn("title", sec)
            self.assertIn("key", sec)
            self.assertIn("lines", sec)
            self.assertIn("content", sec)
            self.assertIn("citations", sec)

        cov = result["documentation_coverage"]
        self.assertTrue(cov["covered"])
        self.assertGreater(cov["coverage_percentage"], 0)
        self.assertEqual(cov["total_sources_cited"], 2)
        self.assertEqual(cov["matched_topics"], ["Installment Plans"])
        self.assertEqual(cov["uncovered_aspects"], [])

    def test_compose_response_unanswered(self):
        for status in ("out_of_scope", "unable_to_verify", "documentation_unavailable"):
            result = RR.compose_response("", [], status, {"card_title": "OOS"})
            self.assertIsNone(result["structured_answer"])
            cov = result["documentation_coverage"]
            self.assertFalse(cov["covered"])
            self.assertEqual(cov["coverage_percentage"], 0.0)
            self.assertEqual(cov["total_sources_cited"], 0)
            self.assertIn(status, cov["uncovered_aspects"])

    def test_no_new_prose_synthesized(self):
        result = RR.compose_response(self.sample_answer, self.sample_sources, "answered", self.sample_meta)
        sa = result["structured_answer"]
        self.assertIsNotNone(sa)

        # Ensure all section lines exist verbatim in the sample answer
        for sec in sa["sections"]:
            for line in sec["lines"]:
                self.assertIn(line, self.sample_answer)

    def test_deterministic(self):
        res1 = RR.compose_response(self.sample_answer, self.sample_sources, "answered", self.sample_meta)
        res2 = RR.compose_response(self.sample_answer, self.sample_sources, "answered", self.sample_meta)
        self.assertEqual(res1, res2)

    def test_citation_extraction(self):
        text = "Fact one [S3] and fact two [S1] repeated [S3]."
        cits = RR.extract_citations(text)
        self.assertEqual(cits, ["S3", "S1"])

    def test_short_answer_consolidates_into_overview(self):
        short_ans = "A contract account is a master data object. [S1]\nIt contains payment terms. [S1]"
        result = RR.compose_response(short_ans, self.sample_sources, "answered", self.sample_meta)
        sa = result["structured_answer"]
        self.assertIsNotNone(sa)
        self.assertEqual(len(sa["sections"]), 1)
        self.assertEqual(sa["sections"][0]["title"], "Overview")
        self.assertEqual(sa["sections"][0]["key"], "overview")

    def test_single_category_answer_consolidates_into_overview(self):
        single_cat = (
            "Line one is general description [S1].\n"
            "Line two is also general description [S1].\n"
            "Line three concludes the description [S1]."
        )
        result = RR.compose_response(single_cat, self.sample_sources, "answered", self.sample_meta)
        sa = result["structured_answer"]
        self.assertIsNotNone(sa)
        self.assertEqual(len(sa["sections"]), 1)
        self.assertEqual(sa["sections"][0]["title"], "Overview")

    def test_purpose_statements_are_overview_never_procedures(self):
        # "This component enables you to create and manage contract account master data." mentions creating and
        # managing, but it states what the topic IS: it belongs under Overview, not Procedure & Usage.
        purpose = "This component enables you to create and manage contract account master data. [S1]"
        self.assertEqual(RR.categorize_line(purpose), "overview")
        self.assertEqual(RR.categorize_line("The purpose of the app is to monitor incoming payments. [S1]"), "overview")
        self.assertEqual(RR.categorize_line("In Utilities, one contract account contains all those contracts. [S1]"), "overview")
        # real procedures and prerequisites keep their sections
        self.assertEqual(RR.categorize_line("To configure an installment plan, use transaction code FPR1 [S2]."), "procedure_and_usage")
        self.assertEqual(RR.categorize_line("To create a contract account, choose Account > Contract Account. [S1]"), "procedure_and_usage")
        self.assertEqual(RR.categorize_line("A prerequisite is that the items must be open. [S1]"), "conditions_and_prerequisites")
        self.assertEqual(RR.categorize_line("In Contract Accounts Receivable and Payable, each posting is assigned to one contract account. [S1]"), "overview")

    def test_a_purpose_answer_is_grouped_under_overview(self):
        answer = (
            "This component enables you to create and manage contract account master data. [S1]\n"
            "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one contract account. [S1]\n"
            "In the contract account master record, you can define the procedures that apply. [S1]"
        )
        result = RR.compose_response(answer, self.sample_sources, "answered", self.sample_meta)
        sa = result["structured_answer"]
        self.assertIsNotNone(sa)
        self.assertEqual([sec["key"] for sec in sa["sections"]], ["overview"])
        self.assertEqual(sa["sections"][0]["lines"], answer.split("\n"))


if __name__ == "__main__":
    unittest.main()
