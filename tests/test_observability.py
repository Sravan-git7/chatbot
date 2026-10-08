"""Tests for Phase 2.1 Observability: structured JSON logging, X-Request-Id header,
SURA_LOG_QUERIES query masking, and scripts/log_summary.py utility.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, make_pipeline
from tests.test_phase11_service import Q_PLAN, RANKING
import rag_api
import rag_generate as RG
import rag_service as S
from scripts.log_summary import summarize_logs, parse_log_lines


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")
        self.app = rag_api.create_app(service=svc, static_dir=Path("/nonexistent"))
        self.c = TestClient(self.app)

    def test_every_response_includes_x_request_id(self):
        # 1. Successful request generates X-Request-Id
        r1 = self.c.post("/api/chat", json={"message": Q_PLAN})
        self.assertEqual(r1.status_code, 200)
        self.assertIn("X-Request-Id", r1.headers)
        self.assertTrue(r1.headers["X-Request-Id"])

        # 2. Provided X-Request-Id is echoed
        custom_id = "test-req-abc-123"
        r2 = self.c.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": custom_id})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.headers["X-Request-Id"], custom_id)

        # 3. Validation error includes X-Request-Id in header and error body
        r3 = self.c.post("/api/chat", json={"message": ""}, headers={"X-Request-Id": "err-req-456"})
        self.assertEqual(r3.status_code, 422)
        self.assertEqual(r3.headers["X-Request-Id"], "err-req-456")
        self.assertEqual(r3.json()["error"]["request_id"], "err-req-456")

        # 4. Health and ready include X-Request-Id
        r4 = self.c.get("/health")
        self.assertEqual(r4.status_code, 200)
        self.assertIn("X-Request-Id", r4.headers)

        r5 = self.c.get("/ready")
        self.assertEqual(r5.status_code, 200)
        self.assertIn("X-Request-Id", r5.headers)

    def test_structured_json_logging_record_fields(self):
        logged_records = []

        class TestHandler(logging.Handler):
            def emit(self, record):
                try:
                    logged_records.append(json.loads(record.getMessage()))
                except Exception:
                    pass

        handler = TestHandler()
        target_logger = logging.getLogger("sura.structured")
        target_logger.addHandler(handler)
        target_logger.setLevel(logging.INFO)

        try:
            req_id = "observability-audit-789"
            r = self.c.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": req_id})
            self.assertEqual(r.status_code, 200)

            # Locate the record with our request_id
            rec = next((x for x in logged_records if x.get("request_id") == req_id), None)
            self.assertIsNotNone(rec, "Expected structured log record for request")

            # Check all required fields from spec
            required_fields = [
                "request_id",
                "timestamp",
                "route",
                "selected_chunk_ids",
                "retrieved_chunk_ids",
                "scores",
                "validator_results",
                "latency_per_stage",
                "config_hash",
                "corpus_hash",
                "query",
                "status",
                "http_status",
            ]
            for f in required_fields:
                self.assertIn(f, rec, f"Missing required field {f} in structured log")

            self.assertEqual(rec["request_id"], req_id)
            self.assertEqual(rec["http_status"], 200)
            self.assertEqual(rec["status"], "answered")
            self.assertTrue(isinstance(rec["selected_chunk_ids"], list))
            self.assertTrue(isinstance(rec["retrieved_chunk_ids"], list))
            self.assertTrue(isinstance(rec["validator_results"], dict))
            self.assertTrue(isinstance(rec["latency_per_stage"], dict))
        finally:
            target_logger.removeHandler(handler)

    def test_sura_log_queries_env_control(self):
        logged_records = []

        class TestHandler(logging.Handler):
            def emit(self, record):
                try:
                    logged_records.append(json.loads(record.getMessage()))
                except Exception:
                    pass

        handler = TestHandler()
        target_logger = logging.getLogger("sura.structured")
        target_logger.addHandler(handler)
        target_logger.setLevel(logging.INFO)

        try:
            # Case A: Default (safe): SURA_LOG_QUERIES is unset/false -> log hash of query
            with patch.dict(os.environ, {}, clear=True):
                r1 = self.c.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": "safe-q-1"})
                self.assertEqual(r1.status_code, 200)
                rec1 = next((x for x in logged_records if x.get("request_id") == "safe-q-1"), None)
                self.assertIsNotNone(rec1)
                expected_hash = hashlib.sha256(Q_PLAN.encode("utf-8")).hexdigest()[:16]
                self.assertEqual(rec1["query"], expected_hash)
                self.assertNotIn(Q_PLAN, json.dumps(rec1))

            # Case B: Opt-in (dev): SURA_LOG_QUERIES="1" -> log raw query
            with patch.dict(os.environ, {"SURA_LOG_QUERIES": "1"}):
                r2 = self.c.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": "dev-q-2"})
                self.assertEqual(r2.status_code, 200)
                rec2 = next((x for x in logged_records if x.get("request_id") == "dev-q-2"), None)
                self.assertIsNotNone(rec2)
                self.assertEqual(rec2["query"], Q_PLAN)
        finally:
            target_logger.removeHandler(handler)

    def test_log_summary_utility(self):
        sample_logs = [
            {"request_id": "r1", "status": "answered", "route": "M2C-24", "latency_ms": 20.0, "http_status": 200},
            {"request_id": "r2", "status": "answered", "route": "M2C-11", "latency_ms": 30.0, "http_status": 200},
            {"request_id": "r3", "status": "out_of_scope", "route": "out_of_scope", "latency_ms": 10.0, "http_status": 200},
            {"request_id": "r4", "status": "unable_to_verify", "route": "unable_to_verify", "latency_ms": 40.0, "http_status": 200},
            {"request_id": "r5", "status": "error", "route": "error", "latency_ms": 5.0, "http_status": 500},
        ]
        summary = summarize_logs(sample_logs)

        self.assertEqual(summary["request_count"], 5)
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(summary["route_counts"], {"M2C-11": 1, "M2C-24": 1, "error": 1, "out_of_scope": 1, "unable_to_verify": 1})
        # Completed non-error: 4 total (2 answered, 2 abstained) -> abstention_rate = 2/4 = 0.5
        self.assertEqual(summary["abstention_rate"], 0.5)
        self.assertEqual(summary["p50_latency_ms"], 20.0)
        self.assertEqual(summary["p95_latency_ms"], 38.0)


if __name__ == "__main__":
    unittest.main()
