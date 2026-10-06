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


class DispatchAndNovelty(unittest.TestCase):
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

        self.assertEqual(result["status"], "unable_to_verify")
        self.assertNotEqual(result["answer"], BASE_ANSWER)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["metadata"]["reason_code"], "NO_ADDITIONAL_SUPPORTED_DETAILS")
        self.assertEqual(result["metadata"]["follow_up_category"], "elaborate")
        self.assertFalse(result["metadata"]["grounded"])
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
            object(), retriever, SimpleNamespace(page_index=object()), corpus, generator, lambda _text: 1, cards=[card],
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


if __name__ == "__main__":
    unittest.main()
