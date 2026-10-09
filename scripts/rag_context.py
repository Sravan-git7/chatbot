"""Phase 8F - context assembly for the grounded answer (pure functions).

Input: ranked ``ChunkHit`` objects from ONE page (identity-constrained retrieval). Output: a ``ContextBlock`` holding the chunks that
fit the token budget, labelled ``S1..Sn`` in reading order, with full provenance and a list of what was dropped and why.

* dedup: identical ``content_hash`` or a chunk whose text is contained in an already selected chunk is dropped (``duplicate``);
* overlap: if a selected chunk repeats the first line(s) of the previous chunk of the same page (the chunker's sentence overlap), the
  repeated prefix is removed from the RENDERED text only (``text`` keeps the original, ``rendered_text`` is what the model sees);
* budget: chunks are taken in retrieval-rank order by default until adding the next would exceed ``budget_tokens`` (``budget``); at most
  ``max_chunks`` are taken. An optional deterministic ``selection_key`` may prioritize query-appropriate evidence without changing
  the source rank recorded on each chunk. The first selected chunk is always kept if it alone exceeds the budget and is flagged
  ``over_budget=True`` - nothing is cut silently;
* order: selected chunks are shown in document order (``chunk_index``), because the pages are procedures and descriptions that read
  top to bottom; the retrieval rank stays in the provenance;
* the prompt never contains a URL, a card, or an identifier other than the markers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

DEFAULT_BUDGET_TOKENS = 700           # context tokens (MiniLM tokenizer); the 3B local model has ample room, the cap keeps answers focused
DEFAULT_MAX_CHUNKS = 4


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


@dataclass
class ContextItem:
    marker: str
    chunk_id: str
    guide_id: str
    page_id: str
    title: str
    heading_path: List[str]
    section_title: str
    chunk_index: int
    rank: int
    similarity: float
    text: str
    rendered_text: str
    tokens: int
    content_hash: str
    source_url: str
    overlap_removed_chars: int = 0

    def to_dict(self, with_text: bool = False) -> Dict[str, Any]:
        d = {"marker": self.marker, "chunk_id": self.chunk_id, "guide_id": self.guide_id, "page_id": self.page_id, "title": self.title,
             "heading_path": self.heading_path, "section_title": self.section_title, "chunk_index": self.chunk_index, "rank": self.rank,
             "similarity": round(self.similarity, 4), "tokens": self.tokens, "content_hash": self.content_hash, "source_url": self.source_url,
             "overlap_removed_chars": self.overlap_removed_chars}
        if with_text:
            d["text"] = self.text
            d["rendered_text"] = self.rendered_text
        return d


@dataclass
class ContextBlock:
    items: List[ContextItem] = field(default_factory=list)
    dropped: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    over_budget: bool = False

    @property
    def markers(self) -> List[str]:
        return [i.marker for i in self.items]

    def by_marker(self, marker: str) -> Optional[ContextItem]:
        return next((i for i in self.items if i.marker == marker), None)

    def render(self) -> str:
        """The exact text placed in the prompt: marker, section path, content. No URLs, no card data."""
        parts = []
        for i in self.items:
            where = " > ".join(i.heading_path) if i.heading_path else i.title
            parts.append(f"[{i.marker}] {where}\n{i.rendered_text}")
        return "\n\n".join(parts)

    def to_dict(self, with_text: bool = False) -> Dict[str, Any]:
        return {"items": [i.to_dict(with_text) for i in self.items], "dropped": list(self.dropped), "total_tokens": self.total_tokens,
                "budget_tokens": self.budget_tokens, "over_budget": self.over_budget}


def _strip_overlap(text: str, prev_text: Optional[str]) -> str:
    """Remove leading lines of ``text`` that already end the previous chunk (sentence overlap added by the chunker)."""
    if not prev_text:
        return text
    lines = text.split("\n")
    prev = _norm(prev_text)
    cut = 0
    while cut < len(lines) - 1 and _norm(lines[cut]) and _norm(lines[cut]) in prev:
        cut += 1
    return "\n".join(lines[cut:])


def build_context(hits: Sequence[Any], count_tokens: Callable[[str], int], budget_tokens: int = DEFAULT_BUDGET_TOKENS,
                  max_chunks: int = DEFAULT_MAX_CHUNKS,
                  selection_key: Optional[Callable[[Any], Any]] = None) -> ContextBlock:
    """Select chunks under the usual limits; ``selection_key`` optionally changes only selection priority.

    Presentation remains in document order, and every item's original retrieval rank is retained for provenance. With no
    key supplied, the shipped retrieval-rank selection order is unchanged.
    """
    block = ContextBlock(budget_tokens=budget_tokens)
    selected: List[Any] = []
    seen_hash = set()
    used = 0
    for h in sorted(hits, key=selection_key or (lambda x: x.rank)):
        if h.content_hash in seen_hash or any(_norm(h.text) in _norm(s.text) for s in selected):
            block.dropped.append({"chunk_id": h.chunk_id, "reason": "duplicate"})
            continue
        if len(selected) >= max_chunks:
            block.dropped.append({"chunk_id": h.chunk_id, "reason": "max_chunks"})
            continue
        t = count_tokens(h.text)
        if selected and used + t > budget_tokens:
            block.dropped.append({"chunk_id": h.chunk_id, "reason": "budget"})
            continue
        if not selected and t > budget_tokens:
            block.over_budget = True
        selected.append(h)
        seen_hash.add(h.content_hash)
        used += t
    selected.sort(key=lambda x: x.chunk_index)
    prev: Optional[Any] = None
    for n, h in enumerate(selected, start=1):
        adjacent = prev is not None and prev.page_id == h.page_id and h.chunk_index == prev.chunk_index + 1
        rendered = _strip_overlap(h.text, prev.text if adjacent else None)
        block.items.append(ContextItem(marker=f"S{n}", chunk_id=h.chunk_id, guide_id=h.guide_id, page_id=h.page_id, title=h.title, heading_path=list(h.heading_path),
                                       section_title=h.section_title, chunk_index=h.chunk_index, rank=h.rank, similarity=h.similarity, text=h.text,
                                       rendered_text=rendered, tokens=count_tokens(rendered), content_hash=h.content_hash, source_url=h.source_url,
                                       overlap_removed_chars=len(h.text) - len(rendered) if rendered != h.text else 0))
        prev = h
    block.total_tokens = sum(i.tokens for i in block.items)
    return block
