"""Regression coverage for unavailable registered topics taking precedence over semantic neighbors."""
from __future__ import annotations

import unittest

from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, make_pipeline
import rag_generate as RG  # noqa: E402
import rag_service as S  # noqa: E402

NEEDS_PIPELINE = unittest.skipUnless(HAVE_BS4 and HAVE_CHROMA, "bs4 / chromadb not installed")

Q_BUDGET_PLAN = "How do I create a budget billing plan?"
Q_CONTRACT_OBJECT = "What does the contract account business object contain?"
Q_PERIODIC_ANALYSIS = "What does periodic billing analysis show?"
Q_UTILITIES_MASTER_DATA = "Tell me about Utilities Master Data."
Q_GENERIC_CONTRACT_ACCOUNT = "What is a contract account?"
Q_BILLING = "What does invoicing do in SAP Utilities?"
Q_INVOICING_PROCESS = "What is the invoicing process?"
Q_BUDGET_INVOICING = "How are budget billing plans treated in invoicing?"
Q_MOVEOUT_BUDGET = "What happens to budget billing plans when a move-out is processed?"
Q_BUDGET_DEACTIVATION = "What does deactivation of a budget billing plan in invoicing mean?"

# These forced rankings represent the semantic neighbors the normal router would return; a focused missing-topic
# match should short-circuit before routing or reranking can use them.
RANKING = {
    Q_BUDGET_PLAN: ["M2C-15"],
    Q_CONTRACT_OBJECT: ["M2C-17"],
    Q_PERIODIC_ANALYSIS: ["M2C-14"],
    Q_UTILITIES_MASTER_DATA: ["M2C-05"],
    Q_GENERIC_CONTRACT_ACCOUNT: ["M2C-17"],
    Q_BILLING: ["M2C-14"],
    Q_INVOICING_PROCESS: ["M2C-14"],
    Q_BUDGET_INVOICING: ["M2C-15"],
    Q_MOVEOUT_BUDGET: ["M2C-04"],
    Q_BUDGET_DEACTIVATION: ["M2C-15"],
}


@NEEDS_PIPELINE
class UnavailableTopicRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pipeline = make_pipeline(RG.ExtractiveGenerator(), ranking=RANKING)
        cls.service = S.RagService(pipeline, "extractive")

    def ask(self, question: str, conversation_id: str, debug: bool = True):
        return self.service.ask(question, conversation_id=conversation_id, debug=debug)

    def ask_unavailable(self, question: str, conversation_id: str, source_id: str):
        backend = self.service.pipeline.backend
        calls_before = len(backend.calls)
        result = self.ask(question, conversation_id)
        self.assert_documentation_unavailable(result, source_id)
        self.assertEqual(len(backend.calls), calls_before, "focused unavailable topics must short-circuit card routing")
        return result

    def assert_documentation_unavailable(self, result, source_id: str):
        self.assertEqual(result["status"], "documentation_unavailable")
        self.assertEqual(result["metadata"]["pipeline_status"], "page_not_ingested")
        self.assertEqual(result["metadata"]["reason_code"], "PAGE_IDENTIFIED_NO_LOCAL_CONTENT")
        self.assertEqual(result["metadata"]["card_id"], source_id)
        self.assertFalse(result["metadata"]["page_available"])
        self.assertFalse(result["metadata"]["grounded"])
        self.assertEqual(result["sources"], [])
        self.assertNotIn("generation", result["debug"]["pipeline"])
        self.assertNotIn("retrieved", result["debug"]["pipeline"])
        self.assertNotIn("context", result["debug"]["pipeline"])
        self.assertEqual(result["debug"]["citations"]["answer_sources"], [])
        self.assertEqual(result["debug"]["routing"]["selected_source_id"], source_id)
        self.assertEqual(result["debug"]["routing"]["mode"], "focused_unavailable_topic")
        self.assertEqual(result["debug"]["routing"]["candidates"], [])
        self.assertEqual(result["debug"]["pipeline"]["named_topic"]["named_source_id"], source_id)
        self.assertIsNone(result["debug"]["pipeline"]["named_topic"]["routed_source_id"])
        if result.get("topic_reference"):
            self.assertIn("not used as evidence", result["topic_reference"]["note"])

    def test_budget_billing_plan_is_now_answered_instead_of_unavailable(self):
        # 2026-10-12: the budget billing plan page (guide 021b182b) is machine-verified and ingested, so this
        # formerly missing topic now goes through the real chain. Regression guard: generation must actually run
        # (no leftover short-circuit), and the answer must cite only the budget-plan family page.
        backend = self.service.pipeline.backend
        calls_before = len(backend.calls)
        result = self.ask(Q_BUDGET_PLAN, "formerly-missing-budget")
        self.assertEqual(result["status"], "answered", result["metadata"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-15"})
        self.assertIn("generation", result["debug"]["pipeline"])
        self.assertGreater(len(backend.calls), calls_before)
        self.assertNotEqual(result["debug"]["routing"]["mode"], "focused_unavailable_topic")

    def test_contract_account_business_object_beats_searchable_contract_accounts_neighbor(self):
        result = self.ask_unavailable(Q_CONTRACT_OBJECT, "missing-contract-object", "M2C-18")

    def test_periodic_billing_analysis_is_now_answered_from_ingested_m2c16(self):
        # 2026-10-12: M2C-16's page is ingested under machine-verified guide 021b182b; the oracle-ranked query
        # answers from it instead of the not-ingested gate.
        pipeline = make_pipeline(RG.ExtractiveGenerator(), ranking={Q_PERIODIC_ANALYSIS: ["M2C-16"]})
        service = S.RagService(pipeline, "extractive")
        result = service.ask(Q_PERIODIC_ANALYSIS, conversation_id="formerly-missing-periodic", debug=True)
        self.assertEqual(result["status"], "answered", result["metadata"])
        self.assertEqual(result["metadata"]["card_id"], "M2C-16")
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-16"})
        self.assertNotEqual(result["debug"]["routing"]["mode"], "focused_unavailable_topic")

    def test_explicit_utilities_master_data_navigation_is_now_answered_from_corrected_identity(self):
        # 2026-10-12: the Topic 1 map-root correction is machine-checked, so M2C-01 answers from its effective
        # identity page (guide e52c8ee6, page e369ce53) — not from the original card URL's guide 021b182b.
        pipeline = make_pipeline(RG.ExtractiveGenerator(), ranking={Q_UTILITIES_MASTER_DATA: ["M2C-01"]})
        service = S.RagService(pipeline, "extractive")
        result = service.ask(Q_UTILITIES_MASTER_DATA, conversation_id="formerly-missing-master-data", debug=True)
        self.assertEqual(result["status"], "answered", result["metadata"])
        self.assertEqual(result["metadata"]["card_id"], "M2C-01")
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-01"})
        for source in result["sources"]:
            self.assertTrue(source["chunk_id"].startswith("e52c8ee6197147ec97dfc2eb8c46a3ad/e369ce53118d4308e10000000a174cb4"))
        self.assertEqual(result["debug"]["pipeline"]["identity"]["effective_guide_id"], "e52c8ee6197147ec97dfc2eb8c46a3ad")

    def test_generic_contract_account_question_still_answers_from_searchable_contract_accounts(self):
        result = self.ask(Q_GENERIC_CONTRACT_ACCOUNT, "generic-contract-account")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metadata"]["card_id"], "M2C-17")
        self.assertTrue(result["sources"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-17"})

    def test_normal_billing_question_still_answers_from_searchable_invoicing(self):
        result = self.ask(Q_BILLING, "normal-billing")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metadata"]["card_id"], "M2C-14")
        self.assertTrue(result["sources"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-14"})

    def test_invoicing_process_question_still_answers_from_searchable_m2c14(self):
        result = self.ask(Q_INVOICING_PROCESS, "invoicing-process")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metadata"]["card_id"], "M2C-14")
        self.assertTrue(result["sources"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-14"})

    def test_budget_billing_invoicing_query_still_answers_from_searchable_m2c15(self):
        result = self.ask(Q_BUDGET_INVOICING, "budget-invoicing-control")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metadata"]["card_id"], "M2C-15")
        self.assertTrue(result["sources"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-15"})

    def test_budget_billing_mention_in_move_out_question_keeps_its_searchable_topic(self):
        result = self.ask(Q_MOVEOUT_BUDGET, "moveout-budget")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metadata"]["card_id"], "M2C-04")
        self.assertTrue(result["sources"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-04"})

    def test_deactivation_question_about_budget_billing_keeps_searchable_m2c15(self):
        result = self.ask(Q_BUDGET_DEACTIVATION, "budget-deactivation")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["metadata"]["card_id"], "M2C-15")
        self.assertTrue(result["sources"])
        self.assertEqual({source["source_id"] for source in result["sources"]}, {"M2C-15"})

    def test_unavailable_topic_does_not_inherit_previous_conversation_evidence(self):
        # 2026-10-12: re-anchored on M2C-18, the only topic that remains unavailable (conflicting identity,
        # fail-closed). The budget-plan predecessor was ingested on this date.
        conversation_id = "unavailable-topic-context-isolation"
        previous = self.ask(Q_BILLING, conversation_id)
        self.assertEqual(previous["status"], "answered")
        self.assertTrue(previous["sources"])

        result = self.ask_unavailable(Q_CONTRACT_OBJECT, conversation_id, "M2C-18")
        self.assertNotIn(previous["answer"], result["answer"])
        self.assertNotIn("follow_up_category", result["metadata"])


if __name__ == "__main__":
    unittest.main()
