"""Phase 11 - HTTP API (``scripts/rag_api.py``). The happy path runs the real ``RagPipeline`` code (real page corpus, stub router, fake embedder); the
store-backed class additionally runs the real card store, page store and embedding model and is skipped when they are absent."""
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.phase8_support import HAVE_BS4, HAVE_CHROMA, ROOT, make_pipeline
from tests.test_phase9 import NEED_STORES

import rag_generate as RG  # noqa: E402
import rag_service as S  # noqa: E402

HAVE_API = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None
NEED_API = unittest.skipUnless(HAVE_API and HAVE_BS4 and HAVE_CHROMA, "fastapi / httpx / bs4 / chromadb not installed")
from tests.test_phase11_service import Boom, Q_ABSENT, Q_BILLING, Q_CONFLICT, Q_DUNNING, Q_OOD, Q_PLAN, RANKING  # noqa: E402

if HAVE_API:
    import warnings
    warnings.filterwarnings("ignore", message=".*httpx.*")
    from fastapi.testclient import TestClient
    import rag_api  # noqa: E402

INTERNAL_ID = re.compile(r"\bM2C-\d+\b")
RESPONSE_KEYS = {"schema_version", "conversation_id", "status", "answer", "sources", "topic_reference", "metadata"}
META_KEYS = {"card_id", "card_title", "identity_status", "page_available", "generator", "grounded", "grounding", "pipeline_status", "reason_code", "latency_ms", "topic_identity"}
SOURCE_KEYS = {"type", "marker", "title", "section", "url", "source_id", "chunk_id"}


def client(generator=None, name="extractive", **kw):
    svc = S.RagService(make_pipeline(generator or RG.ExtractiveGenerator(), RANKING), name)
    return TestClient(rag_api.create_app(service=svc, static_dir=Path("/nonexistent"), **kw)), svc


def post(c, message=Q_PLAN, **kw):
    return c.post("/api/chat", json={"message": message, **kw})


@NEED_API
class HealthTests(unittest.TestCase):
    def test_health_ready(self):
        c, svc = client()
        r = c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual((b["status"], b["ready"], b["generator"], b["topics"]), ("ok", True, "extractive", 29))
        self.assertEqual(b["pages_available"], 7)

    def test_health_reports_a_failed_start_instead_of_hiding_it(self):
        def factory(generator):
            raise FileNotFoundError("card store missing")
        with TestClient(rag_api.create_app(service_factory=factory, static_dir=Path("/nonexistent"))) as c:
            h = c.get("/api/health")
            self.assertEqual(h.status_code, 503)
            self.assertFalse(h.json()["ready"])
            self.assertIn("card store missing", h.json()["reason"])
            r = post(c)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "service_not_ready"))
            self.assertNotIn("answer", r.json())


@NEED_API
class ChatRequestTests(unittest.TestCase):
    def setUp(self):
        self.c, self.svc = client()

    def test_valid_request(self):
        r = post(self.c)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "answered")
        self.assertTrue(r.json()["answer"].strip())

    def test_empty_and_blank_message(self):
        for m in ("", "   ", "\n\t"):
            r = post(self.c, m)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "invalid_request"))
            self.assertNotIn("answer", r.json())

    def test_malformed_requests(self):
        for kwargs in ({"content": "not json", "headers": {"content-type": "application/json"}}, {"json": {}}, {"json": {"message": 5}}, {"json": {"message": None}},
                       {"json": ["x"]}, {"json": {"message": "hi", "unknown": 1}}, {"json": {"message": "hi", "debug": "yes please"}}):
            r = self.c.post("/api/chat", **kwargs)
            self.assertEqual(r.status_code, 422, kwargs)
            self.assertEqual(r.json()["error"]["code"], "invalid_request")

    def test_validation_error_does_not_echo_the_input(self):
        r = self.c.post("/api/chat", json={"message": 12345678, "secret_field": "SECRET-VALUE"})
        self.assertNotIn("SECRET-VALUE", r.text)

    def test_too_long_message(self):
        r = post(self.c, "word " * 1000)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "invalid_request"))

    def test_oversized_body(self):
        r = self.c.post("/api/chat", content=b'{"message": "' + b"a" * 20000 + b'"}', headers={"content-type": "application/json"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (413, "payload_too_large"))

    def test_conversation_id_handling(self):
        self.assertEqual(post(self.c, conversation_id="chat_1-A").json()["conversation_id"], "chat_1-A")
        minted = post(self.c).json()["conversation_id"]
        self.assertRegex(minted, r"^[0-9a-f]{32}$")
        self.assertEqual(post(self.c, conversation_id="bad id!").status_code, 422)

    def test_method_not_allowed_and_unknown_path(self):
        self.assertEqual(self.c.get("/api/chat").status_code, 405)
        self.assertEqual(self.c.get("/api/nothing").status_code, 404)


@NEED_API
class ResponseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.svc = client()

    def test_answer_response_schema(self):
        b = post(self.c).json()
        self.assertEqual(set(b), RESPONSE_KEYS)
        self.assertEqual(set(b["metadata"]), META_KEYS)
        self.assertIn(b["status"], S.API_STATUSES)
        self.assertEqual(b["schema_version"], S.SCHEMA_VERSION)

    def test_citation_schema(self):
        b = post(self.c).json()
        self.assertTrue(b["sources"])
        for s in b["sources"]:
            self.assertEqual(set(s), SOURCE_KEYS)
            self.assertEqual(s["type"], "page")
            self.assertRegex(s["marker"], r"^S\d+$")
            self.assertRegex(s["url"], r"^https://")

    def test_grounding_metadata_is_preserved(self):
        m = post(self.c).json()["metadata"]
        self.assertTrue(m["grounded"])
        self.assertEqual((m["grounding"]["checked"], m["grounding"]["ok"], m["grounding"]["violations"]), (True, True, 0))
        self.assertTrue(m["grounding"]["cited_markers"])
        self.assertEqual(m["pipeline_status"], "answered")

    def test_citation_urls_come_from_the_existing_citation_pipeline(self):
        b = post(self.c).json()
        raw = self.svc.pipeline.answer(Q_PLAN, debug=True)
        self.assertEqual([s["url"] for s in b["sources"]], [s["url"] for s in raw["citations"]["answer_sources"]])
        for s in b["sources"]:
            self.assertEqual(s["url"], next(x["url"] for x in raw["citations"]["answer_sources"] if x["chunk_id"] == s["chunk_id"]))

    def test_page_not_ingested_is_honest(self):
        b = post(self.c, Q_DUNNING).json()
        self.assertEqual((b["status"], b["sources"], b["metadata"]["grounded"], b["metadata"]["page_available"]), ("documentation_unavailable", [], False, False))
        self.assertIn("not currently available", b["answer"])
        self.assertEqual(b["topic_reference"]["type"], "topic_reference")
        self.assertEqual(b["topic_reference"]["url"], self.svc.pipeline.cards["M2C-26"]["source_url"])

    def test_unresolved_identity(self):
        b = post(self.c, Q_CONFLICT).json()
        self.assertEqual((b["status"], b["sources"], b["topic_reference"], b["metadata"]["pipeline_status"]), ("unable_to_verify", [], None, "unresolved_identity"))

    def test_out_of_scope(self):
        b = post(self.c, Q_OOD).json()
        self.assertEqual((b["status"], b["sources"], b["metadata"]["card_id"]), ("out_of_scope", [], None))

    def test_absent_detail_abstains(self):
        b = post(self.c, Q_ABSENT).json()
        self.assertEqual((b["status"], b["sources"], b["answer"]), ("unable_to_verify", [], S.USER_TEXT[S.UNABLE_TO_VERIFY]))

    def test_no_fabricated_citation_or_answer_for_any_non_answered_status(self):
        for q in (Q_DUNNING, Q_CONFLICT, Q_OOD, Q_ABSENT):
            b = post(self.c, q).json()
            self.assertNotEqual(b["status"], "answered")
            self.assertEqual(b["sources"], [])
            self.assertFalse(INTERNAL_ID.search(b["answer"]), b["answer"])
            self.assertFalse(b["metadata"]["grounded"])

    def test_reference_is_never_listed_among_sources(self):
        b = post(self.c, Q_DUNNING).json()
        self.assertNotIn(b["topic_reference"]["url"], [s["url"] for s in b["sources"]])

    def test_deterministic_extractive_response(self):
        a, b = post(self.c, conversation_id="same").json(), post(self.c, conversation_id="same").json()
        for r in (a, b):
            r["metadata"].pop("latency_ms")
        self.assertEqual(a, b)

    def test_json_serialisation_is_strict_and_utf8(self):
        r = post(self.c)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        json.loads(r.text, parse_constant=lambda c: self.fail(f"non-finite {c}"))
        self.assertEqual(r.json(), json.loads(r.content.decode("utf-8")))

    def test_message_with_html_is_not_reflected(self):
        b = post(self.c, "<script>alert(1)</script> How is billing handled?").json()
        self.assertNotIn("<script>", json.dumps(b))


@NEED_API
class FailureTests(unittest.TestCase):
    def test_generator_failure_is_a_controlled_error(self):
        c, _ = client(Boom(), "boom")
        r = post(c)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["error"]["code"], "generator_failed")
        self.assertNotIn("answer", r.json())
        self.assertNotIn("sources", r.json())
        self.assertNotIn("exploded", r.text)

    def test_ollama_unavailable_is_reported_not_replaced(self):
        def chat(**kw):
            raise ConnectionError("refused")
        c, _ = client(RG.LLMGenerator(RG.OllamaClient(model="m", options={}, chat=chat), name="ollama"), "ollama")
        r = post(c)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (502, "generator_failed"))
        self.assertEqual(c.get("/api/health").json()["generator"], "ollama")      # still honest about which generator is configured

    def test_pipeline_failure_is_a_controlled_error(self):
        c, svc = client()

        def broken(*a, **k):
            raise OSError("boom")
        svc.pipeline.retriever.retrieve_in_page = broken
        r = post(c)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (500, "pipeline_failed"))


@NEED_API
class DebugAndSecurityTests(unittest.TestCase):
    def test_debug_is_off_by_default_and_optional(self):
        c, _ = client()
        self.assertNotIn("debug", post(c).json())
        d = post(c, debug=True).json()
        self.assertIn("pipeline", d["debug"])
        self.assertEqual(d["status"], "answered")

    def test_debug_can_be_disabled_on_the_server(self):
        c, _ = client(enable_debug=False)
        r = post(c, debug=True)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "debug_disabled"))
        self.assertEqual(post(c).status_code, 200)
        self.assertFalse(c.get("/api/health").json()["debug_enabled"])

    def test_cors_allows_only_configured_origins(self):
        c, _ = client()
        ok = c.options("/api/chat", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "http://localhost:5173")
        bad = c.options("/api/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", bad.headers)
        self.assertNotEqual(ok.headers.get("access-control-allow-origin"), "*")
        self.assertNotIn("access-control-allow-credentials", ok.headers)
        simple = c.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", simple.headers)

    def test_cors_origins_are_configurable(self):
        c, _ = client(cors_origins=["https://chat.example"])
        r = c.get("/api/health", headers={"Origin": "https://chat.example"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "https://chat.example")
        self.assertNotIn("access-control-allow-origin", c.get("/api/health", headers={"Origin": "http://localhost:5173"}).headers)

    def test_security_headers(self):
        c, _ = client()
        h = c.get("/api/health").headers
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["cache-control"], "no-store")

    def test_static_host_serves_the_ui_and_blocks_traversal_and_api_shadowing(self):
        with tempfile.TemporaryDirectory() as d:
            dist = Path(d) / "dist"
            (dist / "assets").mkdir(parents=True)
            (dist / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
            (dist / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
            (Path(d) / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
            svc = S.RagService(make_pipeline(RG.ExtractiveGenerator(), RANKING), "extractive")
            c = TestClient(rag_api.create_app(service=svc, static_dir=dist))
            r = c.get("/")
            self.assertIn("<title>x</title>", r.text)
            self.assertIn("default-src 'self'", r.headers["content-security-policy"])
            self.assertEqual(c.get("/assets/a.js").status_code, 200)
            self.assertEqual(c.get("/some/client/route").text, r.text)
            for evil in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
                self.assertNotIn("TOP SECRET", c.get(evil).text)
            self.assertEqual(c.get("/api/health").json()["ready"], True)
            self.assertEqual(c.get("/api/unknown").status_code, 404)


@NEED_STORES
@NEED_API
class RealPipelineTests(unittest.TestCase):
    """The real card store, page store, embedding model and router - no stubs anywhere in this class."""

    @classmethod
    def setUpClass(cls):
        cls.app_cm = TestClient(rag_api.create_app(generator="extractive", static_dir=Path("/nonexistent")))
        cls.c = cls.app_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.app_cm.__exit__(None, None, None)

    def test_health_is_ready_with_the_real_corpus(self):
        b = self.c.get("/api/health").json()
        self.assertEqual((b["ready"], b["topics"], b["pages_available"]), (True, 29, 7))

    def test_real_question_gets_a_real_grounded_cited_answer(self):
        r = post(self.c, "How do I create an installment plan?")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(b["status"], "answered")
        self.assertTrue(b["answer"].strip())
        self.assertEqual(b["metadata"]["card_id"], "M2C-24")
        self.assertTrue(b["metadata"]["grounded"])
        units = json.loads((ROOT / "data" / "retrieval_units.json").read_text(encoding="utf-8"))
        units = units["units"] if isinstance(units, dict) else units
        card_url = next(u["source_url"] for u in units if u.get("source_id") == "M2C-24")
        self.assertTrue(b["sources"])
        for s in b["sources"]:
            self.assertEqual(s["url"], card_url)                          # the stored URL of the card's own page, unchanged
        for marker in set(re.findall(r"\[(S\d+)\]", b["answer"])):
            self.assertIn(marker, {s["marker"] for s in b["sources"]})

    def test_real_missing_page_is_not_answered_from_the_card(self):
        b = post(self.c, "How are dunning notices created?").json()
        self.assertEqual((b["status"], b["sources"]), ("documentation_unavailable", []))
        self.assertEqual(b["metadata"]["page_available"], False)

    def test_real_out_of_scope_and_absent_detail(self):
        self.assertEqual(post(self.c, "What is the weather in Hyderabad?").json()["status"], "out_of_scope")
        b = post(self.c, Q_ABSENT).json()
        self.assertEqual((b["status"], b["sources"]), ("unable_to_verify", []))

    def test_real_responses_are_deterministic(self):
        a, b = post(self.c, "How is billing handled?").json(), post(self.c, "How is billing handled?").json()
        for r in (a, b):
            r["metadata"].pop("latency_ms")
            r.pop("conversation_id")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
