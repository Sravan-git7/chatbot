"""Root-cause regressions: API admission cleanup, received-byte limit, finite queue,
privacy-safe failures, example security defaults, safe byte-exact checkout refresh.
No real Ollama inference is used: the queue/failure fixtures are explicitly injected.
"""
from pathlib import Path
import concurrent.futures
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.phase8_support import make_pipeline
from tests.test_phase11_service import Q_PLAN, RANKING
import rag_api
import rag_generate as RG
import rag_service as S

ROOT = Path(__file__).resolve().parents[1]


def service():
    return S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")


class HardeningTests(unittest.TestCase):
    def test_uninitialized_requests_do_not_leak_admission_slots_and_recover(self):
        app = rag_api.create_app(service=service(), static_dir=Path("/nonexistent"))
        app.state.rag["service"] = None
        client = TestClient(app)
        for _ in range(6):
            self.assertEqual(client.post("/api/chat", json={"message": Q_PLAN}).status_code, 503)
            self.assertEqual(app.state.rag["active_requests"], 0)
        app.state.rag["service"] = service()
        self.assertEqual(client.post("/api/chat", json={"message": Q_PLAN}).status_code, 200)
        self.assertEqual(app.state.rag["active_requests"], 0)

    def test_received_body_limit_without_content_length(self):
        app = rag_api.create_app(service=service(), static_dir=Path("/nonexistent"))
        client = TestClient(app)
        # Iterator body uses chunked encoding; no trustworthy Content-Length exists.
        payload = b'{"message":"' + b'x' * (rag_api.MAX_BODY_BYTES + 1) + b'"}'
        resp = client.post("/api/chat", content=iter([payload[:100], payload[100:]]),
                           headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["error"]["code"], "payload_too_large")
        self.assertEqual(app.state.rag["active_requests"], 0)
        self.assertEqual(client.post("/api/chat", json={"message": Q_PLAN}).status_code, 200)

    def test_queue_expiry_removes_waiter_and_preserves_permit_accounting(self):
        sem = S._FIFOBoundedSemaphore(1, wait_timeout=0.02)
        self.assertTrue(sem.acquire())
        with self.assertRaises(S.RequestTimeout):
            sem.acquire()
        self.assertEqual(len(sem._waiters), 0)
        sem.release()
        self.assertTrue(sem.acquire(blocking=False))
        sem.release()
        with self.assertRaises(ValueError):
            sem.release()

    def test_request_queue_timeout_is_504_no_state_mutation_and_recovery(self):
        svc = service()
        svc._request_sem = S._FIFOBoundedSemaphore(1, wait_timeout=0.02)
        svc._request_sem.acquire()
        app = rag_api.create_app(service=svc, static_dir=Path("/nonexistent"))
        client = TestClient(app)
        resp = client.post("/api/chat", json={"message": Q_PLAN, "conversation_id": "deadline-case"})
        self.assertEqual(resp.status_code, 504)
        self.assertEqual(resp.json()["error"]["code"], "request_timeout")
        self.assertNotIn("deadline-case", svc._conversations)
        self.assertEqual(app.state.rag["active_requests"], 0)
        svc._request_sem.release()
        self.assertEqual(client.post("/api/chat", json={"message": Q_PLAN,
                                                        "conversation_id": "deadline-case"}).status_code, 200)

    def test_example_keeps_debug_and_experiments_off(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        pairs = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#") and "=" in line)
        self.assertEqual(pairs["RAG_ENABLE_DEBUG"], "0")
        self.assertEqual(pairs["SURA_LOG_QUERIES"], "0")
        for key in ("SURA_INTENT_AWARE", "SURA_SECTION_SELECTION", "SURA_ADDITIONAL_EVIDENCE"):
            self.assertEqual(pairs[key], "0")

    def test_generation_queue_timeout_is_preserved_as_controlled_504(self):
        class TimedOutGenerator:
            name = "ollama"
            def generate(self, *args):
                raise S.RequestTimeout("The request queue deadline expired. Please retry shortly.")
        with self.assertRaises(S.RequestTimeout):
            S.GeneratorGuard(TimedOutGenerator()).generate("q", None)

    def test_invalid_configuration_fails_closed_not_a_warning_only(self):
        app = rag_api.create_app(service=service(), static_dir=Path("/nonexistent"))
        with patch.dict("os.environ", {"SURA_MAX_CONCURRENT_REQUESTS": "not-an-integer"}):
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/ready").status_code, 503)
                self.assertEqual(client.post("/api/chat", json={"message": Q_PLAN}).status_code, 503)
                self.assertEqual(app.state.rag["active_requests"], 0)

    def test_legacy_health_does_not_claim_ready_for_an_unavailable_model(self):
        svc = service()
        svc.generator_name = "ollama"
        # Deliberately no Ollama availability probe in the extractive test generator chain.
        client = TestClient(rag_api.create_app(service=svc, static_dir=Path("/nonexistent")))
        self.assertEqual(client.get("/ready").status_code, 503)
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ready"])

    def test_unexpected_error_logs_type_not_exception_message_or_query(self):
        svc = service()
        def broken(*args, **kwargs):
            raise RuntimeError("private-query-and-secret-do-not-log")
        svc.ask = broken
        client = TestClient(rag_api.create_app(service=svc, static_dir=Path("/nonexistent")))
        with self.assertLogs(rag_api.logger, level="ERROR") as captured:
            response = client.post("/api/chat", json={"message": Q_PLAN})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-query-and-secret", response.text)
        self.assertNotIn("private-query-and-secret", " ".join(captured.output))
        self.assertNotIn(Q_PLAN, " ".join(captured.output))
        self.assertIn("RuntimeError", " ".join(captured.output))
        self.assertEqual(client.app.state.rag["active_requests"], 0)

    def test_untrusted_request_id_is_replaced_with_safe_identifier(self):
        client = TestClient(rag_api.create_app(service=service(), static_dir=Path("/nonexistent")))
        response = client.get("/health", headers={"X-Request-Id": "private arbitrary value " * 10})
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.headers["X-Request-Id"], r"^[a-f0-9]{32}$")
        safe = client.get("/health", headers={"X-Request-Id": "safe-id_1"})
        self.assertEqual(safe.headers["X-Request-Id"], "safe-id_1")

    def test_body_deadline_returns_controlled_408_and_recovers(self):
        client = TestClient(rag_api.create_app(service=service(), static_dir=Path("/nonexistent")))
        async def timeout(awaitable, timeout):
            self.assertEqual(timeout, 10.0)
            awaitable.close()
            raise rag_api.asyncio.TimeoutError
        with patch.object(rag_api.asyncio, "wait_for", timeout):
            response = client.post("/api/chat", json={"message": Q_PLAN})
        self.assertEqual(response.status_code, 408)
        self.assertEqual(response.json()["error"]["code"], "request_body_timeout")
        self.assertEqual(client.post("/api/chat", json={"message": Q_PLAN}).status_code, 200)

    def test_preselected_default_detail_cannot_be_answered_by_generic_instructions(self):
        import rag_evidence as E
        for wording in ("preselected", "pre-selected", "preset", "predefined", "default"):
            needs = E.analyze_question(f"Which interval type is {wording} for new installment plans?")
            self.assertIn("default", needs.kinds)
            self.assertFalse(E.kind_satisfied("default", "Enter the interval type.", needs))
            self.assertTrue(E.kind_satisfied("default", "The default interval type is monthly.", needs))

    def test_live_absent_preselected_detail_abstains(self):
        svc = S.build_service("extractive")
        result = svc.ask("Which interval type is preselected for new installment plans?", debug=True)
        self.assertEqual(result["status"], "unable_to_verify")
        self.assertFalse(result["metadata"]["grounded"])
        self.assertEqual(result["sources"], [])

    def test_live_named_code_purpose_does_not_answer_from_navigation_pointer(self):
        svc = S.build_service("extractive")
        result = svc.ask("What is the business function ISU_AMI_1 required for?", debug=True)
        self.assertEqual(result["status"], "unable_to_verify")
        self.assertFalse(result["metadata"]["grounded"])
        self.assertEqual(result["sources"], [])
        # Positive control: an explicit supported capability question must keep its verified answer.
        positive = svc.ask("What is the purpose of transaction EL43?", debug=True)
        self.assertEqual(positive["status"], "answered")
        self.assertEqual(positive["metadata"]["card_id"], "M2C-07")

    def test_configured_model_is_used_by_the_shipped_generator_not_ignored(self):
        with patch.dict("os.environ", {"OLLAMA_MODEL": "approved-local:test"}):
            svc = S.build_service("ollama")
            node = svc.pipeline.generator
            client = None
            for _ in range(8):
                client = getattr(node, "client", None)
                if client is not None:
                    break
                node = getattr(node, "inner", None)
            self.assertIsNotNone(client)
            self.assertEqual(client.model, "approved-local:test")
            self.assertEqual(RG.OllamaClient(model="explicit:test").model, "explicit:test")


class CheckoutBytesTests(unittest.TestCase):
    def test_refresh_only_newline_conversion_and_refuses_real_edits(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("refresh", ROOT / "scripts/refresh_checkout_bytes.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            git("config", "core.autocrlf", "false")
            path = root / "pinned.json"
            path.write_bytes(b'{"a":1}\n')
            git("add", "pinned.json")
            git("commit", "-m", "fixture")
            backup = root / "av" / "private.txt"
            backup.parent.mkdir()
            backup.write_bytes(b"do not touch")
            path.write_bytes(b'{"a":1}\r\n')
            planned = module.inspect(root)
            self.assertEqual(planned, [(path, b'{"a":1}\n')])
            self.assertEqual(backup.read_bytes(), b"do not touch")
            path.write_bytes(b'{"a":2}\r\n')
            with self.assertRaises(ValueError):
                module.inspect(root)
            self.assertEqual(path.read_bytes(), b'{"a":2}\r\n')
