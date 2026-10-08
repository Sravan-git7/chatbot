"""Tests for Phase 2.3 Rate Limiting and Concurrency:
- Enforces MAX_CONCURRENT_REQUESTS = 4
- Rejection returns HTTP 429 with Retry-After header and standard error schema
- Concurrency test with 10 and 20 concurrent requests reporting metrics.
"""
from __future__ import annotations

import concurrent.futures
import math
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests.phase8_support import make_pipeline
from tests.test_phase11_service import Q_PLAN, RANKING
import rag_api
import rag_generate as RG
import rag_service as S


def _percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(s[int(k)], 2)
    return round(s[int(f)] * (c - k) + s[int(c)] * (k - f), 2)


class ConcurrencyRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")
        self.app = rag_api.create_app(service=self.svc, static_dir=Path("/nonexistent"))
        self.client = TestClient(self.app)

    def test_rate_limit_429_schema_and_headers(self):
        # Artificially hold the pipeline busy so concurrent requests saturate
        orig_ask = self.svc.ask
        def slow_ask(*a, **k):
            time.sleep(0.3)
            return orig_ask(*a, **k)

        self.svc.ask = slow_ask

        def make_request(idx: int):
            req_id = f"ratelimit-probe-{idx}"
            t0 = time.perf_counter()
            resp = self.client.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": req_id})
            lat = (time.perf_counter() - t0) * 1000.0
            return idx, resp.status_code, resp, lat, req_id

        # Fire 8 concurrent requests (limit is 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(make_request, i) for i in range(8)]
            results = [f.result() for f in futures]

        status_codes = [r[1] for r in results]
        self.assertIn(429, status_codes, "Expected at least one HTTP 429 rejection when 8 concurrent requests arrive with limit 4")

        # Verify 429 response structure
        for idx, code, resp, lat, req_id in results:
            if code == 429:
                self.assertIn("Retry-After", resp.headers)
                self.assertIn("X-Request-Id", resp.headers)
                self.assertEqual(resp.headers["X-Request-Id"], req_id)
                body = resp.json()
                self.assertIn("error", body)
                self.assertEqual(body["error"]["code"], "rate_limited")
                self.assertEqual(body["error"]["request_id"], req_id)
                self.assertIn("retry", body["error"]["message"].lower())

    def _run_concurrency_batch(self, count: int, delay_s: float = 0.25):
        orig_ask = self.svc.ask
        def delayed_ask(*a, **k):
            time.sleep(delay_s)
            return orig_ask(*a, **k)

        self.svc.ask = delayed_ask

        def worker(idx: int):
            req_id = f"batch-{count}-req-{idx}"
            t0 = time.perf_counter()
            r = self.client.post("/api/chat", json={"message": Q_PLAN}, headers={"X-Request-Id": req_id})
            dur = (time.perf_counter() - t0) * 1000.0
            return idx, r.status_code, r, dur, req_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            futures = [pool.submit(worker, i) for i in range(count)]
            results = [f.result() for f in futures]

        successful = [r for r in results if r[1] == 200]
        rejected = [r for r in results if r[1] == 429]
        errors = [r for r in results if r[1] not in (200, 429)]
        latencies = [r[3] for r in results]

        report = {
            "total_requests": count,
            "successful_requests": len(successful),
            "rejected_requests": len(rejected),
            "error_requests": len(errors),
            "p50_latency_ms": _percentile(latencies, 0.50),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "request_ids": [r[4] for r in results],
            "rejected_request_ids": [r[4] for r in rejected],
        }
        return report

    def test_ten_concurrent_requests(self):
        report = self._run_concurrency_batch(10, delay_s=0.20)
        self.assertEqual(report["total_requests"], 10)
        self.assertEqual(report["error_requests"], 0)
        self.assertTrue(report["successful_requests"] > 0)
        self.assertTrue(report["rejected_requests"] > 0)
        self.assertEqual(report["successful_requests"] + report["rejected_requests"], 10)

    def test_twenty_concurrent_requests(self):
        report = self._run_concurrency_batch(20, delay_s=0.20)
        self.assertEqual(report["total_requests"], 20)
        self.assertEqual(report["error_requests"], 0)
        self.assertTrue(report["successful_requests"] > 0)
        self.assertTrue(report["rejected_requests"] >= 10)
        self.assertEqual(report["successful_requests"] + report["rejected_requests"], 20)


    def test_per_ip_rate_limiting(self):
        import os
        old_val = os.environ.get("SURA_RATE_LIMIT_PER_MINUTE")
        os.environ["SURA_RATE_LIMIT_PER_MINUTE"] = "3"
        try:
            rag_api.ip_request_history.clear()
            # Send 3 requests (should succeed)
            for i in range(3):
                resp = self.client.post("/api/chat", json={"message": Q_PLAN})
                self.assertEqual(resp.status_code, 200)

            # 4th request from same client should be rate limited
            resp = self.client.post("/api/chat", json={"message": Q_PLAN})
            self.assertEqual(resp.status_code, 429)
            body = resp.json()
            self.assertEqual(body["error"]["code"], "rate_limited")
            self.assertEqual(resp.headers.get("retry-after"), "60")
        finally:
            if old_val is not None:
                os.environ["SURA_RATE_LIMIT_PER_MINUTE"] = old_val
            else:
                os.environ.pop("SURA_RATE_LIMIT_PER_MINUTE", None)
            rag_api.ip_request_history.clear()

    def test_configuration_validation(self):
        cfg = rag_api.validate_configuration()
        self.assertIn("generator", cfg)
        self.assertIn("feature_flags", cfg)
        self.assertIn("rate_limit_per_minute", cfg)

        import os
        old_gen = os.environ.get("RAG_GENERATOR")
        try:
            os.environ["RAG_GENERATOR"] = "unsupported_gen"
            with self.assertRaises(ValueError):
                rag_api.validate_configuration()
        finally:
            if old_gen is not None:
                os.environ["RAG_GENERATOR"] = old_gen
            else:
                os.environ.pop("RAG_GENERATOR", None)


if __name__ == "__main__":
    unittest.main()
