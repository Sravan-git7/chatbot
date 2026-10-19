"""Adversarial and deep multi-turn RAG validation test suite for SURA.

Tests compound questions, noun-phrase conjunction preservation, multi-aspect disclosures,
multi-turn conversation chains, state isolation across interleaved conversations,
standalone LRU cache isolation and eviction, and grounding verification security.
Zero access to protected production Chroma databases; uses isolated ephemeral fixtures.
"""
import copy
import time
import uuid
import pytest

from types import SimpleNamespace
import ephemeral_service as ES
import rag_generate as RG
import rag_text as T


@pytest.fixture(scope="module")
def ephemeral_service_instance():
    """Build an isolated in-memory ephemeral service instance for adversarial testing."""
    svc = ES.build_ephemeral_service("extractive")
    yield svc
    svc.close()


def test_adv_compound_multi_aspect_contract_accounts(ephemeral_service_instance):
    """Compound question with 3 aspects: contract accounts, purpose, and relationship to business partners."""
    q = "Explain contract accounts, their purpose, and their relationship to business partners."
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    assert res["metadata"]["card_id"] == "M2C-17"
    assert res["metadata"]["verification_status"] == "verified"
    ans = res["answer"].lower()
    assert "contract account" in ans
    assert "business partner" in ans


def test_adv_compound_meter_reading_partial_gap_disclosure(ephemeral_service_instance):
    """Compound question where entry is documented but estimation is absent -> disclosed and partially_supported."""
    q = "How are meter readings entered and when are they estimated?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    assert "meter reading" in res["answer"].lower()
    assert "available documentation does not establish details for: when are they estimated" in res["answer"].lower()
    assert res["metadata"]["verification_status"] == "partially_supported"
    assert res["metadata"]["verification_label"] == "Partially supported by documentation"


def test_adv_compound_unsupported_prerequisites_abstention(ephemeral_service_instance):
    """Compound question asking for nonexistent prerequisites for meter reading orders -> honest abstention."""
    q = "How are meter readings entered, when are they estimated, and what prerequisites apply?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "unable_to_verify"
    assert res["metadata"]["verification_status"] == "unverified"
    assert res["metadata"]["verification_label"] is None


def test_adv_compound_billing_invoicing_comparison(ephemeral_service_instance):
    """Compare billing and invoicing including sequence: framing words don't pollute focus terms."""
    q = "Compare billing and invoicing, including their sequence."
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    assert res["metadata"]["verification_status"] == "partially_supported"
    assert "billing" in res["answer"].lower()
    assert "invoicing" in res["answer"].lower()


def test_adv_noun_phrase_conjunction_preservation(ephemeral_service_instance):
    """Conjunctions inside legitimate noun phrases like 'Contract Accounts Receivable and Payable' are preserved."""
    q = "What is Contract Accounts Receivable and Payable?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    assert res["metadata"]["card_id"] == "M2C-17"
    assert res["metadata"]["verification_status"] in ("verified", "partially_supported")


def test_adv_multi_turn_8_step_conversation(ephemeral_service_instance):
    """Rigorous 8-turn conversation sequence maintaining and updating active topic anchors correctly."""
    cid = f"test_adv_chain_{uuid.uuid4().hex[:8]}"

    # Turn 1: Initial question
    r1 = ephemeral_service_instance.ask("What is an installment plan in SAP Utilities?", conversation_id=cid)
    assert r1["status"] == "answered"
    assert r1["metadata"]["card_title"] == "Creating Installment Plans"

    # Turn 2: Aspect follow-up
    r2 = ephemeral_service_instance.ask("What about prerequisites?", conversation_id=cid)
    assert r2["status"] == "answered"
    assert r2["metadata"]["card_title"] == "Creating Installment Plans"
    assert "customizing" in r2["answer"].lower() or "business transactions" in r2["answer"].lower()

    # Turn 3: Ordinal step follow-up
    r3 = ephemeral_service_instance.ask("Explain the second point.", conversation_id=cid)
    assert r3["status"] == "answered"
    assert r3["metadata"]["card_title"] == "Creating Installment Plans"

    # Turn 4: Simplification follow-up (must preserve root anchor)
    r4 = ephemeral_service_instance.ask("Make it simpler.", conversation_id=cid)
    assert r4["status"] == "answered"
    assert r4["metadata"]["card_title"] == "Creating Installment Plans"

    # Turn 5: Elaboration
    r5 = ephemeral_service_instance.ask("Elaborate.", conversation_id=cid)
    assert r5["status"] == "answered"
    assert r5["metadata"]["card_title"] == "Creating Installment Plans"

    # Turn 6: Specific relational follow-up
    r6 = ephemeral_service_instance.ask("How does it relate to open items?", conversation_id=cid)
    assert r6["status"] == "answered"
    assert r6["metadata"]["card_title"] == "Creating Installment Plans"

    # Turn 7: Topic switch to Technical Master Data
    r7 = ephemeral_service_instance.ask("Tell me about technical master data.", conversation_id=cid)
    assert r7["status"] == "answered"
    assert r7["metadata"]["card_title"] == "Utilities Master Data"
    assert "technical master data" in r7["answer"].lower()

    # Turn 8: Follow-up on the newly switched topic (must bind to Technical Master Data, not Installment Plans)
    r8 = ephemeral_service_instance.ask("How does it work?", conversation_id=cid)
    assert r8["metadata"]["card_title"] == "Utilities Master Data"
    assert r8["status"] in ("answered", "no_additional_verified_evidence")


def test_adv_interleaved_conversations_state_isolation(ephemeral_service_instance):
    """Two concurrent/interleaved conversation IDs must maintain complete state isolation."""
    cid_inst = f"test_iso_inst_{uuid.uuid4().hex[:8]}"
    cid_master = f"test_iso_mast_{uuid.uuid4().hex[:8]}"

    # Turn 1 for both
    r_inst_1 = ephemeral_service_instance.ask("What is an installment plan in SAP Utilities?", conversation_id=cid_inst)
    r_mast_1 = ephemeral_service_instance.ask("Tell me about technical master data.", conversation_id=cid_master)

    assert r_inst_1["metadata"]["card_title"] == "Creating Installment Plans"
    assert r_mast_1["metadata"]["card_title"] == "Utilities Master Data"

    # Turn 2 interleaved: both ask "What about prerequisites?"
    r_inst_2 = ephemeral_service_instance.ask("What about prerequisites?", conversation_id=cid_inst)
    r_mast_2 = ephemeral_service_instance.ask("What about prerequisites?", conversation_id=cid_master)

    # cid_inst must remain anchored to Installment Plans
    assert r_inst_2["metadata"]["card_title"] == "Creating Installment Plans"
    # cid_master must not inherit Installment Plans context
    assert r_mast_2["metadata"]["card_title"] != "Creating Installment Plans"


def test_adv_failed_followup_preserves_anchor(ephemeral_service_instance):
    """An unsupported follow-up must not wipe out the active conversation topic anchor."""
    cid = f"test_fail_anchor_{uuid.uuid4().hex[:8]}"
    r1 = ephemeral_service_instance.ask("What is an installment plan in SAP Utilities?", conversation_id=cid)
    assert r1["status"] == "answered"

    # Turn 2: Out of scope inquiry
    r2 = ephemeral_service_instance.ask("What about astronaut training programs?", conversation_id=cid)
    assert r2["status"] == "out_of_scope"

    # Turn 3: Follow-up should still resolve against Installment Plans from turn 1
    r3 = ephemeral_service_instance.ask("Explain the steps to create it.", conversation_id=cid)
    assert r3["status"] == "answered"
    assert r3["metadata"]["card_title"] == "Creating Installment Plans"


def test_adv_lru_cache_audit(ephemeral_service_instance):
    """Audit standalone LRU cache: latency drop, conversation ID isolation, and debug bypass."""
    q = "What is a contract account?"
    cid1 = f"test_cache_1_{uuid.uuid4().hex[:8]}"
    cid2 = f"test_cache_2_{uuid.uuid4().hex[:8]}"

    # Initial request (cold cache)
    t0 = time.perf_counter()
    r1 = ephemeral_service_instance.ask(q, conversation_id=cid1)
    cold_ms = (time.perf_counter() - t0) * 1000
    assert r1["status"] == "answered"
    assert r1["conversation_id"] == cid1

    # Second identical request (cache hit)
    t1 = time.perf_counter()
    r2 = ephemeral_service_instance.ask(q, conversation_id=cid2)
    hit_ms = (time.perf_counter() - t1) * 1000
    assert r2["status"] == "answered"
    assert r2["conversation_id"] == cid2
    assert r2["conversation_id"] != r1["conversation_id"]
    assert r1.get("id") and r2.get("id") and r1["id"] != r2["id"]
    assert r2["metadata"].get("cached") is True
    assert r2["metadata"]["verification_label"] == "Lexically checked against documentation"
    assert hit_ms < 15.0

    # Normalized whitespace request should hit standalone cache
    cid3 = f"test_cache_3_{uuid.uuid4().hex[:8]}"
    r3 = ephemeral_service_instance.ask("  What is a   contract account?  ", conversation_id=cid3)
    assert r3["status"] == "answered"
    assert r3["metadata"].get("cached") is True
    assert r3["conversation_id"] == cid3

    # debug=True on a standalone query must bypass cache and execute full pipeline
    cid4 = f"test_cache_4_{uuid.uuid4().hex[:8]}"
    r_debug = ephemeral_service_instance.ask(q, conversation_id=cid4, debug=True)
    assert r_debug["status"] == "answered"
    assert r_debug["metadata"].get("cached") is not True
    assert "debug" in r_debug


def test_adv_grounding_rejects_hallucinated_transaction_code():
    """Grounding strictly rejects hallucinated transaction codes even if mentioned in prompt."""
    item = SimpleNamespace(
        marker="S1",
        text="A contract account contains master data for posting line items.",
    )
    ctx = SimpleNamespace(items=[item])

    # Case 1: Answer includes common domain token 'SAP' not in chunk text -> permitted
    ans_sap = "In SAP, a contract account contains master data for posting line items. [S1]"
    rep_sap = RG.verify_grounding(ans_sap, ctx)
    assert rep_sap.ok is True

    # Case 2: Answer asserts a hallucinated transaction code FPR99 -> strictly rejected
    ans_halluc = "Use transaction FPR99 to post line items for a contract account. [S1]"
    rep_halluc = RG.verify_grounding(ans_halluc, ctx, question="Can I use transaction FPR99?")
    assert rep_halluc.ok is False
    assert any(v["kind"] == "TOKEN_NOT_IN_CONTEXT" and "FPR99" in v["detail"] for v in rep_halluc.violations)
