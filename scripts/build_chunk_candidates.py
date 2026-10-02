#!/usr/bin/env python3
"""Phase 3: chunk CANDIDATES for the 29 normalised reference cards (no embeddings, no vector DB, no network, no LLM).

Reads the normalised corpus `data/source_corpus.json` (never modifies it) and writes three candidate representations:

  A  whole_document     one chunk per source PDF                          (29 chunks)
  B  section_based      one chunk per section already in the corpus       (sections are NOT invented)
  C  bounded_sections   sections, split only when longer than --max-chars (default 250; sentence boundaries first)

plus `chunk_candidate_report.md`, which compares them with structural measurements. It does not choose a strategy.

Rules that hold for every strategy
  * `text` is ALWAYS an exact slice `content[char_start:char_end]` of the document's normalised `content`; nothing is
    rewritten, summarised or added. Chunks never overlap, so no text is duplicated by the chunker.
  * The printed section heading (e.g. "What it covers") is part of the source text, so it is part of the section's
    chunk (span = heading line + body). Only whitespace between chunks (the newline / blank line separators that
    `source_corpus.json` placed between sections) is not in any chunk; the report states how many characters that is.
  * Chunk ids are `<source_id>-C<nn>` (index within the source, in offset order). They are unique inside one strategy
    file; the same id in another strategy file denotes a different span, so always read `strategy` with `chunk_id`.
  * Deterministic: no timestamps, sorted/ordered iteration only; identical input -> byte-identical output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
STRATEGIES = ("whole_document", "section_based", "bounded_sections")
STRATEGY_LABEL = {"whole_document": "A whole_document", "section_based": "B section_based", "bounded_sections": "C bounded_sections"}
DEFAULT_MAX_CHARS = 250          # experiment value: every section is <= 277 chars, so this only splits the longest one (see report)
DEFAULT_SMALL_CHARS = 60
DEFAULT_LARGE_CHARS = 600
SENSITIVITY_MAX_CHARS = (100, 150, 200, 250, 300, 400, 500, 1200)
MIN_ADJACENT_REPEAT = 12         # a text repeat shorter than this between neighbours is treated as coincidence
MINILM_SEQ_LIMIT_TOKENS = 256    # all-MiniLM-L6-v2 (named in scripts/rag_core.py) truncates input at 256 word pieces
LEGACY_CHUNK_LIMIT = 1000        # scripts/chunk_pages.py packs sentences up to 1000 characters

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n\s*\n")
_LINE = re.compile(r"\n")
_WORD = re.compile(r"\s+")
_SPLITTERS = (_SENTENCE, _LINE, _WORD)       # tried in this order; a single token longer than the maximum stays whole


# ----------------------------------------------------------------------------- corpus access
def load_corpus(path: Path) -> Tuple[Dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def section_span(doc: Dict[str, Any], sec: Dict[str, Any]) -> Tuple[int, int]:
    """Span of a section INCLUDING its printed heading line (heading + "\\n" sits directly before `char_start`)."""
    start, end, content = sec["char_start"], sec["char_end"], doc["content"]
    if sec.get("heading"):
        head = sec["heading"] + "\n"
        hs = start - len(head)
        if hs < 0 or content[hs:start] != head:
            raise ValueError(f"{sec['section_id']}: heading {sec['heading']!r} not found before char_start {start}")
        start = hs
    if content[start:end] == "" or content[sec["char_start"]:end] != sec["text"]:
        raise ValueError(f"{sec['section_id']}: section offsets do not address its text")
    return start, end


def _stripped(content: str, s: int, e: int) -> Tuple[int, int]:
    while s < e and content[s].isspace():
        s += 1
    while e > s and content[e - 1].isspace():
        e -= 1
    return s, e


# ----------------------------------------------------------------------------- chunk construction
def _make_chunk(doc: Dict[str, Any], strategy: str, idx: int, s: int, e: int, *, sec: Optional[Dict[str, Any]],
                part: Tuple[int, int], exceeds: bool, sections: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    content = doc["content"]
    text = content[s:e]
    prov = doc["provenance"]
    if sec is None:
        where = "full card"
    else:
        where = f"section '{sec['heading'] or sec['key']}'"
    if part[1] > 1:
        where += f" (part {part[0]}/{part[1]})"
    page_start = min(x["page_start"] for x in sections)
    page_end = max(x["page_end"] for x in sections)
    return {
        "chunk_id": f"{doc['source_id']}-C{idx:02d}",
        "strategy": strategy,
        "chunk_index": idx,
        "source_id": doc["source_id"],
        "source_number": doc["source_number"],
        "filename": doc["filename"],
        "title": doc["title"],
        "category": doc["category"],
        "source_status": doc["status"],
        "source_url_status": doc["review"]["source_url_status"],
        "has_source_correction": doc["source_correction"] is not None,
        "sha256": doc["sha256"],
        "source_url": doc["authoritative_source"],
        "page_start": page_start,
        "page_end": page_end,
        "section_id": sec["section_id"] if sec else None,
        "section_key": sec["key"] if sec else None,
        "section_heading": (sec["heading"] if sec else None),
        "section_ids": [x["section_id"] for x in sections],
        "section_part_index": part[0],
        "section_part_count": part[1],
        "char_start": s,
        "char_end": e,
        "char_count": e - s,
        "word_count": len(text.split()),
        "exceeds_max_chars": exceeds,
        "text": text,
        "citation": f"{prov['citation']}, p.{page_start}, {where}, chars {s}-{e}",
    }


def _finish(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    n = len(chunks)
    for c in chunks:
        c["chunks_in_source"] = n
    return chunks


def chunk_whole(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    s, e = _stripped(doc["content"], 0, len(doc["content"]))
    return _finish([_make_chunk(doc, "whole_document", 1, s, e, sec=None, part=(1, 1), exceeds=False, sections=doc["sections"])])


def chunk_sections(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for i, sec in enumerate(sorted(doc["sections"], key=lambda x: x["order"]), 1):
        s, e = section_span(doc, sec)
        out.append(_make_chunk(doc, "section_based", i, s, e, sec=sec, part=(1, 1), exceeds=False, sections=[sec]))
    return _finish(out)


def _pieces(content: str, s: int, e: int, max_chars: int, level: int = 0) -> List[Tuple[int, int]]:
    """Smallest source-aligned pieces <= max_chars where a boundary exists: sentence -> line -> word. A token longer than
    the maximum is left whole (never cut mid-word / mid-URL)."""
    s, e = _stripped(content, s, e)
    if e - s <= max_chars or level >= len(_SPLITTERS):
        return [(s, e)]
    spans, pos = [], s
    for m in _SPLITTERS[level].finditer(content, s, e):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, e))
    spans = [sp for sp in spans if sp[1] > sp[0]]
    if len(spans) <= 1:
        return _pieces(content, s, e, max_chars, level + 1)
    out: List[Tuple[int, int]] = []
    for a, b in spans:
        out.extend(_pieces(content, a, b, max_chars, level + 1) if b - a > max_chars else [_stripped(content, a, b)])
    return out


def split_span(content: str, s: int, e: int, max_chars: int) -> List[Tuple[int, int, bool]]:
    """Greedy packing of consecutive pieces into chunks of at most `max_chars`. Returns (start, end, exceeds_max)."""
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    s, e = _stripped(content, s, e)
    if e - s <= max_chars:
        return [(s, e, False)]
    pieces = _pieces(content, s, e, max_chars)
    out: List[Tuple[int, int, bool]] = []
    cur_s, cur_e = pieces[0]
    for a, b in pieces[1:]:
        if b - cur_s <= max_chars:
            cur_e = b
        else:
            out.append((cur_s, cur_e, cur_e - cur_s > max_chars))
            cur_s, cur_e = a, b
    out.append((cur_s, cur_e, cur_e - cur_s > max_chars))
    return out


def chunk_bounded(doc: Dict[str, Any], max_chars: int = DEFAULT_MAX_CHARS) -> List[Dict[str, Any]]:
    out, idx = [], 0
    for sec in sorted(doc["sections"], key=lambda x: x["order"]):
        s, e = section_span(doc, sec)
        parts = split_span(doc["content"], s, e, max_chars)
        for p, (a, b, over) in enumerate(parts, 1):
            idx += 1
            out.append(_make_chunk(doc, "bounded_sections", idx, a, b, sec=sec, part=(p, len(parts)), exceeds=over, sections=[sec]))
    return _finish(out)


def build_strategy(strategy: str, docs: Sequence[Dict[str, Any]], max_chars: int = DEFAULT_MAX_CHARS) -> List[Dict[str, Any]]:
    fn = {"whole_document": chunk_whole, "section_based": chunk_sections,
          "bounded_sections": lambda d: chunk_bounded(d, max_chars)}[strategy]
    return [c for d in docs for c in fn(d)]


# ----------------------------------------------------------------------------- measurement
def _ws_free(s: str) -> str:
    return "".join(s.split())


def _overlap_repeat(a: str, b: str) -> int:
    for k in range(min(len(a), len(b)), 0, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def _union_len(spans: Sequence[Tuple[int, int]]) -> int:
    total, cur_e = 0, -1
    for s, e in sorted(spans):
        s = max(s, cur_e)
        if e > s:
            total += e - s
            cur_e = e
    return total


def _summary(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "min": 0, "max": 0, "mean": 0.0, "median": 0.0}
    return {"n": len(values), "min": min(values), "max": max(values), "mean": round(sum(values) / len(values), 1),
            "median": round(float(statistics.median(values)), 1)}


def analyse(chunks: Sequence[Dict[str, Any]], docs: Sequence[Dict[str, Any]], *, pdf_dir: Optional[Path] = None,
            small_chars: int = DEFAULT_SMALL_CHARS, large_chars: int = DEFAULT_LARGE_CHARS,
            max_chars: Optional[int] = None) -> Dict[str, Any]:
    """Structural measurements only (no retrieval is run)."""
    by_doc = {d["source_id"]: d for d in docs}
    per: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in chunks:
        per[c["source_id"]].append(c)
    m: Dict[str, Any] = {"chunks": len(chunks), "sources": len(per), "sources_missing": sorted(set(by_doc) - set(per))}
    m["chunk_ids_unique"] = len({c["chunk_id"] for c in chunks}) == len(chunks)
    m["empty_chunks"] = sum(1 for c in chunks if not c["text"].strip())

    # completeness / boundary whitespace / text == slice / overlaps
    lost = introduced = gap_chars = mismatches = overlaps = 0
    gap_nonws = 0
    crossing = 0
    repeats_adjacent: List[int] = []
    intra_dup_chars = 0
    intra_exact_dups = 0
    for sid, cs in per.items():
        doc = by_doc[sid]
        content = doc["content"]
        cs = sorted(cs, key=lambda c: (c["char_start"], c["char_end"]))
        pos = 0
        for c in cs:
            if content[c["char_start"]:c["char_end"]] != c["text"]:
                mismatches += 1
            if c["char_start"] < pos:
                overlaps += 1
            gap = content[pos:c["char_start"]] if c["char_start"] > pos else ""
            gap_chars += len(gap)
            gap_nonws += len(_ws_free(gap))
            pos = max(pos, c["char_end"])
        tail = content[pos:]
        gap_chars += len(tail)
        gap_nonws += len(_ws_free(tail))
        if _ws_free(content) != _ws_free("".join(c["text"] for c in cs)):
            a, b = Counter(_ws_free(content)), Counter(_ws_free("".join(c["text"] for c in cs)))
            lost += sum((a - b).values())
            introduced += sum((b - a).values())
        for x, y in zip(cs, cs[1:]):
            r = _overlap_repeat(x["text"], y["text"])
            if r >= MIN_ADJACENT_REPEAT:
                repeats_adjacent.append(r)
        intra_dup_chars += sum(c["char_count"] for c in cs) - _union_len([(c["char_start"], c["char_end"]) for c in cs])
        cnt = Counter(c["text"] for c in cs)
        intra_exact_dups += sum(v - 1 for v in cnt.values() if v > 1)
        sec_spans = [(section_span(doc, s), s["section_id"]) for s in doc["sections"]]
        for c in cs:
            touched = {sid2 for (a, b), sid2 in sec_spans if c["char_start"] < b and c["char_end"] > a}
            if len(touched) > 1:
                crossing += 1
    m.update(lost_nonwhitespace_chars=lost, introduced_nonwhitespace_chars=introduced, text_slice_mismatches=mismatches,
             offset_overlaps=overlaps, boundary_whitespace_chars=gap_chars, boundary_nonwhitespace_chars=gap_nonws,
             chunks_crossing_section_boundaries=crossing, adjacent_repeats_ge_min=len(repeats_adjacent),
             max_adjacent_repeat=max(repeats_adjacent) if repeats_adjacent else 0,
             duplicated_chars_within_source=intra_dup_chars, exact_duplicate_chunks_within_source=intra_exact_dups)
    total_chars = sum(c["char_count"] for c in chunks)
    m["total_chunk_chars"] = total_chars
    m["duplicated_chars_within_source_pct"] = round(100.0 * intra_dup_chars / total_chars, 2) if total_chars else 0.0

    # cross-source identical texts (source-inherent boilerplate, NOT chunker-introduced)
    groups: Dict[str, set] = defaultdict(set)
    counts: Counter = Counter()
    for c in chunks:
        groups[c["text"]].add(c["source_id"])
        counts[c["text"]] += 1
    dup_texts = [t for t, s in groups.items() if len(s) > 1]
    m["cross_source_identical_text_groups"] = len(dup_texts)
    m["cross_source_identical_chunks"] = sum(counts[t] for t in dup_texts)
    m["cross_source_identical_chars"] = sum(counts[t] * len(t) for t in dup_texts)
    m["cross_source_identical_chars_pct"] = round(100.0 * m["cross_source_identical_chars"] / total_chars, 1) if total_chars else 0.0
    m["cross_source_identical_chunks_pct"] = round(100.0 * m["cross_source_identical_chunks"] / len(chunks), 1) if chunks else 0.0

    # granularity
    m["chars"] = _summary([c["char_count"] for c in chunks])
    m["words"] = _summary([c["word_count"] for c in chunks])
    m["chunks_per_source"] = _summary([len(v) for v in per.values()])
    m["small_chunks"] = [c["chunk_id"] for c in chunks if c["char_count"] < small_chars]
    m["large_chunks"] = [c["chunk_id"] for c in chunks if c["char_count"] > large_chars]
    m["exceeding_max_chars"] = [c["chunk_id"] for c in chunks if c["exceeds_max_chars"]]
    if max_chars is not None:
        m["over_max_without_flag"] = [c["chunk_id"] for c in chunks if c["char_count"] > max_chars and not c["exceeds_max_chars"]]
    by_key: Dict[str, List[int]] = defaultdict(list)
    for c in chunks:
        by_key[c["section_key"] or "(whole card)"].append(c["char_count"])
    m["by_section_key"] = {k: _summary(v) for k, v in by_key.items()}
    m["small_by_section_key"] = dict(Counter(c["section_key"] or "(whole card)" for c in chunks if c["char_count"] < small_chars))
    m["split_sections"] = sorted({c["section_id"] for c in chunks if c["section_part_count"] > 1})
    m["approx_tokens_max"] = math.ceil(max((c["char_count"] for c in chunks), default=0) / 4)

    # provenance: chunk -> section -> corpus document -> manifest sha256 -> original PDF
    bad: List[str] = []
    pdf_checked = 0
    pdf_sha_cache: Dict[str, Optional[str]] = {}
    for c in chunks:
        d = by_doc.get(c["source_id"])
        if d is None:
            bad.append(f"{c['chunk_id']}: unknown source_id")
            continue
        secs = {s["section_id"]: s for s in d["sections"]}
        if any(sid not in secs for sid in c["section_ids"]) or (c["section_id"] is not None and c["section_id"] not in secs):
            bad.append(f"{c['chunk_id']}: section id not in document")
        if c["section_id"] is not None and c["section_ids"] != [c["section_id"]]:
            bad.append(f"{c['chunk_id']}: section_ids inconsistent")
        for k_chunk, k_doc in (("source_number", "source_number"), ("filename", "filename"), ("title", "title"), ("category", "category"),
                               ("sha256", "sha256"), ("source_status", "status"), ("source_url", "authoritative_source")):
            if c[k_chunk] != d[k_doc]:
                bad.append(f"{c['chunk_id']}: {k_chunk} differs from corpus")
        if d["source_id"] != f"M2C-{d['source_number']:02d}":
            bad.append(f"{c['chunk_id']}: source_id/source_number mismatch")
        if not c["chunk_id"].startswith(c["source_id"] + "-C") or c["page_start"] < 1 or c["page_end"] > d["page_count"]:
            bad.append(f"{c['chunk_id']}: id/page range invalid")
        if d["provenance"]["citation"] not in c["citation"]:
            bad.append(f"{c['chunk_id']}: citation lacks source citation")
        if pdf_dir is not None:
            if c["filename"] not in pdf_sha_cache:
                p = pdf_dir / c["filename"]
                pdf_sha_cache[c["filename"]] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            sha = pdf_sha_cache[c["filename"]]
            if sha != c["sha256"]:
                bad.append(f"{c['chunk_id']}: original PDF {'missing' if sha is None else 'sha256 differs'}")
            else:
                pdf_checked += 1
    m["provenance_failures"] = bad
    m["provenance_resolved"] = len(chunks) - len({b.split(":")[0] for b in bad})
    m["provenance_pdf_hash_checked"] = pdf_checked if pdf_dir is not None else None
    return m


def corpus_structure(docs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Facts about the cards themselves that drive the strategy choice."""
    keys: List[str] = []
    for d in docs:
        for s in d["sections"]:
            if s["key"] not in keys:
                keys.append(s["key"])
    rows = {}
    boiler_chars = 0
    total = sum(len(d["content"]) for d in docs)
    for k in keys:
        secs = [(d, s) for d in docs for s in d["sections"] if s["key"] == k]
        spans = [section_span(d, s) for d, s in secs]
        lens = [b - a for a, b in spans]
        distinct = len({s["text"] for _, s in secs})
        identical_all = distinct == 1 and len(secs) == len(docs)
        if identical_all:
            boiler_chars += sum(lens)
        rows[k] = {"sections": len(secs), "min": min(lens), "median": float(statistics.median(lens)), "max": max(lens),
                   "distinct_texts": distinct, "identical_in_every_card": identical_all}
    doc_lens = [len(d["content"]) for d in docs]
    return {"section_keys": keys, "rows": rows, "total_chars": total, "boilerplate_chars": boiler_chars,
            "boilerplate_pct": round(100.0 * boiler_chars / total, 1) if total else 0.0,
            "doc_chars": _summary(doc_lens), "docs_over_legacy_limit": sum(1 for n in doc_lens if n > LEGACY_CHUNK_LIMIT),
            "approx_tokens_whole_doc_max": math.ceil(max(doc_lens) / 4),
            "distinct_chars_per_doc_mean": round((total - boiler_chars) / len(docs), 1) if docs else 0.0}


# ----------------------------------------------------------------------------- output
def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


DESCRIPTION = {
    "whole_document": "Strategy A: one chunk per source PDF (the full normalised card text).",
    "section_based": "Strategy B: one chunk per section present in source_corpus.json (section heading line + body); sections are not invented or merged.",
    "bounded_sections": "Strategy C: section chunks, split only when a section (with its heading) exceeds max_chars; splits at sentence boundaries, then lines, then words; a token longer than max_chars is never cut.",
}


def strategy_payload(strategy: str, chunks: List[Dict[str, Any]], corpus: Dict[str, Any], corpus_sha: str,
                     max_chars: Optional[int]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": strategy,
        "description": DESCRIPTION[strategy],
        "parameters": {"max_chars": max_chars if strategy == "bounded_sections" else None,
                       "overlap_chars": 0,
                       "boundary_whitespace": "separator whitespace between sections (newline / blank line) is in no chunk; "
                                              "chunk text is an exact slice of the document content, stripped at both ends"},
        "source_corpus": {"path": "data/source_corpus.json", "file_sha256": corpus_sha, "content_fingerprint": corpus["content_fingerprint"],
                          "manifest_sha256": corpus["manifest_sha256"]},
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def _table(head: List[str], rows: List[List[Any]], align: Optional[List[str]] = None) -> str:
    align = align or ["---"] * len(head)
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def _f(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def write_report(path: Path, *, corpus: Dict[str, Any], corpus_sha: str, docs: Sequence[Dict[str, Any]], chunks: Dict[str, List[Dict[str, Any]]],
                 metrics: Dict[str, Dict[str, Any]], structure: Dict[str, Any], sensitivity: List[Dict[str, Any]], max_chars: int,
                 small_chars: int, large_chars: int, test_summary: Optional[str]) -> None:
    L: List[str] = []
    L += ["# Chunk candidate report (Phase 3)", "",
          "Generated by `scripts/build_chunk_candidates.py` (offline, deterministic, no LLM, no embeddings, no vector DB). "
          "It compares three candidate retrieval units using **structural** measurements only; **no strategy has been chosen** and no retrieval was run.", "",
          "## Inputs and parameters", "",
          f"* source corpus: `data/source_corpus.json` (file sha256 `{corpus_sha}`; content fingerprint `{corpus['content_fingerprint'][:16]}`; read only, never modified)",
          f"* documents: **{len(docs)}**   pages: **{sum(d['page_count'] for d in docs)}**",
          f"* strategy C `--max-chars`: **{max_chars}** (configurable; chosen as an experiment value, see *Sensitivity of strategy C*)",
          f"* 'unusually small' = under **{small_chars}** chars; 'unusually large' = over **{large_chars}** chars (both configurable)",
          "* overlap between chunks: 0 characters in every strategy",
          "* chunk ids are `<source_id>-C<nn>` and are unique within one strategy file; the same id in another file is a different span, so read `strategy` together with `chunk_id`",
          "", "## What the cards look like (drives the decision)", ""]
    rows = []
    for k in structure["section_keys"]:
        r = structure["rows"][k]
        rows.append([f"`{k}`", r["sections"], r["min"], _f(r["median"]), r["max"], r["distinct_texts"],
                     "**yes - boilerplate**" if r["identical_in_every_card"] else "no"])
    L += [_table(["Section (heading + body chars)", "Cards", "Min", "Median", "Max", "Distinct texts", "Identical in every card"], rows,
                 ["---", "--:", "--:", "--:", "--:", "--:", "---"]), ""]
    dc = structure["doc_chars"]
    L += [f"* whole card: min {dc['min']}, median {_f(dc['median'])}, max {dc['max']} chars; approx. {structure['approx_tokens_whole_doc_max']} tokens for the longest (chars / 4, an estimate, not a tokenizer count)",
          f"* cards longer than {LEGACY_CHUNK_LIMIT} chars (the limit used by the legacy `scripts/chunk_pages.py`): **{structure['docs_over_legacy_limit']}** of {len(docs)}",
          f"* **boilerplate**: sections whose text is identical in all {len(docs)} cards make up **{structure['boilerplate_chars']} of {structure['total_chars']} characters ({structure['boilerplate_pct']}%)**; "
          f"the card-specific text is about {structure['distinct_chars_per_doc_mean']} characters per card",
          f"* the longest section (with heading) is {max(r['max'] for r in structure['rows'].values())} chars, so no section is long by conventional RAG standards", ""]

    L += ["## Strategy comparison", ""]
    rows = []
    for s in STRATEGIES:
        m = metrics[s]
        rows.append([STRATEGY_LABEL[s], m["chunks"], _f(m["chars"]["mean"]), m["chars"]["min"], m["chars"]["max"],
                     _f(m["words"]["mean"]), m["words"]["max"]])
    L += [_table(["Strategy", "Chunks", "Avg chars", "Min", "Max", "Avg words", "Max words"], rows, ["---", "--:", "--:", "--:", "--:", "--:", "--:"]), "",
          _table(["Strategy", "Median chars", "Chunks/source min", "mean", "max", "Sources covered", "Approx. tokens of largest chunk"],
                 [[STRATEGY_LABEL[s], _f(metrics[s]["chars"]["median"]), metrics[s]["chunks_per_source"]["min"],
                   _f(metrics[s]["chunks_per_source"]["mean"]), metrics[s]["chunks_per_source"]["max"],
                   f"{metrics[s]['sources']}/{len(docs)}", metrics[s]["approx_tokens_max"]] for s in STRATEGIES],
                 ["---", "--:", "--:", "--:", "--:", "--:", "--:"]), "",
          f"Token figures are chars/4 estimates. `all-MiniLM-L6-v2` (the embedding model named in `scripts/rag_core.py`) truncates input at {MINILM_SEQ_LIMIT_TOKENS} word pieces; "
          "URLs and hex identifiers usually cost more word pieces than plain text, so the real count for strategy A is likely at or above that limit. This is **unmeasured** (no tokenizer was run here) and must be checked before embedding.", ""]

    L += ["## Integrity checks", ""]
    def yn(ok: bool) -> str:
        return "PASS" if ok else "**FAIL**"
    rows = []
    for s in STRATEGIES:
        m = metrics[s]
        rows.append([STRATEGY_LABEL[s],
                     yn(not m["sources_missing"] and m["sources"] == len(docs)),
                     yn(m["lost_nonwhitespace_chars"] == 0 and m["introduced_nonwhitespace_chars"] == 0 and m["text_slice_mismatches"] == 0),
                     m["lost_nonwhitespace_chars"], m["introduced_nonwhitespace_chars"], m["boundary_whitespace_chars"],
                     yn(m["chunk_ids_unique"] and m["empty_chunks"] == 0),
                     yn(m["offset_overlaps"] == 0 and m["duplicated_chars_within_source"] == 0),
                     m["chunks_crossing_section_boundaries"],
                     f"{m['provenance_resolved']}/{m['chunks']}"])
    L += [_table(["Strategy", "Coverage", "Completeness", "Lost non-ws chars", "Introduced non-ws chars", "Boundary whitespace chars (documented)",
                  "Unique ids, none empty", "No overlap", "Chunks crossing section boundaries", "Provenance resolved"], rows,
                 ["---", "---", "---", "--:", "--:", "--:", "---", "---", "--:", "--:"]), "",
          "* Completeness: for every source, the chunk texts are exact slices of the normalised content, do not overlap, and the only characters in no chunk are the whitespace separators between sections (and, for A, nothing). "
          "The heading line of each section is included in that section's chunk.",
          "* Strategy A crosses section boundaries by design (one chunk = all 8 sections).", "",
          "### Duplication", ""]
    rows = []
    for s in STRATEGIES:
        m = metrics[s]
        rows.append([STRATEGY_LABEL[s], m["exact_duplicate_chunks_within_source"], m["adjacent_repeats_ge_min"], m["max_adjacent_repeat"],
                     f"{m['duplicated_chars_within_source_pct']}%", m["cross_source_identical_text_groups"], m["cross_source_identical_chunks"],
                     f"{m['cross_source_identical_chunks_pct']}%", f"{m['cross_source_identical_chars_pct']}%"])
    L += [_table(["Strategy", "Exact duplicate chunks inside a source", f"Adjacent repeats >= {MIN_ADJACENT_REPEAT} chars", "Max adjacent repeat",
                  "Chars duplicated inside a source (chunker-introduced)", "Identical-text groups across sources", "Chunks in such groups", "% of chunks", "% of chunk chars"],
                 rows, ["---", "--:", "--:", "--:", "--:", "--:", "--:", "--:", "--:"]), "",
          "The chunker introduces **no** duplication (chunks never overlap). The cross-source figures are duplication **inherited from the source cards**: "
          "`library_use` and `copyright_note` have identical text in every card. Strategy A embeds that text inside every card (see boilerplate share above); "
          "B and C turn it into identical stand-alone chunks. Identical chunks from 29 sources cannot be told apart by similarity, so a generic query would tie across all of them.", "",
          "## Chunks per source", ""]
    rows = []
    for d in docs:
        rows.append([f"{d['source_number']:02d}", d["source_id"], len(d["content"])] +
                    [sum(1 for c in chunks[s] if c["source_id"] == d["source_id"]) for s in STRATEGIES])
    L += [_table(["#", "Source", "Card chars", "A", "B", "C"], rows, ["--:", "---", "--:", "--:", "--:", "--:"]), ""]

    L += ["## Section distribution (chars per chunk, by section)", ""]
    for s in ("section_based", "bounded_sections"):
        L += [f"**{STRATEGY_LABEL[s]}**", ""]
        rows = []
        for k in structure["section_keys"]:
            r = metrics[s]["by_section_key"].get(k)
            if r:
                rows.append([f"`{k}`", r["n"], r["min"], _f(r["median"]), r["max"], metrics[s]["small_by_section_key"].get(k, 0)])
        L += [_table(["Section", "Chunks", "Min", "Median", "Max", f"Chunks < {small_chars} chars"], rows, ["---", "--:", "--:", "--:", "--:", "--:"]), ""]

    L += ["## Unusually small and large chunks", ""]
    for s in STRATEGIES:
        m = metrics[s]
        ks = ", ".join(f"`{k}` x{v}" for k, v in sorted(m["small_by_section_key"].items())) or "none"
        L += [f"* {STRATEGY_LABEL[s]}: **{len(m['small_chunks'])}** chunks under {small_chars} chars ({ks}); "
              f"**{len(m['large_chunks'])}** chunks over {large_chars} chars"
              + (f"; chunks over the configured maximum (unsplittable token): {len(m['exceeding_max_chars'])}" if s == "bounded_sections" else "")]
    bm = metrics["section_based"]
    L += ["", f"In B, the first three sections of every card (`reference_line`, `title`, `category`) are {sum(bm['small_by_section_key'].get(k, 0) for k in ('reference_line', 'title', 'category'))} of {bm['chunks']} chunks "
              f"({round(100.0 * sum(bm['small_by_section_key'].get(k, 0) for k in ('reference_line', 'title', 'category')) / bm['chunks'])}%). "
              "Each is a label, not an answerable statement: by itself it says nothing about what SAP covers.", ""]

    L += ["## Sensitivity of strategy C to `--max-chars`", ""]
    L += [_table(["max_chars", "Chunks", "Sections split", "Chunks over max (unsplittable)", "Largest chunk", "Smallest chunk", "Chunks < small threshold"],
                 [[r["max_chars"], r["chunks"], r["sections_split"], r["over_max"], r["largest"], r["smallest"], r["small"]] for r in sensitivity],
                 ["--:", "--:", "--:", "--:", "--:", "--:", "--:"]), "",
          "Every section is at most "
          f"{max(r['max'] for r in structure['rows'].values())} characters, so any `max_chars` of that size or more makes C identical to B. "
          "Smaller values begin to cut boilerplate and URL sections into fragments that carry less meaning, without creating anything retrievable that B does not already have.", ""]

    L += ["## Provenance validation", "",
          "Each chunk was resolved: chunk -> `section_id` (exists in the document) -> corpus document (source id, number, filename, title, category, status, URL and sha256 all equal) -> "
          "`page_count` range -> original PDF (file present and its sha256 equals the recorded sha256).", ""]
    rows = [[STRATEGY_LABEL[s], metrics[s]["chunks"], f"{metrics[s]['provenance_resolved']}", len(metrics[s]["provenance_failures"]),
             metrics[s]["provenance_pdf_hash_checked"]] for s in STRATEGIES]
    L += [_table(["Strategy", "Chunks", "Resolved without ambiguity", "Failures", "Chunks whose PDF hash was re-checked"], rows, ["---", "--:", "--:", "--:", "--:"]), ""]
    for s in STRATEGIES:
        for b in metrics[s]["provenance_failures"][:10]:
            L.append(f"* {STRATEGY_LABEL[s]}: {b}")
    L += ["Source review state rides on every chunk (`source_status`, `source_url_status`, `has_source_correction`) so the unresolved items stay visible after chunking: "
          "#05 (Guide A vs C correction metadata), #14 (URL casing), #18 (version query / different deliverable), #23 (version query). None was changed, and no SAP page was externally verified.", ""]

    L += ["## Observations for the decision (no strategy chosen here)", ""]
    a, b_, c_ = metrics["whole_document"], metrics["section_based"], metrics["bounded_sections"]
    boiler_keys = [k for k in structure["section_keys"] if structure["rows"][k]["identical_in_every_card"]]
    boiler_chunks = sum(1 for c in chunks["section_based"] if c["section_key"] in boiler_keys)
    c_split = sorted({c["section_key"] for c in chunks["bounded_sections"] if c["section_part_count"] > 1})
    L += [f"1. **Size.** Every card is about {_f(dc['median'])} characters and every section is at most {max(r['max'] for r in structure['rows'].values())}. "
          f"Strategy A's largest chunk is {a['chars']['max']} chars; strategy B's is {b_['chars']['max']}. Splitting (C) only ever cuts a section that is already short: at max_chars={max_chars} it splits only "
          f"{', '.join('`' + k + '`' for k in c_split) or 'nothing'} ({len(c_['split_sections'])} sections, all {'boilerplate' if set(c_split) <= set(boiler_keys) else 'including card-specific text'}).",
          f"2. **Information per chunk.** A card-specific question ('what does Move-In cover?') is answered by `what_it_covers` and `meter_to_cash_relevance` "
          f"(median {_f(structure['rows']['what_it_covers']['median'])} and {_f(structure['rows']['meter_to_cash_relevance']['median'])} chars). "
          "In B/C those become small chunks that do not contain the card title; the title travels only as metadata. A keeps the title, category, both statements and the SAP URL together.",
          f"3. **Boilerplate.** {structure['boilerplate_pct']}% of each card's characters (heading + body of `{'`, `'.join(boiler_keys)}`) are identical in all 29 cards. In A that text sits inside every card; in B/C it becomes "
          f"{boiler_chunks} identical stand-alone chunks ({round(100.0 * boiler_chunks / b_['chunks'], 1)}% of B's chunks) that compete for the top-k slots (`TOP_K = 3` in `scripts/rag_core.py`). "
          f"A further {b_['cross_source_identical_chunks'] - boiler_chunks} B chunks are repeated `category` labels (only {structure['rows']['category']['distinct_texts']} distinct categories across {len(docs)} cards).",
          f"4. **Tiny label chunks.** B and C each contain {len(b_['small_chunks'])} chunks under {small_chars} chars.",
          f"5. **Model window.** A's largest chunk is approx. {a['approx_tokens_max']} tokens by the chars/4 estimate, at the edge of the {MINILM_SEQ_LIMIT_TOKENS}-word-piece limit of the embedding model currently named in the repo; "
          "check with the real tokenizer in the next phase. Text beyond the limit would be the trailing boilerplate, but URL-heavy text can push it earlier.",
          "6. **Traceability and integrity** are equal across all three strategies (see tables): no loss, no chunker-introduced duplication, every chunk resolves to its section, document and PDF.",
          "7. **Not tested here:** actual retrieval quality. Structure cannot show whether A, B or C retrieves better; that requires embeddings and an evaluation set, which are out of scope for this phase.", "",
          "### Options worth reviewing (not generated)", "",
          "* Keep A as the retrieval unit and carry the boilerplate as metadata or cite it from the corpus rather than embedding it 29 times.",
          "* A 'card-specific' chunk (reference line, title, category, what it covers, relevance, SAP source) that omits the two boilerplate sections from the **embedded** text while keeping them in the corpus; the omitted text would remain available through the source offsets.",
          "* Keep B only if per-section retrieval is wanted, with boilerplate and label sections excluded or down-weighted in retrieval.",
          "", "These would be separate, documented decisions for the next phase; none of them changes the normalised source text.", ""]
    L += ["## Test results", "", test_summary or "_Not recorded in this run. Pass `--test-summary \"<pytest result>\"` to record the final test outcome._", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def sensitivity_table(docs: Sequence[Dict[str, Any]], small_chars: int) -> List[Dict[str, Any]]:
    rows = []
    for mc in SENSITIVITY_MAX_CHARS:
        cs = build_strategy("bounded_sections", docs, mc)
        rows.append({"max_chars": mc, "chunks": len(cs), "sections_split": len({c["section_id"] for c in cs if c["section_part_count"] > 1}),
                     "over_max": sum(1 for c in cs if c["exceeds_max_chars"]), "largest": max(c["char_count"] for c in cs),
                     "smallest": min(c["char_count"] for c in cs), "small": sum(1 for c in cs if c["char_count"] < small_chars)})
    return rows


# ----------------------------------------------------------------------------- main
def run(corpus_path: Path, pdf_dir: Optional[Path], out_dir: Path, max_chars: int, small_chars: int, large_chars: int,
        test_summary: Optional[str]) -> Tuple[int, Dict[str, Dict[str, Any]]]:
    corpus, sha = load_corpus(corpus_path)
    docs = [d for d in sorted(corpus["documents"], key=lambda d: d["source_number"])]
    bad_docs = [d["source_id"] for d in docs if d["extraction_status"] != "extracted" or not d["content"].strip()]
    if bad_docs:
        print(f"ERROR: corpus documents not extracted / empty: {bad_docs}", file=sys.stderr)
        return 2, {}
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = {s: build_strategy(s, docs, max_chars) for s in STRATEGIES}
    metrics = {s: analyse(chunks[s], docs, pdf_dir=pdf_dir, small_chars=small_chars, large_chars=large_chars,
                          max_chars=max_chars if s == "bounded_sections" else None) for s in STRATEGIES}
    for s in STRATEGIES:
        (out_dir / f"{s}.json").write_text(_dump(strategy_payload(s, chunks[s], corpus, sha, max_chars)), encoding="utf-8")
    write_report(out_dir / "chunk_candidate_report.md", corpus=corpus, corpus_sha=sha, docs=docs, chunks=chunks, metrics=metrics,
                 structure=corpus_structure(docs), sensitivity=sensitivity_table(docs, small_chars), max_chars=max_chars,
                 small_chars=small_chars, large_chars=large_chars, test_summary=test_summary)
    failed = any(m["sources_missing"] or m["lost_nonwhitespace_chars"] or m["introduced_nonwhitespace_chars"] or m["text_slice_mismatches"]
                 or m["offset_overlaps"] or m["provenance_failures"] or not m["chunk_ids_unique"] or m["empty_chunks"]
                 or m.get("over_max_without_flag") for m in metrics.values())
    return (1 if failed else 0), metrics


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=str(ROOT / "data" / "source_corpus.json"))
    ap.add_argument("--pdf-dir", default=str(ROOT), help="directory holding the original PDFs (provenance hash re-check)")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "chunk_candidates"))
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="strategy C maximum chunk size in characters")
    ap.add_argument("--small-chars", type=int, default=DEFAULT_SMALL_CHARS)
    ap.add_argument("--large-chars", type=int, default=DEFAULT_LARGE_CHARS)
    ap.add_argument("--test-summary", default=None, help="text recorded in the report's 'Test results' section")
    a = ap.parse_args(argv)
    rc, metrics = run(Path(a.corpus), Path(a.pdf_dir), Path(a.out_dir), a.max_chars, a.small_chars, a.large_chars, a.test_summary)
    for s, m in metrics.items():
        print(f"{STRATEGY_LABEL[s]:20s} chunks={m['chunks']:4d} avg={m['chars']['mean']:7.1f} min={m['chars']['min']:4d} max={m['chars']['max']:4d} "
              f"lost={m['lost_nonwhitespace_chars']} introduced={m['introduced_nonwhitespace_chars']} provenance_failures={len(m['provenance_failures'])}")
    print("OK" if rc == 0 else f"FAILED (exit {rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
