#!/usr/bin/env python3
"""Phase 11 / Phase 2 - Production-hardened HTTP API (FastAPI) around ``rag_service``.

Features:
- Structured JSON observability per request (with query suppression by default, controlled by SURA_LOG_QUERIES)
- X-Request-Id propagation across all requests, responses, and errors
- Consistent error schema: {"error": {"code": str, "message": str, "request_id": str}}
- Concurrency rate-limiting: fail-fast admission cap (default MAX_CONCURRENT_REQUESTS = 4, configurable via
  SURA_MAX_CONCURRENT_REQUESTS) returning HTTP 429 with Retry-After; admitted requests queue FIFO in RagService
- Separate /health (liveness) and /ready (readiness validating retriever/index/model)
- Backward-compatible /api/health
- Graceful shutdown draining in-flight requests
- Static host for built chat UI (web/dist)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import hmac
import secrets
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_service as S  # noqa: E402
import rag_followup as FU  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, field_validator  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATIC_DIR = ROOT / "web" / "dist"
DEFAULT_CORS = ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173", "http://localhost:8000", "http://127.0.0.1:8000")
MAX_BODY_BYTES = 16 * 1024
MAX_IP_BUCKETS = 4096
FRAME_ANCESTORS_ENV = "RAG_CSP_FRAME_ANCESTORS"
CSP_TEMPLATE = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors {frame_ancestors}"

logger = logging.getLogger("sura.api")
structured_logger = logging.getLogger("sura.structured")


def _configure_structured_logging() -> None:
    """Emit the per-request structured JSON observability records on stdout by default.

    ``structured_logger.info(json.dumps(record))`` produces the record, but without a handler the module logger
    propagates to root, whose last-resort handler only emits WARNING and above - so the INFO records were silently
    dropped under a normal ``python scripts/rag_api.py`` start even though ``docs/DEPLOYMENT.md`` documents them.
    Attach exactly one stdout handler (raw message = one JSON object per line) and stop propagation so the lines are
    not re-formatted or duplicated. Idempotent across repeated imports/``create_app`` calls; a deployment that has
    already attached its own handler to ``sura.structured`` is left untouched.
    """
    if getattr(structured_logger, "_sura_default_handler", None) is not None:
        return
    if structured_logger.handlers:            # an operator/test handler is already configured; do not interfere
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    structured_logger.addHandler(handler)
    structured_logger.setLevel(logging.INFO)
    structured_logger.propagate = False
    structured_logger._sura_default_handler = handler


# Configured from main() (the documented production start), not at import time, so embedding tests that call
# create_app() directly keep full control of the logger and are not polluted with stdout records.


def build_csp(frame_ancestors: Optional[str] = None) -> str:
    """The Content-Security-Policy for static (non-API) responses; ``frame-ancestors`` is overridable, everything else is fixed."""
    value = frame_ancestors if frame_ancestors is not None else os.environ.get(FRAME_ANCESTORS_ENV)
    return CSP_TEMPLATE.format(frame_ancestors=(value or "'none'").strip() or "'none'")


CSP = build_csp()

# Deprecated: the per-IP sliding window is now stored per application instance
# (``app.state.rag["ip_request_history"]``) so that independent app instances -
# including test clients - never share rate-limit state. This module-level dict
# is kept only for backward compatibility with older imports; the API no longer
# reads or writes it.
ip_request_history: Dict[str, List[float]] = {}


def validate_configuration() -> Dict[str, Any]:
    """Validates runtime configuration and environment variables."""
    gen = os.environ.get("RAG_GENERATOR", "extractive")
    if gen not in ("extractive", "ollama"):
        raise ValueError(f"Invalid RAG_GENERATOR='{gen}'; expected 'extractive' or 'ollama'")

    # Validate feature flags
    flags = {}
    for flag_name in ("SURA_INTENT_AWARE", "SURA_SECTION_SELECTION", "SURA_ADDITIONAL_EVIDENCE"):
        val = os.environ.get(flag_name, "0")
        if val not in ("0", "1", ""):
            raise ValueError(f"Invalid {flag_name}='{val}'; expected '0' or '1'")
        flags[flag_name] = val == "1"

    # Rate limiting
    rate_limit_raw = os.environ.get("SURA_RATE_LIMIT_PER_MINUTE", "60")
    try:
        rate_limit = int(rate_limit_raw)
        if rate_limit < 0:
            raise ValueError()
    except ValueError:
        raise ValueError(f"Invalid SURA_RATE_LIMIT_PER_MINUTE='{rate_limit_raw}'; expected non-negative integer")

    # Concurrency admission cap (the fail-fast 429 gate). Default: rag_service.MAX_CONCURRENT_REQUESTS.
    # Requests admitted past this gate queue FIFO inside RagService (max_concurrency), so raising the cap
    # converts fast rejections into graceful queuing rather than unbounded admission.
    max_conc_raw = os.environ.get("SURA_MAX_CONCURRENT_REQUESTS", "")
    if max_conc_raw.strip():
        try:
            max_concurrent = int(max_conc_raw)
            if max_concurrent < 1:
                raise ValueError()
        except ValueError:
            raise ValueError(f"Invalid SURA_MAX_CONCURRENT_REQUESTS='{max_conc_raw}'; expected integer >= 1")
    else:
        max_concurrent = S.MAX_CONCURRENT_REQUESTS

    # Logging mode
    log_queries_raw = os.environ.get("SURA_LOG_QUERIES", "0").lower()
    if log_queries_raw not in ("0", "1", "true", "false", "yes", "no", ""):
        raise ValueError(f"Invalid SURA_LOG_QUERIES='{log_queries_raw}'")

    profile = os.environ.get("SURA_PROFILE", "local")
    if profile not in ("local", "production"):
        raise ValueError("SURA_PROFILE must be local or production")
    token = os.environ.get("SURA_API_TOKEN", "")
    if token and (not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token)):
        raise ValueError("SURA_API_TOKEN must contain 32-256 non-whitespace ASCII characters")
    hosts = [h.strip() for h in os.environ.get("SURA_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if profile == "production":
        if not token or not hosts or any("*" in h for h in hosts):
            raise ValueError("Production requires an API token and explicit allowed hosts")
        if log_queries_raw in ("1", "true", "yes") or os.environ.get("RAG_ENABLE_DEBUG", "0").lower() in ("1", "true", "yes"):
            raise ValueError("Production forbids raw query logging and debug output")
        if any(flags.values()) or "*" in os.environ.get("RAG_CORS_ORIGINS", ""):
            raise ValueError("Production forbids experimental flags and wildcard CORS")
        if "*" in os.environ.get(FRAME_ANCESTORS_ENV, ""):
            raise ValueError("Production forbids wildcard frame ancestors")

    card_store_dir = ROOT / "data" / "vector_store"
    page_store_dir = card_store_dir / "page_collection"
    page_corpus_dir = ROOT / "data" / "page_corpus"
    return {
        "generator": gen,
        "profile": profile,
        "authentication_enabled": bool(token),
        "allowed_hosts": hosts,
        "feature_flags": flags,
        "rate_limit_per_minute": rate_limit,
        "max_concurrent_requests": max_concurrent,
        "log_queries_raw": log_queries_raw in ("1", "true", "yes"),
        "card_collection_exists": (card_store_dir / "chroma.sqlite3").is_file(),
        "page_collection_exists": (page_store_dir / "chroma.sqlite3").is_file(),
        "page_corpus_exists": (page_corpus_dir / "manifest.json").is_file(),
    }


class TopicIdentity(BaseModel):
    """Server-issued page identity."""
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(..., min_length=1, max_length=64)
    title: Optional[str] = Field(default=None, max_length=300)
    guide_id: Optional[str] = Field(default=None, max_length=200)
    page_id: Optional[str] = Field(default=None, max_length=200)
    industry: Optional[str] = Field(default=None, max_length=100)


class ActiveTopicContext(BaseModel):
    """A successfully answered standalone query and its immutable page identity."""
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=1, max_length=FU.MAX_QUESTION_CHARS)
    answer: str = Field(..., min_length=1, max_length=FU.MAX_ANSWER_CHARS)
    identity: TopicIdentity
    seen_answers: List[str] = Field(default_factory=list, max_length=4)


class ChatContext(BaseModel):
    """Previous turns used only to resolve short context-dependent follow-up messages."""
    model_config = ConfigDict(extra="forbid")
    questions: List[str] = Field(default_factory=list, max_length=FU.MAX_QUESTIONS + 2)
    answer: Optional[str] = Field(default=None, max_length=FU.MAX_ANSWER_CHARS)
    active_topic: Optional[ActiveTopicContext] = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., max_length=S.MAX_MESSAGE_CHARS * 2)
    conversation_id: Optional[str] = Field(default=None, max_length=128)
    debug: bool = False
    context: Optional[ChatContext] = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("The message cannot be empty or blank.")
        return v


class Source(BaseModel):
    type: str
    marker: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    url: Optional[str] = None
    source_id: Optional[str] = None
    chunk_id: Optional[str] = None


class TopicReference(BaseModel):
    type: str
    title: str
    url: str
    note: str


class Grounding(BaseModel):
    checked: bool
    ok: Optional[bool] = None
    sentences: int = 0
    violations: int = 0
    cited_markers: List[str] = []


class StructuredSection(BaseModel):
    title: str
    key: str
    lines: List[str] = Field(default_factory=list)
    content: Optional[str] = None
    citations: List[str] = Field(default_factory=list)


class StructuredAnswer(BaseModel):
    summary: Optional[str] = None
    sections: List[StructuredSection] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    unstructured_fallback: Optional[str] = None


class DocumentationCoverage(BaseModel):
    covered: bool
    coverage_percentage: float
    total_sources_cited: int
    matched_topics: List[str] = Field(default_factory=list)
    uncovered_aspects: List[str] = Field(default_factory=list)


class Metadata(BaseModel):
    card_id: Optional[str] = None
    card_title: Optional[str] = None
    identity_status: Optional[str] = None
    page_available: Optional[bool] = None
    generator: str
    grounded: bool
    # The backend is authoritative about elaboration availability: true for a grounded answer, false once the
    # verified evidence of the active topic is exhausted (status no_additional_verified_evidence).
    can_elaborate: bool = True
    grounding: Grounding
    pipeline_status: str
    reason_code: Optional[str] = None
    latency_ms: float
    topic_identity: Optional[TopicIdentity] = None
    follow_up_category: Optional[str] = None
    elaboration_sections: Optional[List[Dict[str, Any]]] = None
    documentation_coverage: Optional[DocumentationCoverage] = None


class ChatResponse(BaseModel):
    schema_version: str
    conversation_id: str
    status: str
    answer: str
    sources: List[Source]
    topic_reference: Optional[TopicReference] = None
    metadata: Metadata
    debug: Optional[Dict[str, Any]] = None
    structured_answer: Optional[StructuredAnswer] = None
    documentation_coverage: Optional[DocumentationCoverage] = None


def error_body(code: str, message: str, request_id: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message, "request_id": request_id or ""}
    err.update(extra)
    return {"error": err}


def create_app(service: Optional[S.RagService] = None, generator: Optional[str] = None, cors_origins: Optional[Sequence[str]] = None, enable_debug: Optional[bool] = None,
               static_dir: Optional[Path] = None, service_factory: Optional[Callable[[str], S.RagService]] = None) -> FastAPI:
    gen = generator or os.environ.get("RAG_GENERATOR", "extractive")
    origins = list(cors_origins) if cors_origins is not None else ([o.strip() for o in os.environ["RAG_CORS_ORIGINS"].split(",") if o.strip()] if os.environ.get("RAG_CORS_ORIGINS") else ([] if os.environ.get("SURA_PROFILE") == "production" else list(DEFAULT_CORS)))
    debug_on = bool(enable_debug) if enable_debug is not None else (os.environ.get("RAG_ENABLE_DEBUG", "0").strip().lower() in ("1", "true", "yes"))
    csp = build_csp()
    sdir = Path(static_dir) if static_dir is not None else Path(os.environ.get("RAG_STATIC_DIR", DEFAULT_STATIC_DIR))

    profile = os.environ.get("SURA_PROFILE", "local")
    api_token = os.environ.get("SURA_API_TOKEN", "")
    log_key = secrets.token_bytes(32)  # Never logged; production hashes resist query dictionary lookup.
    owned_service = service is None
    state: Dict[str, Any] = {
        "service": service,
        "error": None,
        "shutting_down": False,
        "active_requests": 0,
        # Per-IP sliding-window rate limiting tracker: client_ip -> list of epoch
        # timestamps. Stored per app so separate instances never share state.
        "ip_request_history": {},
    }
    in_flight_lock = threading.Lock()
    # Fail closed even when an ASGI host omits lifespan startup.
    try:
        initial_config = validate_configuration()
        if profile == "production" and (debug_on or "*" in origins):
            raise ValueError("Unsafe production app overrides")
    except ValueError:
        initial_config = {}
        state.update(configuration_invalid=True, error="Invalid server configuration.", service=None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            cfg_validation = validate_configuration()
            logger.info("Configuration validated: %s", cfg_validation)
        except Exception as e:
            logger.warning("Configuration rejected (%s)", type(e).__name__)
            state["configuration_invalid"] = True
            state["error"] = "Invalid configuration; see startup configuration documentation."
            state["service"] = None

        if state["service"] is None and not state.get("configuration_invalid"):
            try:
                state["service"] = (service_factory or S.build_service)(gen)
            except Exception as e:                                   # noqa: BLE001
                logger.error("Service initialization failed (%s)", type(e).__name__)
                state["error"] = "Service initialization failed; consult operator diagnostics."
        try:
            yield
        finally:
            state["shutting_down"] = True
            t_drain0 = time.monotonic()
            while state["active_requests"] > 0 and (time.monotonic() - t_drain0) < 5.0:
                await asyncio.sleep(0.05)
            if state["active_requests"]:
                logger.error("Shutdown drain deadline expired; resources retained until process exit")
            elif owned_service and state.get("service") is not None:
                close = getattr(state["service"], "close", None)
                if callable(close):
                    close()  # Failure is visible, never falsely report a successful shutdown.

    app = FastAPI(title="SAP Utilities RAG chat API", version="11.1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.state.rag = state
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "X-Request-Id", "Authorization"], max_age=600)

    if profile == "production" and initial_config.get("allowed_hosts"):
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=initial_config["allowed_hosts"])

    def secure(resp, request):
        resp.headers["X-Request-Id"] = getattr(request.state, "request_id", "")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/") or request.url.path in ("/health", "/ready"):
            resp.headers.setdefault("Cache-Control", "no-store")
        else:
            resp.headers.setdefault("Content-Security-Policy", csp)
        return resp

    @app.middleware("http")
    async def guard(request: Request, call_next):
        supplied_id = request.headers.get("x-request-id", "")
        req_id = supplied_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied_id) else uuid.uuid4().hex
        request.state.request_id = req_id

        if state.get("configuration_invalid") and request.url.path != "/health":
            return secure(JSONResponse(error_body("service_not_ready", "Invalid server configuration.", request_id=req_id), status_code=503), request)
        if api_token and request.url.path not in ("/health", "/ready") and request.method != "OPTIONS":
            scheme, _, credential = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or len(credential) > 256 or not secrets.compare_digest(credential.encode("utf-8"), api_token.encode("utf-8")):
                return secure(JSONResponse(error_body("unauthorized", "Authentication required.", request_id=req_id), status_code=401,
                                           headers={"WWW-Authenticate": "Bearer"}), request)

        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
            resp = JSONResponse(error_body("payload_too_large", f"The request body is larger than {MAX_BODY_BYTES} bytes.", request_id=req_id), status_code=413)
            return secure(resp, request)

        if request.method == "POST" and request.url.path.startswith("/api/"):
            async def consume_body():
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        return None
                    body.extend(chunk)
                return bytes(body)
            try:
                body = await asyncio.wait_for(consume_body(), timeout=10.0)
            except asyncio.TimeoutError:
                return secure(JSONResponse(error_body("request_body_timeout", "The request body was not received in time.", request_id=req_id),
                                    status_code=408), request)
            if body is None:
                return secure(JSONResponse(error_body("payload_too_large", f"The request body is larger than {MAX_BODY_BYTES} bytes.", request_id=req_id),
                                    status_code=413), request)
            request._body = body

        return secure(await call_next(request), request)

    @app.exception_handler(S.ServiceError)
    async def on_service_error(request: Request, exc: S.ServiceError):
        req_id = getattr(request.state, "request_id", "")
        return JSONResponse(error_body(exc.code, exc.message, request_id=req_id), status_code=exc.http_status, headers={"X-Request-Id": req_id})

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError):
        req_id = getattr(request.state, "request_id", "")
        fields = sorted({".".join(str(p) for p in e.get("loc", ()) if p != "body") or "body" for e in exc.errors()})
        return JSONResponse(error_body("invalid_request", "The request is malformed: check " + ", ".join(fields) + ".", request_id=req_id, fields=fields), status_code=422, headers={"X-Request-Id": req_id})

    @app.exception_handler(Exception)
    async def on_unexpected_error(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", "")
        logger.error("Unhandled exception for request %s (%s)", req_id, type(exc).__name__)
        return JSONResponse(error_body("internal_error", "An unexpected error occurred.", request_id=req_id), status_code=500, headers={"X-Request-Id": req_id})

    def current() -> S.RagService:
        svc = state["service"]
        if svc is None:
            raise S.NotReady("The RAG service is not ready" + (f": {state['error']}" if state["error"] else ".") + " Build the card and page stores first (see data/phase11_report.md).")
        return svc

    @app.get("/health")
    def liveness(request: Request):
        req_id = getattr(request.state, "request_id", "")
        return JSONResponse({"status": "ok", "process": "live"}, headers={"X-Request-Id": req_id})

    @app.get("/ready")
    def readiness(request: Request):
        req_id = getattr(request.state, "request_id", "")
        svc = state.get("service")
        if svc is None:
            return JSONResponse(error_body("service_not_ready", "Service is not initialized.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
        if state.get("error"):
            return JSONResponse(error_body("service_not_ready", state["error"], request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
        try:
            if not hasattr(svc.pipeline, "retriever") or svc.pipeline.retriever is None:
                return JSONResponse(error_body("retriever_unavailable", "Retriever is not configured.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
            retriever_count = getattr(svc.pipeline.retriever, "count", None)
            if callable(retriever_count) and int(retriever_count()) < 1:
                return JSONResponse(error_body("index_unavailable", "Page vector collection is empty or unavailable.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
            if not hasattr(svc.pipeline, "corpus") or not svc.pipeline.corpus.entries:
                return JSONResponse(error_body("index_unavailable", "Corpus index is empty or unavailable.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
            card_health_check = getattr(svc.pipeline.backend, "health_check", None)
            if callable(card_health_check):
                card_health_check()
            if svc.generator_name == "ollama":
                # Walk the shipped guard chain (GeneratorGuard -> EvidenceGuard -> LLMGenerator -> OllamaClient) to
                # find a model client exposing check_available. The old single-level lookup stopped at EvidenceGuard
                # and silently skipped the check, so readiness claimed ready:true even when the model was
                # unreachable. If no probe is found at all, fail closed rather than falsely report ready.
                client = None
                node = getattr(svc.pipeline, "generator", None)
                for _ in range(8):                                   # bounded guard-chain depth
                    if node is None:
                        break
                    cand = getattr(node, "client", None)
                    if cand is not None and hasattr(cand, "check_available"):
                        client = cand
                        break
                    node = getattr(node, "inner", None)
                if client is None:
                    return JSONResponse(error_body("model_unavailable", "Ollama model availability cannot be verified (no probe in the generator chain).", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
                if not client.check_available():
                    return JSONResponse(error_body("model_unavailable", "Ollama model is not reachable.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
        except Exception as e:
            logger.error("Readiness check failed (%s)", type(e).__name__)
            return JSONResponse(error_body("service_not_ready", "Dependency readiness check failed.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})
        # Match /api/health: count pages actually admitted/searchable, not the 29 registered topic cards (28/29 today;
        # only M2C-18 stays un-ingested under its conflicting identity).
        # This is a reporting correction only; the readiness checks above and the response shape stay unchanged.
        return JSONResponse({"status": "ok", "ready": True, "topics": len(svc.pipeline.cards),
                             "pages_available": svc.info()["pages_available"], "generator": svc.generator_name},
                            headers={"X-Request-Id": req_id})

    @app.get("/api/health")
    def api_health(request: Request):
        req_id = getattr(request.state, "request_id", "")
        svc = state.get("service")
        if svc is None:
            return JSONResponse({"status": "unavailable", "ready": False, "reason": state.get("error") or "starting", "debug_enabled": debug_on}, status_code=503, headers={"X-Request-Id": req_id})
        dependency_readiness = readiness(request)
        if dependency_readiness.status_code != 200:
            return JSONResponse({"status": "unavailable", "ready": False, "reason": "Dependency readiness failed.",
                                 "debug_enabled": debug_on}, status_code=503, headers={"X-Request-Id": req_id})
        return JSONResponse({"status": "ok", "ready": True, "debug_enabled": debug_on, **svc.info()}, headers={"X-Request-Id": req_id})

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, request: Request):
        req_id = getattr(request.state, "request_id", "") or uuid.uuid4().hex
        if state.get("shutting_down"):
            return JSONResponse(error_body("service_shutting_down", "Server is shutting down.", request_id=req_id), status_code=503, headers={"X-Request-Id": req_id})

        if req.debug and not debug_on:
            return JSONResponse(error_body("debug_disabled", "Debug output is disabled on this server.", request_id=req_id), status_code=403, headers={"X-Request-Id": req_id})

        if state.get("configuration_invalid"):
            return JSONResponse(error_body("service_not_ready", "Invalid server configuration.", request_id=req_id),
                                status_code=503, headers={"X-Request-Id": req_id})

        # Rate limiting: configurable per-IP window (SURA_RATE_LIMIT_PER_MINUTE)
        client_ip = request.client.host if request.client else "unknown"
        if client_ip != "unknown":
            limit_per_min = int(os.environ.get("SURA_RATE_LIMIT_PER_MINUTE", "60"))
            if limit_per_min > 0:
                now_sec = time.time()
                window_start = now_sec - 60.0
                with in_flight_lock:
                    history = state["ip_request_history"]
                    if client_ip not in history and len(history) >= MAX_IP_BUCKETS:
                        expired = [ip for ip, stamps in history.items() if not stamps or max(stamps) <= window_start]
                        for ip in expired:
                            del history[ip]
                        if len(history) >= MAX_IP_BUCKETS:
                            return JSONResponse(error_body("rate_limited", "Rate-limit capacity reached; retry later.", request_id=req_id),
                                                status_code=429, headers={"Retry-After": "60"})
                    hist = history.setdefault(client_ip, [])
                    hist[:] = [t for t in hist if t > window_start]
                    if len(hist) >= limit_per_min:
                        return JSONResponse(
                            error_body("rate_limited", "Rate limit exceeded for this client IP. Please wait before retrying.", request_id=req_id),
                            status_code=429,
                            headers={"Retry-After": "60", "X-Request-Id": req_id},
                        )
                    hist.append(now_sec)

        # Rate limiting: max concurrent requests (admission cap; SURA_MAX_CONCURRENT_REQUESTS validated at startup)
        max_concurrent = int(os.environ.get("SURA_MAX_CONCURRENT_REQUESTS", "").strip() or S.MAX_CONCURRENT_REQUESTS)
        with in_flight_lock:
            if state["active_requests"] >= max_concurrent:
                return JSONResponse(
                    error_body("rate_limited", "Too many concurrent requests. Please retry shortly.", request_id=req_id),
                    status_code=429,
                    headers={"Retry-After": "1", "X-Request-Id": req_id},
                )
            state["active_requests"] += 1

        t_req0 = time.perf_counter()
        try:
            svc = current()
            context = req.context.model_dump(exclude_none=True) if req.context else None
            # Shared production API is stateless across requests: never trust a caller's
            # conversation ID to retrieve another caller's server-side conversation.
            # The UI already sends its explicit context; revalidate it in RagService.
            if profile == "production":
                result = svc.ask_stateless(req.message, debug=False, context=context)
            else:
                result = svc.ask(req.message, conversation_id=req.conversation_id, debug=(req.debug and debug_on), context=context)
        except S.ServiceError:
            raise
        except Exception as exc:
            logger.error("Unhandled exception for request %s (%s)", req_id, type(exc).__name__)
            return JSONResponse(error_body("internal_error", "An unexpected error occurred.", request_id=req_id), status_code=500, headers={"X-Request-Id": req_id})
        finally:
            with in_flight_lock:
                state["active_requests"] -= 1

        latency_total_ms = round((time.perf_counter() - t_req0) * 1000.0, 1)

        # Structured JSON observability log record
        try:
            log_query_raw = os.environ.get("SURA_LOG_QUERIES", "").lower() in ("1", "true", "yes")
            if profile == "production":
                logged_query = hmac.new(log_key, req.message.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
            else:
                logged_query = req.message if log_query_raw else hashlib.sha256(req.message.encode("utf-8")).hexdigest()[:16]

            dbg = result.get("debug") or {}
            routing = dbg.get("routing") or {}
            citations = result.get("sources") or []
            selected_chunks = [s["chunk_id"] for s in citations if isinstance(s, dict) and "chunk_id" in s]

            cfg_dict = svc.pipeline.cfg.to_dict() if hasattr(svc.pipeline.cfg, "to_dict") else {}
            cfg_hash = hashlib.sha256(json.dumps(cfg_dict, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            corpus_hash = getattr(svc.pipeline.corpus, "corpus_sha256", "") or ""

            log_record = {
                "request_id": req_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "route": result.get("metadata", {}).get("card_id") or result.get("status"),
                "selected_chunk_ids": selected_chunks,
                "retrieved_chunk_ids": [c.get("chunk_id") for c in dbg.get("pipeline", {}).get("retrieved_chunks", []) if isinstance(c, dict)] if "retrieved_chunks" in dbg.get("pipeline", {}) else selected_chunks,
                "scores": {
                    "candidates": [
                        {"source_id": c.get("source_id"), "similarity": c.get("similarity")}
                        for c in routing.get("candidates", [])[:3]
                    ]
                },
                "validator_results": {
                    "grounding": result.get("metadata", {}).get("grounding"),
                    "grounded": result.get("metadata", {}).get("grounded"),
                    "coverage": result.get("documentation_coverage"),
                },
                "latency_per_stage": dbg.get("timings_ms") or {"total_ms": latency_total_ms},
                "latency_ms": latency_total_ms,
                "config_hash": cfg_hash,
                "corpus_hash": corpus_hash,
                "query": logged_query,
                "status": result.get("status"),
                "http_status": 200,
            }
            structured_logger.info(json.dumps(log_record))
        except Exception:
            pass

        data = ChatResponse(**result).model_dump()
        for field in ("topic_identity", "follow_up_category", "elaboration_sections"):
            if data["metadata"].get(field) is None:
                data["metadata"].pop(field, None)
        if not req.debug:
            data.pop("debug", None)
        return JSONResponse(data, headers={"X-Request-Id": req_id})

    if (sdir / "index.html").is_file():
        if (sdir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=sdir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(error_body("not_found", "No such API endpoint."), status_code=404)
            target = (sdir / path).resolve()
            if path and target.is_file() and sdir.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(sdir / "index.html")
    return app


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Serve the grounded RAG chat API (and the built UI from web/dist when present).")
    ap.add_argument("--generator", choices=("extractive", "ollama"), default=os.environ.get("RAG_GENERATOR", "extractive"))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=os.environ.get("PORT", "8000"))
    a = ap.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("SURA_PROFILE") != "production":
        ap.error("Non-loopback binding requires SURA_PROFILE=production and authenticated configuration")
    validate_configuration()  # Invalid production settings must not start a listening socket.
    _configure_structured_logging()          # production start emits the structured JSON request records on stdout
    import uvicorn
    uvicorn.run(create_app(generator=a.generator), host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
