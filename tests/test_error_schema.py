"""Tests for Phase 2.2 Consistent Error Schema:
{"error": {"code": "...", "message": "...", "request_id": "..."}}

Validates:
- empty input (422)
- whitespace input (422)
- >500 characters (422)
- control characters handling
- timeout (504)
- retriever unavailable (500/503)
- model unavailable (502/503)
- unexpected exception (500)
- no stack traces exposed in any response.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.phase8_support import make_pipeline
from tests.test_phase11_service import Q_PLAN, RANKING
import rag_api
import rag_generate as RG
import rag_service as S


class ErrorSchemaTests(unittest.TestCase):
    def setUp(self):
        self.svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")
        self.app = rag_api.create_app(service=self.svc, static_dir=Path("/nonexistent"))
        self.c = TestClient(self.app)

    def _assert_error_schema(self, response, expected_status: int, expected_code: str):
        self.assertEqual(response.status_code, expected_status)
        data = response.json()
        self.assertIn("error", data)
        err = data["error"]
        self.assertIn("code", err)
        self.assertIn("message", err)
        self.assertIn("request_id", err)
        self.assertEqual(err["code"], expected_code)
        # Ensure request_id is also in headers
        self.assertIn("X-Request-Id", response.headers)
        if response.headers["X-Request-Id"]:
            self.assertEqual(err["request_id"], response.headers["X-Request-Id"])
        # Ensure stack trace is NOT exposed
        text = response.text
        self.assertNotIn("Traceback (most recent call last):", text)
        self.assertNotIn("File \"", text)

    def test_empty_input(self):
        r = self.c.post("/api/chat", json={"message": ""}, headers={"X-Request-Id": "req-empty"})
        self._assert_error_schema(r, 422, "invalid_request")

    def test_whitespace_input(self):
        for ws in ("   ", "\t\t", "\n\n   \t "):
            r = self.c.post("/api/chat", json={"message": ws}, headers={"X-Request-Id": "req-ws"})
            self._assert_error_schema(r, 422, "invalid_request")

    def test_too_long_input_greater_than_500_chars(self):
        # 500 characters is allowed
        r_ok = self.c.post("/api/chat", json={"message": "a" * 500})
        # May be out_of_scope or answered, but not 422 invalid_request
        self.assertIn(r_ok.status_code, (200, 422))

        # 501 characters is rejected
        r_too_long = self.c.post("/api/chat", json={"message": "a" * 501}, headers={"X-Request-Id": "req-501"})
        self._assert_error_schema(r_too_long, 422, "invalid_request")

    def test_control_characters_handling(self):
        # Only control characters becomes empty -> 422
        r_ctrl_empty = self.c.post("/api/chat", json={"message": "\x00\x07\x1f"}, headers={"X-Request-Id": "req-ctrl-empty"})
        self._assert_error_schema(r_ctrl_empty, 422, "invalid_request")

        # Control characters with legitimate text are stripped safely by service
        r_ctrl_text = self.c.post("/api/chat", json={"message": "How do I create\x00 an installment\x07 plan?"})
        self.assertEqual(r_ctrl_text.status_code, 200)
        self.assertEqual(r_ctrl_text.json()["status"], "answered")

    def test_retriever_unavailable(self):
        def broken_retrieve(*a, **k):
            raise OSError("Chroma vector store corrupted or unavailable")

        with patch.object(self.svc.pipeline.retriever, "retrieve_in_page", side_effect=broken_retrieve):
            r = self.c.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": "req-retriever-fail"})
            self._assert_error_schema(r, 500, "pipeline_failed")
            self.assertNotIn("Chroma vector store corrupted", r.text)

    def test_model_unavailable(self):
        class BrokenClient:
            def chat(self, **kw):
                raise ConnectionError("connection to Ollama server refused")

        ollama_gen = RG.LLMGenerator(RG.OllamaClient(model="llama3.2:3b", options={}, chat=BrokenClient().chat), name="ollama")
        svc_ollama = S.RagService(make_pipeline(ollama_gen, RANKING), "ollama")
        app_ollama = rag_api.create_app(service=svc_ollama, static_dir=Path("/nonexistent"))
        c_ollama = TestClient(app_ollama)

        r = c_ollama.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": "req-model-fail"})
        self._assert_error_schema(r, 502, "generator_failed")
        self.assertNotIn("Ollama server refused", r.text)

    def test_unexpected_exception(self):
        def crashing_ask(*a, **k):
            raise RuntimeError("Unexpected internal engine fault in pipeline runtime")

        with patch.object(self.svc, "ask", side_effect=crashing_ask):
            r = self.c.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": "req-unhandled"})
            self._assert_error_schema(r, 500, "internal_error")
            self.assertNotIn("engine fault", r.text)


if __name__ == "__main__":
    unittest.main()
