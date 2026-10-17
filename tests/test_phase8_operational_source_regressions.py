"""Operational P2.1/P5.1 retrieval regressions over admitted source pages and in-memory adapters only.

These tests intentionally do not construct RagService/build_service, a persistent Chroma client, or a vector-store
fallback. The card backend and page retriever below are deterministic in-memory lexical adapters; the cited page text,
identity, corpus hashes, and card metadata are read from the repository's admitted local source records.
"""

from __future__ import annotations

import builtins
import hashlib
import os
from pathlib import Path
import re
import sqlite3

import page_corpus as PC
import m2c_page_identity as PID
import rag_completeness as RC
import rag_generate as RG
import rag_text as T
from page_retriever import ChunkHit
from rag_pipeline import PageCorpusIndex, PipelineConfig, RagPipeline

ROOT = Path(__file__).resolve().parents[1]
_PROTECTED = {
    os.path.abspath(ROOT / "data/vector_store/chroma.sqlite3"),
    os.path.abspath(ROOT / "data/vector_store/page_collection/chroma.sqlite3"),
}


def _guard_protected_path(path):
    if isinstance(path, int):
        return
    try:
        candidate = os.path.abspath(os.fspath(path))
    except TypeError:
        return
    if candidate in _PROTECTED:
        raise AssertionError(f"protected persistent Chroma path access blocked: {candidate}")


def _records_by_source_id():
    result = {}
    for record in PC.load_records():
        for source_id in record.get("source_ids", []):
            result[source_id] = record
    return result


class _MemoryCardBackend:
    distance_metric = "cosine"

    def __init__(self, cards):
        self.cards = list(cards)
        self.queries = []

    def query(self, query, n_results):
        self.queries.append(query)
        terms = set(T.terms(query))
        scored = []
        for card in self.cards:
            card_terms = T.term_set(card.get("embedding_text", ""))
            score = len(terms & card_terms) / len(terms) if terms else 0.0
            scored.append((score, int(card.get("source_number") or 0), card))
        scored.sort(key=lambda row: (-row[0], row[1]))
        chosen = scored[:n_results]
        return {
            "ids": [[card["source_id"] for _score, _number, card in chosen]],
            "metadatas": [[{key: card.get(key) for key in (
                "source_id", "title", "category", "source_url", "source_status", "source_url_status",
                "has_source_correction", "citation", "retrieval_unit_id", "source_number", "filename",
                "sha256", "corpus_document", "page_start", "page_end",
            )} for _score, _number, card in chosen]],
            "distances": [[1.0 - score for score, _number, _card in chosen]],
        }


class _MemoryPageRetriever:
    """Single full-page chunks; no persistent collection and no Chroma-compatible fallback."""

    def __init__(self, records):
        self.hits = {}
        self.queries = []
        for record in records:
            text = record["text"]
            guide_id, page_id = record["guide_id"], record["page_id"]
            doc_id = record["doc_id"]
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            metadata = {
                "doc_id": doc_id,
                "source_ids": list(record["source_ids"]),
                "page_text_sha256": record["text_sha256"],
            }
            hit = ChunkHit(
                rank=1,
                chunk_id=f"{doc_id}/000",
                guide_id=guide_id,
                page_id=page_id,
                source_url=record["source_url"],
                title=record.get("page_title") or record.get("title") or "",
                heading_path=(record.get("page_title") or record.get("title") or "",),
                section_title=record.get("page_title") or record.get("title") or "",
                chunk_index=0,
                chunk_count=1,
                content_hash=content_hash,
                text=text,
                distance=0.0,
                similarity=1.0,
                metadata=metadata,
            )
            self.hits[(guide_id, page_id)] = [hit]

    def page_chunks(self, guide_id, page_id):
        return list(self.hits.get((guide_id, page_id), []))

    def retrieve_in_page(self, query, guide_id, page_id, top_k=5, query_embedding=None):
        self.queries.append(query)
        hits = self.page_chunks(guide_id, page_id)
        hits.sort(key=lambda hit: -T.coverage(T.terms(query), hit.text))
        return hits[:top_k]


class _RecordingExtractiveGenerator:
    name = "extractive"

    def __init__(self):
        self.inner = RG.ExtractiveGenerator()
        self.queries = []

    def generate(self, query, context):
        self.queries.append(query)
        return self.inner.generate(query, context)


def _pipeline(monkeypatch):
    """Construct an explicit in-memory pipeline and block all protected database opens/imports."""
    real_import = builtins.__import__

    def import_without_chroma(name, *args, **kwargs):
        if name == "chromadb" or name.startswith("chromadb."):
            raise AssertionError("persistent Chroma import blocked in source regression")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_chroma)
    original_path_open = Path.open

    def guarded_path_open(self, *args, **kwargs):
        _guard_protected_path(self)
        return original_path_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_path_open)
    original_builtin_open = builtins.open

    def guarded_builtin_open(file, *args, **kwargs):
        _guard_protected_path(file)
        return original_builtin_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)

    def blocked_sqlite_connect(*args, **kwargs):
        raise AssertionError("SQLite access blocked in in-memory source regression")

    monkeypatch.setattr(sqlite3, "connect", blocked_sqlite_connect)

    records = PC.load_records()
    corpus = PageCorpusIndex.from_dir()
    cards = PID.load_cards(ROOT)
    context = PID.IdentityContext.from_root(ROOT)
    card_backend = _MemoryCardBackend(cards)
    retriever = _MemoryPageRetriever(records)
    generator = _RecordingExtractiveGenerator()
    pipeline = RagPipeline(
        card_backend, retriever, context, corpus, generator, lambda text: len(text.split()),
        cards=cards, config=PipelineConfig(rerank_router=False, context_budget_tokens=700, max_context_chunks=4),
    )
    return pipeline, card_backend, retriever, generator, {source_id: record for record in records for source_id in record["source_ids"]}


def _answer_without_markers(answer):
    return re.sub(r"\s*\[S[1-9]\d*\]", "", answer or "")


def test_retrieval_aliases_append_without_rewriting_user_query():
    question = "Which technical objects are included in SAP Utilities?"
    expanded = RC.normalize_retrieval_query(question)
    assert expanded.startswith(question)
    assert "technical master data objects" in expanded
    assert "technical objects" in question

    clearing_question = "What sequence of clearing rules is processed in the clearing process for selected open items?"
    clearing_expanded = RC.normalize_retrieval_query(clearing_question)
    assert clearing_expanded.startswith(clearing_question)
    assert "clearing types" in clearing_expanded


def test_p21_technical_objects_are_retrieved_and_cited_from_m2c01_source(monkeypatch):
    pipeline, backend, retriever, generator, records = _pipeline(monkeypatch)
    question = "Which technical objects are included in SAP Utilities?"
    result = pipeline.answer(question, debug=True)

    assert result["query"] == question
    assert result["status"] == "answered", result.get("reason_code")
    assert result["routing"]["selected_source_id"] == "M2C-01"
    assert result["debug"]["retrieval_query"].startswith(question)
    assert backend.queries == [result["debug"]["retrieval_query"]]
    assert retriever.queries == [result["debug"]["retrieval_query"]]
    assert generator.queries == [question]
    assert result["citations"]["answer_sources"]
    assert {source_id for source in result["citations"]["answer_sources"]
            for source_id in source["source_ids"]} == {"M2C-01"}

    source_text = records["M2C-01"]["text"]
    expected_objects = (
        "Grid", "Point of delivery", "Connection", "Connection object", "Technical installation",
        "Premise", "Device location", "Installation", "Device",
    )
    assert "Technical master data includes:" in source_text
    answer = _answer_without_markers(result["answer"])
    assert all(obj in source_text for obj in expected_objects)
    assert all(obj in answer for obj in expected_objects), result["answer"]
    assert all(source["guide_id"] == records["M2C-01"]["guide_id"] and
               source["page_id"] == records["M2C-01"]["page_id"] and
               source["content_hash"] for source in result["citations"]["answer_sources"])


def test_p51_clearing_sequence_is_retrieved_and_cited_from_m2c21_source(monkeypatch):
    pipeline, backend, retriever, generator, records = _pipeline(monkeypatch)
    question = "What sequence of clearing rules is processed in the clearing process for selected open items?"
    result = pipeline.answer(question, debug=True)

    assert result["query"] == question
    assert result["status"] == "answered", result.get("reason_code")
    assert result["routing"]["selected_source_id"] == "M2C-21"
    assert result["debug"]["retrieval_query"].startswith(question)
    assert backend.queries == [result["debug"]["retrieval_query"]]
    assert retriever.queries == [result["debug"]["retrieval_query"]]
    assert generator.queries == [question]
    assert result["citations"]["answer_sources"]
    assert {source_id for source in result["citations"]["answer_sources"]
            for source_id in source["source_ids"]} == {"M2C-21"}

    source_text = records["M2C-21"]["text"]
    expected_steps = (
        "Filter the selected open items according to the specifications for restricting the selection",
        "Creation of a clearing proposal based on the rules of the clearing variant",
        "Handling of unassigned payments (on account or clarification)",
        "Clearing statistical items without follow-on posting (indicator XCLON )",
    )
    assert "following sequence:" in source_text
    # This is a source-grounded lexical/order regression only, not SAP semantic certification.
    source_sequence = source_text[source_text.index("following sequence:"):]
    source_positions = [source_sequence.find(step) for step in expected_steps]
    assert all(position >= 0 for position in source_positions)
    assert all(left < right for left, right in zip(source_positions, source_positions[1:]))
    answer = _answer_without_markers(result["answer"])
    answer_positions = [answer.find(step) for step in expected_steps]
    assert all(position >= 0 for position in answer_positions), result["answer"]
    assert all(left < right for left, right in zip(answer_positions, answer_positions[1:])), result["answer"]
    assert all(source["guide_id"] == records["M2C-21"]["guide_id"] and
               source["page_id"] == records["M2C-21"]["page_id"] and
               source["content_hash"] for source in result["citations"]["answer_sources"])
