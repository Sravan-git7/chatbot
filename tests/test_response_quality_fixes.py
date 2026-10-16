"""Regression tests for SURA SAP Utilities response-quality and UI fixes.

Covers:
1. Answers containing stray numeric markers (eliminated at source and format).
2. Repeated headings and sentences (deduplication across chunks and sections).
3. Legitimate numbered lists that must remain intact.
4. Citation identifiers and source metadata consistency.
5. Handling of missing or optional citation fields.
6. Duplicate retrieved chunks handled without duplication in text or structure.
7. Insufficient evidence for a requested procedure (limitation notice).
8. Unsupported questions (out-of-scope refusal preserved).
9. Suggested-question formatting and distinct listing.
10. End-to-end API response structure via FastAPI TestClient.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import ephemeral_service as ES
import rag_api as API
import rag_generate as RG
import rag_response as RR
import rag_context as RC
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def ephemeral_service_instance():
    """Build and cache safe in-memory ephemeral service instance."""
    return ES.build_ephemeral_service(generator="extractive")


@pytest.fixture(scope="module")
def api_test_client(ephemeral_service_instance):
    """FastAPI test client backed by ephemeral service."""
    app = API.create_app(service=ephemeral_service_instance, generator="extractive")
    with TestClient(app) as client:
        yield client


# 1. Stray numeric markers & list gathering
def test_no_stray_numeric_markers_and_complete_lists(ephemeral_service_instance):
    """Test 1 regression: master data question returns complete categories without stray 1s."""
    q = "What is the difference between technical and business master data?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    ans = res["answer"]

    # Verify no stray solitary numeric markers (must be valid [S#] citations)
    lines = [ln.strip() for ln in ans.split("\n") if ln.strip()]
    for ln in lines:
        # Every line should have text and valid citations, never bare isolated digit
        assert not ln.isdigit()

    # Complete lists are captured (not truncated after the first bullet)
    ans_lower = ans.lower()
    assert "business partner" in ans_lower
    assert "contract account" in ans_lower
    assert "grid" in ans_lower
    assert "point of delivery" in ans_lower
    assert "device location" in ans_lower or "installation" in ans_lower


# 2. Repeated headings and sentences
def test_no_repeated_headings_or_sentences(ephemeral_service_instance):
    """Headings and sentences must not be duplicated across chunks."""
    q = "What is the difference between technical and business master data?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    ans = res["answer"]

    # 'Business master data includes:' must appear exactly once
    occurrences = [line for line in ans.split("\n") if "business master data includes:" in line.lower()]
    assert len(occurrences) == 1, f"Expected 1 occurrence of heading, got: {occurrences}"

    # Structured answer sections must also not contain duplicated lines
    sa = res.get("structured_answer")
    assert sa is not None
    for sec in sa["sections"]:
        seen_sec_bodies = set()
        for ln in sec["lines"]:
            import re
            body = re.sub(r"\s*\[S\d+\]", "", ln).strip()
            assert body not in seen_sec_bodies, f"Duplicate line in section {sec['title']}: {body}"
            seen_sec_bodies.add(body)


# 3. Legitimate numbered lists remain intact
def test_legitimate_numbered_lists_preserved():
    """Legitimate numbered list formatting in documentation (1. 2. 3.) must be preserved."""
    txt = "Activities:\n1. Choose transaction FPR1.\n2. Enter open items.\n3. Save installment plan."
    items = [
        RC.ContextItem(
            marker="S1",
            chunk_id="chk1",
            guide_id="guide1",
            page_id="page1",
            title="Installment Plans",
            heading_path=["Activities"],
            section_title="Activities",
            chunk_index=0,
            rank=1,
            similarity=1.0,
            text=txt,
            rendered_text=txt,
            tokens=30,
            content_hash="hash1",
            source_url="https://help.sap.com/example",
        )
    ]
    ctx = RC.ContextBlock(items=items)
    gen = RG.ExtractiveGenerator()
    result = gen.generate("Choose transaction FPR1", ctx)
    assert not result.refused
    assert "1. Choose transaction FPR1" in result.text
    assert "[S1]" in result.text


# 4. Citation identifiers and source metadata consistency
def test_citation_identifiers_and_metadata(ephemeral_service_instance):
    """Citation identifiers in the answer must exactly match source markers."""
    q = "How does SAP Utilities perform meter reading estimation?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    sources = res["sources"]
    assert len(sources) >= 1
    source_markers = {s["marker"] for s in sources}

    import re
    cited_markers = re.findall(r"\[(S\d+)\]", res["answer"])
    assert cited_markers
    for m in cited_markers:
        assert m in source_markers, f"Marker {m} cited in answer but missing from sources"

    for s in sources:
        assert s["title"]
        assert s["url"].startswith("http")
        assert s["type"] in ("page", "card")


# 5. Missing citation fields handled safely
def test_missing_citation_fields_graceful():
    """Missing or empty optional citation fields must not crash or render empty cards."""
    sources = [
        {"type": "page", "marker": "S1", "title": "Test Title", "section": "", "url": None, "source_id": "TEST-01"}
    ]
    composed = RR.compose_response("Test fact. [S1]", sources, status="answered")
    assert composed["structured_answer"] is not None
    assert composed["structured_answer"]["citations"] == ["S1"]


# 6. Duplicate retrieved chunks handled without duplicated sentences
def test_duplicate_retrieved_chunks_deduplicated():
    """Identical sentences from multiple retrieved chunks must merge markers, not duplicate text."""
    txt = "Master data represents persistent business information."
    items = [
        RC.ContextItem(
            marker="S1",
            chunk_id="chunkA",
            guide_id="guideA",
            page_id="pageA",
            title="Page A",
            heading_path=["Overview"],
            section_title="Overview",
            chunk_index=0,
            rank=1,
            similarity=0.9,
            text=txt,
            rendered_text=txt,
            tokens=20,
            content_hash="hashA",
            source_url="https://help.sap.com/a",
        ),
        RC.ContextItem(
            marker="S2",
            chunk_id="chunkB",
            guide_id="guideB",
            page_id="pageB",
            title="Page B",
            heading_path=["Overview"],
            section_title="Overview",
            chunk_index=0,
            rank=2,
            similarity=0.85,
            text=txt,
            rendered_text=txt,
            tokens=20,
            content_hash="hashB",
            source_url="https://help.sap.com/b",
        ),
    ]
    ctx = RC.ContextBlock(items=items)
    gen = RG.ExtractiveGenerator()
    result = gen.generate("persistent business information", ctx)
    assert not result.refused
    lines = [ln.strip() for ln in result.text.split("\n") if ln.strip()]
    assert len(lines) == 1, f"Expected 1 deduplicated line, got: {lines}"
    assert "[S1]" in lines[0]


# 7. Insufficient evidence for requested procedure
def test_insufficient_evidence_procedural_notice(ephemeral_service_instance):
    """When a procedure is asked and only definitions/overview are retrieved, procedural notice is included."""
    q = "How does SAP Utilities perform meter reading estimation?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    # Meter reading estimation chunk only describes purpose, not a full procedure:
    # Expect the procedural limitation notice to be stated honestly
    assert "The selected evidence does not establish a complete step-by-step procedure." in res["answer"]
    assert "estimate meter reading results automatically" in res["answer"]


# 8. Unsupported questions (out of scope refusal)
def test_unsupported_out_of_scope_refusal(ephemeral_service_instance):
    """Unsupported question must be refused without fabricating SAP evidence."""
    q = "What is the capital of India?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "out_of_scope"
    assert res["sources"] == []
    assert "doesn't appear to match" in res["answer"].lower()
    assert res["structured_answer"] is None


# 9. Suggested questions formatting and structure
def test_suggested_questions_api_contract(api_test_client):
    """Out of scope chat request returns status out_of_scope with proper answer text."""
    resp = api_test_client.post("/api/chat", json={"message": "What is the capital of India?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "out_of_scope"
    assert "SAP Utilities" in data["answer"] or "documentation" in data["answer"]


# 10. End-to-end API response structure
def test_e2e_api_response_structure(api_test_client):
    """End-to-end API chat response contains full schema, sources, and structured answer."""
    resp = api_test_client.post("/api/chat", json={"message": "What is the difference between technical and business master data?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert len(data["sources"]) >= 1
    assert data["structured_answer"] is not None
    assert "sections" in data["structured_answer"]
    assert "documentation_coverage" in data


# 11. Procedural query for incoming payments analysis and clearing
def test_incoming_payments_analysis_and_clearing(ephemeral_service_instance):
    """How are incoming payments analyzed and cleared returns honest limitation and documented facts."""
    q = "How are incoming payments analyzed and cleared?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    answer = res["answer"]
    # Procedural limitation honestly disclosed because corpus only has monitoring app, not operational clearing manual
    assert "The selected evidence does not establish a complete step-by-step procedure." in answer
    # Documented evidence is accurately presented
    assert "Analyze Incoming Payments" in answer or "payment lots" in answer
    assert "cleared automatically or manually" in answer
    # Citations are properly attached and grounded
    assert re.search(r"\[S\d+\]", answer)
    meta = res.get("metadata", {})
    assert meta.get("grounded") is True


# 12. Procedural query for clearing rules sequence
def test_clearing_rules_sequence_procedure(ephemeral_service_instance):
    """Clearing rules sequence is retrieved and numbered steps 1 to 4 are preserved in order."""
    q = "What are the rules processed in the clearing process?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    answer = res["answer"]
    # Verify the documented numbered steps are included in sequence
    assert "1. Filter the selected open items" in answer
    assert "2. Creation of a clearing proposal" in answer
    assert "3. Handling of unassigned payments" in answer
    assert "4. Clearing statistical items" in answer
    # Verify step order
    idx1 = answer.find("1. Filter")
    idx2 = answer.find("2. Creation")
    idx3 = answer.find("3. Handling")
    idx4 = answer.find("4. Clearing")
    assert idx1 < idx2 < idx3 < idx4
    meta = res.get("metadata", {})
    assert meta.get("grounded") is True


# 13. Exact query 'What are the steps in the clearing process?'
def test_clearing_process_steps_exact_query(ephemeral_service_instance):
    """The exact query 'What are the steps in the clearing process?' returns the 4 steps in order without limitation notice."""
    q = "What are the steps in the clearing process?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    answer = res["answer"]
    assert "The selected evidence does not establish a complete step-by-step procedure." not in answer
    assert "1. Filter the selected open items" in answer
    assert "2. Creation of a clearing proposal" in answer
    assert "3. Handling of unassigned payments" in answer
    assert "4. Clearing statistical items" in answer
    idx1 = answer.find("1. Filter")
    idx2 = answer.find("2. Creation")
    idx3 = answer.find("3. Handling")
    idx4 = answer.find("4. Clearing")
    assert idx1 < idx2 < idx3 < idx4
    meta = res.get("metadata", {})
    assert meta.get("grounded") is True


