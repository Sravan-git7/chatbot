"""Deterministic, structure-aware chunker.

Differences to scripts/chunk_pages.py (which is left untouched):
  * the unit is a *block* (a cleaned line/paragraph), never a regex-split sentence fragment;
  * a block is only split when it alone exceeds ``max_chars`` (sentence boundaries first, then whitespace);
  * section labels (Purpose/Use/Features/...) and the page title stick to the block that follows them, and a
    lead-in line ending with ``:`` sticks to its list;
  * blocks are joined with newlines, so headings survive inside the chunk text;
  * when a section continues into the next chunk the section heading is repeated at its top
    (``heading_prefixed``); no other text is ever duplicated unless ``overlap_chars`` > 0;
  * overlap is explicit: trailing WHOLE blocks of the previous chunk whose total length <= ``overlap_chars``;
  * ids are positional and deterministic: ``<guide_id>/<page_id>#<index:04d>``, plus a content ``chunk_hash``.
Defaults (max_chars=1000, overlap 0) deliberately equal the legacy values: nothing is size-tuned here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .clean import SECTION_LABELS
from .schema import chunk_id, doc_id, sha256_text

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“‘])")


_HEADING_SLACK = 40      # room kept free so a section label can sit in front of a split block within max_chars


@dataclass(frozen=True)
class ChunkConfig:
    max_chars: int = 1000
    overlap_chars: int = 0
    section_labels: FrozenSet[str] = SECTION_LABELS
    prefix_section_on_continuation: bool = True
    embedding_context: str = "none"      # none | title | title_section  (what gets embedded; 'none' = chunk text)

    def validate(self):
        if self.max_chars < 200:
            raise ValueError("max_chars must be >= 200")
        if not 0 <= self.overlap_chars <= self.max_chars // 2:
            raise ValueError("overlap_chars must be between 0 and max_chars/2")
        if self.embedding_context not in ("none", "title", "title_section"):
            raise ValueError("embedding_context must be none|title|title_section")
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["section_labels"] = sorted(self.section_labels)
        return d


@dataclass
class _Block:
    text: str
    start: int
    end: int
    heading: bool
    split: bool = False


def _split_long(text: str, start: int, limit: int) -> List[_Block]:
    """Split a block longer than ``limit`` at sentence boundaries, then at whitespace."""
    pieces: List[str] = []
    cur = ""
    for sent in _SENT.split(text):
        cand = f"{cur} {sent}" if cur else sent
        if len(cand) <= limit:
            cur = cand
            continue
        if cur:
            pieces.append(cur)
        cur = sent
        while len(cur) > limit:
            cut = cur.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(cur[:cut].rstrip())
            cur = cur[cut:].lstrip()
    if cur:
        pieces.append(cur)
    blocks, pos = [], start
    for p in pieces:
        i = text.find(p, pos - start if pos >= start else 0)
        s = start + (i if i >= 0 else 0)
        blocks.append(_Block(p, s, s + len(p), False, True))
        pos = s + len(p)
    return blocks


def _blocks(text: str, title: str, cfg: ChunkConfig) -> List[_Block]:
    out: List[_Block] = []
    pos = 0
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        heading = line.lower() in cfg.section_labels or (bool(title) and line == title and start == 0)
        if len(line) > cfg.max_chars - _HEADING_SLACK and not heading:
            out.extend(_split_long(line, start, cfg.max_chars - _HEADING_SLACK))
        else:
            out.append(_Block(line, start, start + len(line), heading))
    return out


def _units(blocks: List[_Block]) -> List[List[_Block]]:
    units, i = [], 0
    while i < len(blocks):
        unit = [blocks[i]]
        while (unit[-1].heading or unit[-1].text.endswith(":")) and i + 1 < len(blocks):
            i += 1
            unit.append(blocks[i])
        units.append(unit)
        i += 1
    return units


def chunk_document(doc: Dict[str, Any], cfg: Optional[ChunkConfig] = None) -> List[Dict[str, Any]]:
    cfg = (cfg or ChunkConfig()).validate()
    text, title = doc["text"], doc.get("page_title", "")
    blocks = _blocks(text, title, cfg)
    if not blocks:
        return []
    # (chunk blocks, section heading in effect at its first body block)
    groups: List[Tuple[List[_Block], Optional[str]]] = []
    cur: List[_Block] = []
    cur_len = 0
    section: Optional[str] = None
    chunk_section: Optional[str] = None
    reserve = 0

    def flush():
        nonlocal cur, cur_len
        if cur:
            groups.append((cur, chunk_section))
        cur, cur_len = [], 0

    for unit in _units(blocks):
        ulen = sum(len(b.text) + 1 for b in unit)
        if cur and cur_len + ulen > cfg.max_chars - reserve:
            flush()
        if not cur:
            chunk_section = section if not unit[0].heading else unit[0].text
            # room for what _render may put in front of the body: repeated section heading + explicit overlap
            reserve = 0
            if groups:
                reserve = cfg.overlap_chars
                if cfg.prefix_section_on_continuation and chunk_section and not unit[0].heading:
                    reserve += len(chunk_section) + 1
        for b in unit:
            if b.heading:
                section = b.text
        cur.extend(unit)
        cur_len += ulen
        # a unit larger than max_chars is allowed to stand alone (heading stays with its first block)
        if cur_len > cfg.max_chars - reserve:
            flush()
    flush()

    chunks: List[Dict[str, Any]] = []
    prev_blocks: List[_Block] = []
    for idx, (body, sec) in enumerate(groups):
        lines: List[str] = []
        prefixed = False
        if cfg.prefix_section_on_continuation and idx > 0 and sec and not body[0].heading and body[0].text != sec:
            lines.append(sec)
            prefixed = True
        overlap: List[_Block] = []
        if cfg.overlap_chars and prev_blocks:
            total = 0
            for b in reversed(prev_blocks):
                if total + len(b.text) + 1 > cfg.overlap_chars:
                    break
                overlap.insert(0, b)
                total += len(b.text) + 1
        lines.extend(b.text for b in overlap)
        lines.extend(b.text for b in body)
        ctext = "\n".join(lines)
        chunks.append({
            "chunk_id": chunk_id(doc["guide_id"], doc["page_id"], idx), "doc_id": doc_id(doc["guide_id"], doc["page_id"]),
            "chunk_index": idx, "chunk_count": len(groups),
            "topic_id": doc["topic_id"], "topic_title": doc["topic_title"], "topic_ids": list(doc["topic_ids"]),
            "guide_id": doc["guide_id"], "numeric_deliverable_id": doc.get("numeric_deliverable_id"),
            "build_no": doc.get("build_no"), "page_id": doc["page_id"], "page_title": doc["page_title"],
            "toc_path": list(doc["toc_path"]), "source_url": doc["source_url"], "canonical_url": doc["canonical_url"],
            "source_type": doc.get("source_type"), "content_hash": doc["content_hash"], "chunk_hash": sha256_text(ctext),
            "section": sec or title, "char_start": body[0].start, "char_end": body[-1].end,
            "heading_prefixed": prefixed, "overlap_chars_prev": sum(len(b.text) + 1 for b in overlap) if overlap else 0,
            "text": ctext})
        prev_blocks = body
    return chunks


def embedding_text(chunk: Dict[str, Any], mode: str = "none") -> str:
    """What would be embedded. 'none' = the chunk text unchanged (current behaviour of the legacy index)."""
    if mode == "title":
        return f"{chunk['page_title']}\n{chunk['text']}"
    if mode == "title_section":
        return f"{chunk['page_title']} > {chunk['section']}\n{chunk['text']}"
    return chunk["text"]


def embedding_record(chunk: Dict[str, Any], mode: str = "none") -> Dict[str, Any]:
    """Chroma-ready record: id, document, SCALAR-only metadata (lists flattened).
    ``title``/``url`` mirror the keys the existing retrieval code reads (url = canonical_url)."""
    md = {k: chunk[k] for k in ("chunk_id", "doc_id", "topic_id", "topic_title", "guide_id", "page_id", "page_title",
                                "source_url", "canonical_url", "source_type", "content_hash", "chunk_hash", "section",
                                "chunk_index", "chunk_count") if chunk.get(k) is not None}
    md.update(topic_ids=",".join(str(t) for t in chunk["topic_ids"]), toc_path=" > ".join(chunk["toc_path"]),
              title=chunk["page_title"], url=chunk["canonical_url"])
    return {"id": chunk["chunk_id"], "document": embedding_text(chunk, mode), "metadata": md}
