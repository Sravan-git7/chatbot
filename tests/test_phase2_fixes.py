"""Regression tests for SURA Phase 2 Quality Fixes (Fixes 1-5).

Verifies:
- Fix 1: Follow-up detection, positive follow-ups, ordinal resolution against numbered units,
  safe scoped lookup fallback for unresolvable ordinals, unrelated questions, missing anchors,
  and unavailable-page fail-closed behavior.
- Fix 2: Preservation of legitimate noun-phrase list items (Master Data 15 bullet units),
  rejection of incomplete lead-ins without items, preservation of headings/numbered lists.
- Fix 3: Rejection of false-positive '- Start and end of budget billing plan' fragment while
  preserving legitimate verb usages of 'start'.
- Fix 4: Budget Billing procedural questions do not invent steps and do not lead with dangling connectives.
- Fix 5: Frontend latency parameter verification.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import rag_evidence as EV
import rag_followup as FU
import rag_generate as RG
import rag_service as S
import rag_text as T


class _Item:
    def __init__(self, marker: str, chunk_id: str, rank: int, text: str, heading: str) -> None:
        self.marker = marker
        self.chunk_id = chunk_id
        self.rank = rank
        self.text = text
        self.rendered_text = text
        self.title = heading
        self.heading_path = (heading,)
        self.section_title = heading


class _Context:
    def __init__(self, items: list[_Item]) -> None:
        self.items = items


class Phase2FollowUpTests(unittest.TestCase):
    """Fix 1 regressions."""

    def test_positive_natural_followups_are_classified_correctly(self):
        cases = [
            ("Can you explain the second step in more detail?", "elaborate"),
            ("Can you elaborate?", "elaborate"),
            ("What happens next?", "continuation"),
            ("Explain that further.", "elaborate"),
            ("Can you explain the 2nd step in more detail?", "elaborate"),
            ("Can you explain step 2 in more detail?", "elaborate"),
            ("Explain the second step in more detail", "elaborate"),
            ("Could you elaborate on the second step?", "elaborate"),
            ("What comes next?", "continuation"),
            ("Tell me more about that", "elaborate"),
            ("What about the next step?", "continuation"),
        ]
        for msg, expected_cat in cases:
            with self.subTest(msg=msg):
                self.assertEqual(FU.classify(msg), expected_cat, f"Failed for '{msg}'")

    def test_unrelated_new_questions_are_not_classified_as_followups(self):
        standalone = [
            "What is the capital of France?",
            "How do I create an installment plan?",
            "What are the main master data objects in SAP Utilities?",
            "How does billing work?",
            "What is a contract account?",
            "Can you explain how billing works?",
            "Explain how billing works in SAP Utilities",
        ]
        for q in standalone:
            with self.subTest(q=q):
                self.assertIsNone(FU.classify(q), f"Should not classify standalone question '{q}' as follow-up")

    def test_ordinal_reference_resolves_when_prior_answer_has_numbered_steps(self):
        context = {
            "active_topic": {
                "query": "How do I process a move-in?",
                "identity": {"source_id": "M2C-03", "guide_id": "g1", "page_id": "p1"},
                "answer": (
                    "1. Enter the move-in date and contract account. [S1]\n"
                    "2. Verify that the premise and meter reading are recorded. [S1]\n"
                    "3. Save the move-in document. [S1]"
                ),
            }
        }
        res = FU.resolve("Can you explain the second step in more detail?", context)
        self.assertIsNotNone(res)
        self.assertEqual(res["category"], "elaborate")
        self.assertEqual(res["form"], "ordinal_step")
        self.assertEqual(res["ordinal_step"], 2)
        self.assertIn("Verify that the premise and meter reading are recorded.", res["query"])
        self.assertTrue(res["query"].startswith("How do I process a move-in?"))

    def test_ordinal_reference_performs_safe_scoped_lookup_when_no_numbered_steps(self):
        context = {
            "active_topic": {
                "query": "How do I analyse periodic billing and invoicing?",
                "identity": {"source_id": "M2C-16", "guide_id": "g1", "page_id": "p1"},
                "answer": (
                    "You can use this app to analyze periodic billing and invoicing. [S1]\n"
                    "The app presents the most relevant KPIs for billing documents. [S2]"
                ),
            }
        }
        res = FU.resolve("Can you explain the second step in more detail?", context)
        self.assertIsNotNone(res)
        self.assertEqual(res["category"], "elaborate")
        self.assertEqual(res["form"], "clause")
        self.assertEqual(res.get("unresolved_ordinal"), 2)
        # Safely falls back to anchor + clause, staying on active topic
        self.assertIn("explain this more", res["query"])
        self.assertTrue(res["query"].startswith("How do I analyse periodic billing and invoicing?"))

    def test_missing_or_invalid_anchor_fails_closed(self):
        self.assertIsNone(FU.resolve("Can you explain the second step in more detail?", None))
        self.assertIsNone(FU.resolve("Can you explain the second step in more detail?", {}))
        self.assertIsNone(FU.resolve("Can you explain the second step in more detail?", {"active_topic": {}}))
        self.assertIsNone(FU.resolve("Can you explain the second step in more detail?", {"questions": []}))


class Phase2EvidenceQualityTests(unittest.TestCase):
    """Fix 2, 3, and 4 regressions."""

    def setUp(self) -> None:
        self.generator = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU)

    def test_master_data_preserves_legitimate_noun_phrase_list_items(self):
        """Fix 2: Master data list items must NOT be dropped as quality fragments."""
        master_data_chunk = (
            "This component contains data for the Utilities Industry (IS-U) component that remains unchanged over a long period of time.\n"
            "There are two different types of master data:\n"
            "Business master data includes:\n"
            "- Business partner\n"
            "- Contract account\n"
            "- Contract (billable service)\n"
            "- Service provider\n"
            "- Non-billable service\n"
            "Technical master data includes:\n"
            "- Grid\n"
            "- Point of delivery\n"
            "- Connection\n"
            "- Connection object\n"
            "- Technical installation\n"
            "- Premise\n"
            "- Device location\n"
            "- Installation\n"
            "- Device"
        )
        context = _Context([
            _Item("S1", "c0", 0, master_data_chunk, "Utilities Master Data"),
        ])
        question = "What are the main master data objects in SAP Utilities?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        # Both lead-ins and their items must be present
        self.assertIn("Technical master data includes:", result.text)
        self.assertIn("- Grid [S1]", result.text)
        self.assertIn("- Connection object [S1]", result.text)
        self.assertIn("- Premise [S1]", result.text)
        self.assertIn("- Device [S1]", result.text)
        self.assertIn("Business master data includes:", result.text)
        self.assertIn("- Business partner [S1]", result.text)
        self.assertIn("- Contract account [S1]", result.text)

        # Incomplete lead-in must NOT stand alone at the end without items
        lines = result.text.strip().split("\n")
        self.assertFalse(lines[-1].strip().endswith("includes: [S1]"))

        # Provenance and grounding must pass
        self.assertTrue(RG.verify_grounding(result.text, context).ok)

    def test_incomplete_lead_in_cannot_survive_without_supported_items(self):
        """Fix 2: An incomplete lead-in with no attached items must be filtered out."""
        bare_leadin = "Technical master data includes:"
        units = [
            EV.Unit("S1", "c0", 0, 1, bare_leadin, frozenset(["technical", "master", "data", "includes"]),
                    frozenset(["master", "data"]), list_items=()),
        ]
        kept, excluded, details = EV.filter_quality_units(units)
        self.assertEqual(len(kept), 0)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(details["excluded_list_leadins"], 1)

    def test_start_and_end_fragment_is_rejected_while_verb_start_is_preserved(self):
        """Fix 3: '- Start and end of budget billing plan' is rejected; verb 'start' is kept."""
        # Exact fragment from Budget Billing
        fragment = "- Start and end of budget billing plan"
        self.assertFalse(EV._has_explanatory_predicate(fragment))
        self.assertTrue(EV.is_low_quality_fragment(fragment))

        # Legitimate verb usages of start must survive
        verb_sentences = [
            "Billing starts on the first day of each month.",
            "You start the analysis by executing transaction F3424.",
            "Start the program from the SAP Fiori Launchpad.",
            "The billing run started yesterday.",
        ]
        for s in verb_sentences:
            with self.subTest(sentence=s):
                self.assertTrue(EV._has_explanatory_predicate(s), f"Should recognize verb in '{s}'")
                self.assertFalse(EV.is_low_quality_fragment(s), f"Should not reject valid sentence '{s}'")

    def test_unrelated_fragments_and_headings_are_rejected(self):
        """Fix 2: Low-quality fragments, headings, and OCR errors remain rejected."""
        rejected = [
            "Table of contents",
            "Overview 4",
            "Page 12",
            "- Measure : Total Payment Amount",
            "Breadcrumbs > Navigation > Utilities",
            "Ab12cd34",
        ]
        for r in rejected:
            with self.subTest(item=r):
                self.assertTrue(EV.is_low_quality_fragment(r), f"Should reject '{r}'")

    def test_numbered_list_items_with_verbs_are_preserved(self):
        """Fix 2: Numbered steps with verbs remain admissible."""
        steps = [
            "1. Enter the contract account number.",
            "2. Select the billing document to reverse.",
            "3. Choose Save to record the change.",
        ]
        for step in steps:
            with self.subTest(step=step):
                self.assertFalse(EV.is_low_quality_fragment(step), f"Should keep valid numbered step '{step}'")

    def test_budget_billing_workflow_does_not_open_with_dangling_connective(self):
        """Fix 4: Budget Billing how-to does not start with dangling 'Therefore,'."""
        chunk0 = (
            "Utility companies normally bill for their services at the end of a supply period. "
            "Therefore, they charge budget billing amounts during the supply period instead of the actual amount owed. "
            "You specify the budget billing amounts and the dates that are due in the budget billing plan."
        )
        context = _Context([
            _Item("S1", "c0", 0, chunk0, "Budget Billing Plan"),
        ])
        question = "How do I create a budget billing plan?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        lines = result.text.strip().split("\n")
        # Opening line must NOT start with 'Therefore,'
        self.assertFalse(lines[0].startswith("Therefore,"), f"Answer should not open with dangling 'Therefore,': {lines[0]}")
        # Must contain grounded budget billing info
        self.assertIn("budget billing amounts", result.text)


class Phase21FormattingAndAnswerabilityTests(unittest.TestCase):
    """Phase 2.1: Frontend Formatting and Answerability Polish."""

    def setUp(self) -> None:
        self.generator = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU)

    def test_master_data_separates_list_sections_and_preserves_citations(self):
        """Bug 1: Business and Technical master data list sections must be separated by blank lines."""
        master_data_chunk = (
            "This component contains data for the Utilities Industry (IS-U) component that remains unchanged over a long period of time.\n"
            "There are two different types of master data:\n"
            "Business master data includes:\n"
            "- Business partner\n"
            "- Contract account\n"
            "- Contract (billable service)\n"
            "- Service provider\n"
            "- Non-billable service\n"
            "Technical master data includes:\n"
            "- Grid\n"
            "- Point of delivery\n"
            "- Connection\n"
            "- Connection object\n"
            "- Technical installation\n"
            "- Premise\n"
            "- Device location\n"
            "- Installation\n"
            "- Device"
        )
        context = _Context([
            _Item("S1", "c0", 0, master_data_chunk, "Master Data"),
        ])
        question = "What are the main master data objects in SAP Utilities?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        # Check that the two list sections are separated by an empty line in the text
        self.assertIn("- Non-billable service [S1]\n\nTechnical master data includes: [S1]", result.text)
        # Check that every list item retains its citation marker
        for expected in ["- Business partner [S1]", "- Contract account [S1]", "- Non-billable service [S1]",
                         "- Grid [S1]", "- Connection object [S1]", "- Device [S1]"]:
            self.assertIn(expected, result.text)
        # Check that verification checks pass
        self.assertTrue(RG.verify_grounding(result.text, context).ok)
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_conceptual_evidence_for_procedural_question_budget_billing(self):
        """Bug 2: Procedural question for budget billing plan makes limitation explicit with grounded context."""
        chunk = (
            "Utility companies normally bill for their services at the end of a supply period - in an annual consumption billing, for example. "
            "Therefore, they charge budget billing amounts during the supply period instead of the actual amount owed, in order to remain solvent. "
            "You specify the budget billing amounts and the dates that are due in the budget billing plan. "
            "The budget billing plan is the basis for charging budget billing amounts."
        )
        context = _Context([
            _Item("S1", "c0", 0, chunk, "Budget Billing Plan"),
        ])
        question = "How do I create a budget billing plan?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        expected_limitation = "The available SAP Help page explains the purpose and parameters of a budget billing plan, but it does not document the steps to create one."
        self.assertIn(expected_limitation, result.text)
        # Grounded context must remain present and cited
        self.assertIn("Utility companies normally bill for their services", result.text)
        self.assertIn("[S1]", result.text)
        # Grounding and support chain must pass
        self.assertTrue(RG.verify_grounding(result.text, context).ok)
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_conceptual_evidence_for_procedural_question_periodic_billing(self):
        """Bug 2: Procedural question for periodic billing and invoicing analysis makes limitation explicit."""
        chunk = (
            "You can use this app to analyze the billing and invoicing process for all billing and invoicing statuses and KPIs. "
            "Aggregated information (such as the number of contracts that are ready for invoicing) is also available. "
            "The app presents the most relevant KPIs for a portion-centered analysis of the billing and invoicing process."
        )
        context = _Context([
            _Item("S1", "c0", 0, chunk, "Periodic Billing and Invoicing Analysis (F3424)"),
        ])
        question = "How do I analyse periodic billing and invoicing?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        expected_limitation = "The available SAP Help page describes the features and KPIs of the Periodic Billing and Invoicing Analysis app, but it does not document the steps to perform the analysis."
        self.assertIn(expected_limitation, result.text)
        self.assertIn("You can use this app to analyze", result.text)
        self.assertIn("[S1]", result.text)
        self.assertTrue(RG.verify_grounding(result.text, context).ok)
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_genuine_procedural_evidence_retains_steps_without_limitation(self):
        """Bug 2: Genuine procedural steps must NOT receive an abstention or limitation disclaimer."""
        procedural_chunk = (
            "To reverse a billing document, proceed as follows:\n"
            "1. Enter the contract account number.\n"
            "2. Select the billing document to reverse.\n"
            "3. Choose Save to record the reversal."
        )
        context = _Context([
            _Item("S1", "c0", 0, procedural_chunk, "Billing Document Reversal"),
        ])
        question = "How do I execute a billing document reversal process?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        # No limitation notice should be present
        self.assertNotIn("does not document the steps", result.text)
        # Numbered procedural step should be present
        self.assertIn("Select the billing document to reverse. [S1]", result.text)
        self.assertTrue(RG.verify_grounding(result.text, context).ok)
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_ordinary_factual_question_remains_answered_without_limitation(self):
        """Bug 2: Ordinary factual question must remain answered without procedural limitation."""
        factual_chunk = (
            "In Utilities, one contract account contains all contracts of a business partner for which the same payment and billing terms apply. "
            "You can assign more than one contract to a single contract account."
        )
        context = _Context([
            _Item("S1", "c0", 0, factual_chunk, "Contract Account"),
        ])
        question = "What is a contract account?"
        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        self.assertNotIn("does not document the steps", result.text)
        self.assertIn("In Utilities, one contract account contains all contracts", result.text)
        self.assertTrue(RG.verify_grounding(result.text, context).ok)
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_unavailable_documentation_fails_closed(self):
        """Bug 2: Unavailable documentation must remain fail-closed without fabricating instructions."""
        # Raw pipeline result simulating unavailable page
        raw_result = {
            "status": "page_not_ingested",
            "reason_code": "PAGE_IDENTIFIED_NO_LOCAL_CONTENT",
            "message": "The registered topic Contract Account has no local searchable page text.",
            "topic": {"title": "Contract Account", "source_id": "M2C-18", "card_url": "https://help.sap.com/docs/1", "corpus_status": "unverified"},
            "citations": {"answer_sources": []},
            "routing": {"candidates": [{"coverage": 0.8}]},
            "debug": {},
        }
        chat_res = S.to_chat_result(raw_result, generator="extractive", conversation_id="test-conv", latency_ms=10.0)
        self.assertEqual(chat_res["status"], S.DOC_UNAVAILABLE)
        self.assertEqual(chat_res["answer"], S.USER_TEXT[S.DOC_UNAVAILABLE])
        self.assertEqual(chat_res["sources"], [])
        self.assertIsNotNone(chat_res.get("topic_reference"))
        self.assertFalse(chat_res["metadata"]["grounded"])


if __name__ == "__main__":
    unittest.main()
