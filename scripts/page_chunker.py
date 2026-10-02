"""Phase 8C - chunking strategies for page records (pure functions; no model download, no network).

Three strategies are compared by ``evaluate_phase8.py`` on the same pages and the same queries:

* ``A_legacy_1000c``  - the legacy chunker (``scripts/chunk_pages.py``): split the flat text at blank lines / sentence ends, pack greedily
  to 1000 characters. No headings, no overlap, token length not considered. ``legacy_chunk_texts`` reproduces it exactly (a test
  compares it with the committed ``chunks.json``). It is the baseline, not a recommendation.
* ``B_heading_200``   - structure-aware: blocks (paragraph / list / table / note) are grouped by heading path and packed to ~200 model
  tokens; a chunk never crosses a heading unless the section is tiny; long blocks are split at sentence / list-item / table-row
  boundaries; a section that continues into the next chunk repeats one sentence of overlap; the page title and heading path are
  prefixed to the text that is EMBEDDED (``embedding_text``) but are not part of ``text`` (what is cited and shown).
* ``C_heading_128``   - the same algorithm with a smaller target (~128 tokens), to see whether finer chunks retrieve better.

Chunk size is measured in tokens of the embedding model's own tokenizer (``make_token_counter``), because the model truncates silently
at 256 tokens; a chunk whose ``embedding_text`` exceeds the limit is flagged (``exceeds_model_limit``), never hidden.

Chunk fields: chunk_id (``<guide>/<page>/<index:03d>``), guide_id, page_id, source_id(s), source_url (the card's URL, never rewritten),
title, heading_path, section_title, chunk_index, chunk_count, text, embedding_text, content_hash (sha256 of ``text``), token_count,
char_count, block_range, strategy, split (bool), overlap_chars.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

MODEL_MAX_TOKENS = 256
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“‘])")
_REGEX_TOKEN = re.compile(r"\w+|[^\w\s]")
TokenCounter = Callable[[str], int]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


@dataclass(frozen=True)
class ChunkConfig:
    name: str
    strategy: str                       # "legacy" | "heading"
    max_chars: int = 1000               # legacy only
    target_tokens: int = 200            # heading only: soft target for embedding_text
    max_tokens: int = 250               # heading only: hard cap for embedding_text (model limit 256 incl. special tokens)
    min_tokens: int = 24                # heading only: a section chunk smaller than this is merged into its neighbour
    overlap_sentences: int = 1          # heading only: sentences repeated when ONE paragraph/section is split across chunks
    embed_prefix: bool = True           # heading only: title > heading path is prepended to embedding_text

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


STRATEGIES: Dict[str, ChunkConfig] = {
    "A_legacy_1000c": ChunkConfig("A_legacy_1000c", "legacy", embed_prefix=False, overlap_sentences=0),
    "B_heading_200": ChunkConfig("B_heading_200", "heading", target_tokens=200, max_tokens=250, min_tokens=24),
    "C_heading_128": ChunkConfig("C_heading_128", "heading", target_tokens=128, max_tokens=250, min_tokens=24),
}
DEFAULT_STRATEGY = "B_heading_200"       # pre-declared default before evaluation; the evaluation reports whether the data supports it


def make_token_counter(model_dir: Optional[str] = None) -> Tuple[TokenCounter, Dict[str, Any]]:
    """Token counter of the embedding model's tokenizer (includes [CLS]/[SEP], i.e. the real model input length). If the tokenizer file cannot
    be loaded, a deterministic regex counter is used and the fallback is recorded in the returned info."""
    try:
        from tokenizers import Tokenizer
        if model_dir is None:
            import m2c_common
            model_dir, _ = m2c_common.resolve_model()
        tok = Tokenizer.from_file(str(Path(model_dir) / "tokenizer.json"))
        tok.no_truncation()
        tok.no_padding()
        return (lambda t: len(tok.encode(t).ids)), {"tokenizer": "all-MiniLM-L6-v2 WordPiece (tokenizers)", "model_dir": str(model_dir), "exact": True}
    except Exception as e:                                       # noqa: BLE001
        return (lambda t: len(_REGEX_TOKEN.findall(t)) + 2), {"tokenizer": "regex fallback (words+punctuation+2)", "exact": False, "reason": f"{type(e).__name__}: {e}"[:200]}


# ---------------------------------------------------------------------------------------------------- A: legacy


def legacy_chunk_texts(text: str, max_chars: int = 1000) -> List[str]:
    """Exact re-implementation of the packing loop in ``scripts/chunk_pages.py`` (which cannot be imported: it runs on import)."""
    chunks: List[str] = []
    current = ""
    for part in re.split(r"\n\s*\n|(?<=[.!?])\s+", text):
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) <= max_chars:
            current += " " + part
        else:
            if current.strip():
                chunks.append(current.strip())
            current = part
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ---------------------------------------------------------------------------------------------------- B/C: heading-aware


@dataclass
class _Piece:
    text: str
    kind: str                 # sentence | item | row | block | words
    block_index: int
    glue_next: bool = False   # a lead-in ("... following:") must stay with what follows
    tokens: int = 0


def _split_words(text: str, budget: int, count: TokenCounter) -> List[str]:
    out, cur = [], []
    for w in text.split():
        trial = " ".join(cur + [w])
        if cur and count(trial) > budget:
            out.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        out.append(" ".join(cur))
    return out


def _pieces_for_block(block: Mapping[str, Any], budget: int, count: TokenCounter) -> List[_Piece]:
    text = block["text"]
    bi = block["block_index"]
    kind = block["kind"]
    if count(text) <= budget:
        return [_Piece(text, "block", bi, tokens=count(text))]
    if kind in ("list", "table", "definitions", "code"):
        parts, pk = [l for l in text.split("\n") if l.strip()], ("row" if kind == "table" else "item")
    else:
        parts, pk = [s for s in _SENT.split(text) if s.strip()], "sentence"
    out: List[_Piece] = []
    for part in parts:
        if count(part) <= budget:
            out.append(_Piece(part, pk, bi, tokens=count(part)))
        else:
            sents = [s for s in _SENT.split(part) if s.strip()] if pk != "sentence" else [part]
            for s in sents:
                if count(s) <= budget:
                    out.append(_Piece(s, "sentence", bi, tokens=count(s)))
                else:
                    out += [_Piece(w, "words", bi, tokens=count(w)) for w in _split_words(s, budget, count)]
    return out


def _is_label(text: str) -> bool:
    """A short line without sentence punctuation (an inline sub-heading such as ``Meter Reading Orders``)."""
    return len(text.split()) <= 8 and not text.rstrip().endswith((".", "!", "?", ";", ","))


def _header(title: Optional[str], heading_path: Sequence[str]) -> str:
    parts = [p for p in heading_path if p]
    if not parts and title:
        parts = [title]
    return " > ".join(parts)


def _sections(blocks: Sequence[Mapping[str, Any]]) -> List[Tuple[Tuple[str, ...], List[Mapping[str, Any]]]]:
    secs: List[Tuple[Tuple[str, ...], List[Mapping[str, Any]]]] = []
    for b in blocks:
        hp = tuple(b["heading_path"])
        if secs and secs[-1][0] == hp:
            secs[-1][1].append(b)
        else:
            secs.append((hp, [b]))
    return secs


def _chunk_heading(record: Mapping[str, Any], cfg: ChunkConfig, count: TokenCounter) -> List[Dict[str, Any]]:
    title = record.get("title")
    raw: List[Dict[str, Any]] = []
    for hp, blocks in _sections(record["blocks"]):
        header = _header(title, hp)
        prefix_tokens = count(header + "\n") if cfg.embed_prefix and header else 0
        budget_max = max(cfg.max_tokens - prefix_tokens, 40)
        budget_target = max(min(cfg.target_tokens - prefix_tokens, budget_max), 30)
        pieces: List[_Piece] = []
        for i, b in enumerate(blocks):
            ps = _pieces_for_block(b, budget_max, count)
            if b["kind"] == "paragraph" and ps and i + 1 < len(blocks) and (b["text"].rstrip().endswith(":") or _is_label(b["text"])):
                ps[-1].glue_next = True          # lead-in ("... following:") or short label line stays with what follows
            pieces += ps
        # greedy packing to the soft target
        groups: List[List[_Piece]] = []
        cur: List[_Piece] = []
        for p in pieces:
            trial = "\n".join(x.text for x in cur + [p])
            hold = bool(cur) and cur[-1].glue_next and count(trial) <= budget_max          # a lead-in/label may overshoot the soft target
            if cur and count(trial) > budget_target and not hold:
                tail: List[_Piece] = []
                while cur and cur[-1].glue_next and len(cur) > 1:          # keep a lead-in with what follows
                    tail.insert(0, cur.pop())
                groups.append(cur)
                carry = []
                if cfg.overlap_sentences and cur and all(x.kind == "sentence" for x in cur[-cfg.overlap_sentences:]) and p.kind == "sentence":
                    carry = cur[-cfg.overlap_sentences:]
                cur = tail + (carry if not tail else [])
                if cur and count("\n".join(x.text for x in cur + [p])) > budget_max:
                    cur = tail
            cur.append(p)
        if cur:
            groups.append(cur)
        for g in groups:
            raw.append({"hp": list(hp), "header": header, "pieces": g, "prefix_tokens": prefix_tokens, "blocks": sorted({x.block_index for x in g}),
                        "split": len(groups) > 1})
    # tiny chunks are merged into the previous chunk when that stays within the cap (so a heading with one short line is not its own vector)
    merged: List[Dict[str, Any]] = []
    for r in raw:
        body_tokens = count("\n".join(p.text for p in r["pieces"]))
        if merged and body_tokens < cfg.min_tokens:
            prev = merged[-1]
            label = r["hp"][-1] if len(r["hp"]) > 1 and r["hp"] != prev["hp"] else None          # the section's own heading, as written on the page
            add = ([label] if label else []) + [p.text for p in r["pieces"]]
            trial = "\n".join([p.text for p in prev["pieces"]] + add)
            if count((prev["header"] + "\n" if cfg.embed_prefix and prev["header"] else "") + trial) <= cfg.max_tokens:
                extra = ([_Piece(label, "block", r["blocks"][0])] if label else []) + r["pieces"]
                prev["pieces"] = prev["pieces"] + extra
                prev["blocks"] = sorted(set(prev["blocks"]) | set(r["blocks"]))
                prev["merged_headings"] = prev.get("merged_headings", []) + ([label] if label else [])
                continue
        merged.append(r)
    out = []
    for r in merged:
        text = "\n".join(p.text for p in r["pieces"])
        ov = 0
        out.append({"text": text, "heading_path": r["hp"], "header": r["header"], "block_range": [r["blocks"][0], r["blocks"][-1]], "split": r["split"],
                    "overlap_chars": ov, "merged_headings": r.get("merged_headings", [])})
    # overlap bookkeeping: a repeated first sentence relative to the previous chunk of the same heading path
    for i in range(1, len(out)):
        if out[i]["heading_path"] == out[i - 1]["heading_path"]:
            first = out[i]["text"].split("\n")[0]
            if first and first in out[i - 1]["text"]:
                out[i]["overlap_chars"] = len(first)
    return out


# ---------------------------------------------------------------------------------------------------- public API


def chunk_page(record: Mapping[str, Any], cfg: ChunkConfig, count: TokenCounter) -> List[Dict[str, Any]]:
    """Chunks for one page record, deterministic, with the metadata the retriever and the citation layer need."""
    if cfg.strategy == "legacy":
        raw = [{"text": t, "heading_path": [], "header": "", "block_range": None, "split": None, "overlap_chars": 0, "merged_headings": []}
               for t in legacy_chunk_texts(record["text"], cfg.max_chars)]
    elif cfg.strategy == "heading":
        raw = _chunk_heading(record, cfg, count)
    else:
        raise ValueError(f"unknown strategy {cfg.strategy!r}")
    n = len(raw)
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(raw):
        header = r["header"]
        emb = f"{header}\n{r['text']}" if (cfg.embed_prefix and header) else r["text"]
        hp = r["heading_path"]
        out.append({
            "chunk_id": f"{record['guide_id']}/{record['page_id']}/{i:03d}", "guide_id": record["guide_id"], "page_id": record["page_id"],
            "source_ids": ",".join(record.get("source_ids", [])), "source_url": record["source_url"], "title": record["title"],
            "heading_path": hp, "section_title": (hp[-1] if hp else record["title"]), "chunk_index": i, "chunk_count": n,
            "text": r["text"], "embedding_text": emb, "content_hash": sha256_text(r["text"]), "token_count": count(emb), "char_count": len(r["text"]),
            "exceeds_model_limit": count(emb) > MODEL_MAX_TOKENS, "block_range": r["block_range"], "strategy": cfg.name, "split": r["split"],
            "overlap_chars": r["overlap_chars"], "merged_headings": r["merged_headings"],
        })
    return out


def chunk_corpus(records: Sequence[Mapping[str, Any]], cfg: ChunkConfig, count: TokenCounter) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in sorted(records, key=lambda r: r["doc_id"]):
        out += chunk_page(rec, cfg, count)
    return out


def chunk_stats(chunks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Size / structure statistics for one strategy over one corpus."""
    if not chunks:
        return {"chunks": 0}
    toks = sorted(c["token_count"] for c in chunks)
    chars = sorted(c["char_count"] for c in chunks)

    def q(xs: Sequence[int], p: float) -> float:
        k = (len(xs) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(xs) - 1)
        return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)

    pages = {c["page_id"] for c in chunks}
    return {"chunks": len(chunks), "pages": len(pages), "chunks_per_page_mean": round(len(chunks) / len(pages), 2),
            "tokens": {"min": toks[0], "median": q(toks, 0.5), "mean": round(sum(toks) / len(toks), 1), "p90": q(toks, 0.9), "max": toks[-1]},
            "chars": {"min": chars[0], "median": q(chars, 0.5), "mean": round(sum(chars) / len(chars), 1), "max": chars[-1]},
            "over_model_limit": sum(1 for c in chunks if c["exceeds_model_limit"]),
            "tiny_chunks_under_24_tokens": sum(1 for c in chunks if c["token_count"] < 24),
            "split_chunks": sum(1 for c in chunks if c.get("split")), "chunks_with_overlap": sum(1 for c in chunks if c.get("overlap_chars")),
            "total_chunk_chars": sum(chars)}
