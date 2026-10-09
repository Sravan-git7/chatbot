"""Context-aware follow-up resolution (``scripts/rag_followup.py`` + the optional ``context`` of ``POST /api/chat``).

These tests pin down the follow-up contract: the UI must send only eligible context from the selected conversation,
while a bare elaboration alias without that context must clarify safely instead of reaching ordinary topic routing.

Three layers, matching how the feature is built:
* ``Detector`` / ``Resolution`` - pure functions, no stores: what counts as a context-dependent follow-up, what the
  resolved query looks like, and what must stay untouched.
* ``ApiContextTests`` - the HTTP contract with the fast stub pipeline (fixed ranking): the context travels, the
  resolved query is what reaches the pipeline, a standalone question is never rewritten, malformed context is refused.
* ``RealFollowUpTests`` - the acceptance runs against the real card store, page store, embedding model and router
  (skipped when those are absent). Nothing here is asserted from a stub: it is the shipped pipeline.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rag_followup as FU  # noqa: E402
import rag_service as S  # noqa: E402
import rag_text as T  # noqa: E402
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
NO_ADDITIONAL_VERIFIED_EVIDENCE = "no_additional_verified_evidence"
HONEST_NON_ANSWERS = (OUT_OF_SCOPE, UNABLE_TO_VERIFY, DOC_UNAVAILABLE, NO_ADDITIONAL_VERIFIED_EVIDENCE)

CONTRACT = "What is a contract account?"
BILLING = "How does billing work?"
BILL_CREATED = "What happens after a bill is created?"

# The reported case: a message with no topic of its own, and the categories the product spec lists.
FOLLOW_UP_EXAMPLES = {
    "elaborate": "elaborate",
    "Elaborate.": "elaborate",
    "elaborat": "elaborate",
    "elaboratee": "elaborate",
    "elabroate": "elaborate",
    "explain": "elaborate",
    "explain more": "elaborate",
    "explain in detail": "elaborate",
    "explain in more detail": "elaborate",
    "tell me more": "elaborate",
    "explain that": "elaborate",
    "can you explain further?": "elaborate",
    "go into more detail": "elaborate",
    "what does that mean?": "reference",
    "what about this?": "reference",
    "how?": "reference",
    "why?": "reason",
    "why is that?": "reason",
    "Explain why companies use it.": "reason",
    "give me an example": "example",
    "show me an example": "example",
    "what happens next?": "continuation",
    "what happens after that?": "continuation",
    "and then?": "continuation",
    "what about the next step?": "continuation",
    "simplify that": "simplify",
    "in simple terms": "simplify",
    "How does it relate to a business partner?": "reference",
}

# Standalone questions must never be rewritten (the spec's counter-examples plus neighbours of the patterns above).
STANDALONE = (
    CONTRACT, BILLING, "What is the invoicing process?", "What is the capital of France?",
    "How is billing handled?", "How do I create an installment plan?", BILL_CREATED,
    "Explain how billing works",                       # has its own topic: "explain" does not make it a follow-up
    "Explain in detail how billing works",
    "Give me an example of a billing procedure",
    "Why is billing important?",
    "How does billing relate to invoicing?",
    "What happens after a bill is created in SAP?",
    "What does a contract account contain?",
    "What is electricity?", "electricity", "elaborated",
    "Summarize the dunning process",
    "How many dunning levels exist?",
    "What is the difference between billing and invoicing?",
    "thanks", "hello",
)


class Detector(unittest.TestCase):
    def test_context_dependent_messages_are_detected_with_their_category(self):
        for message, category in FOLLOW_UP_EXAMPLES.items():
            with self.subTest(message=message):
                self.assertEqual(FU.classify(message), category)

    def test_standalone_questions_are_never_treated_as_follow_ups(self):
        for message in STANDALONE:
            with self.subTest(message=message):
                self.assertIsNone(FU.classify(message))

    def test_detection_is_bounded(self):
        self.assertIsNone(FU.classify(""))
        self.assertIsNone(FU.classify("   "))
        self.assertIsNone(FU.classify("explain " + "x " * 1200))     # long messages are never resolved
        self.assertEqual(FU.classify("  ELABORATE!! "), "elaborate")  # case/punctuation/space insensitive
        self.assertEqual(FU.classify("Okay, elaborate"), "elaborate")  # leading filler is tolerated
        self.assertEqual(len(FOLLOW_UP_EXAMPLES), len(set((m.lower()) for m in FOLLOW_UP_EXAMPLES)))

    def test_typo_matching_is_one_word_and_bounded_not_a_domain_term_heuristic(self):
        for message in ("electricity", "elaborated", "elaborates", "elaborations", "elaborate about electricity"):
            with self.subTest(message=message):
                self.assertIsNone(FU.classify(message))
        self.assertEqual(FU.classify("elaborat"), "elaborate")
        self.assertIsNone(FU.resolve("electricity", {"questions": [CONTRACT], "answer": "A contract account is a record."}))
        self.assertIsNone(FU.resolve("elaborat", None))  # a typo alone is still not a topic or an answer


class Resolution(unittest.TestCase):
    ctx = {"questions": [CONTRACT], "answer": "A contract account holds the master data of a business partner."}

    def test_resolved_query_is_standalone_and_carries_the_anchor(self):
        for message in ("elaborate", "why?", "give me an example", "what happens next?", "simplify that"):
            with self.subTest(message=message):
                r = FU.resolve(message, self.ctx)
                self.assertIsNotNone(r, message)
                self.assertIn(CONTRACT, r["query"])
                self.assertLessEqual(len(r["query"]), FU.MAX_RESOLVED_CHARS)
                # the resolved query must never contain a fact the user or the docs did not bring: no numbers, no codes
                self.assertFalse(re.search(r"\d", r["query"]), r["query"])
                self.assertNotRegex(r["query"], r"\bM2C-\d+\b")

    def test_a_follow_up_that_names_its_own_topic_keeps_the_user_words(self):
        r = FU.resolve("How does it relate to a business partner?", self.ctx)
        self.assertEqual(r["category"], "reference")
        self.assertIn("business partner", r["query"])
        self.assertTrue(r["query"].startswith(CONTRACT))

    def test_anaphoric_why_question_uses_the_active_topic_without_guessing_from_its_own_words(self):
        message = "Explain why companies use it."
        active = {"active_topic": {"query": CONTRACT, "answer": self.ctx["answer"],
                                   "identity": {"source_id": "M2C-17", "guide_id": "contract-guide", "page_id": "contract-page"},
                                   "seen_answers": []}}
        resolved = FU.resolve(message, active)
        self.assertEqual(resolved["category"], "reason")
        self.assertEqual(resolved["anchor"], CONTRACT)
        self.assertEqual(resolved["anchor_source"], "active_topic")
        self.assertEqual(resolved["form"], "message")
        self.assertEqual(resolved["query"], f"{CONTRACT} {message}")
        self.assertIsNone(FU.resolve(message, None))

    def test_the_anchor_is_the_most_recent_question_that_stands_on_its_own(self):
        chained = {"questions": ["elaborate", "give me an example", CONTRACT], "answer": "..."}
        r = FU.resolve("elaborate", chained)
        self.assertEqual(r["anchor"], CONTRACT)
        self.assertEqual(r["anchor_index"], 2)

    def test_explicit_active_topic_beats_history_and_recommendation_text(self):
        active = {"query": BILLING, "answer": "Billing was answered.",
                  "identity": {"source_id": "M2C-12", "guide_id": "billing-guide", "page_id": "billing-page"},
                  "seen_answers": []}
        context = {"active_topic": active, "questions": [CONTRACT], "answer": "Contract Account suggestion text."}
        resolved = FU.resolve("elaborate", context)
        self.assertEqual(resolved["anchor"], BILLING)
        self.assertEqual(resolved["anchor_source"], "active_topic")
        self.assertEqual(resolved["anchor_index"], -1)

    def test_invalid_explicit_state_and_answerless_legacy_history_fail_closed(self):
        invalid = {"active_topic": {}, "questions": [BILLING], "answer": "Billing was answered."}
        self.assertIsNone(FU.resolve("elaborate", invalid))
        # A weather question may be the newest failed turn; without a successful-answer state, do not skip back to Billing.
        self.assertIsNone(FU.resolve("elaborate", {"questions": ["What is the weather today?", BILLING]}))

    def test_topic_switches_and_revisits_anchor_to_the_current_topic(self):
        plan = "How do I create an installment plan?"
        billing = "How is billing handled?"
        cases = (
            # A -> B -> elaborate: the newest standalone question B owns the active answer.
            ([plan, CONTRACT], plan),
            # A -> B -> A -> elaborate: a revisit to A supersedes both the old A and B.
            ([CONTRACT, plan, CONTRACT], CONTRACT),
            # A typo follow-up cannot become a new topic between B and its next elaboration.
            (["elaborat", plan, CONTRACT], plan),
            # Repeated follow-ups are skipped until the current standalone question is found.
            (["tell me more", "elaborate", billing, plan, CONTRACT], billing),
        )
        for questions, expected in cases:
            with self.subTest(questions=questions):
                resolved = FU.resolve("elaborate", {"questions": questions, "answer": f"Answer about {expected}."})
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved["anchor"], expected)
                self.assertEqual(resolved["query"], f"{expected} explain this more")

    def test_bounded_typos_resolve_against_the_last_real_topic_not_the_typo(self):
        for typo in ("elaborat", "elaboratee", "elabroate"):
            with self.subTest(typo=typo):
                resolved = FU.resolve("elaborate", {"questions": [typo, BILLING], "answer": "Billing answer."})
                self.assertEqual(resolved["anchor"], BILLING)
                current_typo = FU.resolve(typo, {"questions": [BILLING], "answer": "Billing answer."})
                self.assertEqual(current_typo["anchor"], BILLING)

    def test_query_rewriting_preserves_utilities_and_is_u_scope(self):
        anchor = "How does SAP Utilities (IS-U) manage contract accounts?"
        resolved = FU.resolve("Tell me more.", {"questions": [anchor], "answer": "..."})
        self.assertTrue(resolved["query"].startswith(anchor))
        self.assertIn("SAP Utilities (IS-U)", resolved["query"])
        self.assertEqual(resolved["query"], f"{anchor} explain this more")

    def test_only_the_preceding_turns_are_used(self):
        wide = {"questions": ["something else entirely", CONTRACT], "answer": "..."}
        self.assertEqual(FU.resolve("elaborate", wide)["anchor"], "something else entirely")  # most recent first
        self.assertEqual(FU.resolve("elaborate", {"questions": [CONTRACT], "answer": "The contract account is master data."})["anchor"], CONTRACT)

    def test_the_previous_answer_is_only_a_fallback_anchor(self):
        r = FU.resolve("elaborate", {"questions": [], "answer": "A contract account holds master data. More text."})
        self.assertEqual(r["anchor_source"], "previous_answer")
        self.assertEqual(r["anchor"], "A contract account holds master data.")
        # a one-word answer anchors nothing
        self.assertIsNone(FU.resolve("elaborate", {"questions": [], "answer": "Yes."}))

    def test_nothing_is_resolved_without_context_or_for_standalone_messages(self):
        self.assertIsNone(FU.resolve("elaborate", None))
        self.assertIsNone(FU.resolve("elaborate", {}))
        self.assertIsNone(FU.resolve("elaborate", {"questions": [], "answer": None}))
        self.assertIsNone(FU.resolve(CONTRACT, self.ctx))
        self.assertIsNone(FU.resolve("What is the capital of France?", self.ctx))
        for junk in ({"questions": "not a list"}, {"questions": [None, 12]}, {"questions": ["   "]}, {"questions": [""]}, "not a mapping"):
            self.assertIsNone(FU.resolve("elaborate", junk), junk)

    def test_clauses_add_no_new_content_terms_beyond_the_gates_vocabulary(self):
        """Measured on the shipped pipeline: clauses that introduce a content term flip marginal anchors between
        ``unable_to_verify`` and ``out_of_scope``. The clauses stay inside the stopword/question-frame vocabulary."""
        for category, clause in FU._CLAUSES.items():
            with self.subTest(category=category):
                extra = [t for t in T.terms(clause) if t not in {"exampler"} and t not in {"happen"}]
                self.assertLessEqual(len(extra), 1, f"{category}: {T.terms(clause)}")

    def test_debug_view_is_metadata_only(self):
        view = FU.debug_view(FU.resolve("elaborate", self.ctx), "elaborate")
        self.assertEqual(set(view), {"category", "anchor_source", "anchor", "message", "resolved_query"})
        self.assertIsNone(FU.debug_view(None, "elaborate"))


@NEED_API
class ApiContextTests(unittest.TestCase):
    """The HTTP contract, with the fast stub pipeline (fixed ranking per exact query string)."""

    RESOLVED = "How do I create an installment plan? explain this more"
    CONTRACT_RESOLVED = f"{CONTRACT} explain this more"

    @classmethod
    def setUpClass(cls):
        import rag_generate as RG
        ranking = dict(RANKING)
        ranking[CONTRACT] = ["M2C-17"]
        ranking[cls.RESOLVED] = ["M2C-24"]                       # the installment-plan query stays on its Utilities page
        ranking[cls.CONTRACT_RESOLVED] = ["M2C-17"]
        cls.svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), ranking), "extractive")
        cls.client = TestClient(rag_api.create_app(service=cls.svc, static_dir=Path("/nonexistent")))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def post(self, message, **kw):
        return self.client.post("/api/chat", json={"message": message, **kw})

    def test_a_follow_up_is_rewritten_before_the_pipeline_runs(self):
        without = self.post("elaborate", conversation_id="conv-followup-1")
        self.assertEqual(without.json()["status"], UNABLE_TO_VERIFY)
        self.assertEqual(without.json()["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertEqual(without.json()["sources"], [])
        with_ctx = self.post("elaborate", conversation_id="conv-followup-1", debug=True,
                             context={"questions": [Q_PLAN], "answer": "Choose Account > Installment Plan."})
        body = with_ctx.json()
        self.assertEqual(body["status"], ANSWERED, body)                   # ... and answered with context
        self.assertEqual(body["conversation_id"], "conv-followup-1")       # still ONE conversation
        self.assertTrue(body["sources"], "the answer must carry fresh citations")
        follow_up = body["debug"]["pipeline"]["follow_up"]
        self.assertEqual(follow_up["category"], "elaborate")
        self.assertEqual(follow_up["resolved_query"], self.RESOLVED)
        self.assertEqual(follow_up["anchor"], Q_PLAN)
        # the lexical gate saw the resolved query, i.e. the pipeline itself consumed it
        self.assertEqual(body["debug"]["pipeline"]["gate_topic"]["query_terms"], T.terms(self.RESOLVED))

    def test_api_context_after_topic_switches_and_typo_history_uses_the_current_anchor(self):
        scenarios = (
            ([Q_PLAN, CONTRACT], "The installment plan answer is the current answer.", Q_PLAN),
            ([CONTRACT, "Elaborate.", Q_PLAN, CONTRACT], "The contract account answer is current.", CONTRACT),
            (["elaborat", Q_PLAN, CONTRACT], "The installment plan answer is current.", Q_PLAN),
        )
        for index, (questions, answer, expected_anchor) in enumerate(scenarios):
            with self.subTest(questions=questions):
                body = self.post("elaborate", conversation_id=f"conv-switch-{index}", debug=True,
                                 context={"questions": questions, "answer": answer}).json()
                follow_up = body["debug"]["pipeline"]["follow_up"]
                self.assertEqual(follow_up["anchor"], expected_anchor)
                self.assertEqual(follow_up["retrieval_query"], expected_anchor)
                self.assertEqual(follow_up["pass"], "elaboration")
                self.assertEqual(body["metadata"]["generator"], "extractive")
                if body["status"] == ANSWERED:
                    self.assertTrue(body["sources"])
                    self.assertTrue(body["metadata"]["grounded"])

    def test_a_standalone_question_is_never_rewritten_even_when_context_is_sent(self):
        with_ctx = self.post(BILLING, conversation_id="conv-followup-2", debug=True,
                             context={"questions": [Q_PLAN], "answer": "..."})
        body = with_ctx.json()
        self.assertNotIn("follow_up", body["debug"]["pipeline"])
        plain = self.post(BILLING, conversation_id="conv-followup-2", debug=True).json()
        self.assertEqual((body["status"], body["answer"]), (plain["status"], plain["answer"]))
        self.assertEqual(body["debug"]["pipeline"]["gate_topic"]["query_terms"], plain["debug"]["pipeline"]["gate_topic"]["query_terms"])

    def test_context_is_optional_and_the_request_shape_is_validated(self):
        self.assertIn(self.post(Q_PLAN).json()["status"], (ANSWERED, *HONEST_NON_ANSWERS))     # no context: unchanged
        for bad in (
            {"questions": ["q"] * (FU.MAX_QUESTIONS + 5)},                                     # too many questions
            {"questions": ["q"], "answer": "a" * (FU.MAX_ANSWER_CHARS + 1)},                  # answer too long
            {"questions": ["q"], "history": []},                                               # unknown field
        ):
            with self.subTest(bad=bad):
                r = self.post("elaborate", context=bad)
                self.assertEqual(r.status_code, 422, r.text)
                self.assertEqual(r.json()["error"]["code"], "invalid_request")

    def test_context_without_a_usable_anchor_returns_a_safe_clarification(self):
        r = self.post("elaborate", debug=True, context={"questions": [], "answer": None})
        body = r.json()
        self.assertEqual(body["status"], UNABLE_TO_VERIFY)
        self.assertEqual(body["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertEqual(body["sources"], [])
        self.assertIsNone(body["topic_reference"])
        self.assertNotIn("follow_up", body["debug"]["pipeline"])

    def test_unsupported_standalone_question_stays_out_of_scope_with_context(self):
        body = self.post("What is the capital of France?", debug=True,
                         context={"questions": [Q_PLAN], "answer": "Installment plan context."}).json()
        self.assertEqual(body["status"], OUT_OF_SCOPE)
        self.assertEqual(body["sources"], [])
        self.assertNotIn("follow_up", body["debug"]["pipeline"])


@NEED_STORES
class RealFollowUpTests(unittest.TestCase):
    """The acceptance runs, against the real card store, page store, embedding model and router (no stubs)."""

    @classmethod
    def setUpClass(cls):
        cls.svc = S.build_service("extractive")

    def turn(self, question, context=None, cid="conv-real"):
        return self.svc.ask(question, conversation_id=cid, context=context)

    def context_of(self, *answers):
        return {"questions": [a for a, _ in answers], "answer": answers[-1][1]}

    def test_01_the_reported_case_contract_account_then_elaborate(self):
        first = self.turn(CONTRACT)
        self.assertEqual(first["status"], ANSWERED)
        self.assertTrue(first["sources"])
        # the reported failure, without prior context ...
        fresh = self.turn("elaborate", cid="conv-fresh")
        self.assertEqual(fresh["status"], UNABLE_TO_VERIFY)
        self.assertEqual(fresh["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertEqual(fresh["sources"], [])
        # ... and the fix
        second = self.turn("elaborate", self.context_of((CONTRACT, first["answer"])), cid=first["conversation_id"])
        self.assertEqual(second["status"], ANSWERED, second["answer"])
        self.assertEqual(second["conversation_id"], first["conversation_id"])
        self.assertTrue(second["sources"], "a follow-up answer must be cited like any other answer")
        self.assertTrue(second["metadata"]["grounded"])
        markers = {s["marker"] for s in second["sources"]}
        self.assertTrue(markers, "citations come from this retrieval, not the previous answer")
        for marker in markers:
            self.assertIn(f"[{marker}]", second["answer"])
        self.assertNotRegex(second["answer"], r"\bM2C-\d+\b")

    def test_02_explain_that_in_detail_after_a_billing_question(self):
        first = self.turn(BILLING)
        self.assertEqual(first["status"], ANSWERED)
        second = self.turn("Explain that in detail.", self.context_of((BILLING, first["answer"])))
        self.assertEqual(second["status"], ANSWERED, second["answer"])
        self.assertTrue(second["sources"])

    def test_03_why_after_a_bill_creation_answer_stays_grounded_or_abstains(self):
        first = self.turn(BILL_CREATED)
        self.assertEqual(first["status"], ANSWERED)
        second = self.turn("Why?", self.context_of((BILL_CREATED, first["answer"])))
        self.assertIn(second["status"], (ANSWERED, *HONEST_NON_ANSWERS))
        if second["status"] == ANSWERED:
            self.assertTrue(second["sources"])
            self.assertTrue(second["metadata"]["grounded"])
        else:
            self.assertFalse(second["sources"])

    def test_04_an_example_is_only_answered_when_the_documentation_supports_it(self):
        first = self.turn(CONTRACT)
        example = self.turn("Give me an example.", self.context_of((CONTRACT, first["answer"])))
        self.assertIn(example["status"], (ANSWERED, *HONEST_NON_ANSWERS))
        if example["status"] == ANSWERED:
            self.assertTrue(example["sources"])
            self.assertTrue(example["metadata"]["grounded"], "no example may be invented: it must be documentation-grounded")
        # an anchor the corpus does not answer stays an honest non-answer after elaboration
        marginal = self.turn("What is the pricing model for residential customers?")
        self.assertIn(marginal["status"], HONEST_NON_ANSWERS)
        elaborated = self.turn("Explain that in more detail.", self.context_of(("What is the pricing model for residential customers?", marginal["answer"])))
        self.assertIn(elaborated["status"], HONEST_NON_ANSWERS, "unsupported detail must not become an answer")
        self.assertFalse(elaborated["sources"])

    def test_05_an_out_of_scope_question_does_not_inherit_the_conversation_topic(self):
        first = self.turn(CONTRACT)
        unrelated = self.turn("What is the capital of France?", self.context_of((CONTRACT, first["answer"])))
        self.assertEqual(unrelated["status"], OUT_OF_SCOPE)
        self.assertFalse(unrelated["sources"])

    def test_06_a_relational_follow_up_uses_the_conversation_and_the_new_topic(self):
        first = self.turn(CONTRACT)
        second = self.turn("How does it relate to a business partner?", self.context_of((CONTRACT, first["answer"])))
        self.assertEqual(second["status"], ANSWERED, second["answer"])
        self.assertTrue(second["sources"])

    def test_07_a_chain_of_follow_ups_stays_one_conversation(self):
        cid = "conv-chain"
        first = self.svc.ask(CONTRACT, conversation_id=cid)
        second = self.svc.ask("Give me an example.", conversation_id=cid, context=self.context_of((CONTRACT, first["answer"])))
        third = self.svc.ask("Elaborate.", conversation_id=cid,
                             context={"questions": ["Give me an example.", CONTRACT], "answer": second["answer"]})
        self.assertEqual({first["conversation_id"], second["conversation_id"], third["conversation_id"]}, {cid})
        for r in (second, third):
            self.assertEqual(r["status"], ANSWERED, r["answer"])
            self.assertTrue(r["sources"])

    def test_08_standalone_questions_are_unchanged_by_the_context_field(self):
        ctx = {"questions": [CONTRACT], "answer": "..."}
        for question in (CONTRACT, BILLING, "What is the capital of France?"):
            with self.subTest(question=question):
                plain = self.turn(question)
                with_context = self.turn(question, ctx)
                self.assertEqual(plain["status"], with_context["status"])
                self.assertEqual(plain["answer"], with_context["answer"])
                self.assertEqual([s["chunk_id"] for s in plain["sources"]], [s["chunk_id"] for s in with_context["sources"]])
                debug = self.svc.ask(question, debug=True, context=ctx)
                self.assertNotIn("follow_up", debug["debug"]["pipeline"])

    def test_09_the_resolution_is_visible_in_the_developer_view_only(self):
        first = self.turn(CONTRACT)
        ctx = self.context_of((CONTRACT, first["answer"]))
        public = self.turn("elaborate", ctx)
        self.assertNotIn("follow_up", str(public.get("debug") or ""))
        debug = self.svc.ask("elaborate", debug=True, context=ctx)
        follow_up = debug["debug"]["pipeline"]["follow_up"]
        self.assertEqual(follow_up["category"], "elaborate")
        self.assertEqual(follow_up["anchor"], CONTRACT)
        self.assertEqual(follow_up["resolved_query"], f"{CONTRACT} explain this more")


if __name__ == "__main__":
    unittest.main()
