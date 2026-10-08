"""Phase 8E/8G/8I - retriever, answer contract and statuses, with a stub card backend, a fake embedder and an in-memory page store."""
from __future__ import annotations

import json
import unittest

from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, ROOT, StubBackend, corpus_records, ephemeral_page_collection, fake_embed, make_pipeline, regex_count

import m2c_page_identity as pid  # noqa: E402
import rag_generate as RG  # noqa: E402

NEEDS = unittest.skipUnless(HAVE_CHROMA and HAVE_BS4, "chromadb / bs4 not installed")


class _Stub:
    def __init__(self, text):
        self.text, self.prompts = text, []

    def generate(self, *args):
        prompt = args[-1] if args else ""
        self.prompts.append(prompt)
        return self.text(prompt) if callable(self.text) else self.text


@NEEDS
class RetrieverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import page_retriever as PR
        cls.PR = PR
        cls.records = corpus_records()
        cls.col, cls.chunks = ephemeral_page_collection(cls.records)
        cls.r = PR.PageRetriever(cls.col, fake_embed)
        cls.by_sid = {x["source_ids"][0]: x for x in cls.records}

    def test_identity_constrained_retrieval_never_leaks(self):
        for sid, rec in self.by_sid.items():
            for q in ("installment plan interest", "meter reading monitoring", "contract account billing invoicing device", "move in move out"):
                hits = self.r.retrieve_in_page(q, rec["guide_id"], rec["page_id"], top_k=10)
                self.assertTrue(hits)
                self.assertTrue(all(h.guide_id == rec["guide_id"] and h.page_id == rec["page_id"] for h in hits), (sid, q))

    def test_wrong_guide_with_right_page_returns_nothing(self):
        rec = self.by_sid["M2C-24"]
        self.assertEqual(self.r.retrieve_in_page("installment", "0" * 32, rec["page_id"]), [])

    def test_unconstrained_mode_crosses_pages(self):
        pages = {h.page_id for h in self.r.retrieve_corpus("contract account billing meter reading installment device", top_k=20)}
        self.assertGreater(len(pages), 1)

    def test_hits_keep_citation_metadata(self):
        rec = self.by_sid["M2C-14"]
        h = self.r.retrieve_in_page("invoicing bill creation", rec["guide_id"], rec["page_id"], top_k=3)[0]
        self.assertEqual(h.source_url, rec["source_url"])
        self.assertEqual(h.title, rec["title"])
        self.assertTrue(h.heading_path and h.heading_path[0] == rec["title"])
        self.assertEqual(len(h.content_hash), 64)
        self.assertTrue(h.chunk_id.startswith(rec["doc_id"]))
        self.assertEqual(h.rank, 1)
        self.assertAlmostEqual(h.similarity, 1 - h.distance)
        self.assertEqual(h.metadata["page_text_sha256"], rec["text_sha256"])

    def test_chunk_text_matches_content_hash(self):
        import hashlib
        rec = self.by_sid["M2C-24"]
        for h in self.r.page_chunks(rec["guide_id"], rec["page_id"]):
            self.assertEqual(hashlib.sha256(h.text.encode()).hexdigest(), h.content_hash)
        self.assertEqual([h.chunk_index for h in self.r.page_chunks(rec["guide_id"], rec["page_id"])], sorted(h.chunk_index for h in self.r.page_chunks(rec["guide_id"], rec["page_id"])))

    def test_leakage_is_detected_not_swallowed(self):
        rec, other = self.by_sid["M2C-24"], self.by_sid["M2C-07"]
        class Leaky(self.PR.PageRetriever):
            def _query(s, query, top_k, where):
                return self.r._query(query, top_k, {"$and": [{"guide_id": other["guide_id"]}, {"page_id": other["page_id"]}]})
        with self.assertRaises(self.PR.LeakageError):
            Leaky(self.col, fake_embed).retrieve_in_page("installment", rec["guide_id"], rec["page_id"])

    def test_empty_query_and_missing_identity(self):
        rec = self.by_sid["M2C-24"]
        self.assertEqual(self.r.retrieve_in_page("   ", rec["guide_id"], rec["page_id"]), [])
        with self.assertRaises(ValueError):
            self.r.retrieve_in_page("x", "", rec["page_id"])

    def test_has_page(self):
        rec = self.by_sid["M2C-24"]
        self.assertTrue(self.r.has_page(rec["guide_id"], rec["page_id"]))
        self.assertFalse(self.r.has_page("0" * 32, "1" * 32))

    def test_legacy_names_refused(self):
        import build_page_collection as BP
        with self.assertRaises(SystemExit):
            BP.guard_names("sap_docs", BP.PAGE_VECTOR_DIR)
        with self.assertRaises(SystemExit):
            BP.guard_names("sap_m2c_card_v1", BP.PAGE_VECTOR_DIR)
        with self.assertRaises(SystemExit):
            BP.guard_names("x", ROOT / "chroma_db")
        with self.assertRaises(SystemExit):
            BP.guard_names("x", BP.C.VECTOR_DIR)


@NEEDS
class PipelineStatusTests(unittest.TestCase):
    def ans(self, query, route, generator=None, **kw):
        p = make_pipeline(generator or RG.ExtractiveGenerator(), ranking={query: route})
        return p.answer(query, debug=True, **kw)

    def test_answered_with_grounded_citations_and_contract_shape(self):
        a = self.ans("When do I create an installment plan with open items?", ["M2C-24", "M2C-23"])
        self.assertEqual(a["status"], "answered", a["reason_code"])
        for k in ("schema_version", "query", "status", "answer", "reason_code", "message", "topic", "citations", "routing", "ui", "timings_ms", "debug"):
            self.assertIn(k, a)
        self.assertEqual(a["routing"]["selected_source_id"], "M2C-24")
        self.assertEqual(a["routing"]["mode"], "router_reranked_top10")
        self.assertTrue(a["citations"]["answer_sources"])
        self.assertTrue(all(s["verified_used"] for s in a["citations"]["answer_sources"]))
        self.assertFalse(a["citations"]["topic_pointer"]["used_as_answer_text"])
        self.assertEqual(a["ui"]["sources"][0]["url"], a["topic"]["card_url"])
        json.dumps(a)                                                  # JSON-serialisable
        # every cited marker exists in the context shown to the generator; no answer without markers
        ctx_markers = {i["marker"] for i in a["debug"]["context"]["items"]}
        self.assertTrue({s["marker"] for s in a["citations"]["answer_sources"]} <= ctx_markers)

    def test_not_ingested_page_is_never_answered(self):
        stub = _Stub("should never be called")
        a = self.ans("How do I create a budget billing plan?", ["M2C-15"], generator=stub)
        self.assertEqual(a["status"], "page_not_ingested")
        self.assertEqual(a["reason_code"], "PAGE_IDENTIFIED_NO_LOCAL_CONTENT")
        self.assertIsNone(a["answer"])
        self.assertEqual(a["topic"]["source_id"], "M2C-13")
        self.assertEqual(a["citations"]["answer_sources"], [])
        self.assertEqual(stub.prompts, [])
        self.assertNotIn("generation", a["debug"])

    def test_explicitly_named_m2c18_conflict_is_unavailable_without_generation(self):
        stub = _Stub("must not be used")
        a = self.ans("What is the contract account business object and what does it represent?", ["M2C-18", "M2C-17"], generator=stub)
        self.assertEqual(a["status"], "page_not_ingested")
        self.assertEqual(a["reason_code"], "PAGE_IDENTIFIED_NO_LOCAL_CONTENT")
        self.assertEqual(a["routing"]["selected_source_id"], "M2C-18")
        self.assertIsNone(a["answer"])
        self.assertEqual(a["citations"]["answer_sources"], [])
        self.assertEqual(stub.prompts, [])
        self.assertTrue(any("conflicting identity" in n for n in a["citations"]["notes"]))

    def test_identity_only_cards_are_unresolved(self):
        for sid, q in (("M2C-01", "How are business partner premise and installation related?"), ("M2C-13", "How is a budget billing plan set up for a customer?")):
            a = self.ans(q, [sid])
            self.assertEqual(a["status"], "unresolved_identity", sid)
            self.assertEqual(a["citations"]["answer_sources"], [])

    def test_out_of_domain_by_lexical_gate(self):
        a = self.ans("What is the capital of France?", ["M2C-24"])
        self.assertEqual(a["status"], "out_of_domain")
        self.assertEqual(a["answer"], None)
        self.assertLess(a["debug"]["gate_topic"]["coverage"], 0.25)

    def test_empty_query_is_no_relevant_page(self):
        p = make_pipeline(RG.ExtractiveGenerator())
        a = p.answer("   ")
        self.assertEqual(a["status"], "no_relevant_page")
        self.assertEqual(p.backend.calls, [])

    def test_m2c05_correction_visible_in_topic_and_citation(self):
        a = self.ans("What is the purpose of the device management component?", ["M2C-05"])
        self.assertEqual(a["status"], "answered", a["reason_code"])
        self.assertTrue(a["topic"]["corrected_identity"])
        self.assertEqual(a["topic"]["identity_status"], pid.CORRECTED_IDENTITY)
        self.assertTrue(any("corrected identity" in n for n in a["citations"]["notes"]))
        self.assertEqual(a["citations"]["answer_sources"][0]["url"], a["topic"]["card_url"])

    def test_m2c14_review_flag_travels_with_the_answer(self):
        a = self.ans("What link does invoicing establish to contract accounting?", ["M2C-14"])
        self.assertEqual(a["status"], "answered", a["reason_code"])
        self.assertTrue(a["topic"]["review_flag"])
        self.assertIn("card:needs_review", a["ui"]["badges"])

    def test_oracle_routing_bypasses_router_and_is_marked(self):
        p = make_pipeline(RG.ExtractiveGenerator())
        a = p.answer("When do I create an installment plan with open items?", oracle_source_id="M2C-24")
        self.assertEqual(a["routing"]["mode"], "oracle")
        self.assertEqual(p.backend.calls, [])
        with self.assertRaises(KeyError):
            p.answer("x", oracle_source_id="M2C-999")

    def test_page_is_registered_but_missing_from_store(self):
        p = make_pipeline(RG.ExtractiveGenerator(), ranking={"installment plan open items": ["M2C-24"]})
        p.retriever.collection.delete(where={"page_id": "790dc5536a51204be10000000a174cb4"})
        a = p.answer("installment plan open items")
        self.assertIn(a["status"], ("page_not_ingested", "out_of_domain"))

    def test_page_text_changes_nothing_in_card_route(self):
        p = make_pipeline(RG.ExtractiveGenerator(), ranking={"q installment plan": ["M2C-23", "M2C-24"]})
        a = p.answer("q installment plan")
        self.assertEqual(a["routing"]["selected_source_id"], "M2C-23")  # page evidence does not change the card route
        self.assertEqual(a["status"], "answered")  # M2C-23 is currently ingested in the corpus
        self.assertEqual({s["join"]["card_source_id"] for s in a["citations"]["answer_sources"]}, {"M2C-23"})


@NEEDS
class HallucinationGuardPipelineTests(unittest.TestCase):
    Q = "When do I create an installment plan with open items?"

    def run_stub(self, text):
        stub = _Stub(text)
        a = make_pipeline(RG.LLMGenerator(stub), ranking={self.Q: ["M2C-24"]}).answer(self.Q, debug=True)
        return a, stub

    def first_marker_sentence(self, prompt):
        import re
        body = prompt.split("DOCUMENTATION EXCERPTS:")[1].split("QUESTION:")[0]
        m = re.search(r"\[(S\d+)\][^\n]*\n(.+)", body)
        sent = [s for s in re.split(r"(?<=[.!?])\s+", m.group(2)) if len(s.split()) >= 5][0]
        return m.group(1), sent

    def test_faithful_llm_answer_passes(self):
        a, stub = self.run_stub(lambda p: "{} [{}]".format(self.first_marker_sentence(p)[1], self.first_marker_sentence(p)[0]))
        self.assertEqual(a["status"], "answered", a["debug"]["grounding"])
        self.assertEqual(len(stub.prompts), 1)

    def test_fabrications_are_withheld_and_never_cited(self):
        fabs = {
            "url": lambda p: "{} [{}] See https://help.sap.com/docs/a/b/c.html.".format(self.first_marker_sentence(p)[1], self.first_marker_sentence(p)[0]),
            "code": lambda p: "{} [{}] Run transaction ZZ99.".format(self.first_marker_sentence(p)[1], self.first_marker_sentence(p)[0]),
            "phantom": lambda p: "{} [S9]".format(self.first_marker_sentence(p)[1]),
            "uncited": lambda p: self.first_marker_sentence(p)[1],
            "off_topic": lambda p: "Paris is the capital of France. [S1]",
            "number": lambda p: "{} [{}] It takes 4711 days.".format(self.first_marker_sentence(p)[1], self.first_marker_sentence(p)[0]),
        }
        for name, fn in fabs.items():
            a, _ = self.run_stub(fn)
            self.assertEqual(a["status"], "insufficient_context", name)
            self.assertEqual(a["reason_code"], "GROUNDING_VERIFICATION_FAILED", name)
            self.assertIsNone(a["answer"], name)
            self.assertEqual(a["citations"]["answer_sources"], [], name)
            self.assertIn("answer_withheld", a["debug"], name)

    def test_llm_refusal_is_insufficient_context(self):
        a, _ = self.run_stub(RG.NO_ANSWER_TEXT)
        self.assertEqual((a["status"], a["reason_code"]), ("insufficient_context", "GENERATOR_REFUSED"))

    def test_absent_topic_words_trip_the_context_gate_before_any_llm_call(self):
        stub = _Stub("irrelevant")
        q = "photovoltaic inverter firmware encryption quantum"
        a = make_pipeline(RG.LLMGenerator(stub), ranking={q: ["M2C-24"]}).answer(q)
        self.assertIn(a["status"], ("out_of_domain", "insufficient_context"))
        self.assertEqual(stub.prompts, [])

    def test_generator_exception_propagates_not_swallowed(self):
        class Boom:
            def generate(self, prompt):
                raise RuntimeError("ollama down")
        p = make_pipeline(RG.LLMGenerator(Boom()), ranking={self.Q: ["M2C-24"]})
        with self.assertRaises(RuntimeError):
            p.answer(self.Q)


class AnswerCliTests(unittest.TestCase):
    def test_cli_uses_injected_pipeline_and_prints_contract(self):
        import contextlib
        import io
        import rag_answer
        class P:
            def answer(self, q, debug=False):
                return {"status": "answered", "answer": "x [S1]", "message": None, "topic": None, "ui": {"headline": "Answer"}, "citations": {}}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rag_answer.main(["--question", "hi", "--json"], pipeline=P())
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["status"], "answered")

    def test_cli_reports_generation_failure_without_fallback(self):
        import contextlib
        import io
        import rag_answer
        class P:
            def answer(self, q, debug=False):
                raise ModuleNotFoundError("No module named 'ollama'")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = rag_answer.main(["--question", "hi"], pipeline=P())
        self.assertEqual(rc, 3)
        self.assertIn("generation failed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
