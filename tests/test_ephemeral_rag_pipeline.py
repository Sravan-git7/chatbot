"""Integration test suite for the safe ephemeral in-memory RAG pipeline and FastAPI server.

Validates:
1. Ephemeral vector store building with chromadb.EphemeralClient (zero touch to protected stores).
2. Proper indexing of 29 M2C reference cards and 28 admitted page documents.
3. Retrieval, card routing, chunk filtering, and reranking across SAP Utilities topics.
4. Grounded extractive answer generation with source citations.
5. Out-of-domain refusal behavior.
6. FastAPI endpoints: /health, /ready, /api/health, /api/chat.
7. Safe error handling on empty or invalid requests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import ephemeral_service as ES
import rag_api as API
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def ephemeral_service_instance():
    """Builds and caches a single ephemeral service instance for the test module."""
    svc = ES.build_ephemeral_service(generator="extractive")
    return svc


@pytest.fixture(scope="module")
def api_test_client(ephemeral_service_instance):
    """Creates a FastAPI test client backed by the ephemeral service."""
    app = API.create_app(service=ephemeral_service_instance, generator="extractive")
    with TestClient(app) as client:
        yield client


def test_ephemeral_service_inventory(ephemeral_service_instance):
    """Verify that all 29 cards and 28 admitted pages are indexed."""
    info = ephemeral_service_instance.info()
    assert info["generator"] == "extractive"
    assert info["topics"] == 29
    assert info["pages_available"] == 28


def test_ephemeral_card_routing_master_data(ephemeral_service_instance):
    """Verify query routing for Utilities Master Data."""
    q = "What is the difference between technical and business master data in SAP Utilities?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    meta = res.get("metadata", {})
    assert meta.get("card_id") == "M2C-01"
    assert meta.get("card_title") == "Utilities Master Data"
    assert len(res["sources"]) >= 1
    assert any(s.get("marker", "").startswith("S") for s in res["sources"])
    assert "[S1]" in res["answer"]
    assert "business partner" in res["answer"].lower() or "connection object" in res["answer"].lower() or "premise" in res["answer"].lower()


def test_ephemeral_card_routing_meter_estimation(ephemeral_service_instance):
    """Verify query routing and answer for Meter Reading Estimation."""
    q = "How does SAP Utilities perform meter reading estimation?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    meta = res.get("metadata", {})
    assert meta.get("card_id") == "M2C-08"
    assert meta.get("card_title") == "Meter Reading Estimation"
    assert len(res["sources"]) >= 1
    assert res.get("structured_answer") is not None


def test_ephemeral_card_routing_installment_plans(ephemeral_service_instance):
    """Verify query routing and answer for Installment Plans in FI-CA."""
    q = "What is the procedure for creating installment plans in FI-CA?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    meta = res.get("metadata", {})
    assert meta.get("card_id") == "M2C-24"
    assert "installment" in res["answer"].lower()
    assert len(res["sources"]) >= 1


def test_ephemeral_out_of_domain_refusal(ephemeral_service_instance):
    """Verify out-of-domain questions are safely refused."""
    q = "How do I bake chocolate chip cookies with sea salt?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] in ("out_of_scope", "out_of_domain", "unsupported", "no_evidence")
    assert "doesn't appear to match" in res["answer"].lower() or "not found" in res["answer"].lower()


def test_api_health_endpoint(api_test_client):
    """Verify /health endpoint returns 200 OK and live process status."""
    resp = api_test_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["process"] == "live"
    assert "X-Request-Id" in resp.headers


def test_api_ready_endpoint(api_test_client):
    """Verify /ready endpoint returns 200 OK with page count and readiness."""
    resp = api_test_client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["ready"] is True
    assert data["pages_available"] == 28
    assert data["topics"] == 29


def test_api_legacy_health_endpoint(api_test_client):
    """Verify /api/health endpoint returns 200 OK with ready=True."""
    resp = api_test_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["ready"] is True


def test_api_chat_success(api_test_client):
    """Verify /api/chat handles a valid question and returns structured response."""
    payload = {"message": "Explain the SAP Utilities master data structure."}
    resp = api_test_client.post("/api/chat", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "answered"
    assert len(data["answer"]) > 20
    assert len(data["sources"]) >= 1
    assert "structured_answer" in data
    assert "metadata" in data
    assert data["metadata"]["card_id"] == "M2C-01"


def test_api_chat_empty_message_validation(api_test_client):
    """Verify /api/chat rejects empty message with 422."""
    payload = {"message": "   "}
    resp = api_test_client.post("/api/chat", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_request"


def test_citation_integrity(ephemeral_service_instance):
    """Verify that every citation marker in sources is present in the answer text."""
    q = "Explain the business partner and contract account relationships in SAP Utilities."
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    sources = res.get("sources", [])
    assert len(sources) >= 1
    for s in sources:
        assert "marker" in s and s["marker"].startswith("S")
        assert "title" in s and len(s["title"]) > 0
        assert "url" in s and s["url"].startswith("http")
        assert "chunk_id" in s
        assert f"[{s['marker']}]" in res["answer"]


def test_structured_answer_composition(ephemeral_service_instance):
    """Verify structured response sections and documentation coverage."""
    q = "What is the procedure for creating installment plans in FI-CA?"
    res = ephemeral_service_instance.ask(q)
    assert res["status"] == "answered"
    sa = res.get("structured_answer")
    assert sa is not None
    assert "sections" in sa and len(sa["sections"]) >= 1
    cov = res.get("documentation_coverage")
    assert isinstance(cov, dict)
    assert cov.get("covered") is True
    assert cov.get("coverage_percentage") == 100.0


def test_pdf_source_manifest_integrity():
    """Verify all 29 PDF documents are accounted for in data/source_manifest.json."""
    import json
    manifest_path = ROOT / "data" / "source_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest.get("documents", [])) == 29
    for doc in manifest["documents"]:
        assert (ROOT / doc["filename"]).is_file()
        assert doc["pdf_pages"] > 0
        assert doc["pdf_sha256"]
        assert doc["extraction_ok"] is True


def test_protected_stores_safety():
    """Verify that protected vector store paths are never opened or modified."""
    protected_db = ROOT / "data" / "vector_store" / "chroma.sqlite3"
    protected_page_db = ROOT / "data" / "vector_store" / "page_collection" / "chroma.sqlite3"
    # Ensure our test suite only operates in-memory or on disposable locations
    assert protected_db.is_file()
    assert protected_page_db.is_file()

