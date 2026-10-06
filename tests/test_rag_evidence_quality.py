"""Focused regressions for shared deterministic evidence-quality filtering."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_elaborate as EL  # noqa: E402
import rag_evidence as EV  # noqa: E402
import rag_generate as RG  # noqa: E402


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


class SharedEvidenceQuality(unittest.TestCase):
    def test_normal_qa_rejects_navigation_before_scoring_and_keeps_a_short_explanation(self):
        navigation = (
            "Billing Execution 4",
            "Simulation/Billing Simulation 4",
        )
        explanation = "Billing is executed based on intervals defined in scheduling."
        context = _Context([
            _Item("S1", "billing-heading", 0, navigation[0], "Billing Execution"),
            _Item("S2", "billing-simulation", 1, navigation[1], "SAP Utilities Billing"),
            _Item("S3", "billing-explanation", 2, explanation, "Billing Execution"),
        ])
        question = "How does billing work?"

        # This is the pre-filter behavior: all three units share the topic term and appear sufficient.
        raw_units = EV.build_units(context.items)
        raw_decision, raw_selected = EV.assess(EV.analyze_question(question), raw_units, EV.SHIPPED_TAU)
        self.assertTrue(raw_decision.supported)
        self.assertEqual({unit.text for unit in raw_selected} & set(navigation), set(navigation))

        result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(question, context)
        self.assertFalse(result.refused)
        self.assertIn(explanation, result.text)
        for fragment in navigation:
            self.assertNotIn(fragment, result.text)
        self.assertEqual(result.evidence["quality_filter"]["excluded_units"], 2)
        self.assertEqual(result.evidence["quality_filter"]["excluded_markers"], ["S1", "S2"])
        self.assertEqual({item["marker"] for item in result.evidence["selected"]}, {"S3"})
        self.assertFalse(EV.is_low_quality_fragment(explanation, ("Billing Execution",)))
        self.assertFalse(EV.is_low_quality_fragment("Payments due"))  # short text is not rejected by length alone
        self.assertFalse(EV.is_incomplete_list_leadin("Billing has two levels: standard and advanced."))
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])

    def test_evidence_guard_does_not_prompt_with_or_accept_a_rejected_heading(self):
        heading = "Billing Execution 4"
        explanation = "Billing is executed based on intervals defined in scheduling."
        context = _Context([
            _Item("S1", "billing-heading", 0, heading, "Billing Execution"),
            _Item("S2", "billing-explanation", 1, explanation, "Billing Execution"),
        ])

        class _Inner:
            name = "stub"

            def __init__(self) -> None:
                self.seen = []

            def generate(self, question, model_context):
                self.seen = [f"{item.title} {' '.join(item.heading_path)} {item.text}" for item in model_context.items]
                return RG.GenerationResult(f"{heading} [S1]", False, self.name, f"{heading} [S1]")

        inner = _Inner()
        result = EV.EvidenceGuard(inner, tau=EV.SHIPPED_TAU).generate("How does billing work?", context)
        self.assertNotIn(heading, " ".join(inner.seen))
        self.assertTrue(result.refused)
        self.assertEqual(result.evidence["reason"], "ANSWER_INCLUDES_REJECTED_FRAGMENT")
        self.assertEqual(result.evidence["quality_filter"]["excluded_markers"], ["S1"])
        citation_context = _Context([item for item in context.items if item.marker != "S1"])
        grounded = RG.verify_grounding(f"{heading} [S1]", citation_context, in_page_grounding=True, citation_normalization=True)
        self.assertFalse(grounded.ok)  # the rejected heading marker cannot pass citation/grounding

    def test_incomplete_installment_list_intro_is_rejected_when_its_items_are_absent(self):
        leadin = "You create an installment plan when both of the following apply:"
        question = "How do I create an installment plan?"
        context = _Context([_Item("S1", "plan-intro", 0, leadin, "Installment Plan")])

        raw_decision, raw_selected = EV.assess(
            EV.analyze_question(question), EV.build_units(context.items), EV.SHIPPED_TAU,
        )
        self.assertTrue(raw_decision.supported)
        self.assertEqual([unit.text for unit in raw_selected], [leadin])

        generator = EL.IntentExtractiveGenerator("elaborate", anchor=question)
        result = generator.generate(question, context)
        self.assertTrue(result.refused)
        self.assertNotIn(leadin, result.text)
        self.assertEqual(generator.last["quality_filter"]["excluded_list_leadins"], 1)
        self.assertEqual(generator.last["quality_filter"]["excluded_markers"], ["S1"])

    def test_available_installment_list_items_are_selected_instead_of_the_intro(self):
        leadin = "You create an installment plan when both of the following apply:"
        item_one = "An installment plan is created only for open items with an eligible due date."
        item_two = "The system recalculates due dates for items covered by the installment plan."
        question = "How do I create an installment plan?"
        context = _Context([
            _Item("S1", "plan-intro", 0, leadin, "Installment Plan"),
            _Item("S2", "plan-item-1", 1, item_one, "Creating Installment Plans"),
            _Item("S3", "plan-item-2", 2, item_two, "Creating Installment Plans"),
        ])

        generator = EL.IntentExtractiveGenerator("elaborate", anchor=question)
        result = generator.generate(question, context)
        self.assertFalse(result.refused)
        self.assertNotIn(leadin, result.text)
        self.assertIn(item_one, result.text)
        self.assertIn(item_two, result.text)
        self.assertEqual(generator.last["quality_filter"]["excluded_list_leadins"], 1)
        self.assertEqual({item["sentence"] for item in generator.last["selected"]}, {item_one, item_two})
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])


if __name__ == "__main__":
    unittest.main()
