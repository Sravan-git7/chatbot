"""Keep historical metric scopes distinct; no inference or frozen-output mutation."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase10_lib as historical

spec = importlib.util.spec_from_file_location(
    "strict_quality", ROOT / "benchmarks/run_quality.py"
)
strict = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strict)


def evidence_case():
    query = {"gold_doc_id": "guide/page", "evidence": ["The documented fact."]}
    item = {
        "chunk_id": "chunk",
        "guide_id": "guide",
        "page_id": "page",
        "text": "The documented fact. Other text.",
    }
    raw = {
        "status": "answered",
        "answer": "Other text. [S1]",
        "debug": {"context": {"items": [item]}},
        "citations": {
            "answer_sources": [
                {"chunk_id": "chunk", "guide_id": "guide", "page_id": "page"}
            ]
        },
    }
    return query, raw


def test_context_correct_does_not_prove_answer_correct():
    query, raw = evidence_case()
    assert historical.correct(query, raw)
    assert not strict.strict_evidence_correct(query, raw)
    raw["answer"] = "The documented fact. [S1]"
    assert historical.correct(query, raw)
    assert strict.strict_evidence_correct(query, raw)


def test_strict_requires_context_identity_as_well_as_citation_identity():
    query, raw = evidence_case()
    raw["answer"] = "The documented fact. [S1]"
    raw["debug"]["context"]["items"][0]["page_id"] = "wrong-page"
    before = copy.deepcopy(raw)
    assert historical.correct(
        query, raw
    )  # Historical predicate checks cited identity, not item identity.
    assert not strict.strict_evidence_correct(query, raw)
    assert raw == before


def test_both_metrics_reject_abstention_as_answer_correctness():
    query, raw = evidence_case()
    raw.update(status="insufficient_context", answer=None)
    assert not historical.correct(query, raw)
    assert not strict.strict_evidence_correct(query, raw)
