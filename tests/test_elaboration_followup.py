"""Tests for Grounded Elaborate / Follow-up Expansion (Requirements A - K).

Validates:
A. "elaborate" after Billing -> expanded grounded answer
B. "explain more" after Billing -> expanded grounded answer
C. "tell me more" after Contract Account -> Contract Account expansion
D. "elaborate" after Installment Plan -> Installment Plan expansion
E. topic switch followed by elaborate -> elaborates latest topic only
F. elaborate with no previous answer -> existing safe OOS behavior
G. elaborate after OOS -> remains safe, no fabricated answer
H. elaborate after Unable-to-Verify -> remains safe
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
HONEST_NON_ANSWERS = (OUT_OF_SCOPE, UNABLE_TO_VERIFY, DOC_UNAVAILABLE)


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
        self.assertEqual(resp["status"], OUT_OF_SCOPE)
        self.assertEqual(resp["sources"], [])

    def test_G_elaborate_after_oos(self):
        cid = "test-elab-after-oos"
        first = self.svc.ask(OOS_QUERY, conversation_id=cid)
        self.assertEqual(first["status"], OUT_OF_SCOPE)
        self.assertEqual(first["sources"], [])

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertEqual(second["status"], OUT_OF_SCOPE)
        self.assertEqual(second["sources"], [])

    def test_H_elaborate_after_unable_to_verify(self):
        cid = "test-elab-after-utv"
        first = self.svc.ask(NEAR_MISS, conversation_id=cid)
        self.assertIn(first["status"], HONEST_NON_ANSWERS)

        second = self.svc.ask("elaborate", conversation_id=cid)
        self.assertIn(second["status"], HONEST_NON_ANSWERS)
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


if __name__ == "__main__":
    unittest.main()
