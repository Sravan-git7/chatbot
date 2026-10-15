"""List relevance regressions; cached/synthetic context only, not live SAP verification."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "eval/phase3")]
import adapters
import rag_evidence as EV
import rag_generate as RG


def context(text):
    return adapters.build_context_block(
        [
            {
                "marker": "S1",
                "chunk_id": "fixture",
                "title": "Master Data",
                "heading_path": ["Master Data"],
                "text": text,
                "rendered_text": text,
            }
        ]
    )


@pytest.mark.parametrize("case_id", ["CASE-012", "CASE-040"])
def test_business_list_does_not_append_sibling_technical_list(case_id):
    snapshot = json.loads((ROOT / "eval/phase3/evidence_cache.json").read_text())[
        "snapshots"
    ][case_id]
    ctx = adapters.build_context_block(snapshot["context_items"])
    before = copy.deepcopy(ctx)
    result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(
        snapshot["question"], ctx
    )
    assert not result.refused
    for fact in [
        "Business partner",
        "Contract account",
        "Contract (billable service)",
        "Service provider",
        "Non-billable service",
    ]:
        assert fact in result.text
    for sibling in [
        "Technical master data includes",
        "Grid",
        "Premise",
        "Device location",
    ]:
        assert sibling not in result.text
    assert result.evidence["list_subject_filter"]["excluded_list_leadins"] == [
        "Technical master data includes:"
    ]
    assert EV.verify_support_chain(result.text, ctx)["ok"]
    assert RG.verify_grounding(result.text, ctx).ok
    assert ctx.to_dict(with_text=True) == before.to_dict(with_text=True)


@pytest.mark.parametrize(
    "question",
    [
        "List the business and technical master data objects.",
        "What types of master data are there?",
    ],
)
def test_broad_or_both_subjects_preserve_both_lists(question):
    ctx = context(
        "Business master data includes:\n- Business partner\nTechnical master data includes:\n- Device location"
    )
    result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(question, ctx)
    assert not result.refused
    assert "Business partner" in result.text
    assert "Device location" in result.text
    assert "list_subject_filter" not in result.evidence


def test_reverse_subject_selection_keeps_all_technical_items():
    ctx = context(
        "Business master data includes:\n- Business partner\nTechnical master data includes:\n- Grid\n- Premise"
    )
    result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(
        "List the technical master data objects.", ctx
    )
    assert not result.refused
    assert "Grid" in result.text and "Premise" in result.text
    assert "Business partner" not in result.text


def test_guard_prompt_removes_only_unrequested_list_and_preserves_shared_value():
    ctx = context(
        "Business master data includes:\n- Shared object\n- Business partner\nTechnical master data includes:\n- Shared object\n- Grid"
    )
    original = ctx.to_dict(with_text=True)
    seen = []

    class Inner:
        name = "stub"

        def generate(self, question, model_context):
            seen.append(model_context.to_dict(with_text=True))
            return RG.GenerationResult(
                "Business master data includes: [S1]\n- Shared object [S1]",
                False,
                self.name,
                "",
            )

    result = EV.EvidenceGuard(Inner(), tau=EV.SHIPPED_TAU).generate(
        "List the business master data objects.", ctx
    )
    assert not result.refused
    prompt = seen[0]["items"][0]["text"]
    assert "Technical master data" not in prompt and "Grid" not in prompt
    assert prompt.count("Shared object") == 1
    assert ctx.to_dict(with_text=True) == original


def test_guard_rejects_return_of_unrequested_sibling_list():
    ctx = context(
        "Business master data includes:\n- Business partner\nTechnical master data includes:\n- Grid"
    )

    class Inner:
        name = "stub"

        def generate(self, question, model_context):
            return RG.GenerationResult(
                "Technical master data includes: [S1]\n- Grid [S1]",
                False,
                self.name,
                "",
            )

    result = EV.EvidenceGuard(Inner(), tau=EV.SHIPPED_TAU).generate(
        "List the business master data objects.", ctx
    )
    assert result.refused
    assert result.evidence["reason"] == "ANSWER_INCLUDES_UNREQUESTED_LIST"


@pytest.mark.parametrize(
    "question",
    [
        "What objects belong to unrelated business records?",
        "Which authorization object is required for business master data?",
        "What is the default number of business master data objects?",
    ],
)
def test_list_membership_does_not_waive_topic_or_specific_detail_gates(question):
    ctx = context(
        "Business master data includes:\n- Business partner\n- Contract account"
    )
    result = EV.EvidenceExtractiveGenerator(tau=EV.SHIPPED_TAU).generate(question, ctx)
    assert result.refused
    assert result.evidence["selected"] == []
