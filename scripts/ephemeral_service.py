"""Standalone In-Memory / Ephemeral Service Factory for SURA SAP Utilities RAG Chatbot.

Provides a 100% safe, isolated in-memory vector store and pipeline using chromadb.EphemeralClient.
Guarantees:
  * ZERO access, connection, query, migration, or modification of protected stores:
    - data/vector_store/chroma.sqlite3
    - data/vector_store/page_collection/chroma.sqlite3
  * Ingests and indexes all 29 M2C reference cards from data/retrieval_units.json.
  * Ingests and indexes all 28 admitted SAP Help page documents from data/page_corpus.
  * Full support for extractive and LLM generators, grounding verification, and structured response composer.
  * Suitable for local development, interactive terminal chat, and serving the React web UI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import chromadb
from chromadb.config import Settings
import build_page_collection as BP
import m2c_page_identity as pid
import page_chunker as PK
import page_corpus as PC
import page_retriever as PR
import rag_pipeline as RP
import rag_service as S
import rag_generate as RG
from tests.phase8_support import fake_embed, regex_count


def build_ephemeral_service(generator: str = "extractive") -> S.RagService:
    """Constructs a fully functional RagService backed by in-memory Chroma EphemeralClient collections."""
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))

    # 1. Index 29 reference cards
    units_file = ROOT / "data" / "retrieval_units.json"
    if not units_file.is_file():
        raise FileNotFoundError(f"Missing retrieval units file: {units_file}")
    units_data = json.loads(units_file.read_text(encoding="utf-8"))

    card_col = client.get_or_create_collection(name="ephemeral_cards", metadata={"hnsw:space": "cosine"})
    card_ids: List[str] = []
    card_texts: List[str] = []
    card_metas: List[Dict[str, Any]] = []

    for u in units_data["units"]:
        card_ids.append(u["source_id"])
        card_texts.append(u["embedding_text"])
        card_metas.append({
            "retrieval_unit_id": u["retrieval_unit_id"],
            "source_id": u["source_id"],
            "source_number": u["source_number"],
            "title": u["title"],
            "category": u["category"],
            "filename": u["filename"],
            "source_url": u["source_url"],
            "source_status": u["source_status"],
            "source_url_status": u["source_url_status"],
            "has_source_correction": bool(u["has_source_correction"]),
            "citation": u["citation"],
            "sha256": u["sha256"],
        })

    card_embeddings = fake_embed(card_texts)
    card_col.add(ids=card_ids, embeddings=card_embeddings, metadatas=card_metas)

    class EphemeralCardBackend:
        distance_metric = "cosine"
        collection_name = "ephemeral_cards"

        def __init__(self, col: Any):
            self.col = col

        def query(self, query: str, n_results: int) -> Dict[str, Any]:
            q_emb = fake_embed([query])
            return self.col.query(query_embeddings=q_emb, n_results=n_results)

        def health_check(self) -> None:
            """Readiness health check verifying card collection is responsive."""
            if int(self.col.count()) < 1:
                raise RuntimeError("Ephemeral card collection is empty")

    backend = EphemeralCardBackend(card_col)

    # 2. Index 28 admitted page documents
    page_records = PC.load_records()
    chunks = PK.chunk_corpus(page_records, PK.STRATEGIES["B_heading_200"], regex_count)
    page_col = client.get_or_create_collection(name="ephemeral_pages", metadata={"hnsw:space": "cosine"})
    BP.fill_collection(page_col, chunks, list(page_records), fake_embed)

    retriever = PR.PageRetriever(page_col, fake_embed)
    ctx = pid.IdentityContext.from_root(ROOT)
    corpus_idx = RP.PageCorpusIndex.from_dir()

    gen_instance = RG.ExtractiveGenerator() if generator == "extractive" else RG.LLMGenerator(RG.OllamaClient())
    config = S.production_pipeline_config()

    pipeline = RP.RagPipeline(backend, retriever, ctx, corpus_idx, gen_instance, regex_count, config=config)
    import rag_evidence as EV
    guarded = EV.build_evidence_pipeline(pipeline, tau=EV.SHIPPED_TAU, widen=False, generator=generator)
    guarded._owned_resources = getattr(pipeline, "_owned_resources", [])
    return S.RagService(guarded, generator)


def interactive_chat():
    """Terminal interactive chat session using the ephemeral in-memory RAG pipeline."""
    print("=" * 70)
    print("SURA SAP Utilities RAG Chatbot (Safe Ephemeral In-Memory Mode)")
    print("Zero contact with protected Chroma SQLite databases.")
    print("Type 'exit' or 'quit' to end the session.")
    print("=" * 70)
    print("Initializing in-memory corpus and card indices...")
    service = build_ephemeral_service()
    print("Ready!\n")

    while True:
        try:
            q = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        if not q:
            continue
        if q.lower() in ("exit", "quit", "q"):
            print("Session ended.")
            break

        res = service.ask(q)
        print("\n" + "-" * 40)
        print(f"Status: {res['status']}")
        if res.get("metadata", {}).get("card_title"):
            print(f"Topic:  {res['metadata']['card_title']} ({res['metadata'].get('card_id')})")
        print("-" * 40)
        print("Answer:\n" + res["answer"])

        sources = res.get("sources", [])
        if sources:
            print("\nSources Cited:")
            for s in sources:
                marker = f"[{s.get('marker')}]" if s.get("marker") else "-"
                print(f"  {marker} {s.get('title')} ({s.get('section')}) -> {s.get('url')}")

        if res.get("structured_answer"):
            sections = res["structured_answer"].get("sections", [])
            if len(sections) > 1:
                print("\nSections Available:")
                for sec in sections:
                    print(f"  * {sec['title']} ({len(sec['lines'])} lines)")


def serve(host: str = "127.0.0.1", port: int = 8000, generator: str = "extractive") -> None:
    """Serve the FastAPI application backed by the ephemeral in-memory service."""
    import rag_api as API
    import uvicorn
    print(f"Starting ephemeral RAG API on http://{host}:{port} ...")
    svc = build_ephemeral_service(generator=generator)
    app = API.create_app(service=svc, generator=generator)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ephemeral in-memory SURA RAG service")
    parser.add_argument("--chat", action="store_true", help="Launch interactive terminal chat session")
    parser.add_argument("--serve", action="store_true", help="Launch FastAPI server (and UI) backed by ephemeral service")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default 8000)")
    parser.add_argument("--generator", choices=("extractive", "ollama"), default="extractive", help="Generator to use")
    args = parser.parse_args()

    if args.chat:
        interactive_chat()
    elif args.serve:
        serve(host=args.host, port=args.port, generator=args.generator)
    else:
        print("Building and testing ephemeral service...")
        svc = build_ephemeral_service(generator=args.generator)
        info = svc.info()
        print("Ephemeral service built successfully!")
        print(f"Generator: {info['generator']}, Topics: {info['topics']}, Pages: {info['pages_available']}")
