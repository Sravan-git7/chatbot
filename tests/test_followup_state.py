"""Regressions for active follow-up state, scoped dispatch, and topic-consistency refusal (no real stores required)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import m2c_page_identity as PID  # noqa: E402
import rag_elaborate as EL  # noqa: E402
import rag_pipeline as RP  # noqa: E402
import rag_service as S  # noqa: E402
try:
    import rag_api as API  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
except ModuleNotFoundError:  # the core follow-up tests do not require optional HTTP dependencies
    API = None
    TestClient = None

BILLING = "How does billing work?"
BASE_ANSWER = "Billing calculates charges for each service period. [S1]"
NOVEL_ANSWER = "The billing run selects consumption items using the billing schema. [S2]"


def _source(marker="S2", source_id="M2C-12"):
    return {"marker": marker, "title": "Automatic Billing", "heading_path": ["Automatic Billing"], "url": "https://help.sap.com/billing",
            "chunk_id": "billing/chunk", "join": {"card_source_id": source_id}}


def _raw_answer(answer: str) -> dict:
    return {
        "schema_version": "8.1", "status": "answered", "answer": answer, "reason_code": None,
        "topic": {"source_id": "M2C-12", "title": "Automatic Billing", "card_url": "https://help.sap.com/billing",
                  "identity_status": "resolved_local_page", "effective_guide_id": "billing-guide",
                  "effective_page_id": "billing-page", "corpus_status": "ingested"},
        "citations": {"topic_pointer": None, "answer_sources": [_source()], "context_not_cited": [], "label": "answer_sources", "notes": []},
        "debug": {"grounding": {"ok": True, "sentences": [{"marker": "S2"}], "violations": [], "cited_markers": ["S2"]},
                  "context": {"items": [{"marker": "S2", "text": answer}]}},
        "timings_ms": {},
    }


class _FakeRequestPipeline:
    def __init__(self, answer: str):
        self.generator = SimpleNamespace(name="extractive")
        self.retriever = SimpleNamespace()
        self.answer_text = answer
        self.calls = []

    def answer(self, query, debug=False, **kwargs):
        self.calls.append((query, debug, kwargs))
        return _raw_answer(self.answer_text)


def _service(generator_name="ollama"):
    base = SimpleNamespace(
        backend=object(), retriever=SimpleNamespace(reset_request_state=lambda: None), ctx=object(),
        corpus=SimpleNamespace(entries={}), generator=SimpleNamespace(name=generator_name, reset_request_state=lambda: None),
        count_tokens=lambda text: len(str(text).split()), cards={}, cfg=RP.PipelineConfig(),
    )
    return S.RagService(base, generator_name)


@unittest.skipIf(API is None, "fastapi / httpx not installed")
class APIActiveTopicContract(unittest.TestCase):
    def test_active_topic_context_and_identity_round_trip_through_http_models(self):
        identity = {"source_id": "M2C-12", "title": "Automatic Billing", "guide_id": "billing-guide",
                    "page_id": "billing-page", "industry": S.ACTIVE_INDUSTRY_CONTEXT}
        context = {"questions": [BILLING], "answer": BASE_ANSWER,
                   "active_topic": {"query": BILLING, "answer": BASE_ANSWER, "identity": identity,
                                    "seen_answers": [NOVEL_ANSWER]}}

        class CaptureService:
            received_context = None

            def ask(self, message, conversation_id=None, debug=False, context=None):
                self.received_context = context
                return {
                    "schema_version": S.SCHEMA_VERSION, "conversation_id": conversation_id,
                    "status": "answered", "answer": NOVEL_ANSWER, "sources": [], "topic_reference": None,
                    "metadata": {
                        "card_id": identity["source_id"], "card_title": identity["title"],
                        "identity_status": "resolved_local_page", "page_available": True,
                        "generator": "extractive", "grounded": True,
                        "grounding": {"checked": True, "ok": True, "sentences": 1, "violations": 0, "cited_markers": ["S2"]},
                        "pipeline_status": "answered", "reason_code": None, "latency_ms": 1.0,
                        "topic_identity": identity, "follow_up_category": "elaborate",
                    },
                }

        service = CaptureService()
        with TestClient(API.create_app(service=service, static_dir=ROOT / "missing-static")) as client:
            response = client.post("/api/chat", json={"message": "elaborate", "conversation_id": "active-topic", "context": context})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.received_context["active_topic"]["identity"], identity)
        self.assertEqual(service.received_context["active_topic"]["seen_answers"], [NOVEL_ANSWER])
        self.assertEqual(response.json()["metadata"]["topic_identity"], identity)
        self.assertEqual(response.json()["metadata"]["follow_up_category"], "elaborate")


@unittest.skipIf(API is None, "fastapi / httpx not installed")
class APIElaborationRequestContract(unittest.TestCase):
    def test_api_requires_context_for_bare_alias_and_uses_grounded_same_conversation_context(self):
        service = _service("extractive")
        base = _FakeRequestPipeline(BASE_ANSWER)
        scoped = _FakeRequestPipeline(NOVEL_ANSWER)
        service.pipeline.answer = base.answer
        app = API.create_app(service=service, static_dir=ROOT / "missing-static")

        with patch.object(EL, "scoped_pipeline", return_value=scoped), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            with TestClient(app) as client:
                stale = client.post("/api/chat", json={
                    "message": BILLING, "conversation_id": "api-empty-context",
                })
                self.assertEqual(stale.status_code, 200, stale.text)
                self.assertEqual(stale.json()["status"], S.ANSWERED)
                missing = client.post("/api/chat", json={
                    "message": "Elaborate.", "conversation_id": "api-empty-context",
                    "context": {"questions": []},
                })
                self.assertEqual(missing.status_code, 200, missing.text)
                missing_body = missing.json()
                self.assertEqual(missing_body["status"], S.UNABLE_TO_VERIFY)
                self.assertEqual(missing_body["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
                self.assertEqual(missing_body["sources"], [])
                self.assertIsNone(missing_body["topic_reference"])

                first = client.post("/api/chat", json={
                    "message": BILLING, "conversation_id": "api-grounded-conversation",
                })
                self.assertEqual(first.status_code, 200, first.text)
                first_body = first.json()
                identity = first_body["metadata"]["topic_identity"]
                context = {
                    "questions": [BILLING],
                    "answer": first_body["answer"],
                    "active_topic": {
                        "query": BILLING, "answer": first_body["answer"], "identity": identity,
                        "seen_answers": [],
                    },
                }
                detail = client.post("/api/chat", json={
                    "message": "Elaborate.", "conversation_id": first_body["conversation_id"],
                    "context": context,
                })

        self.assertEqual(detail.status_code, 200, detail.text)
        detail_body = detail.json()
        self.assertEqual(detail_body["conversation_id"], first_body["conversation_id"])
        self.assertEqual(detail_body["status"], S.ANSWERED)
        self.assertEqual(detail_body["metadata"]["follow_up_category"], "elaborate")
        self.assertTrue(detail_body["metadata"]["grounded"])
        self.assertEqual(detail_body["answer"], NOVEL_ANSWER)
        self.assertTrue(detail_body["sources"])
        self.assertIn(f"[{detail_body['sources'][0]['marker']}]", detail_body["answer"])


class DispatchAndNovelty(unittest.TestCase):
    def test_bare_elaboration_aliases_without_eligible_context_clarify_without_routing(self):
        service = _service("ollama")
        with patch.object(service, "_run_pipeline_request", side_effect=AssertionError("bare alias must not route")) as run:
            for index, alias in enumerate(("elaborate", "Elaborate.", "elaborat", "elaboratee", "elabroate")):
                with self.subTest(alias=alias):
                    result = service.ask(alias, conversation_id=f"fresh-elaboration-{index}", debug=True)
                    self.assertEqual(result["status"], S.UNABLE_TO_VERIFY)
                    self.assertEqual(result["answer"], S.ELABORATION_CONTEXT_MISSING_TEXT)
                    self.assertEqual(result["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
                    self.assertFalse(result["metadata"]["grounded"])
                    self.assertFalse(result["metadata"]["can_elaborate"])
                    self.assertIsNone(result["metadata"]["page_available"])
                    self.assertEqual(result["sources"], [])
                    self.assertIsNone(result["topic_reference"])
                    self.assertNotIn("follow_up", result["debug"]["pipeline"])
        run.assert_not_called()

    def test_same_conversation_bare_alias_uses_only_the_prior_grounded_answer(self):
        service = _service("extractive")
        base = _FakeRequestPipeline(BASE_ANSWER)
        scoped = _FakeRequestPipeline(NOVEL_ANSWER)
        service.pipeline.answer = base.answer
        with patch.object(EL, "scoped_pipeline", return_value=scoped), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            first = service.ask(BILLING, conversation_id="same-grounded-topic")
            follow_up = service.ask("elaborate", conversation_id="same-grounded-topic", debug=True)

        self.assertEqual(first["status"], S.ANSWERED)
        self.assertTrue(first["metadata"]["grounded"])
        self.assertEqual(follow_up["conversation_id"], first["conversation_id"])
        self.assertEqual(follow_up["status"], S.ANSWERED)
        self.assertEqual(follow_up["metadata"]["follow_up_category"], "elaborate")
        self.assertTrue(follow_up["metadata"]["grounded"])
        self.assertEqual(follow_up["answer"], NOVEL_ANSWER)
        self.assertTrue(follow_up["sources"])
        self.assertIn(f"[{follow_up['sources'][0]['marker']}]", follow_up["answer"])
        self.assertEqual(scoped.calls[0][0], BILLING)

    def test_new_topic_wording_that_starts_with_elaborate_uses_normal_routing(self):
        service = _service("extractive")
        normal = _FakeRequestPipeline("Installment-plan information. [S2]")
        service.pipeline.answer = normal.answer
        with patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            result = service.ask("elaborate on installment plans", conversation_id="new-topic", debug=True,
                                 context={"questions": [BILLING], "answer": BASE_ANSWER})

        self.assertEqual(result["status"], S.ANSWERED)
        self.assertEqual(normal.calls[0][0], "elaborate on installment plans")
        self.assertNotIn("follow_up", result["debug"]["pipeline"])
        self.assertIsNone(result["metadata"].get("follow_up_category"))

    def test_an_unavailable_topic_cannot_anchor_elaboration(self):
        service = _service("extractive")
        raw_unavailable = {
            "message": "Tell me about Contract Account Business Object.",
            "status": "page_not_ingested",
            "reason_code": "PAGE_NOT_INGESTED",
            "answer": None,
            "topic": {
                "source_id": "M2C-18", "title": "Contract Account Business Object",
                "card_url": "https://help.sap.com/contract-account-business-object",
                "identity_status": "resolved_local_page", "effective_guide_id": "guide-contract",
                "effective_page_id": "page-contract", "corpus_status": "not_ingested",
            },
            "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": "none", "notes": []},
            "routing": {"candidates": [{"coverage": 1.0}], "mode": "normal"},
            "debug": {}, "timings_ms": {},
        }
        with patch.object(service, "_run_pipeline_request", return_value=(raw_unavailable, None)) as run:
            unavailable = service.ask("Tell me about Contract Account Business Object.", conversation_id="unavailable-topic")
            follow_up = service.ask("elaborate", conversation_id="unavailable-topic")

        self.assertEqual(unavailable["status"], S.DOC_UNAVAILABLE)
        self.assertFalse(unavailable["metadata"]["grounded"])
        self.assertEqual(follow_up["status"], S.UNABLE_TO_VERIFY)
        self.assertEqual(follow_up["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
        self.assertEqual(follow_up["sources"], [])
        self.assertIsNone(follow_up["topic_reference"])
        self.assertIsNone(follow_up["metadata"].get("follow_up_category"))
        self.assertEqual(run.call_count, 1)

    def test_first_elaborate_uses_deterministic_scoped_pipeline_even_when_normal_generator_is_ollama(self):
        service = _service("ollama")
        scoped = _FakeRequestPipeline(NOVEL_ANSWER)
        with patch.object(EL, "scoped_pipeline", return_value=scoped) as build_scoped, \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            result = service.ask("elaborate", context={"questions": [BILLING], "answer": BASE_ANSWER}, debug=True)

        self.assertEqual(result["status"], "answered")
        self.assertNotEqual(result["answer"], BASE_ANSWER)
        self.assertEqual(result["answer"], NOVEL_ANSWER)
        self.assertEqual(result["metadata"]["generator"], "extractive")
        self.assertEqual(result["metadata"]["follow_up_category"], "elaborate")
        self.assertEqual(scoped.calls[0][0], BILLING)
        self.assertEqual(build_scoped.call_args.kwargs["previous_answer"], BASE_ANSWER)

    def test_explicit_active_topic_beats_stale_history_and_reaches_both_consistency_gates(self):
        service = _service("extractive")
        card = next(card for card in PID.load_cards(ROOT) if card["source_id"] == "M2C-12")
        service.pipeline.cards = {card["source_id"]: card}
        service.pipeline.ctx = PID.IdentityContext.from_root(ROOT)
        resolved = PID.resolve_identity(card, service.pipeline.ctx)
        identity = {"source_id": card["source_id"], "title": resolved.card_title,
                    "guide_id": resolved.effective_guide_id, "page_id": resolved.effective_page_id,
                    "industry": S.ACTIVE_INDUSTRY_CONTEXT}
        active = {"query": BILLING, "answer": BASE_ANSWER, "identity": identity,
                  "seen_answers": ["Previously shown billing detail. [S3]"]}
        stale_history = {"active_topic": active, "questions": ["What is a contract account?"],
                         "answer": "Contract Account recommendation text."}
        scoped = _FakeRequestPipeline(NOVEL_ANSWER)
        with patch.object(EL, "scoped_pipeline", return_value=scoped) as build_scoped, \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            result = service.ask("elaborate", context=stale_history, debug=True)

        self.assertEqual(result["status"], "answered")
        self.assertEqual(scoped.calls[0][0], BILLING)
        self.assertEqual(scoped.calls[0][2]["expected_topic"]["identity"], identity)
        self.assertEqual(build_scoped.call_args.kwargs["active_identity"], identity)
        self.assertEqual(build_scoped.call_args.kwargs["previous_answer"],
                         f"{BASE_ANSWER}\nPreviously shown billing detail. [S3]")

    def test_byte_identical_fallback_is_converted_to_an_explicit_abstention(self):
        service = _service("extractive")
        scoped = _FakeRequestPipeline(BASE_ANSWER)
        with patch.object(EL, "scoped_pipeline", return_value=scoped), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            result = service.ask("elaborate", context={"questions": [BILLING], "answer": BASE_ANSWER}, debug=True)

        # Exhausted elaboration is its own deterministic state: NOT unable_to_verify, NOT documentation_unavailable.
        self.assertEqual(result["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
        self.assertNotEqual(result["answer"], BASE_ANSWER)
        self.assertEqual(result["answer"], S.USER_TEXT[S.NO_ADDITIONAL_VERIFIED_EVIDENCE])
        self.assertEqual(result["sources"], [])
        self.assertIsNone(result["topic_reference"])          # the used page is never claimed to be missing
        self.assertEqual(result["metadata"]["reason_code"], "NO_ADDITIONAL_SUPPORTED_DETAILS")
        self.assertEqual(result["metadata"]["follow_up_category"], "elaborate")
        self.assertFalse(result["metadata"]["grounded"])
        self.assertFalse(result["metadata"]["can_elaborate"])
        self.assertEqual(result["debug"]["evidence"]["final_novelty_check"]["ok"], False)

    def test_server_canonicalizes_active_page_identity_and_fails_closed_on_mismatch(self):
        cards = PID.load_cards(ROOT)
        identity_context = PID.IdentityContext.from_root(ROOT)
        found = None
        for card in cards:
            resolved = PID.resolve_identity(card, identity_context)
            if resolved.effective_guide_id and resolved.effective_page_id:
                found = (card, resolved)
                break
        self.assertIsNotNone(found, "the checked-in topic registry must have an identified page")
        card, resolved = found
        service = object.__new__(S.RagService)
        service.pipeline = SimpleNamespace(cards={card["source_id"]: card}, ctx=identity_context)
        active = {"query": "What is this topic?", "answer": "A supported answer.",
                  "identity": {"source_id": card["source_id"], "title": resolved.card_title,
                               "guide_id": resolved.effective_guide_id, "page_id": resolved.effective_page_id,
                               "industry": S.ACTIVE_INDUSTRY_CONTEXT}, "seen_answers": []}
        context = service._canonical_active_topic({"active_topic": active})
        self.assertIsNotNone(context)
        self.assertEqual(context["identity"]["source_id"], card["source_id"])
        self.assertEqual(context["identity"]["guide_id"], resolved.effective_guide_id)
        active["identity"]["page_id"] = "a-different-page"
        self.assertIsNone(service._canonical_active_topic({"active_topic": active}))


def _raw_refusal() -> dict:
    return {
        "schema_version": "8.1", "status": "insufficient_context", "answer": None, "reason_code": "GENERATOR_REFUSED",
        "topic": {"source_id": "M2C-12", "title": "Automatic Billing", "card_url": "https://help.sap.com/billing",
                  "identity_status": "resolved_local_page", "effective_guide_id": "billing-guide",
                  "effective_page_id": "billing-page", "corpus_status": "ingested"},
        "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": "none", "notes": []},
        "debug": {"grounding": {"ok": False, "sentences": [], "violations": [], "cited_markers": []}},
        "timings_ms": {},
    }


def _raw_out_of_domain() -> dict:
    return {
        "schema_version": "8.1", "status": "out_of_domain", "answer": None,
        "reason_code": "LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC",
        "topic": {"source_id": None, "title": None, "card_url": None, "identity_status": None,
                  "effective_guide_id": None, "effective_page_id": None, "corpus_status": None},
        "citations": {"topic_pointer": None, "answer_sources": [], "context_not_cited": [], "label": "none", "notes": []},
        "debug": {},
        "timings_ms": {},
    }


class _ScriptedPipeline:
    """A base-pipeline stand-in that answers each scripted query with the given raw result."""

    def __init__(self, script):
        self.script = dict(script)
        self.generator = SimpleNamespace(name="extractive", reset_request_state=lambda: None)
        self.retriever = SimpleNamespace()
        self.calls = []

    def answer(self, query, debug=False, **kwargs):
        self.calls.append(query)
        return self.script.get(query, _raw_out_of_domain())


class ExhaustedElaborationState(unittest.TestCase):
    """The active topic survives an exhausted elaboration; repeated elaboration never falls through to OOS."""

    def _service_with_script(self, script):
        service = _service("extractive")
        base = _ScriptedPipeline(script)
        service.pipeline.answer = base.answer
        return service, base

    def test_repeated_elaborate_after_exhaustion_never_becomes_out_of_scope(self):
        service, base = self._service_with_script({BILLING: _raw_answer(BASE_ANSWER)})
        scoped_answer = _FakeRequestPipeline(NOVEL_ANSWER)
        scoped_refused = _FakeRequestPipeline.__new__(_FakeRequestPipeline)
        scoped_refused.generator = SimpleNamespace(name="extractive")
        scoped_refused.retriever = SimpleNamespace()
        scoped_refused.calls = []
        scoped_refused.answer = lambda query, debug=False, **kwargs: _raw_refusal()
        scoped_pipelines = [scoped_answer, scoped_refused]
        built = []

        def fake_scoped(*args, **kwargs):
            built.append(kwargs)
            return scoped_pipelines[min(len(built) - 1, len(scoped_pipelines) - 1)]

        with patch.object(EL, "scoped_pipeline", side_effect=fake_scoped), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            first = service.ask(BILLING, conversation_id="conv-exhausted")
            self.assertEqual(first["status"], "answered")
            self.assertTrue(first["metadata"]["can_elaborate"])

            second = service.ask("elaborate", conversation_id="conv-exhausted")
            self.assertEqual(second["status"], "answered")                    # expanded grounded elaboration
            self.assertTrue(second["metadata"]["can_elaborate"])

            third = service.ask("elaborate", conversation_id="conv-exhausted")
            self.assertEqual(third["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
            self.assertEqual(third["answer"], S.USER_TEXT[S.NO_ADDITIONAL_VERIFIED_EVIDENCE])
            self.assertEqual(third["metadata"]["reason_code"], "NO_ADDITIONAL_SUPPORTED_DETAILS")
            self.assertEqual(third["metadata"]["follow_up_category"], "elaborate")
            self.assertFalse(third["metadata"]["can_elaborate"])
            self.assertIsNone(third["topic_reference"])                       # never claims the used page is missing
            self.assertEqual(third["sources"], [])

            scoped_calls_before = len(built)
            base_calls_before = len(base.calls)
            for phrase in ("elaborate", "explain more", "tell me more", "go deeper"):
                again = service.ask(phrase, conversation_id="conv-exhausted", debug=True)
                self.assertEqual(again["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE, phrase)
                self.assertEqual(again["answer"], S.USER_TEXT[S.NO_ADDITIONAL_VERIFIED_EVIDENCE], phrase)
                self.assertEqual(again["metadata"]["follow_up_category"], "elaborate", phrase)
                self.assertFalse(again["metadata"]["can_elaborate"], phrase)
                self.assertIsNone(again["topic_reference"], phrase)
                self.assertEqual(again["debug"]["pipeline"]["follow_up"]["pass"], "elaboration_exhausted", phrase)
            # the exhausted state is served from the backend state: no retrieval, no generation, no gates
            self.assertEqual(len(built), scoped_calls_before)
            self.assertEqual(len(base.calls), base_calls_before)

    def test_a_new_query_after_exhaustion_routes_normally_and_re_anchors(self):
        service, base = self._service_with_script({BILLING: _raw_answer(BASE_ANSWER)})
        scoped_refused = _FakeRequestPipeline.__new__(_FakeRequestPipeline)
        scoped_refused.generator = SimpleNamespace(name="extractive")
        scoped_refused.retriever = SimpleNamespace()
        scoped_refused.calls = []
        scoped_refused.answer = lambda query, debug=False, **kwargs: _raw_refusal()
        with patch.object(EL, "scoped_pipeline", return_value=scoped_refused), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            service.ask(BILLING, conversation_id="conv-switch")
            exhausted = service.ask("elaborate", conversation_id="conv-switch")
            self.assertEqual(exhausted["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)

            contract_raw = _raw_answer("A contract account is a master data record. [S1]")
            contract_raw["topic"] = {"source_id": "M2C-17", "title": "Contract Accounts Overview",
                                     "card_url": "https://help.sap.com/contracts", "identity_status": "resolved_local_page",
                                     "effective_guide_id": "contract-guide", "effective_page_id": "contract-page",
                                     "corpus_status": "ingested"}
            base.script["What is a contract account?"] = contract_raw
            switched = service.ask("What is a contract account?", conversation_id="conv-switch")
            self.assertEqual(switched["status"], "answered")
            self.assertEqual(switched["metadata"]["card_id"], "M2C-17")
            self.assertTrue(switched["metadata"]["can_elaborate"])

    def test_an_out_of_scope_turn_after_exhaustion_clears_the_anchor_safely(self):
        service, base = self._service_with_script({BILLING: _raw_answer(BASE_ANSWER)})
        scoped_refused = _FakeRequestPipeline.__new__(_FakeRequestPipeline)
        scoped_refused.generator = SimpleNamespace(name="extractive")
        scoped_refused.retriever = SimpleNamespace()
        scoped_refused.calls = []
        scoped_refused.answer = lambda query, debug=False, **kwargs: _raw_refusal()
        with patch.object(EL, "scoped_pipeline", return_value=scoped_refused), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            service.ask(BILLING, conversation_id="conv-oos")
            exhausted = service.ask("elaborate", conversation_id="conv-oos")
            self.assertEqual(exhausted["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)

            oos = service.ask("What is the capital of France?", conversation_id="conv-oos")
            self.assertEqual(oos["status"], "out_of_scope")

            # No eligible topic remains: return a clarification without routing the bare alias.
            calls_before = len(base.calls)
            after = service.ask("elaborate", conversation_id="conv-oos")
            self.assertEqual(after["status"], S.UNABLE_TO_VERIFY)
            self.assertEqual(after["metadata"]["reason_code"], S.ELABORATION_CONTEXT_MISSING)
            self.assertEqual(after["sources"], [])
            self.assertEqual(len(base.calls), calls_before)                    # the raw alias never reaches topic routing

    def test_a_non_elaborate_follow_up_after_exhaustion_keeps_the_anchor_without_spending_it(self):
        service, base = self._service_with_script({BILLING: _raw_answer(BASE_ANSWER)})
        scoped_refused = _FakeRequestPipeline.__new__(_FakeRequestPipeline)
        scoped_refused.generator = SimpleNamespace(name="extractive")
        scoped_refused.retriever = SimpleNamespace()
        scoped_refused.calls = []
        scoped_refused.answer = lambda query, debug=False, **kwargs: _raw_refusal()
        with patch.object(EL, "scoped_pipeline", return_value=scoped_refused) as build_scoped, \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            service.ask(BILLING, conversation_id="conv-example")
            exhausted = service.ask("elaborate", conversation_id="conv-example")
            self.assertEqual(exhausted["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
            calls_after_exhaustion = build_scoped.call_count

            # "give me an example" is a different intent: it runs its own scoped pass (not the short-circuit) ...
            example = service.ask("give me an example", conversation_id="conv-example")
            self.assertEqual(example["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
            self.assertEqual(build_scoped.call_count, calls_after_exhaustion + 1)
            self.assertEqual(build_scoped.call_args.kwargs["previous_answer"].split("\n")[0], BASE_ANSWER)

            # ... and the topic is still anchored, so a later "elaborate" resolves instead of falling to OOS
            again = service.ask("elaborate", conversation_id="conv-example")
            self.assertEqual(again["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
            self.assertNotEqual(again["status"], "out_of_scope")


class TopicConsistency(unittest.TestCase):
    @staticmethod
    def _identity(source_id="M2C-17", guide_id="contract-guide", page_id="contract-page", title="Contract Accounts Overview"):
        return SimpleNamespace(
            source_id=source_id, card_title=title, card_url="https://help.sap.com/contracts",
            effective_guide_id=guide_id, effective_page_id=page_id, resolution_status="resolved_local_page",
            card_guide_id=guide_id, card_page_id=page_id, card_needs_review=False,
            to_dict=lambda: {"source_id": source_id, "effective_guide_id": guide_id, "effective_page_id": page_id},
        )

    def _answer_with_expected_topic(self, expected):
        card = {"source_id": "M2C-17", "title": "Contract Accounts Overview", "source_url": "https://help.sap.com/contracts"}
        candidate = SimpleNamespace(rank=1, source_id="M2C-17", title="Contract Accounts Overview", distance=0.1)
        route = SimpleNamespace(candidates=[candidate], state="selected")
        corpus = SimpleNamespace(entry=lambda _source_id: {"corpus_status": "ingested"})
        generator = SimpleNamespace(name="extractive", generate=lambda *_: self.fail("mismatched topic must stop before generation"))
        retriever = SimpleNamespace()
        pipeline = RP.RagPipeline(
            object(), retriever, SimpleNamespace(page_index=object(), topic_manifest={}), corpus, generator, lambda _text: 1, cards=[card],
            config=RP.PipelineConfig(rerank_router=False, code_aware_router=False),
        )
        with patch.object(RP, "route_to_page", return_value=route), \
             patch.object(RP.pid, "resolve_identity", return_value=self._identity()):
            return pipeline.answer("How does billing work?", debug=True, expected_topic=expected)

    def test_wrong_active_card_or_page_is_rejected_before_second_retrieval(self):
        expected = {"identity": {"source_id": "M2C-12", "title": "Automatic Billing", "guide_id": "billing-guide",
                                  "page_id": "billing-page", "industry": RP.ACTIVE_INDUSTRY_CONTEXT}}
        raw = self._answer_with_expected_topic(expected)
        self.assertEqual(raw["status"], RP.INSUFFICIENT)
        self.assertEqual(raw["reason_code"], "ACTIVE_TOPIC_MISMATCH")
        self.assertEqual(raw["topic"], {})
        self.assertEqual(raw["citations"]["answer_sources"], [])
        self.assertEqual(raw["debug"]["topic_consistency"]["ok"], False)
        self.assertNotIn("retrieval", raw["debug"])

    def test_same_card_with_a_different_active_page_is_rejected_before_retrieval(self):
        expected = {"identity": {"source_id": "M2C-17", "title": "Contract Accounts Overview", "guide_id": "contract-guide",
                                  "page_id": "billing-page", "industry": RP.ACTIVE_INDUSTRY_CONTEXT}}
        raw = self._answer_with_expected_topic(expected)
        self.assertEqual(raw["reason_code"], "ACTIVE_TOPIC_MISMATCH")
        self.assertEqual(raw["debug"]["topic_consistency"]["mismatches"], ["page_id"])
        self.assertNotIn("retrieval", raw["debug"])

    def test_industry_mismatch_is_rejected_even_when_the_card_and_page_match(self):
        expected = {"identity": {"source_id": "M2C-17", "title": "Contract Accounts Overview", "guide_id": "contract-guide",
                                  "page_id": "contract-page", "industry": "Insurance/FS-CD"}}
        raw = self._answer_with_expected_topic(expected)
        self.assertEqual(raw["reason_code"], "ACTIVE_TOPIC_MISMATCH")
        self.assertIn("industry", raw["debug"]["topic_consistency"]["mismatches"])

    def test_selected_context_units_must_match_active_page_identity(self):
        units = [SimpleNamespace(marker="S1"), SimpleNamespace(marker="S2")]
        context = SimpleNamespace(items=[
            SimpleNamespace(marker="S1", guide_id="billing-guide", page_id="billing-page"),
            SimpleNamespace(marker="S2", guide_id="contract-guide", page_id="contract-page"),
        ])
        kept, details = EL._topic_identity_filter(
            units, context, {"guide_id": "billing-guide", "page_id": "billing-page", "industry": "SAP Utilities/IS-U"},
        )
        self.assertEqual([unit.marker for unit in kept], ["S1"])
        self.assertTrue(details["ok"])
        self.assertEqual(details["excluded_markers"], ["S2"])

    def test_topic_rejected_markers_are_removed_from_grounding_and_citation_context(self):
        context = SimpleNamespace(items=[SimpleNamespace(marker="S1"), SimpleNamespace(marker="S2")])
        filtered = RP._citation_context_after_scope(context, {"topic_consistency": {"excluded_markers": ["S2"]}})
        self.assertEqual([item.marker for item in filtered.items], ["S1"])


class ExhaustedRoutingMetadata(unittest.TestCase):
    """An exhausted scoped follow-up reports routing.mode = elaboration_exhausted; the routed source is kept."""

    ROUTING = {
        "selected_source_id": "M2C-12",
        "candidates": [{"rank": 1, "source_id": "M2C-12", "title": "Automatic Billing", "similarity": 0.91}],
        "mode": "router_reranked_top10_code_aware",
    }

    def _ask_after_answer(self, follow_up, scoped_raw, conversation_id):
        service = _service("extractive")
        base = _ScriptedPipeline({BILLING: dict(_raw_answer(BASE_ANSWER), routing=dict(self.ROUTING))})
        service.pipeline.answer = base.answer
        scoped = _FakeRequestPipeline.__new__(_FakeRequestPipeline)
        scoped.generator = SimpleNamespace(name="extractive")
        scoped.retriever = SimpleNamespace()
        scoped.calls = []
        scoped.answer = lambda query, debug=False, **kwargs: scoped_raw
        with patch.object(EL, "scoped_pipeline", return_value=scoped), \
             patch.object(S, "support_chain", return_value={"ok": True, "verbatim_all": True}):
            first = service.ask(BILLING, conversation_id=conversation_id)
            self.assertEqual(first["status"], "answered")
            return service, service.ask(follow_up, conversation_id=conversation_id, debug=True)

    def test_exhausted_elaboration_keeps_the_routed_source_and_reports_the_exhausted_mode(self):
        _, result = self._ask_after_answer("elaborate", dict(_raw_refusal(), routing=dict(self.ROUTING)), "conv-routing-elaborate")

        self.assertEqual(result["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
        routing = result["debug"]["routing"]
        self.assertEqual(routing["mode"], "elaboration_exhausted")
        self.assertEqual(S.ELABORATION_EXHAUSTED_MODE, "elaboration_exhausted")
        self.assertEqual(routing["selected_source_id"], "M2C-12")
        self.assertEqual(routing["candidates"], self.ROUTING["candidates"])

    def test_a_causal_follow_up_that_abstains_reports_the_exhausted_mode(self):
        _, result = self._ask_after_answer("Why?", dict(_raw_refusal(), routing=dict(self.ROUTING)), "conv-routing-why")

        self.assertEqual(result["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
        self.assertEqual(result["metadata"]["follow_up_category"], "reason")
        self.assertEqual(result["debug"]["routing"]["mode"], "elaboration_exhausted")

    def test_repeated_elaboration_after_exhaustion_keeps_the_exhausted_mode(self):
        service, _ = self._ask_after_answer("elaborate", dict(_raw_refusal(), routing=dict(self.ROUTING)), "conv-routing-repeat")
        again = service.ask("explain more", conversation_id="conv-routing-repeat", debug=True)

        self.assertEqual(again["status"], S.NO_ADDITIONAL_VERIFIED_EVIDENCE)
        self.assertEqual(again["debug"]["routing"]["mode"], "elaboration_exhausted")

    def test_an_answered_elaboration_keeps_its_own_routing_mode(self):
        answered = dict(_raw_answer(NOVEL_ANSWER), routing=dict(self.ROUTING))
        _, result = self._ask_after_answer("elaborate", answered, "conv-routing-answered")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["debug"]["routing"]["mode"], "router_reranked_top10_code_aware")


if __name__ == "__main__":
    unittest.main()
