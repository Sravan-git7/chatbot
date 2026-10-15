"""Tests for Phase 2.4 and 2.5 Health/Readiness and Graceful Shutdown:
- Separate /health (liveness only) and /ready (retriever/index/model verification)
- Backward compatibility for /api/health
- Negative readiness tests (missing retriever, missing corpus, model unavailable)
- Graceful shutdown draining in-flight requests.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
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
        self.assertGreater(data["pages_available"], 0)
        self.assertEqual(data["pages_available"], self.svc.info()["pages_available"],
                         "readiness must report admitted/searchable pages, not merely registered topic cards")
        self.assertIn("X-Request-Id", r.headers)

    def test_api_health_backward_compatibility(self):
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["ready"])
        self.assertEqual(data["generator"], "extractive")
        self.assertEqual(data["topics"], 29)

    def test_build_service_fails_closed_for_missing_card_and_empty_page_stores(self):
        class MissingCardStore:
            @staticmethod
            def health_check():
                raise FileNotFoundError("card collection missing")

        with patch("rag_pipeline.build_pipeline", return_value=SimpleNamespace(
            backend=MissingCardStore(), retriever=SimpleNamespace(count=lambda: 1),
        )):
            with self.assertRaisesRegex(FileNotFoundError, "card collection missing"):
                S.build_service()

        class HealthyCardStore:
            @staticmethod
            def health_check():
                return 29

        with patch("rag_pipeline.build_pipeline", return_value=SimpleNamespace(
            backend=HealthyCardStore(), retriever=SimpleNamespace(count=lambda: 0),
        )):
            with self.assertRaisesRegex(FileNotFoundError, "page vector collection is empty"):
                S.build_service()

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

    def test_readiness_fails_when_page_vector_collection_is_empty(self):
        with patch.object(self.svc.pipeline.retriever, "count", return_value=0):
            r = self.c.get("/ready")
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["code"], "index_unavailable")

    def test_readiness_fails_when_card_collection_is_missing(self):
        class MissingCardStore:
            @staticmethod
            def health_check():
                raise FileNotFoundError("card collection is missing")

        with patch.object(self.svc.pipeline, "backend", MissingCardStore()):
            r = self.c.get("/ready")
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["code"], "service_not_ready")
            self.assertEqual("Dependency readiness check failed.", r.json()["error"]["message"])
            self.assertNotIn("card collection is missing", r.text)  # Do not disclose private dependency errors.

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

    def test_readiness_reaches_ollama_client_through_the_shipped_guard_chain(self):
        """build_service ships GeneratorGuard(EvidenceGuard(LLMGenerator(client))); readiness must find the client
        at that depth - the old single-level lookup silently skipped the check and reported ready:true with an
        unreachable model (false success)."""
        import rag_evidence as EV

        class StubOllamaClient:
            def __init__(self, available: bool):
                self._available = available

            def check_available(self) -> bool:
                return self._available

        def shipped(available: bool):
            llm = RG.LLMGenerator(StubOllamaClient(available), name="ollama")
            guarded = S.GeneratorGuard(EV.EvidenceGuard(llm))
            svc = S.RagService(make_pipeline(guarded, RANKING), "ollama")
            return TestClient(rag_api.create_app(service=svc, static_dir=Path("/nonexistent")))

        r_ok = shipped(True).get("/ready")
        self.assertEqual(r_ok.status_code, 200)
        r_bad = shipped(False).get("/ready")
        self.assertEqual(r_bad.status_code, 503)
        self.assertEqual(r_bad.json()["error"]["code"], "model_unavailable")

    def test_readiness_fails_closed_when_no_ollama_probe_exists(self):
        """An ollama generator whose chain exposes no check_available probe cannot be verified: readiness must
        fail closed (503) instead of claiming ready."""
        class ProbelessClient:
            def generate(self, prompt: str) -> str:
                return "text"

        gen = RG.LLMGenerator(ProbelessClient(), name="ollama")
        svc = S.RagService(make_pipeline(gen, RANKING), "ollama")
        r = TestClient(rag_api.create_app(service=svc, static_dir=Path("/nonexistent"))).get("/ready")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "model_unavailable")

    def test_ollama_client_check_available_is_bounded_and_never_raises(self):
        """Unit contract of the real probe: injected stub chat is available without network; against a stubbed
        ollama module it requires an answering server AND the configured model (strict tag matching); every
        failure mode returns False instead of raising."""
        import sys as _sys
        from types import SimpleNamespace

        # injected chat callable -> available, and the ollama package is never imported for the probe
        self.assertTrue(RG.OllamaClient(model="m", chat=lambda **kw: {}).check_available())

        class FakeOllama:
            def __init__(self, models=None, raises=None):
                self._models, self._raises = models, raises

            def Client(self, timeout=None):                     # noqa: N802 - mirrors the ollama package API
                outer = self

                class _C:
                    def list(self_inner):
                        if outer._raises:
                            raise outer._raises
                        return SimpleNamespace(models=[SimpleNamespace(name=n) for n in outer._models])
                return _C()

        def probe(models=None, raises=None, model="llama3.2:3b"):
            fake = FakeOllama(models=models, raises=raises)
            saved = _sys.modules.get("ollama")
            _sys.modules["ollama"] = fake
            try:
                return RG.OllamaClient(model=model).check_available(timeout=0.01)
            finally:
                if saved is None:
                    _sys.modules.pop("ollama", None)
                else:
                    _sys.modules["ollama"] = saved

        self.assertTrue(probe(models=["llama3.2:3b"]))                       # exact configured model pulled
        self.assertFalse(probe(models=["llama3.2:latest"]))                  # different tag of same base: not accepted
        self.assertFalse(probe(models=["qwen2:7b"]))                         # model not pulled
        self.assertFalse(probe(models=[]))                                   # server up, nothing pulled
        self.assertFalse(probe(raises=ConnectionError("refused")))           # server down
        self.assertTrue(probe(models=["llama3.2:latest"], model="llama3.2")) # implicit-tag convention accepted

        # Regression: ollama>=0.4 returns Model objects with `model` attribute instead of `name`
        class FakeModernOllama:
            def Client(self, timeout=None):
                return SimpleNamespace(list=lambda: SimpleNamespace(models=[SimpleNamespace(model="llama3.2:3b")]))

        saved = _sys.modules.get("ollama")
        _sys.modules["ollama"] = FakeModernOllama()
        try:
            self.assertTrue(RG.OllamaClient(model="llama3.2:3b").check_available(timeout=0.01))
            self.assertFalse(RG.OllamaClient(model="other:model").check_available(timeout=0.01))
        finally:
            if saved is None:
                _sys.modules.pop("ollama", None)
            else:
                _sys.modules["ollama"] = saved

    def test_ollama_generation_timeout_is_finite_by_default_and_wired(self):
        """SURA_OLLAMA_TIMEOUT_SECONDS caps a hung local server so a generation cannot hold a request (and a
        concurrency slot) forever. Unset and invalid settings use a finite 60-second Client timeout."""
        import os as _os
        import sys as _sys

        calls = []

        class FakeOllamaModule:
            @staticmethod
            def chat(**kw):
                calls.append(("module_chat", None))
                return {"message": {"content": "text"}}

            @staticmethod
            def Client(timeout=None):                            # noqa: N802 - mirrors the ollama package API
                calls.append(("client", timeout))

                class _C:
                    @staticmethod
                    def chat(**kw):
                        return {"message": {"content": "text"}}
                return _C()

        saved_mod = _sys.modules.get("ollama")
        saved_env = _os.environ.get("SURA_OLLAMA_TIMEOUT_SECONDS")
        _sys.modules["ollama"] = FakeOllamaModule
        try:
            # 1) no env, no explicit timeout -> a bounded Client, never unbounded module chat
            _os.environ.pop("SURA_OLLAMA_TIMEOUT_SECONDS", None)
            self.assertEqual(RG.OllamaClient(model="m").timeout, 60.0)
            calls.clear()
            RG.OllamaClient(model="m").generate("prompt")
            self.assertEqual(calls, [("client", 60.0)])

            # 2) env knob -> ollama.Client(timeout=X).chat
            _os.environ["SURA_OLLAMA_TIMEOUT_SECONDS"] = "2.5"
            c = RG.OllamaClient(model="m")
            self.assertEqual(c.timeout, 2.5)
            calls.clear()
            c.generate("prompt")
            self.assertEqual(calls, [("client", 2.5)])

            # 3) invalid / non-positive values fall back to the default (never crash construction)
            _os.environ["SURA_OLLAMA_TIMEOUT_SECONDS"] = "not-a-number"
            self.assertEqual(RG.OllamaClient(model="m").timeout, 60.0)
            _os.environ["SURA_OLLAMA_TIMEOUT_SECONDS"] = "-3"
            self.assertEqual(RG.OllamaClient(model="m").timeout, 60.0)

            for invalid in ("0", "nan", "inf", "-inf", ""):
                _os.environ["SURA_OLLAMA_TIMEOUT_SECONDS"] = invalid
                self.assertEqual(RG.OllamaClient(model="m").timeout, 60.0)
            self.assertEqual(RG.OllamaClient(model="m", timeout=float("inf")).timeout, 60.0)

            # 4) explicit constructor argument wins over the environment
            _os.environ["SURA_OLLAMA_TIMEOUT_SECONDS"] = "9"
            self.assertEqual(RG.OllamaClient(model="m", timeout=1.25).timeout, 1.25)
        finally:
            if saved_mod is None:
                _sys.modules.pop("ollama", None)
            else:
                _sys.modules["ollama"] = saved_mod
            if saved_env is None:
                _os.environ.pop("SURA_OLLAMA_TIMEOUT_SECONDS", None)
            else:
                _os.environ["SURA_OLLAMA_TIMEOUT_SECONDS"] = saved_env

    def test_graceful_shutdown_flag(self):
        # When shutting down flag is set, new requests receive 503
        self.app.state.rag["shutting_down"] = True
        r = self.c.post("/api/chat", json={"message": "How is billing handled?"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "service_shutting_down")


if __name__ == "__main__":
    unittest.main()
