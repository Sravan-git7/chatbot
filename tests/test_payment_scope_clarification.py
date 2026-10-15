"""Payment ambiguity policy; hermetic guards and real pipeline code over fake-vector fixtures.

No real embedding model, Ollama, browser or authoritative SAP adjudication is implied.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "eval/phase3")]
import adapters  # noqa: E402
import rag_evidence as EV  # noqa: E402
import rag_service as S  # noqa: E402
from tests.phase8_support import make_pipeline  # noqa: E402


def payment_context():
    snapshot = json.loads((ROOT / "eval/phase3/evidence_cache.json").read_text())["snapshots"]["CASE-052"]
    return adapters.build_context_block(snapshot["context_items"])


@pytest.mark.parametrize("question", ["How do I process payments?", "How can we handle payments?", "How are payments processed?"])
def test_bare_payment_process_never_assumes_cash_desk_channel(question):
    result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(question, payment_context())
    assert result.refused
    assert result.evidence["reason"] == "AMBIGUOUS_PAYMENT_PROCESS"
    assert result.evidence["selected"] == []
    assert "cash desk" not in result.text.lower()


def test_ambiguous_payment_guard_does_not_call_model():
    class Inner:
        name = "stub"

        def generate(self, question, context):
            pytest.fail("Ambiguous payment scope must be rejected before any model call")

    result = EV.EvidenceGuard(Inner(), tau=EV.SHIPPED_TAU).generate("How do I process payments?", payment_context())
    assert result.refused
    assert result.evidence["reason"] == "AMBIGUOUS_PAYMENT_PROCESS"


@pytest.mark.parametrize("question", ["How do I process incoming payments from external cash desks?", "What is a payment lot?", "How does billing work?"])
def test_qualified_or_other_topic_is_not_this_ambiguity_policy(question):
    result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(question, payment_context())
    assert result.evidence["reason"] != "AMBIGUOUS_PAYMENT_PROCESS"


def test_service_exposes_clarification_without_claims_sources_or_cash_desk_reference():
    # Existing hermetic pipeline fixture uses a fixed router and fake vectors over the checked-in page corpus.
    # This tests propagation through the actual pipeline/service, NOT current production retrieval quality.
    pipe = make_pipeline(EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU), default=["M2C-22"])
    svc = S.RagService(pipe, "extractive")
    response = svc.ask("How do I process payments?", conversation_id="payment-ambiguity", debug=True)
    assert response["status"] == "unable_to_verify"
    assert response["answer"] == S.PAYMENT_SCOPE_CLARIFICATION_TEXT
    assert response["sources"] == []
    assert response["topic_reference"] is None
    assert response["metadata"]["reason_code"] == "AMBIGUOUS_PAYMENT_PROCESS"
    assert response["metadata"]["clarification_required"] is True
    assert response["metadata"]["grounded"] is False
    assert response["metadata"]["can_elaborate"] is False
    assert response["metadata"]["card_id"] is None
