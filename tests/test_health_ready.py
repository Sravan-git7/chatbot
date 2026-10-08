"""Tests for Phase 2.4 and 2.5 Health/Readiness and Graceful Shutdown:
- Separate /health (liveness only) and /ready (retriever/index/model verification)
- Backward compatibility for /api/health
- Negative readiness tests (missing retriever, missing corpus, model unavailable)
- Graceful shutdown draining in-flight requests.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.phase8_support import make_pipeline
from tests.test_phase11_service import RANKING
import rag_api
import rag_generate as RG
import rag_service as S


class HealthReadyTests(unittest.TestCase):
    def setUp(self):
        self.svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")
        self.app = rag_api.create_app(service=self.svc, static_dir=Path("/nonexistent"))
        self.c = TestClient(self.app)

    def test_liveness_endpoint_health(self):
        r = self.c.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["process"], "live")
        self.assertIn("X-Request-Id", r.headers)

    def test_readiness_endpoint_ready_when_healthy(self):
        r = self.c.get("/ready")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["ready"])
        self.assertEqual(data["generator"], "extractive")
        self.assertEqual(data["topics"], 29)
        self.assertTrue(data["pages_available"] > 0)
        self.assertIn("X-Request-Id", r.headers)

    def test_api_health_backward_compatibility(self):
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["ready"])
        self.assertEqual(data["generator"], "extractive")
        self.assertEqual(data["topics"], 29)

    def test_readiness_fails_when_service_not_initialized(self):
        app = rag_api.create_app(service_factory=lambda g: None, static_dir=Path("/nonexistent"))
        app.state.rag["service"] = None
        c = TestClient(app)

        # /health is process liveness -> returns 200
        r_live = c.get("/health")
        self.assertEqual(r_live.status_code, 200)

        # /ready verifies service -> returns 503
        r_ready = c.get("/ready")
        self.assertEqual(r_ready.status_code, 503)
        self.assertEqual(r_ready.json()["error"]["code"], "service_not_ready")

    def test_readiness_fails_when_retriever_missing(self):
        with patch.object(self.svc.pipeline, "retriever", None):
            r = self.c.get("/ready")
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["code"], "retriever_unavailable")

    def test_readiness_fails_when_corpus_index_empty(self):
        class EmptyCorpus:
            entries = {}

        with patch.object(self.svc.pipeline, "corpus", EmptyCorpus()):
            r = self.c.get("/ready")
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["code"], "index_unavailable")

    def test_readiness_verifies_ollama_model_when_configured(self):
        class StubOllamaClient:
            def __init__(self, available: bool):
                self._available = available

            def check_available(self) -> bool:
                return self._available

        # Case A: Ollama model reachable
        gen_ok = RG.LLMGenerator(StubOllamaClient(True), name="ollama")
        svc_ok = S.RagService(make_pipeline(gen_ok, RANKING), "ollama")
        c_ok = TestClient(rag_api.create_app(service=svc_ok, static_dir=Path("/nonexistent")))
        r_ok = c_ok.get("/ready")
        self.assertEqual(r_ok.status_code, 200)
        self.assertEqual(r_ok.json()["generator"], "ollama")

        # Case B: Ollama model unreachable
        gen_bad = RG.LLMGenerator(StubOllamaClient(False), name="ollama")
        svc_bad = S.RagService(make_pipeline(gen_bad, RANKING), "ollama")
        c_bad = TestClient(rag_api.create_app(service=svc_bad, static_dir=Path("/nonexistent")))
        r_bad = c_bad.get("/ready")
        self.assertEqual(r_bad.status_code, 503)
        self.assertEqual(r_bad.json()["error"]["code"], "model_unavailable")

    def test_graceful_shutdown_flag(self):
        # When shutting down flag is set, new requests receive 503
        self.app.state.rag["shutting_down"] = True
        r = self.c.post("/api/chat", json={"message": "How is billing handled?"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "service_shutting_down")


if __name__ == "__main__":
    unittest.main()
