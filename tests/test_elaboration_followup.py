"""Tests for Grounded Elaborate / Follow-up Expansion (Requirements A - K).

Validates:
A. "elaborate" after Billing -> expanded grounded answer
B. "explain more" after Billing -> expanded grounded answer
C. "tell me more" after Contract Account -> Contract Account expansion
D. "elaborate" after Installment Plan -> Installment Plan expansion
E. topic switch followed by elaborate -> elaborates latest topic only
F. elaborate with no eligible previous answer -> safe clarification, no topic routing
G. elaborate after OOS -> safe clarification, no fabricated answer
H. elaborate after Unable-to-Verify -> safe clarification
I. normal new query after an answer still routes normally
J. no citation validity regression (100% valid citations)
K. no stale evidence leakage across conversations or topic switches
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
from tests.test_phase9 import NEED_STORES  # noqa: E402

BILLING = "How does billing work?"
CONTRACT = "What is a contract account?"
PLAN = "How do I create an installment plan?"
OOS_QUERY = "What is the weather in Tokyo?"
NEAR_MISS = "What is the pricing model for residential customers?"

ANSWERED = "answered"
OUT_OF_SCOPE = "out_of_scope"
UNABLE_TO_VERIFY = "unable_to_verify"
DOC_UNAVAILABLE = "documentation_unavailable"
NO_ADDITIONAL_VERIFIED_EVIDENCE = "no_additional_verified_evidence"
HONEST_NON_ANSWERS = (OUT_OF_SCOPE, UNABLE_TO_VERIFY, DOC_UNAVAILABLE, NO_ADDITIONAL_VERIFIED_EVIDENCE)


def check_citations_valid(answer: str, sources: list[dict]) -> bool:
    """Verify 100% citation validity according to golden evaluation standards."""
    markers_in_ans = set(re.findall(r"\[(\d+)\]|\[(S\d+)\]", answer))
    flattened_markers = {m[0] or m[1] for m in markers_in_ans}

    src_markers = {s.get("marker") for s in sources if s.get("marker")}
    src_indices = {str(i) for i in range(1, len(sources) + 1)}

    all_valid_markers = flattened_markers.issubset(src_markers | src_indices)
    all_valid_urls = all(bool(s.get("url") and s.get("url").startswith("https://")) for s in sources)
    all_valid_chunks = all(bool(s.get("chunk_id")) for s in sources)
    no_raw_ids = not bool(re.search(r"\bM2C-\d+\b", answer))

    return all_valid_markers and all_valid_urls and all_valid_chunks and no_raw_ids


@NEED_STORES
class ElaborationFollowUpTests(unittest.TestCase):
    """Deterministic backend verification of grounded elaboration mechanism."""

    @classmethod
    def setUpClass(cls):
        cls.svc = S.build_service("extractive")

    def test_A_elaborate_after_billing(self):
        cid = "test-elab-billing"
        first = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)
        self.assertTrue(first["sources"])

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(second["status"], ANSWERED)
        self.assertTrue(second["metadata"]["grounded"])
        self.assertTrue(second["sources"])
        self.assertTrue(check_citations_valid(second["answer"], second["sources"]))
        # Sources must relate to Billing
        first_urls = {s["url"] for s in first["sources"]}
        second_urls = {s["url"] for s in second["sources"]}
        self.assertTrue(first_urls.intersection(second_urls), "Elaboration must share the source document")

    def test_B_explain_more_after_billing(self):
        cid = "test-explain-more-billing"
        first = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)

        second = self.svc.ask("explain more", conversation_id=cid)
        self.assertEqual(second["status"], ANSWERED)
        self.assertTrue(second["metadata"]["grounded"])
        self.assertTrue(second["sources"])
        self.assertTrue(check_citations_valid(second["answer"], second["sources"]))

    def test_C_tell_me_more_after_contract_account(self):
        cid = "test-tell-me-more-contract"
        first = self.svc.ask(CONTRACT, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)
        self.assertTrue(first["sources"])

        second = self.svc.ask("tell me more", conversation_id=cid)
        self.assertEqual(second["status"], ANSWERED)
        self.assertTrue(second["metadata"]["grounded"])
        self.assertTrue(second["sources"])
        self.assertTrue(check_citations_valid(second["answer"], second["sources"]))
        # Verify contract account topic
        first_urls = {s["url"] for s in first["sources"]}
        second_urls = {s["url"] for s in second["sources"]}
        self.assertTrue(first_urls.intersection(second_urls))

    def test_D_elaborate_after_installment_plan(self):
        cid = "test-elaborate-plan"
        first = self.svc.ask(PLAN, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)
        self.assertTrue(first["sources"])

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(second["status"], ANSWERED)
        self.assertTrue(second["metadata"]["grounded"])
        self.assertTrue(second["sources"])
        self.assertTrue(check_citations_valid(second["answer"], second["sources"]))

    def test_E_topic_switch_followed_by_elaborate(self):
        cid = "test-topic-switch-elab"
        # 1. Billing
        billing_resp = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(billing_resp["status"], ANSWERED)
        billing_urls = {s["url"] for s in billing_resp["sources"]}

        # 2. Switch topic to Contract Account
        contract_resp = self.svc.ask(CONTRACT, conversation_id=cid)
        self.assertEqual(contract_resp["status"], ANSWERED)
        contract_urls = {s["url"] for s in contract_resp["sources"]}
        self.assertNotEqual(billing_urls, contract_urls)

        # 3. Elaborate - must elaborate latest topic (Contract Account) ONLY
        elab_resp = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(elab_resp["status"], ANSWERED)
        elab_urls = {s["url"] for s in elab_resp["sources"]}

        # Must match Contract Account, NOT Billing
        self.assertTrue(elab_urls.intersection(contract_urls), "Must elaborate contract account")
        self.assertFalse(elab_urls.intersection(billing_urls) - contract_urls, "No billing leakage")

    def test_F_elaborate_with_no_previous_answer(self):
        cid = "test-no-previous-answer"
        resp = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(resp["status"], UNABLE_TO_VERIFY)
        self.assertEqual(resp["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertEqual(resp["sources"], [])
        self.assertIsNone(resp["topic_reference"])

    def test_G_elaborate_after_oos(self):
        cid = "test-elab-after-oos"
        first = self.svc.ask(OOS_QUERY, conversation_id=cid)
        self.assertEqual(first["status"], OUT_OF_SCOPE)
        self.assertEqual(first["sources"], [])

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(second["status"], UNABLE_TO_VERIFY)
        self.assertEqual(second["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertEqual(second["sources"], [])

    def test_H_elaborate_after_unable_to_verify(self):
        cid = "test-elab-after-utv"
        first = self.svc.ask(NEAR_MISS, conversation_id=cid)
        self.assertIn(first["status"], HONEST_NON_ANSWERS)

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(second["status"], UNABLE_TO_VERIFY)
        self.assertEqual(second["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertFalse(second["sources"])

    def test_I_normal_new_query_after_answer_routes_normally(self):
        cid = "test-normal-after-answer"
        first = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)

        # "what about contract accounts?" must NOT be classified as elaboration follow-up
        follow_up_cat = FU.classify("what about contract accounts?")
        self.assertIsNone(follow_up_cat)

        second = self.svc.ask("what about contract accounts?", conversation_id=cid)
        self.assertEqual(second["status"], ANSWERED)
        second_urls = {s["url"] for s in second["sources"]}
        billing_urls = {s["url"] for s in first["sources"]}
        self.assertNotEqual(billing_urls, second_urls)

    def test_J_no_citation_validity_regression(self):
        # Test various follow-up phrasing variations for 100% citation validity
        phrases = [
            "elaborate",
            "explain more",
            "explain further",
            "tell me more",
            "give more details",
            "go deeper",
            "expand on that",
            "can you elaborate?",
            "explain this in more detail",
        ]
        for i, phrase in enumerate(phrases):
            with self.subTest(phrase=phrase):
                cid = f"test-citation-valid-{i}"
                first = self.svc.ask(BILLING, conversation_id=cid)
                self.assertEqual(first["status"], ANSWERED)
                self.assertTrue(check_citations_valid(first["answer"], first["sources"]))

                second = self.svc.ask(phrase, conversation_id=cid)
                self.assertEqual(second["status"], ANSWERED)
                self.assertTrue(second["metadata"]["grounded"])
                self.assertTrue(
                    check_citations_valid(second["answer"], second["sources"]),
                    f"Invalid citations for phrase '{phrase}': {second['answer']}",
                )

    def test_K_no_stale_evidence_leakage(self):
        # Conversation A: Billing
        cid_a = "test-leakage-conv-a"
        resp_a1 = self.svc.ask(BILLING, conversation_id=cid_a)
        resp_a2 = self.svc.ask("elaborate", conversation_id=cid_a)
        chunks_a = {s["chunk_id"] for s in resp_a2["sources"]}

        # Conversation B: Installment Plan
        cid_b = "test-leakage-conv-b"
        resp_b1 = self.svc.ask(PLAN, conversation_id=cid_b)
        resp_b2 = self.svc.ask("elaborate", conversation_id=cid_b)
        chunks_b = {s["chunk_id"] for s in resp_b2["sources"]}

        # Strictly disjoint evidence chunks
        self.assertTrue(chunks_a, "Conversation A must have sources")
        self.assertTrue(chunks_b, "Conversation B must have sources")
        self.assertFalse(chunks_a.intersection(chunks_b), "No cross-conversation evidence leakage")


@NEED_STORES
class ExhaustedElaborationAndHardeningTests(unittest.TestCase):
    """Repeated elaboration, backend-authoritative elaboration state, and the RAG quality hardening pass.

    B2. Billing -> Elaborate -> Elaborate -> safe no-additional-evidence state (never OOS)
    C2. Billing -> Elaborate -> Elaborate -> Elaborate -> MUST NOT become OOS
    D2. Billing -> exhausted elaboration -> new Contract Account query -> Contract Account answer
    E2. Contract Account -> repeated elaboration -> no OOS fall-through
    F2. typed "explain more" after exhausted evidence -> safe no-additional-evidence state
    L.  typo "elaborat" after an answer -> deterministic elaboration (existing typo handling preserved)
    M.  "elaborate on installment plans" after Billing -> a NEW semantic query, not a Billing elaboration
    N.  queries about the four missing pages -> honest unavailable state, never a fabricated answer
    P.  "What is a contract account?" leads with the SAP Utilities (IS-U) definition
    Q.  answers never contain heading-only fragments, bare list items or duplicated measure labels
    R.  the exhausted state carries no "page not in the knowledge base" claim
    S.  conversation isolation: an exhausted Billing conversation never leaks into another conversation
    """

    @classmethod
    def setUpClass(cls):
        cls.svc = S.build_service("extractive")

    def test_B2_second_elaborate_after_exhausted_evidence_is_safe_not_oos(self):
        cid = "test-b2-exhausted-safe"
        first = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(second["status"], ANSWERED)
        self.assertTrue(second["metadata"]["grounded"])

        third = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(third["status"], NO_ADDITIONAL_VERIFIED_EVIDENCE)
        self.assertEqual(third["answer"], S.USER_TEXT[NO_ADDITIONAL_VERIFIED_EVIDENCE])
        self.assertEqual(third["metadata"]["reason_code"], "NO_ADDITIONAL_SUPPORTED_DETAILS")
        self.assertEqual(third["metadata"]["follow_up_category"], "elaborate")
        self.assertFalse(third["metadata"]["can_elaborate"])
        self.assertFalse(third["metadata"]["grounded"])
        self.assertEqual(third["sources"], [])
        self.assertIsNone(third["topic_reference"])
        self.assertTrue(check_citations_valid(third["answer"], third["sources"]))

    def test_C2_third_elaborate_must_not_become_out_of_scope(self):
        cid = "test-c2-never-oos"
        self.assertEqual(self.svc.ask(BILLING, conversation_id=cid)["status"], ANSWERED)
        for turn in (2, 3, 4):
            result = self.svc.ask("elaborate", conversation_id=cid)
            self.assertNotEqual(result["status"], OUT_OF_SCOPE,
                                 f"turn {turn}: repeated elaboration must never fall through to out_of_scope")
            self.assertIn(result["status"], (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))
            if result["status"] == NO_ADDITIONAL_VERIFIED_EVIDENCE:
                self.assertEqual(result["answer"], S.USER_TEXT[NO_ADDITIONAL_VERIFIED_EVIDENCE])
                self.assertFalse(result["metadata"]["can_elaborate"])

    def test_D2_new_query_after_exhaustion_routes_normally(self):
        cid = "test-d2-switch-after-exhaustion"
        self.assertEqual(self.svc.ask(BILLING, conversation_id=cid)["status"], ANSWERED)
        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertIn(second["status"], (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))

        contract = self.svc.ask(CONTRACT, conversation_id=cid)
        self.assertEqual(contract["status"], ANSWERED)
        self.assertEqual(contract["metadata"]["card_id"], "M2C-17")
        self.assertTrue(contract["metadata"]["can_elaborate"])
        contract_urls = {s["url"] for s in contract["sources"]}
        billing_urls = {s["url"] for s in self.svc.ask(BILLING, conversation_id=cid)["sources"]}
        self.assertFalse(contract_urls & billing_urls, "the new topic must not reuse Billing evidence")

    def test_E2_contract_account_repeated_elaboration_never_oos(self):
        cid = "test-e2-contract-exhausted"
        self.assertEqual(self.svc.ask(CONTRACT, conversation_id=cid)["status"], ANSWERED)
        for turn in (2, 3, 4):
            result = self.svc.ask("elaborate", conversation_id=cid)
            self.assertNotEqual(result["status"], OUT_OF_SCOPE, f"turn {turn}")
            self.assertIn(result["status"], (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))
            if result["status"] == ANSWERED:
                self.assertTrue(result["metadata"]["grounded"])
                self.assertTrue(check_citations_valid(result["answer"], result["sources"]))

    def test_F2_typed_explain_more_after_exhaustion_is_safe(self):
        cid = "test-f2-explain-more-exhausted"
        self.assertEqual(self.svc.ask(BILLING, conversation_id=cid)["status"], ANSWERED)
        self.assertIn(self.svc.ask("elaborate", conversation_id=cid)["status"],
                      (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))
        result = self.svc.ask("explain more", conversation_id=cid)
        self.assertNotEqual(result["status"], OUT_OF_SCOPE)
        self.assertIn(result["status"], (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))
        if result["status"] == NO_ADDITIONAL_VERIFIED_EVIDENCE:
            self.assertEqual(result["metadata"]["follow_up_category"], "elaborate")

    def test_L_typo_elaborat_after_an_answer_still_elaborates(self):
        cid = "test-l-typo-elaborat"
        first = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)
        typo = self.svc.ask("elaborat", conversation_id=cid)
        self.assertIn(typo["status"], (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))
        self.assertNotEqual(typo["status"], OUT_OF_SCOPE)
        self.assertEqual(typo["metadata"]["follow_up_category"], "elaborate")

    def test_M_elaborate_on_installment_plans_is_a_new_semantic_query(self):
        cid = "test-m-elaborate-on-topic"
        first = self.svc.ask(BILLING, conversation_id=cid)
        self.assertEqual(first["status"], ANSWERED)
        self.assertIsNone(FU.classify("elaborate on installment plans"),
                          "a follow-up that names its own topic is never a follow-up intent")

        result = self.svc.ask("elaborate on installment plans", conversation_id=cid)
        self.assertEqual(result["status"], ANSWERED)
        self.assertIsNone(result["metadata"].get("follow_up_category"),
                          "must not blindly elaborate the previous answer")
        self.assertIn(result["metadata"]["card_id"], ("M2C-23", "M2C-24", "M2C-25"),
                      "the new semantic query routes to an installment-plan topic")
        self.assertNotEqual(result["metadata"]["card_id"], "M2C-12")
        billing_urls = {s["url"] for s in first["sources"]}
        result_urls = {s["url"] for s in result["sources"]}
        self.assertFalse(billing_urls & result_urls, "no Billing evidence may leak into the new topic answer")
        self.assertTrue(check_citations_valid(result["answer"], result["sources"]))

    def test_N_missing_pages_get_an_honest_unavailable_state(self):
        # The four topics without an admitted page (data/page_corpus/manifest.json: 25 of 29 ingested).
        # A navigation request that names such a topic must produce the honest unavailable/unresolved state for
        # THAT topic - never an answer assembled from a different, ingested page.
        missing = {
            "Tell me about Utilities Master Data.": "M2C-01",
            "Tell me about Budget Billing Plan.": "M2C-13",
            "Tell me about Periodic Billing and Invoicing Analysis.": "M2C-16",
            "Tell me about Contract Account Business Object.": "M2C-18",
        }
        for question, card_id in missing.items():
            with self.subTest(question=question):
                result = self.svc.ask(question, conversation_id=f"test-n-missing-{card_id}")
                self.assertNotEqual(result["status"], ANSWERED,
                                    "a missing page must never be answered from another page's text")
                self.assertIn(result["status"], (DOC_UNAVAILABLE, UNABLE_TO_VERIFY))
                self.assertEqual(result["sources"], [])
                self.assertEqual(result["metadata"]["card_id"], card_id,
                                 "the response must name the requested topic, not a neighbouring one")
                if result["status"] == DOC_UNAVAILABLE:
                    self.assertFalse(result["metadata"]["page_available"])
                    self.assertIsNotNone(result["topic_reference"])
                    self.assertIn("not currently available in the local knowledge base", result["answer"])
        # content questions that merely mention a topic keep their normal, grounded routing
        content = self.svc.ask("How does a budget billing plan work?", conversation_id="test-n-content-bbp")
        self.assertEqual(content["status"], ANSWERED)
        self.assertTrue(content["sources"])

    def test_P_contract_account_definition_comes_first(self):
        result = self.svc.ask(CONTRACT, conversation_id="test-p-definition-first")
        self.assertEqual(result["status"], ANSWERED)
        self.assertTrue(result["metadata"]["grounded"])
        first_line = result["answer"].split("\n")[0]
        self.assertIn("In Utilities", first_line,
                      "the SAP Utilities (IS-U) definition must lead a definition-style answer")
        self.assertIn("contract account contains all those contracts", first_line)
        self.assertTrue(check_citations_valid(result["answer"], result["sources"]))
        # if generic FI-CA context is included, it follows the industry-specific definition
        fica = [ln for ln in result["answer"].split("\n") if ln.startswith("In Contract Accounts Receivable and Payable")]
        if fica:
            self.assertGreater(result["answer"].split("\n").index(fica[0]), 0)

    def test_Q_answers_contain_no_heading_or_bare_list_fragments(self):
        queries = (
            "What SAP Fiori implementation information is there for the Analyze Incoming Payments app?",
            "What measures can I display for payment lots?",
            "How do I display the total payment amount in relation to the open payment amount in a lot?",
            "What statistics does the details view of individual payment lots show?",
        )
        forbidden = (
            "SAP Fiori Implementation Information [",       # heading-only fragment as answer content
            "- Measure :",                                   # bare configuration list item
            "- Payment usage within a payment lot",          # isolated list item without its introduction
            "- Level of automation within one payment lot",
            "- Chart :",
            "- Dimension :",
        )
        for question in queries:
            with self.subTest(question=question):
                result = self.svc.ask(question, conversation_id=f"test-q-fragments-{abs(hash(question))}")
                self.assertIn(result["status"], (ANSWERED, UNABLE_TO_VERIFY, NO_ADDITIONAL_VERIFIED_EVIDENCE))
                for fragment in forbidden:
                    self.assertNotIn(fragment, result["answer"], f"{fragment!r} leaked into the answer")
                if result["status"] == ANSWERED:
                    self.assertTrue(result["metadata"]["grounded"])
                    self.assertTrue(check_citations_valid(result["answer"], result["sources"]))

    def test_R_exhausted_state_never_claims_the_page_is_missing(self):
        cid = "test-r-no-false-kb-claim"
        self.assertEqual(self.svc.ask(BILLING, conversation_id=cid)["status"], ANSWERED)
        for _ in range(3):
            result = self.svc.ask("elaborate", conversation_id=cid)
            if result["status"] == NO_ADDITIONAL_VERIFIED_EVIDENCE:
                break
        self.assertEqual(result["status"], NO_ADDITIONAL_VERIFIED_EVIDENCE)
        self.assertIsNone(result["topic_reference"])
        self.assertNotIn("not in the local knowledge base", result["answer"])
        self.assertNotIn("not currently available", result["answer"])
        self.assertEqual(result["metadata"]["page_available"], True)
        self.assertEqual(result["metadata"]["card_id"], "M2C-12")

    def test_S_conversation_isolation_with_exhausted_state(self):
        cid_a = "test-s-isolation-a"
        cid_b = "test-s-isolation-b"
        billing = self.svc.ask(BILLING, conversation_id=cid_a)
        self.assertEqual(billing["status"], ANSWERED)
        for _ in range(3):
            exhausted = self.svc.ask("elaborate", conversation_id=cid_a)
            if exhausted["status"] == NO_ADDITIONAL_VERIFIED_EVIDENCE:
                break
        self.assertEqual(exhausted["status"], NO_ADDITIONAL_VERIFIED_EVIDENCE)

        contract = self.svc.ask(CONTRACT, conversation_id=cid_b)
        self.assertEqual(contract["status"], ANSWERED)
        elaborated = self.svc.ask("elaborate", conversation_id=cid_b)
        self.assertIn(elaborated["status"], (ANSWERED, NO_ADDITIONAL_VERIFIED_EVIDENCE))
        if elaborated["status"] == ANSWERED:
            billing_chunks = {s["chunk_id"] for s in billing["sources"]}
            contract_chunks = {s["chunk_id"] for s in elaborated["sources"]}
            self.assertFalse(billing_chunks & contract_chunks, "no Billing evidence may leak into conversation B")
            self.assertEqual(elaborated["metadata"]["card_id"], "M2C-17")


if __name__ == "__main__":
    unittest.main()
