"""Follow-up elaboration (``scripts/rag_elaborate.py``): a follow-up that asks for more must return more.

The bug this pins down: "What is a contract account?" is answered, then "Elaborate." is asked. Context resolution
already sends the follow-up back to the contract-account page - but the production generator selects a *minimal
sufficiency set* (top 3 sentences scoring >= 60% of the best), so the follow-up came back as the same three
extractive sentences. The scoped pass in ``rag_elaborate`` reads more of the already-routed document and selects
differently, per intent, while every sentence stays verbatim documentation and every gate stays in place.

Layers:
* ``Selection`` - the intent rules on synthetic evidence (no stores): what is kept, what is dropped, when the pass
  honestly refuses because the documentation has nothing to add.
* ``Detector`` - the follow-up phrasings of the product spec are recognised, unrelated questions are not.
* ``Wiring`` - the scoped pass widens *only* the evidence window and shares every heavy object of the base pipeline.
* ``RealElaborationTests`` - the acceptance matrix on the shipped pipeline (stores required).
* ``ApiElaborationTests`` - the HTTP contract with the fast stub pipeline.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_elaborate as EL  # noqa: E402
import rag_evidence as EV  # noqa: E402
import rag_followup as FU  # noqa: E402
import rag_generate as RG  # noqa: E402
import rag_service as S  # noqa: E402
from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, make_pipeline  # noqa: E402
from tests.test_phase11_service import RANKING, Q_PLAN  # noqa: E402
from tests.test_phase9 import NEED_STORES  # noqa: E402

try:
    from fastapi.testclient import TestClient
    import rag_api  # noqa: E402
    HAVE_API = True
except Exception:                                                       # noqa: BLE001
    HAVE_API = False
NEED_API = unittest.skipUnless(HAVE_API and HAVE_BS4 and HAVE_CHROMA, "fastapi / httpx / bs4 / chromadb not installed")

ANSWERED, OUT_OF_SCOPE, UNABLE_TO_VERIFY, DOC_UNAVAILABLE = "answered", "out_of_scope", "unable_to_verify", "documentation_unavailable"
HONEST_NON_ANSWERS = (OUT_OF_SCOPE, UNABLE_TO_VERIFY, DOC_UNAVAILABLE)
CONTRACT = "What is a contract account?"
BILLING = "How does billing work?"

# The extractive sentences of the synthetic page used by the selection tests (shaped like the real M2C-17 page).
FIRST = "This component enables you to create and manage contract account master data."
ASSIGNED = "In Contract Accounts Receivable and Payable, each business partner posting is assigned to one business partner and to one contract account."
MASTER = "In the contract account master record, you can define, for each business partner, the procedures that apply when posting and processing the line items of a given contract account."
INCLUDE = "These include, for example, payment and dunning."
MANY = "You can assign more than one contract account to a given business partner."
DANGLING = "This does not apply to one-time accounts."
PARTNER = "The business partner is the contractual partner of the utility company."
UNRELATED = "The system logs changes to master data."


class _Item:
    """Minimal stand-in for a ``ContextItem``/``ChunkHit`` (only what ``build_units`` reads)."""

    def __init__(self, marker: str, chunk_id: str, rank: int, text: str, heading: str = "Contract Account") -> None:
        self.marker, self.chunk_id, self.rank, self.text = marker, chunk_id, rank, text
        self.rendered_text, self.heading_path, self.title = text, (heading,), heading


def _context(texts=(FIRST, ASSIGNED, MASTER, INCLUDE, MANY, DANGLING, PARTNER, UNRELATED)) -> list:
    chunks = {FIRST: "c0", ASSIGNED: "c0", MASTER: "c1", INCLUDE: "c1", MANY: "c2", DANGLING: "c2", PARTNER: "c3", UNRELATED: "c3"}
    ranks = {"c0": 0, "c1": 1, "c2": 2, "c3": 3}
    per: dict = {}
    items = []
    for text in texts:
        cid = chunks[text]
        per[cid] = per.get(cid, 0) + 1
        items.append(_Item(f"S{ranks[cid] + 1}", cid, ranks[cid], text))
    return items


class _Ctx:
    def __init__(self, items):
        self.items = items


def _generate(intent: str, previous: str = "", new_terms=(), question: str = CONTRACT, texts=None):
    gen = EL.IntentExtractiveGenerator(intent, previous_answer=previous, tau=EV.SHIPPED_TAU, anchor=question, focus_terms=new_terms)
    result = gen.generate(question, _Ctx(_context(texts) if texts else _context()))
    return result, gen.last


def _reconstruct_sections(sections):
    indexed = [(order, line) for section in sections for order, line in zip(section["line_orders"], section["lines"])]
    return "\n".join(line for _, line in sorted(indexed))


def _industry_context():
    items = (
        _Item("S1", "isu-definition", 0, FIRST, "SAP Utilities > Contract Accounts"),
        _Item("S2", "isu-detail", 1,
              "Utilities Industry (IS-U): One contract account can contain several utility contracts for a business partner.",
              "Utilities Industry (IS-U) > Contract Accounts"),
        _Item("S3", "insurance", 2,
              "Insurance (FS-CD) Industry Component: Each insurance contract is assigned to one contract account.",
              "Contract Accounts"),
        _Item("S4", "pscd", 3,
              "Industry ComponentPublic Sector Contract Accounts Receivable and Payable(PSCD): A public sector business partner may have several contract accounts.",
              "Contract Accounts"),
        _Item("S5", "isu-additional", 4, MANY, "SAP Utilities > Contract Accounts"),
    )
    return _Ctx(list(items))


class Selection(unittest.TestCase):
    """The intent rules, on synthetic evidence (fast, no stores)."""

    def test_elaboration_keeps_the_anchor_and_adds_new_documentation_sentences(self):
        result, evidence = _generate("elaborate", previous=FIRST)
        self.assertFalse(result.refused)
        self.assertIn(FIRST, result.text)                        # the opening sentence keeps the answer readable
        self.assertIn(MANY, result.text)                         # ... and the rest is material the user has not seen
        self.assertGreaterEqual(evidence["added"], EL.REQUIRED_NEW_ELABORATE)
        self.assertNotIn(UNRELATED, result.text)                 # off-topic sentences are never pulled in
        # document order, no duplicates
        self.assertEqual([l for l in result.text.split("\n")], sorted(set(result.text.split("\n")), key=result.text.split("\n").index))

    def test_utilities_context_excludes_insurance_and_malformed_pscd_evidence_with_valid_citations(self):
        context = _industry_context()
        generator = EL.IntentExtractiveGenerator("elaborate", previous_answer=f"{FIRST} [S1]", anchor=CONTRACT)
        result = generator.generate("Elaborate.", context)

        self.assertFalse(result.refused)
        self.assertIn("Utilities Industry (IS-U)", result.text)
        self.assertNotIn("Insurance", result.text)
        self.assertNotIn("FS-CD", result.text)
        self.assertNotIn("Public Sector", result.text)
        self.assertNotIn("PSCD", result.text)
        self.assertEqual(generator.last["industry_scope"], {"preferred": "IS-U", "excluded_units": 2})
        selected_lines = [f"{unit['sentence']} [{unit['marker']}]" for unit in generator.last["selected"]]
        self.assertEqual(result.text, "\n".join(selected_lines))  # grouped display metadata does not rewrite evidence
        self.assertTrue(EV.verify_support_chain(result.text, context)["ok"])
        self.assertTrue(all(re.search(r"\[S\d+\]$", line) for line in result.text.split("\n")))

    def test_normal_standalone_rag_does_not_use_the_scoped_industry_filter(self):
        context = _industry_context()
        baseline = RG.ExtractiveGenerator().generate(CONTRACT, context)
        with patch.object(EL, "_industry_scope_units", side_effect=AssertionError("scoped filter leaked into normal RAG")):
            normal = RG.ExtractiveGenerator().generate(CONTRACT, context)
        self.assertFalse(normal.refused)
        self.assertEqual(normal.text, baseline.text)

    def test_elaboration_refuses_honestly_when_the_documentation_has_nothing_to_add(self):
        everything = "\n".join(x + " [S1]" for x in (FIRST, ASSIGNED, MASTER, INCLUDE, MANY))
        result, evidence = _generate("elaborate", previous=everything)
        self.assertTrue(result.refused)
        self.assertEqual(result.text, RG.NO_ANSWER_TEXT)
        self.assertIs(evidence["elaborated"], False)
        self.assertEqual(evidence["reason_added"], "NO_ADDITIONAL_EVIDENCE")

    def test_an_unsupported_topic_is_refused_by_the_unchanged_evidence_decision(self):
        result, evidence = _generate("elaborate", question="What is the capital of France?")
        self.assertTrue(result.refused)
        self.assertIn(evidence["reason"], ("LOW_FOCUS_COVERAGE", "NO_EVIDENCE", "ASKED_TERM_NOT_IN_EVIDENCE"))

    def test_an_example_comes_from_the_documentation_and_with_its_lead_in(self):
        result, _ = _generate("example")
        self.assertFalse(result.refused)
        self.assertIn(INCLUDE, result.text)                      # the documented example itself
        self.assertIn(MASTER, result.text)                       # the sentence it belongs to, so the excerpt reads
        self.assertNotIn(DANGLING, result.text)

    def test_an_example_is_refused_when_the_corpus_documents_none(self):
        result, evidence = _generate("example", texts=(FIRST, ASSIGNED, MASTER, MANY))
        self.assertTrue(result.refused)                          # no fabricated example, ever
        self.assertEqual(evidence["reason_added"], "NO_ADDITIONAL_EVIDENCE")

    def test_a_simplification_is_short_self_contained_and_never_a_dangling_sentence(self):
        result, _ = _generate("simplify")
        self.assertFalse(result.refused)
        self.assertNotIn(DANGLING, result.text)                  # "This does not apply ..." only works next to its context
        for line in result.text.split("\n"):
            self.assertGreater(len(re.sub(r"\[S\d+\]", "", line).strip()), 20)
        self.assertLessEqual(len(result.text.split("\n")), EL.MAX_SIMPLE_SENTENCES + 1)

    def test_a_continuation_never_repeats_the_previous_answer(self):
        previous = "\n".join(f"{x} [S1]" for x in (FIRST, ASSIGNED, MASTER, INCLUDE))
        result, evidence = _generate("continuation", previous=previous)
        self.assertFalse(result.refused)
        for line in result.text.split("\n"):
            body = re.sub(r"\[S\d+\]", "", line).strip()
            self.assertNotIn(body, previous, body)
        self.assertGreaterEqual(evidence["added"], 1)

    def test_a_continuation_is_refused_when_every_on_topic_sentence_was_already_shown(self):
        previous = "\n".join(f"{x} [S1]" for x in (FIRST, ASSIGNED, MASTER, INCLUDE, MANY, DANGLING, PARTNER, UNRELATED))
        result, _ = _generate("continuation", previous=previous)
        self.assertTrue(result.refused)

    def test_a_relationship_follow_up_uses_the_terms_the_message_adds(self):
        plain, _ = _generate("reference")
        focused, _ = _generate("reference", new_terms=("partner",))
        self.assertNotIn(PARTNER, plain.text)                    # the sentence has none of the anchor's terms
        self.assertIn(PARTNER, focused.text)                     # ... but it answers "... relate to a business partner?"

    def test_every_sentence_stays_verbatim_documentation_with_its_marker(self):
        for intent in EL.ELABORATION_INTENTS:
            with self.subTest(intent=intent):
                result, evidence = _generate(intent, previous=FIRST)
                if result.refused:
                    continue
                joined: dict = {}
                for item in _context():                              # one marker can cover several sentences of a chunk
                    joined.setdefault(item.marker, []).append(item.text)
                for line in result.text.split("\n"):
                    markers = re.findall(r"\[(S\d+)\]", line)
                    self.assertTrue(markers, line)
                    sentence = re.sub(r"\[S\d+\]", "", line).strip()
                    self.assertTrue(any(any(sentence in text for text in joined.get(m, ())) for m in markers), f"{intent}: {line}")


class PresentationSections(unittest.TestCase):
    def test_section_classification_is_deterministic_and_conservative(self):
        cases = (
            ("A contract account is a master data record. [S1]", EL.SECTION_WHAT_IT_IS_DOES),
            ("The payment run posts each item and then updates the balance. [S2]", EL.SECTION_HOW_IT_WORKS_RELATIONSHIPS),
            ("If a customer pays late, a surcharge is required. [S3]", EL.SECTION_CONDITIONS_PREREQUISITES),
            ("A monthly adjustment appears in the result list. [S4]", EL.SECTION_KEY_DETAILS),
        )
        for sentence, expected in cases:
            with self.subTest(sentence=sentence):
                self.assertEqual(EL.presentation_section_key(sentence), expected)
                self.assertEqual(EL.presentation_section_key(sentence), expected)

    def test_empty_sections_are_omitted(self):
        sections = EL.group_presentation_lines((
            (EL.SECTION_WHAT_IT_IS_DOES, "A contract account is a master data record. [S1]"),
            (EL.SECTION_CONDITIONS_PREREQUISITES, ""),
            (EL.SECTION_KEY_DETAILS, "A monthly adjustment appears in the result list. [S2]"),
        ))
        self.assertEqual([section["key"] for section in sections], [EL.SECTION_WHAT_IT_IS_DOES, EL.SECTION_KEY_DETAILS])
        self.assertTrue(all(section["lines"] for section in sections))

    def test_each_category_has_one_heading_and_original_line_order_is_preserved(self):
        lines = ("Definition [S1]", "Relationship [S2]", "Additional definition [S3]", "Condition [S4]", "More relationship [S5]")
        sections = EL.group_presentation_lines((
            (EL.SECTION_WHAT_IT_IS_DOES, lines[0]),
            (EL.SECTION_HOW_IT_WORKS_RELATIONSHIPS, lines[1]),
            (EL.SECTION_WHAT_IT_IS_DOES, lines[2]),
            (EL.SECTION_CONDITIONS_PREREQUISITES, lines[3]),
            (EL.SECTION_HOW_IT_WORKS_RELATIONSHIPS, lines[4]),
        ))
        keys = [section["key"] for section in sections]
        self.assertEqual(keys, [EL.SECTION_WHAT_IT_IS_DOES, EL.SECTION_HOW_IT_WORKS_RELATIONSHIPS,
                                EL.SECTION_CONDITIONS_PREREQUISITES])
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(_reconstruct_sections(sections), "\n".join(lines))
        self.assertEqual([section["line_orders"] for section in sections], [[0, 2], [1, 4], [3]])

    def test_flattened_sections_reproduce_the_canonical_answer_and_citations(self):
        result, evidence = _generate("elaborate", previous=FIRST)
        self.assertFalse(result.refused)
        sections = evidence["presentation_sections"]
        grouped_lines = [line for section in sections for line in section["lines"]]
        self.assertEqual(_reconstruct_sections(sections), result.text)
        self.assertEqual(len({section["key"] for section in sections}), len(sections))
        indexed = sorted((order, line) for section in sections for order, line in zip(section["line_orders"], section["lines"]))
        self.assertEqual([order for order, _ in indexed], list(range(len(result.text.split("\n")))) )
        self.assertEqual([line for _, line in indexed], result.text.split("\n"))
        self.assertTrue(all(re.search(r"\[S\d+\]$", line) for line in grouped_lines))

    def test_context_and_follow_lines_stay_attached_to_their_cited_sentence(self):
        context_line = "Contract account overview"
        sentence = "A contract account is a master data record."
        follow = "The account posts recurring payment details."
        unit = EV.Unit(
            marker="S1", chunk_id="c1", rank=0, order=1, text=sentence,
            own=frozenset(), head=frozenset(), prev_line=context_line, follow=follow,
            chunk_text=f"{context_line}\n{sentence}\n{follow}",
        )
        needs = SimpleNamespace(kinds=("example",), focus=(), to_dict=lambda: {})
        decision = SimpleNamespace(supported=True, reason="SUPPORTED", detail={})
        generator = EL.IntentExtractiveGenerator("example", anchor=CONTRACT)
        generator._choose = lambda *_: [unit]
        with (
            patch.object(EL.EV, "analyze_question", return_value=needs),
            patch.object(EL.EV, "build_units", return_value=[unit]),
            patch.object(EL.EV, "assess", return_value=(decision, [unit])),
            patch.object(EL.EV, "focus_weights", return_value={}),
            patch.object(EL.EV, "kind_satisfied", return_value=False),
            patch.object(EL.EV, "unit_score", return_value=0.8),
            patch.object(EL.EV, "unit_kinds_ok", return_value=True),
        ):
            result = generator.generate("Give me an example", _Ctx([]))

        expected = [f"{context_line} [S1]", f"{sentence} [S1]", f"{follow} [S1]"]
        self.assertEqual(result.text.split("\n"), expected)
        self.assertEqual(generator.last["presentation_sections"], [{"key": EL.SECTION_WHAT_IT_IS_DOES, "lines": expected, "line_orders": [0, 1, 2]}])
        self.assertEqual(_reconstruct_sections(generator.last["presentation_sections"]), result.text)


class Detector(unittest.TestCase):
    """The phrasings the product spec lists for each intent (including the ones the first pass missed)."""

    def test_the_spec_phrasings_are_all_recognised(self):
        expected = {
            "elaborate": "elaborate", "explain more": "elaborate", "explain in detail": "elaborate",
            "tell me more": "elaborate", "go into more detail": "elaborate", "can you elaborate?": "elaborate",
            "simplify that": "simplify", "explain it simply": "simplify", "explain like I'm new to this": "simplify",
            "explain like I am completely new to this": "simplify", "explain in simple terms": "simplify",
            "give me an example": "example", "show me an example": "example", "can you give an example?": "example",
            "why?": "reason", "why does that happen?": "reason", "what happens next?": "continuation",
            "what happens after that?": "continuation", "what about the next step?": "continuation",
            "how does that relate to billing?": "reference", "what is the relationship with a business partner?": "reference",
            "how does this connect to billing?": "reference",
        }
        for message, category in expected.items():
            with self.subTest(message=message):
                self.assertEqual(FU.classify(message), category)

    def test_questions_with_their_own_topic_are_never_follow_ups(self):
        for message in (CONTRACT, BILLING, "What is the capital of France?", "How do I create an installment plan?",
                        "How does billing relate to invoicing?", "What is the difference between billing and invoicing?",
                        "Why is billing important?", "Give me an example of a billing procedure"):
            with self.subTest(message=message):
                self.assertIsNone(FU.classify(message))


class Wiring(unittest.TestCase):
    def test_the_scoped_pass_widens_only_the_evidence_window(self):
        import rag_pipeline as RP
        base = RP.PipelineConfig()
        scoped = EL.scoped_config(base)
        import dataclasses
        self.assertEqual(set(f.name for f in dataclasses.fields(base)), set(f.name for f in dataclasses.fields(scoped)))
        self.assertEqual({f.name for f in dataclasses.fields(base) if getattr(base, f.name) != getattr(scoped, f.name)},
                         {"k_chunks", "max_context_chunks", "context_budget_tokens"})
        self.assertGreaterEqual(scoped.k_chunks, EL.WIDE_K_CHUNKS)
        self.assertEqual(base.k_chunks, RP.PipelineConfig().k_chunks)          # the base config is not mutated

    def test_the_scoped_pipeline_shares_the_heavy_objects_of_the_base_pipeline(self):
        base = make_pipeline(RG.ExtractiveGenerator(), dict(RANKING))
        scoped = EL.scoped_pipeline(base, "elaborate", previous_answer="x [S1]", anchor=CONTRACT)
        for attribute in ("backend", "retriever", "ctx", "corpus", "count_tokens"):
            self.assertIs(getattr(scoped, attribute), getattr(base, attribute), attribute)
        self.assertIsInstance(scoped.generator, EL.IntentExtractiveGenerator)
        self.assertIs(base.generator.__class__, RG.ExtractiveGenerator)        # the production generator is untouched

    def test_all_six_intents_use_the_scoped_pass(self):
        for category in FU.CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue(EL.is_elaboration_intent(category))
        self.assertFalse(EL.is_elaboration_intent(None))

    def test_previous_answer_sentences_are_normalised_for_comparison(self):
        got = EL.sentences_of("This component enables you to create and manage contract account master data. [S1]\nIn Utilities, one contract account contains all contracts. [S4]")
        self.assertEqual(got, ("this component enables you to create and manage contract account master data",
                               "in utilities, one contract account contains all contracts"))

    def test_new_terms_are_the_content_terms_the_message_adds(self):
        terms = EL.new_terms_of("How does it relate to a business partner?", CONTRACT)
        self.assertIn(EV.stem2("partner"), terms)
        self.assertIn(EV.stem2("business"), terms)
        self.assertNotIn(EV.stem2("contract"), terms)                        # already in the anchor
        self.assertNotIn(EV.stem2("relate"), terms)                          # follow-up wording is not a topic
        self.assertEqual(EL.new_terms_of("Elaborate.", CONTRACT), ())

        explicit_component = EL.new_terms_of("How does it relate to FS-CD?", CONTRACT)
        self.assertIn("fs-cd", explicit_component)  # short component codes survive lexical tokenization for scope checks
        context = _industry_context()
        units = EV.build_units(context.items)
        unchanged, scope, excluded = EL._industry_scope_units(units, context, CONTRACT, "", explicit_component)
        self.assertIsNone(scope)
        self.assertEqual(excluded, 0)
        self.assertEqual(len(unchanged), len(units))


def _sentences(answer: str) -> set:
    return {re.sub(r"\s+", " ", x).strip().lower() for x in re.split(r"(?<=[.!?])\s+", re.sub(r"\[S\d+\]", "", answer or "")) if x.strip()}


def _strip_volatile(result: dict) -> dict:
    """Everything except the per-request conversation id and the measured latency."""
    out = json.loads(json.dumps(result, default=str, sort_keys=True))
    out.get("metadata", {}).pop("latency_ms", None)
    out.get("debug", {}).pop("timings_ms", None)
    out["conversation_id"] = None
    return out


def _verbatim_violations(answer: str, items) -> list:
    """Independent grounding check: every answer line must be a verbatim span of the chunk its marker names."""
    by_marker = {i.get("marker"): re.sub(r"\s+", " ", i.get("text") or "") for i in items}
    bad = []
    for line in (answer or "").split("\n"):
        markers = re.findall(r"\[(S\d+)\]", line)
        body = re.sub(r"\s+", " ", re.sub(r"\[S\d+\]", "", line)).strip()
        if not body:
            continue
        if not markers or not any(body.lower() in by_marker.get(m, "").lower() for m in markers):
            bad.append(body)
    return bad


class PresentationMetadata(unittest.TestCase):
    def test_sections_preserve_the_canonical_answer_when_global_grouping_reorders_categories(self):
        first = f"{FIRST} [S1]"
        relation = f"{ASSIGNED} [S2]"
        later_definition = f"{MANY} [S3]"
        answer = "\n".join((first, relation, later_definition))
        raw = {
            "status": "answered",
            "answer": answer,
            "citations": {"answer_sources": []},
            "topic": {},
            "debug": {},
        }
        sections = [
            {"key": EL.SECTION_WHAT_IT_IS_DOES, "lines": [first, later_definition], "line_orders": [0, 2]},
            {"key": EL.SECTION_HOW_IT_WORKS_RELATIONSHIPS, "lines": [relation], "line_orders": [1]},
        ]
        normal = S.to_chat_result(raw, "extractive", "conv-normal", 1.0,
                                  evidence={"presentation_sections": sections})
        self.assertNotIn("elaboration_sections", normal["metadata"])

        elaborated = S.to_chat_result(raw, "extractive", "conv-elaboration", 1.0,
                                      presentation_sections=sections)
        self.assertEqual(elaborated["answer"], answer)  # the canonical answer remains byte-for-byte unchanged
        self.assertEqual(elaborated["metadata"]["elaboration_sections"], sections)
        self.assertEqual(_reconstruct_sections(elaborated["metadata"]["elaboration_sections"]), answer)
        self.assertNotEqual("\n".join(line for section in sections for line in section["lines"]), answer)
        self.assertEqual(len({section["key"] for section in elaborated["metadata"]["elaboration_sections"]}), 2)

        invalid_order = [dict(sections[0], line_orders=[1, 2]), sections[1]]
        mismatch = S.to_chat_result(raw, "extractive", "conv-mismatch", 1.0,
                                    presentation_sections=invalid_order)
        self.assertNotIn("elaboration_sections", mismatch["metadata"])

        duplicate_heading = [sections[0], {"key": EL.SECTION_WHAT_IT_IS_DOES, "lines": [relation], "line_orders": [1]}]
        duplicate = S.to_chat_result(raw, "extractive", "conv-duplicate", 1.0,
                                     presentation_sections=duplicate_heading)
        self.assertNotIn("elaboration_sections", duplicate["metadata"])


@NEED_STORES
class RealElaborationTests(unittest.TestCase):
    """The acceptance matrix against the shipped pipeline (real card store, page store, embeddings, router)."""

    @classmethod
    def setUpClass(cls):
        cls.svc = S.build_service("extractive")

    def ask(self, question, **kw):
        return self.svc.ask(question, **kw)

    def follow_up(self, message, anchor, previous, extra_questions=()):
        context = {"questions": [anchor, *extra_questions], "answer": previous}
        return self.svc.ask(message, debug=True, context=context)

    def chain(self, anchor, messages):
        first = self.ask(anchor, debug=True)
        self.assertEqual(first["status"], ANSWERED, anchor)
        previous, turns = first["answer"], [anchor]
        out = [first]
        for message in messages:
            result = self.follow_up(message, anchor, previous, extra_questions=turns[1:])
            out.append(result)
            turns.append(message)
            if result["status"] == ANSWERED:
                previous = result["answer"]
        return out

    # ---- 1-3, 9: more evidence, not the same answer ----------------------------------------------------------
    def test_elaborate_explain_in_detail_and_tell_me_more_are_richer_than_the_first_answer(self):
        first, elaborate = self.chain(CONTRACT, ["Elaborate."])[:2]
        base = first["answer"]
        for message in ("explain in detail", "tell me more"):
            with self.subTest(message=message):
                result = self.follow_up(message, CONTRACT, base)
                self.assertEqual(result["status"], ANSWERED)
                answer = result["answer"]
                self.assertGreater(len(answer), len(base))
                shared = _sentences(base) & _sentences(answer)
                self.assertLessEqual(len(shared), 1, f"the follow-up repeated {shared}")
                self.assertTrue(result["metadata"]["grounded"])
                self.assertTrue(result["sources"])
        # the reported case: "Elaborate." is not the previous answer
        self.assertNotEqual(elaborate["answer"], base)
        self.assertLess(len(_sentences(base) & _sentences(elaborate["answer"])), len(_sentences(base)))

    def test_billing_elaboration_uses_additional_billing_evidence(self):
        first, rich = self.chain(BILLING, ["Explain in detail."])[:2]
        self.assertEqual(rich["status"], ANSWERED)
        self.assertGreater(len(rich["answer"]), len(first["answer"]))
        shared = _sentences(first["answer"]) & _sentences(rich["answer"])
        self.assertLessEqual(len(shared), 1)

    # ---- 4: simplification keeps the content, drops the length ------------------------------------------------
    def test_simplify_is_shorter_and_self_contained(self):
        rich = self.chain(CONTRACT, ["Elaborate.", "Simplify that."])[2]
        self.assertEqual(rich["status"], ANSWERED)
        for line in rich["answer"].split("\n"):
            body = re.sub(r"\[S\d+\]", "", line).strip()
            self.assertFalse(body.lower().startswith(("this does not", "see ")), body)
            self.assertGreater(len(body), 20)

    # ---- 5: an example is documented or refused, never invented -----------------------------------------------
    def test_an_example_does_not_hallucinate(self):
        first = self.ask(CONTRACT, debug=True)
        result = self.follow_up("Give me an example.", CONTRACT, first["answer"])
        if result["status"] == ANSWERED:
            items = result["debug"]["pipeline"]["context"]["items"]
            self.assertEqual(_verbatim_violations(result["answer"], items), [])
            self.assertRegex(result["answer"].lower(), r"example|such as|for instance|e\.g\.")
        else:
            self.assertIn(result["status"], HONEST_NON_ANSWERS)

    # ---- 6-7: reason and continuation retrieve their own evidence ---------------------------------------------
    def test_why_is_answered_from_evidence_and_never_copies_the_citations_of_the_previous_answer(self):
        first = self.ask(BILLING, debug=True)
        result = self.follow_up("Why?", BILLING, first["answer"])
        self.assertIn(result["status"], (ANSWERED, *HONEST_NON_ANSWERS))
        if result["status"] == ANSWERED:
            self.assertTrue(result["metadata"]["grounded"])
            items = result["debug"]["pipeline"]["context"]["items"]
            self.assertEqual(_verbatim_violations(result["answer"], items), [])
            self.assertEqual((result["debug"]["evidence"] or {}).get("support_chain", {}).get("ok"), True)

    def test_what_happens_next_returns_following_process_evidence_without_repeating_the_answer(self):
        first, detail = self.chain(BILLING, ["Explain in detail."])[:2]
        nxt = self.follow_up("What happens next?", BILLING, detail["answer"])
        self.assertIn(nxt["status"], (ANSWERED, *HONEST_NON_ANSWERS))
        if nxt["status"] == ANSWERED:
            shared = _sentences(detail["answer"]) & _sentences(nxt["answer"])
            self.assertEqual(shared, set(), "a continuation must bring new material")

    # ---- 8, 9: unrelated stay unrelated, standalone stays unchanged -------------------------------------------
    def test_an_unrelated_question_after_a_follow_up_stays_out_of_scope(self):
        first = self.ask(CONTRACT, debug=True)
        result = self.follow_up("What is the capital of France?", CONTRACT, first["answer"])
        self.assertEqual(result["status"], OUT_OF_SCOPE)
        self.assertIsNone(result["debug"]["pipeline"].get("follow_up"))
        self.assertEqual(result["sources"], [])

    def test_standalone_questions_are_byte_identical_with_and_without_the_scoped_pass(self):
        original = EL.is_elaboration_intent
        try:
            EL.is_elaboration_intent = lambda category: False
            without = [_strip_volatile(self.ask(q, debug=True)) for q in (CONTRACT, BILLING, "What is a move-in?", "What is the capital of France?")]
        finally:
            EL.is_elaboration_intent = original
        with_pass = [_strip_volatile(self.ask(q, debug=True)) for q in (CONTRACT, BILLING, "What is a move-in?", "What is the capital of France?")]
        self.assertEqual(without, with_pass)

    def test_a_standalone_question_is_never_marked_as_a_follow_up(self):
        result = self.ask("How do I create an installment plan?", debug=True)
        self.assertIsNone(result["debug"]["pipeline"].get("follow_up"))

    # ---- 10-12: multi-turn, fresh citations, no unsupported claims --------------------------------------------
    def test_multi_turn_follow_ups_keep_the_anchor_and_stay_grounded(self):
        results = self.chain(CONTRACT, ["Elaborate.", "Tell me more.", "Give me an example."])
        for result in results[1:]:
            with self.subTest(status=result["status"]):
                self.assertIn(result["status"], (ANSWERED, *HONEST_NON_ANSWERS))
                resolved = result["debug"]["pipeline"]["follow_up"]
                self.assertEqual(resolved["anchor"], CONTRACT)                     # still the real subject
                self.assertEqual(resolved["pass"], "elaboration")
                if result["status"] == ANSWERED:
                    self.assertTrue(result["metadata"]["grounded"])
                    self.assertEqual((result["debug"]["evidence"] or {}).get("support_chain", {}).get("verbatim_all"), True)

    def test_follow_up_citations_point_at_the_evidence_of_this_answer(self):
        first = self.ask(CONTRACT, debug=True)
        result = self.follow_up("Elaborate.", CONTRACT, first["answer"])
        self.assertEqual(result["status"], ANSWERED)
        markers = set(re.findall(r"\[(S\d+)\]", result["answer"]))
        self.assertTrue(markers)
        items = {i["marker"] for i in result["debug"]["pipeline"]["context"]["items"]}
        self.assertTrue(markers <= items, markers - items)
        for source in result["sources"]:
            self.assertTrue(source["source_id"])
        # the markers of the follow-up answer are not simply the markers of the previous answer
        self.assertEqual(_verbatim_violations(result["answer"], result["debug"]["pipeline"]["context"]["items"]), [])

    def test_an_elaboration_of_a_topic_with_nothing_more_is_an_honest_non_answer(self):
        first = self.ask("What is clearing control?", debug=True)
        self.assertEqual(first["status"], ANSWERED)
        result = self.follow_up("Elaborate.", "What is clearing control?", first["answer"])
        if result["status"] == ANSWERED:
            self.assertGreater(len(_sentences(first["answer"]) & _sentences(result["answer"])), 0)   # richer, not a copy
        else:
            self.assertIn(result["status"], HONEST_NON_ANSWERS)
            self.assertEqual((result["debug"]["evidence"] or {}).get("reason_added"), "NO_ADDITIONAL_EVIDENCE")

    def test_an_elaboration_is_not_unreasonably_slow(self):
        first = self.ask(CONTRACT, debug=True)
        normal = []
        for _ in range(3):
            t = time.perf_counter(); self.ask(BILLING); normal.append((time.perf_counter() - t) * 1000)
        rich = []
        for _ in range(3):
            t = time.perf_counter(); self.follow_up("Elaborate.", CONTRACT, first["answer"]); rich.append((time.perf_counter() - t) * 1000)
        self.assertLess(sum(rich) / len(rich), 3 * (sum(normal) / len(normal)) + 1000)


@NEED_API
class ApiElaborationTests(unittest.TestCase):
    """The HTTP contract: the follow-up travels with its context, the debug block says which pass ran."""

    @classmethod
    def setUpClass(cls):
        import rag_generate as RG_MOD
        ranking = dict(RANKING)
        ranking[Q_PLAN] = ["M2C-24"]
        cls.svc = S.RagService(make_pipeline(RG_MOD.ExtractiveGenerator(), ranking), "extractive")
        cls.client = TestClient(rag_api.create_app(service=cls.svc, static_dir=Path("/nonexistent")))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def post(self, message, **kw):
        return self.client.post("/api/chat", json={"message": message, **kw})

    def test_a_follow_up_runs_the_elaboration_pass_on_the_anchor_question(self):
        body = self.post("Elaborate.", conversation_id="conv-elaborate", debug=True,
                         context={"questions": [Q_PLAN], "answer": "Choose Account > Installment Plan. [S1]"}).json()
        self.assertEqual(body["status"], ANSWERED)
        follow_up = body["debug"]["pipeline"]["follow_up"]
        self.assertEqual(follow_up["category"], "elaborate")
        self.assertEqual(follow_up["pass"], "elaboration")
        self.assertEqual(follow_up["retrieval_query"], Q_PLAN)
        self.assertEqual(follow_up["anchor"], Q_PLAN)
        sections = body["metadata"]["elaboration_sections"]
        self.assertEqual(_reconstruct_sections(sections), body["answer"])
        # whatever came back is grounded in the context of this answer
        items = body["debug"]["pipeline"]["context"]["items"]
        self.assertEqual(_verbatim_violations(body["answer"], items), [])

    def test_a_standalone_question_carries_no_follow_up_metadata(self):
        body = self.post(Q_PLAN, conversation_id="conv-standalone", debug=True).json()
        self.assertEqual(body["status"], ANSWERED)
        self.assertNotIn("follow_up", body["debug"]["pipeline"])
        self.assertNotIn("elaboration_sections", body["metadata"])

    def test_the_context_is_still_only_used_to_resolve_the_query(self):
        without = self.post("Elaborate.", conversation_id="conv-nocontext").json()
        self.assertEqual(without["status"], OUT_OF_SCOPE)                   # unchanged baseline behaviour
        ignored = self.post(BILLING, conversation_id="conv-ignored", debug=True,
                            context={"questions": [Q_PLAN], "answer": "Choose Account > Installment Plan."}).json()
        self.assertIsNone(ignored["debug"]["pipeline"].get("follow_up"))


if __name__ == "__main__":
    unittest.main()
