"""Phase 11.1 - evidence sufficiency, support chain, widening and the guard (pure functions + stubs; no stores needed)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rag_evidence as E  # noqa: E402
from rag_context import ContextBlock, ContextItem  # noqa: E402
from rag_generate import NO_ANSWER_TEXT, GenerationResult, verify_grounding  # noqa: E402


def item(marker, text, heading=("Gadget > Use",), rank=1, chunk_id=None):
    return ContextItem(marker=marker, chunk_id=chunk_id or f"g/p/{marker}", guide_id="g", page_id="p", title="Gadget", heading_path=list(heading), section_title=heading[-1], chunk_index=int(marker[1:]),
                       rank=rank, similarity=0.5, text=text, rendered_text=text, tokens=len(text.split()), content_hash=marker, source_url="https://example.invalid/x")


def ctx(*items):
    return ContextBlock(items=list(items))


PAGE = ctx(item("S1", "The widget controller manages the pump, the valve and the filter. It is started from the main panel.", ("Widget Controller > Purpose",)),
           item("S2", "Transaction ZW10\nYou can use this transaction to start the pump in manual mode.\nThe pump runs for 30 minutes.", ("Widget Controller > Operation",), rank=2))


class QuestionAnalysis(unittest.TestCase):
    def test_kinds(self):
        k = lambda q: E.analyze_question(q).kinds  # noqa: E731
        self.assertIn("limit", k("What is the minimum pressure?"))
        self.assertIn("limit", k("What is the maximum number of valves?"))
        self.assertIn("number", k("How many pumps can run?"))
        self.assertIn("code", k("Which transaction starts the pump?"))
        self.assertIn("default", k("What is the default speed?"))
        self.assertIn("time", k("How long does the pump run?"))
        self.assertEqual(k("What does the controller manage?"), ())
        self.assertEqual(k("How is the number of valves determined?"), ())      # "number of" in a how-question is not a request for a value

    def test_asked_and_focus_terms(self):
        n = E.analyze_question("Which authorization object is needed for the pump?")
        self.assertEqual(n.asked, ("authoriz",))
        self.assertNotIn("need", n.focus)
        self.assertEqual(E.analyze_question("What must be active?").asked, ("activ",))            # modal verbs are not the asked-for thing

    def test_stem_conflates_manage_forms(self):
        self.assertEqual({E.stem2(w) for w in ("manage", "manages", "managed", "management", "managing")}, {"manag"})

    def test_stemmer_conflates_derivations_without_merging_distinct_words(self):
        for group in (("calculate", "calculated", "calculates", "calculating", "calculation", "calculations"), ("authorize", "authorized", "authorization"), ("process", "processes", "processing"),
                      ("create", "created", "creates", "creation"), ("install", "installs", "installed")):
            self.assertEqual(len({E.stem2(w) for w in group}), 1, group)
        self.assertNotEqual(E.stem2("installment"), E.stem2("installation"))
        self.assertNotEqual(E.stem2("bill"), E.stem2("billing") + "x")

    def test_question_meta_nouns_are_not_asked_for_terms(self):
        self.assertEqual(E.analyze_question("What is the relationship between pumps and valves?").asked, ())
        self.assertNotIn(E.stem2("relationship"), E.analyze_question("What is the relationship between pumps and valves?").focus)

    def test_limit_cue_word_is_a_kind_not_a_focus_term(self):
        n = E.analyze_question("What is the maximum pump pressure?")
        self.assertIn("limit", n.kinds)
        self.assertNotIn(E.stem2("maximum"), n.focus)

    def test_code_words(self):
        self.assertEqual(E.analyze_question("Which transaction creates a plan?").code_words, ("transaction", "t-code", "tcode"))
        self.assertEqual(E.analyze_question("Which function module is called?").code_words, ("function module",))


class SufficiencyDecision(unittest.TestCase):
    def decide(self, q, context=PAGE, tau=0.5):
        return E.assess(E.analyze_question(q), E.build_units(context.items), tau)

    def test_supported_fact_is_answered(self):
        d, units = self.decide("What does the widget controller manage?")
        self.assertTrue(d.supported, d)
        self.assertIn("pump", units[0].text)

    def test_related_but_insufficient_is_refused(self):
        d, _ = self.decide("What is the minimum pump runtime?")
        self.assertFalse(d.supported)
        self.assertEqual(d.reason, "KIND_NOT_IN_EVIDENCE")

    def test_asked_term_absent_is_refused(self):
        d, _ = self.decide("Which authorization object does the pump need?")
        self.assertEqual((d.supported, d.reason), (False, "ASKED_TERM_NOT_IN_EVIDENCE"))

    def test_code_question_needs_a_code_that_names_the_asked_kind(self):
        d, units = self.decide("Which transaction starts the pump?")
        self.assertTrue(d.supported, d)
        self.assertTrue(any("ZW10" in u.full_text() for u in units))
        no_code = ctx(item("S1", "Every transaction that starts the pump is started from the main panel by an operator."))
        self.assertEqual(self.decide("Which transaction starts the pump?", no_code)[0].reason, "KIND_NOT_IN_EVIDENCE")
        self.assertEqual(self.decide("Which transaction starts the pump?", ctx(item("S1", "The pump is started from the main panel.")))[0].reason, "ASKED_TERM_NOT_IN_EVIDENCE")
        other_code = ctx(item("S1", "Event 3000 is defined in function module ZFM_SAMPLE_3000 for the pump."))
        self.assertFalse(self.decide("Which transaction starts the pump?", other_code)[0].supported)       # a code of another kind does not answer a transaction question

    def test_number_question_needs_a_number(self):
        self.assertTrue(self.decide("How many minutes does the pump run?")[0].supported)
        self.assertFalse(self.decide("How many valves does the controller manage?", ctx(item("S1", "The controller manages several valves.")))[0].supported)

    def test_limit_needs_the_matching_direction(self):
        c = ctx(item("S1", "The pump pressure has an upper limit of 5 bar."))
        self.assertTrue(self.decide("What is the maximum pump pressure?", c)[0].supported)
        self.assertFalse(self.decide("What is the minimum pump pressure?", c)[0].supported)

    def test_low_coverage_is_refused_and_empty_is_refused(self):
        self.assertEqual(self.decide("Explain turbine blade maintenance schedules")[0].reason, "LOW_FOCUS_COVERAGE")
        self.assertEqual(E.assess(E.analyze_question("???"), [])[0].reason, "NO_QUERY_TERMS")
        self.assertEqual(E.assess(E.analyze_question("pump"), [])[0].reason, "NO_EVIDENCE")

    def test_heading_counts_as_context_but_weighs_less_than_the_sentence(self):
        n = E.analyze_question("What does the widget controller manage?")
        u = E.build_units(PAGE.items)[0]
        self.assertGreater(E.unit_score(u, n), 0.5)
        only_heading = E.build_units([item("S1", "It is started from the main panel.", ("Widget Controller > Purpose",))])[0]
        self.assertEqual(E.unit_score(only_heading, n), 0.0)                 # no own term -> never selected on the heading alone


class IdfWeighting(unittest.TestCase):
    """IDF weighting is an ablation switch (OFF by default: it over-abstained on DEV2); these tests pin its mechanics and that OFF means uniform weights."""

    def setUp(self):
        self._old, E.USE_IDF = E.USE_IDF, True

    def tearDown(self):
        E.USE_IDF = self._old

    def test_default_is_off_and_off_means_uniform(self):
        E.USE_IDF = False
        self.assertEqual(set(E.focus_weights(E.analyze_question("pump valve"), E.build_units([item("S1", "The pump runs.")])).values()), {1.0})

    def test_topic_words_in_every_sentence_weigh_less_than_the_predicate(self):
        """The sentence that states the asked predicate must beat a sentence that only repeats the page topic."""
        c = ctx(item("S1", "An installment plan can be created for a contract account. The installment plan has several installments. An installment plan is paid in installments.", ("Plan > Basics",)),
                item("S2", "When you calculate interest on the installment plan, the system creates an interest document automatically.", ("Plan > Interest",), rank=2))
        g = E.EvidenceExtractiveGenerator(0.5)
        r = g.generate("What happens when I calculate interest on an installment plan?", c)
        self.assertFalse(r.refused)
        self.assertEqual(g.last["selected"][0]["marker"], "S2")

    def test_weights_are_larger_for_rarer_and_largest_for_absent_terms(self):
        units = E.build_units([item("S1", "The pump pump pump. The pump runs. The pump stops. The valve opens.")])
        w = E.focus_weights(E.analyze_question("pump valve turbine"), units)
        self.assertLess(w[E.stem2("pump")], w[E.stem2("valve")])
        self.assertLess(w[E.stem2("valve")], w[E.stem2("turbine")])


class GeneratorBehaviour(unittest.TestCase):
    def test_answer_cites_the_chunk_that_contains_the_sentence(self):
        g = E.EvidenceExtractiveGenerator(0.5)
        r = g.generate("Which transaction starts the pump?", PAGE)
        self.assertFalse(r.refused)
        self.assertIn("Transaction ZW10 [S2]", r.text)
        self.assertIn("start the pump in manual mode. [S2]", r.text)
        self.assertNotIn("[S1]", r.text)
        self.assertTrue(E.verify_support_chain(r.text, PAGE)["ok"])
        self.assertTrue(verify_grounding(r.text, PAGE).ok)
        self.assertEqual(g.last["selected"][0]["marker"], "S2")

    def test_refusal_uses_the_standard_no_answer_text_and_records_the_reason(self):
        g = E.EvidenceExtractiveGenerator(0.5)
        r = g.generate("What is the minimum pump runtime?", PAGE)
        self.assertTrue(r.refused)
        self.assertEqual(r.text, NO_ANSWER_TEXT)
        self.assertEqual(g.last["reason"], "KIND_NOT_IN_EVIDENCE")

    def test_header_line_is_not_repeated(self):
        c = ctx(item("S1", "Transaction ZW10\nYou can use this transaction to start the pump.\nYou can use this transaction to stop the pump.", ("Pump > Operation",)))
        text = E.EvidenceExtractiveGenerator(0.5).generate("Which transaction starts the pump?", c).text
        self.assertEqual(text.count("Transaction ZW10 [S1]"), 1)

    def test_deterministic(self):
        g = E.EvidenceExtractiveGenerator(0.5)
        self.assertEqual(g.generate("What does the widget controller manage?", PAGE).text, g.generate("What does the widget controller manage?", PAGE).text)

    def test_never_emits_text_that_is_not_in_the_context(self):
        for q in ("What does the widget controller manage?", "Which transaction starts the pump?", "How many minutes does the pump run?", "How is the controller started?"):
            r = E.EvidenceExtractiveGenerator(0.5).generate(q, PAGE)
            if not r.refused:
                self.assertTrue(E.verify_support_chain(r.text, PAGE)["verbatim_all"], q)


class SupportChain(unittest.TestCase):
    def test_verbatim_span_of_the_cited_chunk_passes(self):
        self.assertTrue(E.verify_support_chain("The pump runs for 30 minutes. [S2]", PAGE)["ok"])

    def test_sentence_from_another_chunk_than_its_marker_fails(self):
        self.assertFalse(E.verify_support_chain("The pump runs for 30 minutes. [S1]", PAGE)["ok"])

    def test_paraphrase_or_invented_marker_fails(self):
        self.assertFalse(E.verify_support_chain("The pump keeps going for half an hour. [S2]", PAGE)["ok"])
        self.assertFalse(E.verify_support_chain("The pump runs for 30 minutes. [S9]", PAGE)["ok"])

    def test_empty_answer_is_not_a_chain(self):
        self.assertFalse(E.verify_support_chain("", PAGE)["ok"])

    def test_same_page_unrelated_chunk_cannot_become_the_citation(self):
        r = E.EvidenceExtractiveGenerator(0.5).generate("What does the widget controller manage?", PAGE)
        self.assertEqual(set(re.findall(r"\[(S\d+)\]", r.text)), {"S1"})        # S2 comes from the same page but does not state the fact


class _Hit:
    def __init__(self, i, text, heading="Gadget > Use"):
        self.rank, self.chunk_id, self.text, self.heading_path, self.title = i, f"g/p/{i}", text, tuple(heading.split(" > ")), "Gadget"
        self.metadata = {}
        self.guide_id, self.page_id, self.chunk_index = "g", "p", i


class _Base:
    def __init__(self, chunks):
        self.chunks, self.calls = chunks, []

    def page_chunks(self, g, p):
        return list(self.chunks)

    def retrieve_in_page(self, q, g, p, top_k=5):
        self.calls.append(top_k)
        return [self._rank(i + 1, h) for i, h in enumerate(self.chunks[:top_k])]

    @staticmethod
    def _rank(i, h):
        h2 = _Hit(i, h.text)
        h2.chunk_id = h.chunk_id
        return h2


class Widening(unittest.TestCase):
    def setUp(self):
        import dataclasses

        @dataclasses.dataclass(frozen=True)
        class H:
            rank: int
            chunk_id: str
            text: str
            heading_path: tuple
            title: str
            metadata: dict = dataclasses.field(default_factory=dict, compare=False)
        self.H = H
        self.chunks = [H(1, "g/p/0", "The pump is started from the main panel.", ("Pump > Use",), "Pump"), H(2, "g/p/1", "Filters are replaced every year.", ("Pump > Care",), "Pump"),
                       H(3, "g/p/2", "Transaction ZW10\nYou can use this transaction to start the pump in manual mode.", ("Pump > Operation",), "Pump")]

    def base(self):
        h = self.H
        chunks = self.chunks

        class B:
            calls = []

            def page_chunks(self, g, p):
                return list(chunks)

            def retrieve_in_page(self, q, g, p, top_k=5):
                return [h(i + 1, c.chunk_id, c.text, c.heading_path, c.title) for i, c in enumerate(chunks[:top_k])]
        return B()

    def test_promotes_the_same_page_chunk_that_can_supply_the_asked_kind(self):
        r = E.EvidenceRetriever(self.base(), 0.5)
        hits = r.retrieve_in_page("Which transaction starts the pump?", "g", "p", top_k=2)
        self.assertEqual(hits[0].chunk_id, "g/p/2")
        self.assertEqual(hits[0].rank, 1)
        self.assertEqual(hits[0].metadata["promoted"], "detail_evidence")
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h.chunk_id.startswith("g/p/") for h in hits))

    def test_no_promotion_for_questions_without_a_required_kind(self):
        r = E.EvidenceRetriever(self.base(), 0.5)
        self.assertEqual([h.chunk_id for h in r.retrieve_in_page("How is the pump started?", "g", "p", top_k=2)], ["g/p/0", "g/p/1"])

    def test_no_promotion_when_no_chunk_can_supply_it(self):
        r = E.EvidenceRetriever(self.base(), 0.5)
        hits = r.retrieve_in_page("What is the minimum pump runtime?", "g", "p", top_k=2)
        self.assertEqual([h.chunk_id for h in hits], ["g/p/0", "g/p/1"])
        self.assertIsNone(r.last_promoted)

    def test_delegates_other_attributes(self):
        self.assertEqual(len(E.EvidenceRetriever(self.base()).page_chunks("g", "p")), 3)


class Guard(unittest.TestCase):
    class _Inner:
        name = "llm"

        def __init__(self, text):
            self.text, self.calls = text, 0

        def generate(self, q, c):
            self.calls += 1
            return GenerationResult(self.text, False, self.name, self.text)

    def test_model_is_not_called_when_the_evidence_cannot_contain_the_answer(self):
        inner = self._Inner("The minimum is 3 minutes. [S2]")
        r = E.EvidenceGuard(inner, 0.5).generate("What is the minimum pump runtime?", PAGE)
        self.assertTrue(r.refused)
        self.assertEqual(inner.calls, 0)

    def test_answer_without_the_asked_kind_is_withheld(self):
        r = E.EvidenceGuard(self._Inner("The pump can be started in manual mode. [S2]"), 0.5).generate("Which transaction starts the pump?", PAGE)
        self.assertTrue(r.refused)

    def test_good_answer_passes_through_unchanged(self):
        inner = self._Inner("Use transaction ZW10 to start the pump. [S2]")
        r = E.EvidenceGuard(inner, 0.5).generate("Which transaction starts the pump?", PAGE)
        self.assertFalse(r.refused)
        self.assertEqual(r.text, "Use transaction ZW10 to start the pump. [S2]")


class NoQuestionSpecificCode(unittest.TestCase):
    def test_module_contains_no_evaluation_question_text_or_corpus_identifiers(self):
        src = (ROOT / "scripts" / "rag_evidence.py").read_text(encoding="utf-8").lower()
        for banned in ("fpr1", "el31", "el32", "installment", "m2c-", "e16", "e04", "device management", "p10d", "p111h", "p9-", "p8-"):
            self.assertNotIn(banned, src, banned)

    def test_every_phase11_1_holdout_and_e2e_question_text_is_absent_from_the_module(self):
        import json
        src = (ROOT / "scripts" / "rag_evidence.py").read_text(encoding="utf-8").lower()
        for f, key in (("phase11_1_holdout_questions.json", "query"), ("phase11_e2e_questions.json", "question")):
            for q in json.loads((ROOT / "data" / "evaluation" / f).read_text(encoding="utf-8"))["queries" if key == "query" else "questions"]:
                self.assertNotIn(q[key].lower().rstrip("?"), src)


if __name__ == "__main__":
    unittest.main()
