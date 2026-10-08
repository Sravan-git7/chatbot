"""Comprehensive security and operational test suite for SURA.
Proves:
- Restricted CORS (configured origins allowed, unconfigured rejected/not reflected)
- CSP & security headers (X-Content-Type-Options: nosniff, Referrer-Policy: no-referrer, CSP template)
- Generic sanitized 500 response (no stack traces or internal paths leaked)
- 16KB payload limit returns HTTP 413
- Concurrency limit returns HTTP 429 with Retry-After when exceeded
- Per-IP rate limit returns HTTP 429 with Retry-After when exceeded
- X-Request-ID propagation across all responses
- /api/health endpoint functionality
- /ready and /health endpoints functionality
- Graceful shutdown rejects new traffic with 503
"""
from __future__ import annotations

import concurrent.futures
import os
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests.phase8_support import make_pipeline
from tests.test_phase11_service import Q_PLAN, RANKING
import rag_api
import rag_generate as RG
import rag_service as S


class SecurityAuditTests(unittest.TestCase):
    def setUp(self):
        self.svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")
        self.app = rag_api.create_app(
            service=self.svc,
            static_dir=Path("/nonexistent"),
            cors_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        )
        self.client = TestClient(self.app)

    def test_x_request_id_present_on_all_responses(self):
        # 200 response
        resp = self.client.post("/api/chat", json={"message": Q_PLAN})
        self.assertIn("x-request-id", resp.headers)
        self.assertTrue(len(resp.headers["x-request-id"]) > 0)

        # 422 response
        resp = self.client.post("/api/chat", json={"message": ""})
        self.assertIn("x-request-id", resp.headers)

        # 404 response
        resp = self.client.get("/nonexistent-path")
        self.assertIn("x-request-id", resp.headers)

    def test_security_headers_and_csp(self):
        resp = self.client.post("/api/chat", json={"message": Q_PLAN})
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("referrer-policy"), "no-referrer")
        self.assertIn("no-store", resp.headers.get("cache-control", ""))

        # Non-API / static route gets CSP
        resp_ui = self.client.get("/")
        self.assertEqual(resp_ui.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("default-src 'self'", resp_ui.headers.get("content-security-policy", ""))
        self.assertIn("frame-ancestors 'none'", resp_ui.headers.get("content-security-policy", ""))

    def test_restricted_cors(self):
        # Allowed origin
        resp_allowed = self.client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(resp_allowed.headers.get("access-control-allow-origin"), "http://localhost:5173")

        # Disallowed origin
        resp_disallowed = self.client.options(
            "/api/chat",
            headers={
                "Origin": "http://malicious-site.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertNotEqual(resp_disallowed.headers.get("access-control-allow-origin"), "http://malicious-site.com")

    def test_sanitized_500_response_and_no_stack_traces_leaked(self):
        # Force an unexpected internal exception inside pipeline
        def failing_ask(*args, **kwargs):
            raise ZeroDivisionError("Simulated internal sensitive database error at /internal/secrets/db.py:42")

        orig_ask = self.svc.ask
        self.svc.ask = failing_ask
        try:
            resp = self.client.post("/api/chat", json={"message": Q_PLAN})
            self.assertEqual(resp.status_code, 500)
            data = resp.json()
            self.assertIn("error", data)
            self.assertEqual(data["error"]["code"], "internal_error")
            self.assertEqual(data["error"]["message"], "An unexpected error occurred.")
            # Verify no tracebacks, internal paths, or exceptions are exposed to client
            raw_text = resp.text
            self.assertNotIn("ZeroDivisionError", raw_text)
            self.assertNotIn("Traceback", raw_text)
            self.assertNotIn("/internal/secrets", raw_text)
        finally:
            self.svc.ask = orig_ask

    def test_payload_limit_16kb_returns_413(self):
        huge_payload = {"message": "A" * (17 * 1024)}
        resp = self.client.post("/api/chat", json=huge_payload)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["error"]["code"], "payload_too_large")

    def test_concurrency_limit_returns_429_with_retry_after(self):
        orig_ask = self.svc.ask
        def slow_ask(*args, **kwargs):
            time.sleep(0.3)
            return orig_ask(*args, **kwargs)

        self.svc.ask = slow_ask
        try:
            def send_req(i):
                return self.client.post("/api/chat", json={"message": Q_PLAN})

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(send_req, i) for i in range(8)]
                statuses = [f.result().status_code for f in futures]
                responses = [f.result() for f in futures]

            self.assertIn(429, statuses)
            rate_limited = [r for r in responses if r.status_code == 429]
            for r in rate_limited:
                self.assertEqual(r.json()["error"]["code"], "rate_limited")
                self.assertEqual(r.headers.get("retry-after"), "1")
        finally:
            self.svc.ask = orig_ask

    def test_per_ip_rate_limit_returns_429_with_retry_after(self):
        old_limit = os.environ.get("SURA_RATE_LIMIT_PER_MINUTE")
        os.environ["SURA_RATE_LIMIT_PER_MINUTE"] = "2"
        rag_api.ip_request_history.clear()
        try:
            # 2 allowed requests
            r1 = self.client.post("/api/chat", json={"message": Q_PLAN})
            self.assertEqual(r1.status_code, 200)
            r2 = self.client.post("/api/chat", json={"message": Q_PLAN})
            self.assertEqual(r2.status_code, 200)

            # 3rd request from same IP is rate limited
            r3 = self.client.post("/api/chat", json={"message": Q_PLAN})
            self.assertEqual(r3.status_code, 429)
            self.assertEqual(r3.json()["error"]["code"], "rate_limited")
            self.assertEqual(r3.headers.get("retry-after"), "60")
        finally:
            if old_limit is not None:
                os.environ["SURA_RATE_LIMIT_PER_MINUTE"] = old_limit
            else:
                os.environ.pop("SURA_RATE_LIMIT_PER_MINUTE", None)
            rag_api.ip_request_history.clear()

    def test_api_health_works(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["ready"])

    def test_health_and_ready_work(self):
        # Liveness
        resp_liveness = self.client.get("/health")
        self.assertEqual(resp_liveness.status_code, 200)
        self.assertEqual(resp_liveness.json()["status"], "ok")

        # Readiness
        resp_readiness = self.client.get("/ready")
        self.assertEqual(resp_readiness.status_code, 200)
        self.assertTrue(resp_readiness.json()["ready"])

    def test_graceful_shutdown_rejects_traffic(self):
        # Set shutting_down flag in app state
        self.app.state.rag["shutting_down"] = True
        try:
            resp = self.client.post("/api/chat", json={"message": Q_PLAN})
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["error"]["code"], "service_shutting_down")
        finally:
            self.app.state.rag["shutting_down"] = False


if __name__ == "__main__":
    unittest.main()
