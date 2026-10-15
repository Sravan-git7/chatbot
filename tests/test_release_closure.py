"""Narrow closure regressions; synthetic text is not authoritative SAP evidence."""

import pytest

import rag_evidence as EV
import rag_generate as RG
from tests.test_phase2_fixes import _Context, _Item


NOTICE = "The selected evidence does not establish a complete step-by-step procedure."


def context():
    return _Context(
        [
            _Item(
                "S1",
                "fixture",
                0,
                "The widget plan records the due dates.",
                "Widget Plan",
            )
        ]
    )


def test_procedure_notice_is_scoped_to_selected_evidence_not_a_whole_page():
    ctx = context()
    result = EV.EvidenceExtractiveGenerator().generate(
        "How do I create a widget plan?", ctx
    )
    assert not result.refused
    assert NOTICE in result.text
    assert "The widget plan records the due dates. [S1]" in result.text
    assert "SAP Help page" not in result.text
    assert RG.verify_grounding(result.text, ctx).ok
    assert EV.verify_support_chain(result.text, ctx)["ok"]


@pytest.mark.parametrize(
    "question,title",
    [
        ("How do I create a budget billing plan?", "Budget Billing Plan"),
        ("How do I analyse F3424?", "Periodic Billing and Invoicing Analysis"),
        ("How do I create a widget plan?", "UNTRUSTED HEADER CLAIM"),
    ],
)
def test_meta_notice_invents_no_topic_or_page_facts(question, title):
    from types import SimpleNamespace

    assert (
        EV._procedural_limitation_notice(
            question, [SimpleNamespace(heading_labels=[title])]
        )
        == NOTICE
    )


@pytest.mark.parametrize(
    "forged",
    [
        "The available SAP Help page guarantees arbitrary widget benefits, but does not document exceptions.",
        "The available SAP Help page explains the purpose and parameters of a budget billing plan, but it does not document the steps to create one.",
        NOTICE + " Widgets are always free.",
        NOTICE + " [S999]",
    ],
)
def test_unsupported_meta_prose_cannot_bypass_either_verifier_and_valid_text_recovers(
    forged,
):
    ctx = context()
    valid = "The widget plan records the due dates. [S1]"
    assert not RG.is_procedural_limitation_sentence(forged)
    assert not EV.is_procedural_limitation_sentence(forged)
    assert not RG.verify_grounding(forged + "\n" + valid, ctx).ok
    assert not EV.verify_support_chain(forged + "\n" + valid, ctx)["ok"]
    assert RG.verify_grounding(valid, ctx).ok
    assert EV.verify_support_chain(valid, ctx)["ok"]


def test_legacy_evaluator_retains_partial_answer_classification_without_validator_prefix_exemption():
    from eval.phase3.metrics import determine_actual_behavior

    ctx = context()
    answer = NOTICE + "\nThe widget plan records the due dates. [S1]"
    assert determine_actual_behavior("answered", answer, False) == "partial_answer"
    assert RG.verify_grounding(answer, ctx).ok
    assert EV.verify_support_chain(answer, ctx)["ok"]
    forged = (
        NOTICE
        + "\nUnsupported arbitrary benefit is guaranteed.\nThe widget plan records the due dates. [S1]"
    )
    assert not RG.verify_grounding(forged, ctx).ok
    assert not EV.verify_support_chain(forged, ctx)["ok"]
