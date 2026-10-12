"""Deterministic regression tests for standalone causal questions and conditional explanations."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import rag_evidence as EV  # noqa: E402
import rag_generate as RG  # noqa: E402
from tests.phase8_support import make_pipeline  # noqa: E402


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


class CausalEvidenceRegressions(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU)

    def test_w02_selects_exact_documented_until_the_bill_is_released_sentence(self):
        """W02 must select the exact documented explanatory sentence and avoid topical neighbors."""
        no_postings = "However, no postings occur in contract accounts receivable and payable."
        explanatory = "Postings do not take place until the bill is released using the Outsorting function."
        bill_reversal = (
            "If bills are found to be incorrect, and their documents have been updated in the "
            "Contract Accounts Receivable and Payable (FI-CA) component, you must process them using the Bill Reversal function."
        )
        bill_requests = "The bill requests can be followed up in contract accounts receivable and payable."

        context = _Context([
            _Item("S1", "c0", 0, f"{no_postings} {explanatory} {bill_reversal}", "Process Flow"),
            _Item("S2", "c1", 1, bill_requests, "Result"),
        ])
        question = "Why are no postings made in contract accounts receivable and payable until the bill is released?"

        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        self.assertIn(explanatory, result.text)
        self.assertNotIn("Bill Reversal", result.text)
        self.assertNotIn("bill requests can be followed up", result.text)
        self.assertEqual(len(result.text.strip().split("\n")), 1)
        self.assertEqual(result.text.strip(), f"{explanatory} [S1]")
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])
        self.assertTrue(RG.verify_grounding(result.text, context).ok)

    def test_unsupported_standalone_causal_question_abstains(self):
        """When a causal question asks about an unsupported relationship, the generator must abstain."""
        topical_sentences = [
            "Contract accounts are used to manage business partner postings in utilities.",
            "You can display contract accounts and configure posting locks.",
        ]
        context = _Context([
            _Item("S1", "c0", 0, topical_sentences[0], "Use"),
            _Item("S2", "c1", 1, topical_sentences[1], "Features"),
        ])
        question = "Why are contract accounts printed in green ink?"

        result = self.generator.generate(question, context)

        self.assertTrue(result.refused)
        self.assertEqual(result.text, RG.NO_ANSWER_TEXT)
        self.assertEqual(result.evidence.get("selected"), [])

    def test_temporal_conditional_evidence_works_without_requiring_the_literal_word_because(self):
        """Documented temporal/conditional conditions ('until / unless / only when') satisfy causal needs."""
        condition_sentence = "The payment cannot be cleared until the manager approves the exception."
        unrelated_sentence = "Payments are managed in contract accounts receivable and payable."
        context = _Context([
            _Item("S1", "c0", 0, condition_sentence, "Approval Requirements"),
            _Item("S2", "c1", 1, unrelated_sentence, "Overview"),
        ])
        question = "Why can the payment not be cleared until approval?"

        result = self.generator.generate(question, context)

        self.assertFalse(result.refused)
        self.assertIn(condition_sentence, result.text)
        self.assertNotIn(unrelated_sentence, result.text)
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_ordinary_definition_and_process_answers_retain_existing_behavior(self):
        """Definition and process question paths remain intact and unchanged."""
        def_sentence = "The contract account is the central object in contract accounts receivable and payable."
        step_one = "Once the contract is billed, you start bill creation."
        step_two = "Invoicing with Bill Creation results in a print document and a contract accounting document."

        def_context = _Context([
            _Item("S1", "c0", 0, def_sentence, "Contract Account"),
        ])
        proc_context = _Context([
            _Item("S1", "c0", 0, f"Process Flow\n1. {step_one}\n2. {step_two}", "Process Flow"),
        ])

        def_result = self.generator.generate("What is a contract account?", def_context)
        self.assertFalse(def_result.refused)
        self.assertIn(def_sentence, def_result.text)

        proc_result = self.generator.generate("What is the invoicing process?", proc_context)
        self.assertFalse(proc_result.refused)
        self.assertTrue(step_one in proc_result.text or step_two in proc_result.text)

    def test_real_pipeline_w02_end_to_end(self):
        """Verify W02 against the real pipeline fixture with page M2C-14."""
        pipe = make_pipeline(EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU), default=["M2C-14"])
        question = "Why are no postings made in contract accounts receivable and payable until the bill is released?"

        response = pipe.answer(question)

        self.assertEqual(response.get("status"), "answered")
        self.assertIn("Postings do not take place until the bill is released using the Outsorting function. [S3]", response.get("answer"))
        self.assertNotIn("Bill Reversal", response.get("answer"))
        self.assertNotIn("bill requests can be followed up", response.get("answer"))


if __name__ == "__main__":
    unittest.main()
