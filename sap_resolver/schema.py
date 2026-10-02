"""Canonical document / chunk schema for the target (29-topic) corpus.

Identity fields are never dropped by cleaning, de-duplication or chunking:
a page document carries topic_*, guide_id, numeric_deliverable_id, build_no, page_id ... and every
chunk carries topic_*, guide_id, page_id, page_title, toc_path, source_url, content_hash, chunk_id.

Page document  (data/sap_help/pages/<guide_id>/<page_id>.json)
    schema_version, doc_id ("<guide_id>/<page_id>"),
    topic_id (primary topic), topic_title, topic_ids (ALL referencing topics), topic_refs
        [{topic_id, topic_title, role: topic_page|descendant, via_doc_id|null, pdf_file}],
    guide_id, numeric_deliverable_id, build_no, page_id, file_path, alias_file_paths,
    parent_page_id, toc_path, depth, page_title,
    source_url (card URL for topic pages, else canonical), canonical_url,
    retrieved_at, source_type, fetched_via,
    page_hash  = sha256(raw text),  content_hash = sha256(normalised cleaned text),
    duplicate_of (doc_id of the canonical document or null), duplicate_docs (docs pointing at this one),
    text_raw, text (cleaned), clean_stats, status

Chunk  (data/sap_help/chunks/chunks.jsonl)
    chunk_id ("<guide_id>/<page_id>#<index:04d>"), doc_id, chunk_index, chunk_count,
    topic_id, topic_title, topic_ids, guide_id, numeric_deliverable_id, build_no, page_id, page_title,
    toc_path, source_url, canonical_url, content_hash, chunk_hash, section, char_start, char_end,
    heading_prefixed, overlap_chars_prev, text
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

SCHEMA_VERSION = 1

STATUS_OK = "OK"
STATUS_DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
STATUS_EMPTY = "EMPTY_CONTENT"

PAGE_REQUIRED = ("topic_id", "topic_title", "guide_id", "numeric_deliverable_id", "build_no", "page_id",
                 "parent_page_id", "toc_path", "page_title", "source_url", "canonical_url", "retrieved_at",
                 "source_type", "content_hash", "page_hash", "duplicate_of", "text", "status")
CHUNK_REQUIRED = ("topic_id", "topic_title", "guide_id", "page_id", "page_title", "toc_path", "source_url",
                  "content_hash", "chunk_id")
# keys that may legitimately be None
PAGE_NULLABLE = {"numeric_deliverable_id", "build_no", "parent_page_id", "retrieved_at", "duplicate_of"}


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def doc_id(guide_id: str, page_id: str) -> str:
    return f"{guide_id.lower()}/{page_id.lower()}"


def chunk_id(guide_id: str, page_id: str, index: int) -> str:
    return f"{doc_id(guide_id, page_id)}#{index:04d}"


def _validate(rec: Dict[str, Any], required, nullable=frozenset()) -> List[str]:
    errs = []
    for k in required:
        if k not in rec:
            errs.append(f"missing key {k}")
        elif rec[k] is None and k not in nullable:
            errs.append(f"{k} is null")
        elif rec[k] == "" and k not in nullable and k not in ("text",):
            errs.append(f"{k} is empty")
    return errs


def validate_page(doc: Dict[str, Any]) -> List[str]:
    return _validate(doc, PAGE_REQUIRED, PAGE_NULLABLE)


def validate_chunk(ch: Dict[str, Any]) -> List[str]:
    return _validate(ch, CHUNK_REQUIRED)
