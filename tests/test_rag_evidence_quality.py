"""Focused regressions for shared deterministic evidence-quality filtering."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_context as RC  # noqa: E402
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


class FragmentRules(unittest.TestCase):
    """Bare list entries and embedded heading lines are rejected; real sentences are never rejected by them."""

    def test_bare_list_items_are_fragments_but_punctuated_and_imperative_items_are_not(self):
        bare = (
            "- Measure : Total Payment Amount",
            "- Payment usage within a payment lot",
            "- Level of automation within one payment lot",
            "- Chart : Combined Stacked Line Chart",
            "- Dimension : Lot",
            "1. Introduction",
        )
        for fragment in bare:
            with self.subTest(fragment=fragment):
                self.assertTrue(EV.is_low_quality_fragment(fragment), fragment)

        keep = (
            "- The Chart View shows all payment lots matching the filter criteria.",
            "- Analyze how many payments have been clarified manually within a given period.",
            "- Choose Continue to save the installment plan proposal",
            "The app analyzes payment lots, credit lots, and check lots.",
        )
        for sentence in keep:
            with self.subTest(sentence=sentence):
                self.assertFalse(EV.is_low_quality_fragment(sentence), sentence)

    def test_standalone_heading_lines_inside_a_chunk_are_fragments(self):
        chunk = (
            "To display percentages, select the following:\n"
            "- Chart : 100% Stacked Column Chart\n"
            "SAP Fiori Implementation Information\n"
            "In the SAP Fiori Apps Reference Library , see the details for the Analyze Incoming Payments app."
        )
        self.assertTrue(EV.is_low_quality_fragment("SAP Fiori Implementation Information", (), chunk))
        self.assertTrue(EV.is_low_quality_fragment("Telecommunications(IS-T) component", (), "Features\nTelecommunications(IS-T) component\nYou can assign more than one contract account."))
        # without the chunk text the structural check cannot fire (conservative default: keep)
        self.assertFalse(EV.is_low_quality_fragment("SAP Fiori Implementation Information"))
        # a single-line chunk is not a heading fragment by this rule
        self.assertFalse(EV.is_low_quality_fragment("SAP Fiori Implementation Information", (), "SAP Fiori Implementation Information"))
        # the sentence next to the heading is real evidence
        self.assertFalse(EV.is_low_quality_fragment(
            "In the SAP Fiori Apps Reference Library , see the details for the Analyze Incoming Payments app.", (), chunk))

    def test_filter_quality_units_rejects_bare_items_and_embedded_headings(self):
        chunk_text = (
            "To display the total payment amount in relation to the open payment amount in a lot, select the following:\n"
            "- Chart : Combined Stacked Line Chart\n"
            "- Dimension : Lot\n"
            "- Measure : Total Payment Amount\n"
            "SAP Fiori Implementation Information\n"
            "In the SAP Fiori Apps Reference Library , see the details for the Analyze Incoming Payments app."
        )
        # one context item whose text is the whole chunk, exactly like a production ContextItem
        context = _Context([_Item("S1", "payments-config", 0, chunk_text, "Analyze Incoming Payments")])

        kept, excluded, details = EV.filter_quality_units(EV.build_units(context.items), context)
        kept_texts = {unit.text for unit in kept}
        self.assertEqual(kept_texts, {"In the SAP Fiori Apps Reference Library , see the details for the Analyze Incoming Payments app."})
        excluded_texts = {unit.text for unit in excluded}
        self.assertIn("- Measure : Total Payment Amount", excluded_texts)
        self.assertIn("- Chart : Combined Stacked Line Chart", excluded_texts)
        self.assertIn("SAP Fiori Implementation Information", excluded_texts)
        self.assertIn("To display the total payment amount in relation to the open payment amount in a lot, select the following:", excluded_texts)
        self.assertEqual(details["excluded_units"], 5)


class DefinitionFirstOrdering(unittest.TestCase):
    """Definition-style questions lead with definitional evidence, industry-scoped definitions first."""

    @staticmethod
    def _unit(order, marker, text):
        return EV.Unit(marker=marker, chunk_id=f"c-{order}", rank=0, order=order, text=text,
                       own=frozenset(EV.terms2(text)), head=frozenset(), chunk_text=text)

    def test_definition_questions_are_detected_and_others_are_not(self):
        for question in ("What is a contract account?", "What are clearing types?", "What does a clearing type represent?",
                         "Define the contract account.", "How is a contract account defined in SAP Utilities?",
                         "What is the meaning of dunning?"):
            with self.subTest(question=question):
                self.assertTrue(EV.is_definition_question(question), question)
        for question in ("How does billing work?", "Can a single contract account be assigned to multiple business partners in Utilities?",
                         "What happens when a new customer moves in?", "Why is billing important?",
                         "What's the invoicing process?", "What is the invoicing process?"):
            with self.subTest(question=question):
                self.assertFalse(EV.is_definition_question(question), question)

    def test_process_questions_are_distinguished_from_concept_definitions(self):
        for question in ("What is the invoicing process?", "What's the invoicing process?", "How does billing work?",
                         "How are bills processed?"):
            with self.subTest(question=question):
                self.assertTrue(EV.is_process_question(question), question)
                self.assertFalse(EV.is_definition_question(question), question)
        self.assertFalse(EV.is_process_question("What is a contract account?"))

    def test_definition_rank_prefers_industry_scoped_definitions(self):
        isu = self._unit(1, "S1", "In Utilities, one contract account contains all those contracts belonging to one business partner.")
        purpose = self._unit(2, "S2", "This component enables you to create and manage contract account master data.")
        fica = self._unit(3, "S3", "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one business partner.")
        other = self._unit(4, "S4", "The system logs changes to master data.")
        self.assertEqual(EV.definition_rank(isu), 0)
        self.assertEqual(EV.definition_rank(purpose), 1)
        self.assertEqual(EV.definition_rank(fica), 1)
        self.assertEqual(EV.definition_rank(other), 2)

    def test_assess_prioritizes_the_industry_scoped_definition_within_the_answer_budget(self):
        master = "In the contract account master record, you can define, for each business partner, the procedures that apply."
        purpose = "This component enables you to create and manage contract account master data."
        fica = "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one business partner."
        assign = "You can assign more than one contract account to a given business partner."
        isu = "In Utilities, one contract account contains all those contracts belonging to one business partner."
        units = [self._unit(i + 1, f"S{i + 1}", text) for i, text in enumerate((master, purpose, fica, assign, isu))]
        needs = EV.analyze_question("What is a contract account?")
        decision, chosen = EV.assess(needs, units, EV.SHIPPED_TAU)
        self.assertTrue(decision.supported)
        # The industry-scoped definition leads and stays within the shipped 3-sentence answer budget.
        self.assertEqual(chosen[0].text, isu)
        self.assertEqual(len(chosen), EV.EXTRACTIVE_MAX_SENTENCES)
        self.assertEqual({u.text for u in chosen}, {master, purpose, isu})
        self.assertEqual([u.text for u in chosen[1:]], [master, purpose])

        # the same evidence answers a non-definition question without the definitional preference
        needs = EV.analyze_question("How is a contract account managed?")
        decision, chosen = EV.assess(needs, units, EV.SHIPPED_TAU)
        self.assertTrue(decision.supported)
        self.assertNotEqual(chosen[0].text, "In Utilities, one contract account contains all those contracts belonging to one business partner.")

    def test_the_generator_displays_the_definition_first(self):
        chunk_text = (
            "This component enables you to create and manage contract account master data. "
            "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one business partner. "
            "In Utilities, one contract account contains all those contracts belonging to one business partner."
        )
        item = _Item("S1", "contract", 0, chunk_text, "Contract Accounts")
        result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate("What is a contract account?", _Context([item]))
        self.assertFalse(result.refused)
        self.assertTrue(result.text.split("\n")[0].startswith("In Utilities, one contract account contains"), result.text)
        # every line stays verbatim documentation with its marker
        for line in result.text.split("\n"):
            self.assertRegex(line, r"\[S1\]$")
        self.assertTrue(EV.verify_support_chain(result.text, _Context([item]))["ok"])


class WorkflowContextSelection(unittest.TestCase):
    @staticmethod
    def _hit(rank, chunk_id, chunk_index, heading_path, section_title, text):
        return SimpleNamespace(
            rank=rank, chunk_id=chunk_id, guide_id="guide", page_id="page", source_url="https://example.test/page",
            title="Invoicing Procedure", heading_path=tuple(heading_path), section_title=section_title,
            chunk_index=chunk_index, chunk_count=8, content_hash=chunk_id, distance=0.2, similarity=0.8, text=text,
        )

    def test_workflow_evidence_can_survive_the_rank_cap_without_changing_default_selection(self):
        hits = [
            self._hit(1, "overview", 0, ("Invoicing Procedure", "Use"), "Use",
                      "Invoicing creates the link to contract accounting and provides the basis for bill creation."),
            self._hit(2, "diagram", 4, ("Invoicing Procedure", "Process Flow"), "Process Flow",
                      "The following diagram illustrates the process flow from billing through invoicing and invoice printout."),
            self._hit(3, "result", 5, ("Invoicing Procedure", "Result"), "Result",
                      "The contract accounting document records invoice postings for the billed contracts."),
            self._hit(4, "exceptions", 3, ("Invoicing Procedure", "Process Flow"), "Process Flow",
                      "- If bills are found to be incorrect, you must process them using the Bill Reversal function."),
            self._hit(5, "workflow-steps", 2, ("Invoicing Procedure", "Process Flow"), "Process Flow",
                      "1. Once the contract is billed, you start bill creation.\n"
                      "2. Invoicing with Bill Creation results in a print document and a contract accounting document."),
        ]

        key = EV.workflow_context_selection_key("What is the invoicing process?", hits)
        self.assertIsNotNone(key)
        context = RC.build_context(hits, lambda text: len(text.split()), budget_tokens=1000, max_chunks=4, selection_key=key)
        selected_ids = [item.chunk_id for item in context.items]
        self.assertIn("workflow-steps", selected_ids)
        self.assertNotIn("diagram", selected_ids)
        self.assertEqual([item.chunk_index for item in context.items], sorted(item.chunk_index for item in context.items))
        self.assertIn({"chunk_id": "diagram", "reason": "max_chunks"}, context.dropped)

        # Non-workflow questions keep the existing rank-first context behavior.
        self.assertIsNone(EV.workflow_context_selection_key("What is invoicing?", hits))
        baseline_context = RC.build_context(hits, lambda text: len(text.split()), budget_tokens=1000, max_chunks=4)
        self.assertNotIn("workflow-steps", {item.chunk_id for item in baseline_context.items})


class AnswerSelectionQuality(unittest.TestCase):
    def test_workflow_selection_suppresses_boilerplate_and_preserves_supported_source_order(self):
        workflow = (
            "1. Once the contract is billed, you start bill creation. "
            "You must release the documents previously outsorted during billing checks.\n"
            "2. Invoicing with Bill Creation results in a print document and a contract accounting document.\n"
            "3. To print the bill, you require the print document. When you execute the function, you specify the output type as a print parameter."
        )
        diagram = "The following diagram illustrates the process flow from billing through invoicing and invoice printout."
        leadin = "In addition to these general activities, the following individual processing steps are useful:"
        generic = "Budget billing plans are processed."
        context = _Context([
            _Item("S1", "overview", 1, "Invoicing creates the link to contract accounting and provides the basis for bill creation. " + generic,
                  "Invoicing Procedure > Use"),
            _Item("S2", "diagram", 2, diagram, "Invoicing Procedure > Process Flow"),
            _Item("S3", "workflow", 3, workflow, "Invoicing Procedure > Process Flow"),
            _Item("S4", "exceptions", 4, leadin + "\n- If bills are found to be incorrect, you must process them using the Bill Reversal function.",
                  "Invoicing Procedure > Process Flow"),
        ])
        result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate("What is the invoicing process?", context)

        self.assertFalse(result.refused)
        self.assertIn("Once the contract is billed, you start bill creation.", result.text)
        self.assertIn("You must release the documents previously outsorted during billing checks.", result.text)
        self.assertIn("Invoicing with Bill Creation results in a print document and a contract accounting document.", result.text)
        self.assertNotIn(diagram, result.text)
        self.assertNotIn(leadin, result.text)
        self.assertNotIn(generic, result.text)
        ordered_facts = [
            "Once the contract is billed, you start bill creation.",
            "You must release the documents previously outsorted during billing checks.",
            "Invoicing with Bill Creation results in a print document and a contract accounting document.",
        ]
        positions = [result.text.index(fact) for fact in ordered_facts]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(result.evidence["answer_selection"]["intent"], "workflow")

        # The re-ordered answer stays verbatim, and every selected marker still names its source chunk.
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])
        report = RG.verify_grounding(result.text, context, in_page_grounding=True, citation_normalization=True)
        self.assertTrue(report.ok, report.to_dict())
        by_text = {unit.text: unit for unit in EV.build_units(context.items)}
        selected_units = [by_text[row["sentence"]] for row in result.evidence["selected"]]
        source_steps = [EV._source_sequence_info(unit) for unit in selected_units]
        self.assertEqual([step[1] for step in source_steps if step], [1, 1, 2])
        self.assertEqual({row["marker"] for row in result.evidence["selected"]}, {"S3"})

    def test_exact_overlap_is_deduplicated_without_losing_distinct_facts_across_chunks(self):
        repeated = "A cashier can assign a payment lot to a contract account."
        first = "Incoming payment lots group payments awaiting clarification."
        third = "The lot records when the payments were processed."
        context = _Context([
            _Item("S1", "lot-a", 1, first + " " + repeated, "Payment Lot"),
            _Item("S2", "lot-b", 2, repeated + " " + third, "Payment Lot"),
        ])
        result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate("Explain payment lot handling.", context)

        self.assertFalse(result.refused)
        self.assertIn(first, result.text)
        self.assertIn(repeated, result.text)
        self.assertIn(third, result.text)
        self.assertEqual(result.text.count(repeated), 1)
        self.assertEqual({row["marker"] for row in result.evidence["selected"]}, {"S1", "S2"})
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])
        self.assertTrue(RG.verify_grounding(result.text, context).ok)

    def test_best_supported_sentence_is_retained_when_quality_suppression_has_no_alternative(self):
        only_evidence = "The following diagram illustrates the process flow from billing through invoicing and invoice printout."
        context = _Context([_Item("S1", "diagram-only", 1, only_evidence, "Invoicing Procedure > Process Flow")])
        result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate("What is the invoicing process?", context)

        self.assertFalse(result.refused)
        self.assertIn(only_evidence, result.text)
        self.assertTrue(result.evidence["answer_selection"]["fallback"])
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])


if __name__ == "__main__":
    unittest.main()
