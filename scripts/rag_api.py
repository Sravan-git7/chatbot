#!/usr/bin/env python3
"""Phase 11 - HTTP API (FastAPI) around ``rag_service`` / the existing RAG pipeline, and static host for the built chat UI (``web/dist``).

    python scripts/rag_api.py --generator extractive --host 0.0.0.0 --port 8000

Endpoints
  GET  /api/health   readiness + generator + corpus size (503 while the pipeline cannot start; the reason is reported, never hidden)
  POST /api/chat     {"message": str, "conversation_id"?: str, "debug"?: bool} -> chat result (``rag_service.to_chat_result``)

Errors always have the shape ``{"error": {"code": str, "message": str}}``: ``invalid_request`` 422, ``payload_too_large`` 413, ``debug_disabled`` 403,
``service_not_ready`` 503, ``generator_failed`` 502, ``pipeline_failed`` 500. The server is stateless: ``conversation_id`` is echoed (or minted) and nothing
is stored; every question is answered independently (the pipeline has no conversational memory).

The generator is chosen explicitly (``--generator`` / ``RAG_GENERATOR``); there is no fallback from one generator to another.

Static responses carry a fixed Content-Security-Policy; only ``frame-ancestors`` is deployment-dependent. The default is
``'none'``; a deployment that embeds the UI in a frame opts in with ``RAG_CSP_FRAME_ANCESTORS`` (space-separated sources).
"""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_service as S  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATIC_DIR = ROOT / "web" / "dist"
DEFAULT_CORS = ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173", "http://localhost:8000", "http://127.0.0.1:8000")
MAX_BODY_BYTES = 16 * 1024
# Only ``frame-ancestors`` is deployment-dependent: the shipped default stays 'none' (clickjacking protection unchanged).
# A deployment that embeds the UI in a frame (e.g. an internal preview pane) opts in explicitly via
# RAG_CSP_FRAME_ANCESTORS="'self' https://host.example" - a space-separated CSP source list.
FRAME_ANCESTORS_ENV = "RAG_CSP_FRAME_ANCESTORS"
CSP_TEMPLATE = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors {frame_ancestors}"


def build_csp(frame_ancestors: Optional[str] = None) -> str:
    """The Content-Security-Policy for static (non-API) responses; ``frame-ancestors`` is overridable, everything else is fixed."""
    value = frame_ancestors if frame_ancestors is not None else os.environ.get(FRAME_ANCESTORS_ENV)
    return CSP_TEMPLATE.format(frame_ancestors=(value or "'none'").strip() or "'none'")


CSP = build_csp()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., max_length=S.MAX_MESSAGE_CHARS * 2)
    conversation_id: Optional[str] = Field(default=None, max_length=128)
    debug: bool = False


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


class Metadata(BaseModel):
    card_id: Optional[str] = None
    card_title: Optional[str] = None
    identity_status: Optional[str] = None
    page_available: Optional[bool] = None
    generator: str
    grounded: bool
    grounding: Grounding
    pipeline_status: str
    reason_code: Optional[str] = None
    latency_ms: float


class ChatResponse(BaseModel):
    schema_version: str
    conversation_id: str
    status: str
    answer: str
    sources: List[Source]
    topic_reference: Optional[TopicReference] = None
    metadata: Metadata
    debug: Optional[Dict[str, Any]] = None


def error_body(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


def create_app(service: Optional[S.RagService] = None, generator: Optional[str] = None, cors_origins: Optional[Sequence[str]] = None, enable_debug: Optional[bool] = None,
               static_dir: Optional[Path] = None, service_factory: Optional[Callable[[str], S.RagService]] = None) -> FastAPI:
    gen = generator or os.environ.get("RAG_GENERATOR", "extractive")
    origins = list(cors_origins) if cors_origins is not None else ([o.strip() for o in os.environ["RAG_CORS_ORIGINS"].split(",") if o.strip()] if os.environ.get("RAG_CORS_ORIGINS") else list(DEFAULT_CORS))
    debug_on = enable_debug if enable_debug is not None else os.environ.get("RAG_ENABLE_DEBUG", "1") != "0"
    csp = build_csp()
    sdir = Path(static_dir) if static_dir is not None else Path(os.environ.get("RAG_STATIC_DIR", DEFAULT_STATIC_DIR))
    state: Dict[str, Any] = {"service": service, "error": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state["service"] is None:
            try:
                state["service"] = (service_factory or S.build_service)(gen)
            except Exception as e:                                   # noqa: BLE001 - reported by /api/health and /api/chat, never replaced by a fake service
                state["error"] = f"{type(e).__name__}: {e}"
        yield

    app = FastAPI(title="SAP Utilities RAG chat API", version="11.1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.state.rag = state
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"], max_age=600)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
            return JSONResponse(error_body("payload_too_large", f"The request body is larger than {MAX_BODY_BYTES} bytes."), status_code=413)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        else:
            resp.headers.setdefault("Content-Security-Policy", csp)
        return resp

    @app.exception_handler(S.ServiceError)
    async def on_service_error(_: Request, exc: S.ServiceError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def on_validation(_: Request, exc: RequestValidationError):
        fields = sorted({".".join(str(p) for p in e.get("loc", ()) if p != "body") or "body" for e in exc.errors()})
        return JSONResponse(error_body("invalid_request", "The request is malformed: check " + ", ".join(fields) + ".", fields=fields), status_code=422)

    def current() -> S.RagService:
        svc = state["service"]
        if svc is None:
            raise S.NotReady("The RAG service is not ready" + (f": {state['error']}" if state["error"] else ".") + " Build the card and page stores first (see data/phase11_report.md).")
        return svc

    @app.get("/api/health")
    def health():
        svc = state["service"]
        if svc is None:
            return JSONResponse({"status": "unavailable", "ready": False, "reason": state["error"] or "starting", "debug_enabled": debug_on}, status_code=503)
        return {"status": "ok", "ready": True, "debug_enabled": debug_on, **svc.info()}

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(req: ChatRequest):
        if req.debug and not debug_on:
            return JSONResponse(error_body("debug_disabled", "Debug output is disabled on this server."), status_code=403)
        result = current().ask(req.message, conversation_id=req.conversation_id, debug=req.debug)
        data = ChatResponse(**result).model_dump()                  # schema check: a malformed service result fails loudly instead of reaching the UI
        if not req.debug:
            data.pop("debug", None)
        return JSONResponse(data)

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
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    import uvicorn
    uvicorn.run(create_app(generator=a.generator), host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
