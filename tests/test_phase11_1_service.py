"""Phase 11.1 - answer correctness through the service/API boundary: absent vs answerable detail, citation-evidence chain, abstention wording, routing failures never fabricate.

Store-backed classes use the real card store, page store, embedding model and router (no stubs); they skip when those are absent."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, make_pipeline  # noqa: E402
from tests.test_phase9 import NEED_STORES  # noqa: E402

import rag_evidence as EV  # noqa: E402
import rag_service as S  # noqa: E402

try:
    from fastapi.testclient import TestClient
    import rag_api
    HAVE_API = True
except Exception:                                                        # noqa: BLE001
    HAVE_API = False
NEED_API = unittest.skipUnless(HAVE_API and HAVE_BS4 and HAVE_CHROMA, "fastapi / httpx / bs4 / chromadb not installed")
NEED_PIPE = unittest.skipUnless(HAVE_BS4 and HAVE_CHROMA, "bs4 / chromadb not installed")

ABSTAIN = "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail."
UNVERIFIED = "I couldn't verify the relevant documentation."
INTERNAL_ID = re.compile(r"\bM2C-\d+\b")


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


class Wording(unittest.TestCase):
    def test_exact_abstention_and_unverified_texts(self):
        self.assertEqual(S.USER_TEXT[S.UNABLE_TO_VERIFY], ABSTAIN)
        self.assertEqual(S.UNRESOLVED_TEXT, UNVERIFIED)
        self.assertEqual(S.USER_TEXT[S.DOC_UNAVAILABLE], "I found the relevant topic, but the underlying SAP Help page is not currently available in the local knowledge base.")
        for t in (ABSTAIN, UNVERIFIED):
            self.assertNotRegex(t, r"(?i)here'?s what i found|related|M2C-|chunk|retriev|embedding|pipeline")

    def test_shipped_configuration_is_the_adopted_one(self):
        self.assertEqual(EV.SHIPPED_TAU, 0.5)
        self.assertFalse(EV.USE_IDF)


@NEED_PIPE
class ChainDowngrade(unittest.TestCase):
    def test_an_answer_whose_support_chain_fails_is_abstained_not_labelled_grounded(self):
        from tests.test_phase11_service import Q_PLAN, RANKING
        import rag_pipeline as RP  # noqa: F401
        svc = S.RagService(EV.build_evidence_pipeline(make_pipeline(None or __import__("rag_generate").ExtractiveGenerator(), RANKING), tau=0.5, widen=False), "extractive")
        ok = svc.ask(Q_PLAN, debug=True)
        self.assertEqual(ok["status"], "answered")
        self.assertTrue(ok["debug"]["evidence"]["support_chain"]["ok"])
        original = S.support_chain
        S.support_chain = lambda answer, dbg: {"ok": False, "sentences": []}
        try:
            r = svc.ask(Q_PLAN, debug=True)
        finally:
            S.support_chain = original
        self.assertEqual((r["status"], r["answer"], r["sources"], r["metadata"]["grounded"]), ("unable_to_verify", ABSTAIN, [], False))
        self.assertEqual(r["metadata"]["reason_code"], "SUPPORT_CHAIN_FAILED")

    def test_support_chain_helper_accepts_verbatim_and_rejects_invented_text(self):
        dbg = {"context": {"items": [{"marker": "S1", "text": "The pump runs for 30 minutes."}, {"marker": "S2", "text": "Filters are replaced yearly."}]}}
        self.assertTrue(S.support_chain("The pump runs for 30 minutes. [S1]", dbg)["ok"])
        self.assertFalse(S.support_chain("The pump runs for 30 minutes. [S2]", dbg)["ok"])
        self.assertFalse(S.support_chain("The pump runs for one hour. [S1]", dbg)["ok"])


@NEED_STORES
@NEED_API
class RealAnswerCorrectness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_cm = TestClient(rag_api.create_app(generator="extractive", static_dir=Path("/nonexistent")))
        cls.c = cls.app_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.app_cm.__exit__(None, None, None)

    def ask(self, q, debug=True):
        r = self.c.post("/api/chat", json={"message": q, "debug": debug})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # --- absent detail vs answerable detail (the same page, same topic) ---------------------------------------------------------------
    def test_absent_detail_on_a_routed_page_abstains_with_the_exact_message(self):
        for q in ("What is the minimum installment amount?", "What is the minimum interval between two installments?", "Which authorization object is needed to run the monitoring transaction?"):
            b = self.ask(q)
            self.assertEqual(b["status"], "unable_to_verify", q)
            self.assertEqual(b["answer"], ABSTAIN, q)
            self.assertEqual(b["sources"], [], q)
            self.assertFalse(b["metadata"]["grounded"], q)
            self.assertNotRegex(b["answer"], r"(?i)here'?s what i found")
            self.assertFalse(b["debug"]["evidence"]["supported"], q)

    def test_answerable_detail_on_the_same_pages_is_answered(self):
        for q in ("When do I create an installment plan?", "What does the Device Management component manage?", "Which transaction is used to monitor meter reading results?"):
            b = self.ask(q)
            self.assertEqual(b["status"], "answered", q)
            self.assertTrue(b["sources"], q)
            self.assertTrue(b["debug"]["evidence"]["supported"], q)

    # --- the citation points at the chunk that states the answer ----------------------------------------------------------------------
    def test_every_answer_sentence_is_a_verbatim_span_of_the_chunk_its_citation_names(self):
        for q in ("What does the Device Management component manage?", "When do I create an installment plan?", "What does invoicing do in SAP Utilities?",
                  "Which transaction is used to monitor meter reading results?"):
            b = self.ask(q)
            self.assertEqual(b["status"], "answered", q)
            items = {i["marker"]: i for i in b["debug"]["pipeline"]["context"]["items"]}
            cited = {s["marker"]: s["chunk_id"] for s in b["sources"]}
            self.assertTrue(b["debug"]["evidence"]["support_chain"]["ok"], q)
            for line in [x for x in b["answer"].split("\n") if x.strip()]:
                body = norm(re.sub(r"\[S\d+\]", "", line))
                markers = re.findall(r"\[(S\d+)\]", line)
                self.assertTrue(markers, line)
                self.assertTrue(any(body in norm(items[m]["text"]) for m in markers), (q, line))
                for m in markers:
                    self.assertIn(m, cited)
                    self.assertEqual(items[m]["chunk_id"], cited[m])                  # the source entry IS the chunk that was read

    def test_a_sentence_about_a_sibling_topic_is_not_returned_for_the_asked_one(self):
        b = self.ask("What does the Device Management component manage?")
        text = norm(b["answer"])
        self.assertIn("technical data", text)

    # --- routing failures never fabricate ---------------------------------------------------------------------------------------------
    def test_routing_failures_abstain_or_say_unavailable_but_never_invent(self):
        for q in ("Which authorization object is needed for transaction EL31?", "What is a business partner?", "What is the weather in Hyderabad?",
                  "How are dunning notices created?", "How do I submit receivables to a collection agency?"):
            b = self.ask(q)
            self.assertNotEqual(b["status"], "answered", q)
            self.assertEqual(b["sources"], [], q)
            self.assertFalse(b["metadata"]["grounded"], q)
        self.assertEqual(self.ask("What is a business partner?")["answer"], UNVERIFIED)
        self.assertEqual(self.ask("What is the weather in Hyderabad?")["status"], "out_of_scope")
        self.assertEqual(self.ask("How are dunning notices created?")["status"], "documentation_unavailable")

    def test_wrongly_routed_sibling_questions_never_return_an_ungrounded_answer(self):
        for q in ("What happens to the contract in a move-out?", "What does the Contract Accounts component enable me to do?"):
            b = self.ask(q)
            if b["status"] == "answered":                                             # allowed (wrong topic is a router limit) but must be traceable
                self.assertTrue(b["debug"]["evidence"]["support_chain"]["ok"], q)
                self.assertTrue(b["metadata"]["grounded"], q)
            else:
                self.assertEqual(b["sources"], [], q)

    # --- API contract ------------------------------------------------------------------------------------------------------------------------
    def test_api_contract_for_each_status(self):
        seen = {self.ask(q, debug=False)["status"]: self.ask(q, debug=False) for q in ("When do I create an installment plan?", "What is the minimum installment amount?",
                                                                                      "How are dunning notices created?", "What is the weather in Hyderabad?")}
        self.assertEqual(set(seen), {"answered", "unable_to_verify", "documentation_unavailable", "out_of_scope"})
        for st, b in seen.items():
            self.assertNotIn("debug", b)
            self.assertFalse(INTERNAL_ID.search(b["answer"]), st)
            self.assertTrue(b["answer"].strip())
            self.assertEqual(bool(b["sources"]), st == "answered")
            self.assertEqual(b["metadata"]["grounded"], st == "answered")

    def test_evidence_block_only_in_debug(self):
        self.assertNotIn("debug", self.ask("When do I create an installment plan?", debug=False))
        ev = self.ask("When do I create an installment plan?")["debug"]["evidence"]
        for k in ("supported", "reason", "focus_terms", "asked_terms", "kinds", "selected", "support_chain"):
            self.assertIn(k, ev)

    def test_deterministic(self):
        q = "What is the minimum installment amount?"
        a, b = self.ask(q, debug=False), self.ask(q, debug=False)
        for x in (a, b):
            x["metadata"].pop("latency_ms"), x.pop("conversation_id")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
