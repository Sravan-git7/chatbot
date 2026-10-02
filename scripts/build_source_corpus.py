#!/usr/bin/env python3
"""Phase 2 - deterministic, offline extraction + mechanical normalisation of the 29 source PDFs.

    python scripts/build_source_corpus.py [--manifest data/source_manifest.json] [--pdf-dir .] [--out-dir data]
                                          [--corrections data/topic_corrections.json] [--test-summary TEXT]

Reads  data/source_manifest.json (the source of record; built by scripts/build_source_manifest.py)
       data/topic_corrections.json (exposed as metadata only)
Writes data/source_corpus.json   data/source_corpus.md   data/source_corpus_validation_report.md

Design rules
* Source-ingestion layer, NOT an AI layer: no LLM, no network, no embeddings, no vector store. PDFs are read-only.
* Only MECHANICAL artefacts are touched (each operation is counted and reported):
    - wrapped lines joined with one space inside a paragraph, repeated blanks/whitespace collapsed, NBSP/zero-width
      characters and ligature code points mapped, the literal ``&#8203;`` zero-width-space entity removed from the PRINTED url
      text and the printed url re-joined ONLY when the result equals the PDF's link annotation recorded in the manifest.
    - words are never merged/split/corrected; a hyphen at a line end is NOT joined (cannot be told from a real compound);
      candidates are counted and preserved.
* Every section keeps ``text_raw`` (exactly as extracted) next to the normalised ``text``; a per-document word-preservation
  check proves no word disappeared.
* URLs come from the manifest untouched (#14 lowercase product, #18/#23 ``?version=``); manifest review flags are copied, and an
  existing entry of data/topic_corrections.json (today: #05 only) is exposed as ``source_correction`` metadata - the content is
  never edited because of it. No other correction is created.
* ``status`` is the manifest status. ``extraction_status`` says whether THIS stage extracted the PDF. ``sap_page_externally_verified``
  is always false here: no SAP page was opened by this pipeline.

Exit code: 0 = all documents extracted and checked, 1 = at least one failed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1

_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"}
_ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u2060\u00ad"
ENTITY_ZWSP = "&#8203;"
_BULLET = re.compile(r"^\s*(?:[\u2022\u25cf\u25aa\u25e6*\-\u2013]|\d{1,3}[.)])\s+")

# section key, printed heading (None = no printed heading), source heading used by parse_card
SECTION_KEYS = [
    ("what_it_covers", "What it covers"),
    ("meter_to_cash_relevance", "Meter-to-Cash relevance"),
    ("authoritative_source", "Authoritative SAP Help source"),
    ("library_use", "Library use"),
    ("copyright_note", "Copyright / distribution note"),
]


def _load_manifest_module():
    """Reuse the phase-1 card parser instead of duplicating it."""
    p = Path(__file__).resolve().parent / "build_source_manifest.py"
    spec = importlib.util.spec_from_file_location("build_source_manifest_p1", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_source_manifest_p1", m)
    spec.loader.exec_module(m)
    return m


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ----------------------------------------------------------------------------- extraction
def extract_pages(path: Path) -> Tuple[List[str], Optional[str]]:
    """Per-page text exactly as pypdf returns it. (pages, error)"""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        return [(p.extract_text() or "") for p in r.pages], None
    except Exception as e:                                       # noqa: BLE001 - reported per document
        return [], f"{type(e).__name__}: {e}"


# ----------------------------------------------------------------------------- normalisation
class Ops(Counter):
    """Counts of every mechanical operation actually performed."""


def mechanical_chars(s: str, ops: Ops) -> str:
    """Code-point level artefacts only."""
    out = []
    for ch in s:
        if ch in _LIGATURES:
            ops["ligature_code_points_mapped"] += 1
            out.append(_LIGATURES[ch])
        elif ch in _ZERO_WIDTH:
            ops["zero_width_characters_removed"] += 1
        elif ch in "\u00a0\u2007\u202f\u2009\u2002\u2003":
            ops["nbsp_like_spaces_mapped_to_space"] += 1
            out.append(" ")
        elif ch == "\t":
            ops["tabs_mapped_to_space"] += 1
            out.append(" ")
        elif ch == "\r":
            ops["carriage_returns_removed"] += 1
        else:
            out.append(ch)
    return "".join(out)


def normalise_lines(lines: List[str], ops: Ops) -> str:
    """Wrapped lines -> paragraphs. Paragraph breaks (blank lines) and bullet-like items are kept as separate lines;
    everything else is joined with a single space. No word is merged, split or corrected."""
    paras: List[List[str]] = [[]]
    for raw in lines:
        s = mechanical_chars(raw, ops)
        if s != s.strip():
            ops["leading_trailing_whitespace_stripped"] += 1
        s2 = re.sub(r" {2,}", " ", s.strip())
        if s2 != s.strip():
            ops["repeated_spaces_collapsed"] += 1
        if not s2:
            if paras[-1]:
                paras.append([])
            else:
                ops["repeated_or_edge_blank_lines_dropped"] += 1
            continue
        if _BULLET.match(s2) and paras[-1]:
            paras.append([])                                   # an item starts its own line
        paras[-1].append(s2)
    paras = [p for p in paras if p]
    out = []
    for p in paras:
        for a, b in zip(p, p[1:]):
            ops["wrapped_lines_joined"] += 1
            if a.endswith("-") and b[:1].islower():
                ops["hyphen_line_end_candidates_preserved_as_is"] += 1
        out.append(" ".join(p))
    if len(paras) > 1:
        ops["paragraph_breaks_kept"] += len(paras) - 1
    return "\n".join(out) if any(_BULLET.match(x) for x in out) else "\n\n".join(out)


def normalise_url_block(lines: List[str], manifest_url: Optional[str], ops: Ops) -> Tuple[str, Dict[str, Any]]:
    """Printed link text. The wrapped printed URL is re-joined and `&#8203;` removed ONLY if the result is exactly the link
    annotation recorded in the manifest; otherwise the printed lines are preserved verbatim."""
    body = [mechanical_chars(l, ops) for l in lines]
    label, rest = "", body
    if body and body[0].strip().lower().startswith("open this topic"):
        label, rest = body[0].strip(), body[1:]
    printed_raw = "\n".join(l.rstrip() for l in rest).strip("\n")
    joined = "".join(l.strip() for l in rest)
    cleaned = joined.replace(ENTITY_ZWSP, "")
    info = {"printed_url_raw": printed_raw, "url_rejoined_and_entities_removed": False, "url_equals_manifest_annotation": None}
    if manifest_url is not None and cleaned == manifest_url:
        ops["printed_url_zwsp_entities_removed"] += joined.count(ENTITY_ZWSP)
        ops["printed_url_wrapped_lines_rejoined"] += max(0, len([l for l in rest if l.strip()]) - 1)
        info.update(url_rejoined_and_entities_removed=True, url_equals_manifest_annotation=True)
        url_text = manifest_url
    else:
        info["url_equals_manifest_annotation"] = False if manifest_url is not None else None
        ops["printed_url_preserved_verbatim_not_equal_to_annotation"] += 1
        url_text = "\n".join(l.strip() for l in rest if l.strip())
    return (label + "\n" + url_text).strip("\n"), info


def _words(s: str) -> List[str]:
    return s.split()


# ----------------------------------------------------------------------------- document build
def page_of_heading(heading: str, pages: List[str], start_page: int) -> Optional[int]:
    """1-based page on which a printed heading line first appears (monotonic scan)."""
    # a heading may itself be wrapped over two printed lines ("Meter-to-Cash" / "relevance"): fall back to its first word
    for cand in (heading, heading.split(" ")[0]):
        for i in range(start_page - 1, len(pages)):
            if any(l.strip() == cand or l.strip().startswith(cand) for l in pages[i].split("\n")):
                return i + 1
    return None


def build_document(m: Dict[str, Any], pdf_dir: Path, corrections: Dict[int, Dict[str, Any]], bsm) -> Tuple[Dict[str, Any], Ops]:
    ops = Ops()
    num = int(m["id"])
    doc: Dict[str, Any] = OrderedDict()
    doc["source_number"] = num
    doc["source_id"] = f"M2C-{m['id']}"
    doc["filename"] = m["filename"]
    doc["title"] = m["title"]
    doc["category"] = m["category"]
    doc["status"] = m["status"]                                   # manifest status (NOT external verification)
    doc["sha256"] = m["pdf_sha256"]
    doc["page_count"] = m["pdf_pages"]
    doc["authoritative_source"] = m["authoritative_source"]       # exact, from the manifest
    doc["source_type"] = m["source_type"]
    doc["review"] = OrderedDict([("manifest_status", m["status"]), ("source_url_status", m["source_url_status"]),
                                 ("source_url_reasons", list(m["source_url_reasons"])), ("review_reasons", list(m["review_reasons"]))])
    corr = corrections.get(num)
    doc["source_correction"] = None if corr is None else OrderedDict([
        ("type", "card_guide_correction"), ("note", corr.get("reason")), ("card_guide_id", corr.get("card_guide_id")),
        ("resolved_guide_id", corr.get("resolved_guide_id")), ("evidence_kinds", [e.get("kind") for e in corr.get("evidence", [])]),
        ("source_file", "data/topic_corrections.json"), ("applied_to_content", False)])
    ext = bsm._external_findings(ROOT).get(num) if corr is None else None
    doc["external_finding"] = None if ext is None else OrderedDict([("note", ext), ("is_correction", False)])
    doc["extraction_status"] = "failed"
    doc["sap_page_externally_verified"] = False
    doc["extraction_error"] = None
    doc["content"] = ""
    doc["sections"] = []
    doc["normalisation"] = OrderedDict()
    path = pdf_dir / m["filename"]
    if not path.is_file():
        doc["extraction_error"] = f"PDF not found: {path}"
        return doc, ops
    data = path.read_bytes()
    if sha256_bytes(data) != m["pdf_sha256"]:
        doc["extraction_error"] = "sha256 of the PDF differs from the manifest"
        return doc, ops
    pages, err = extract_pages(path)
    if err or not any(p.strip() for p in pages):
        doc["extraction_error"] = err or "no extractable text"
        return doc, ops
    if len(pages) != m["pdf_pages"]:
        doc["extraction_error"] = f"page count {len(pages)} differs from the manifest ({m['pdf_pages']})"
        return doc, ops
    full = "\n".join(pages)
    card = bsm.parse_card(full)
    if card["issues"] or not card["title"] or not card["category"]:
        doc["extraction_error"] = "card layout not recognised: " + "; ".join(card["issues"] or ["title/category missing"])
        return doc, ops
    if card["title"] != m["title"] or card["category"] != m["category"]:
        doc["extraction_error"] = "title/category in the PDF differ from the manifest"
        return doc, ops

    # ---- build normalised sections in source order
    ref_line = next(l.strip() for l in full.split("\n") if bsm.HDR_RE.match(l))
    parts: List[Tuple[str, Optional[str], str, str, Dict[str, Any]]] = []   # key, heading, text, raw, extra
    title_raw = card["title"]
    parts.append(("reference_line", None, re.sub(r"\s+", " ", ref_line), ref_line, {}))
    parts.append(("title", None, normalise_lines([title_raw], ops), title_raw, {}))
    parts.append(("category", "Category", "Category: " + normalise_lines([card["category"]], ops), "Category: " + card["category"], {}))
    for key, heading in SECTION_KEYS:
        lines = card["sections"][heading]
        raw = "\n".join(l.rstrip() for l in lines).strip("\n")
        if key == "authoritative_source":
            text, extra = normalise_url_block(lines, m["authoritative_source"], ops)
        else:
            text, extra = normalise_lines(lines, ops), {}
        parts.append((key, heading, text, raw, extra))
        # word-preservation check (URL block is checked by equality with the annotation instead)
        if key != "authoritative_source" and _words(mechanical_chars(" ".join(lines), Ops())) != _words(text):
            doc["extraction_error"] = f"word-preservation check failed in section {key}"
            return doc, ops
    # ---- compose content exactly in source order: ref line, title, category, then heading + body per section
    content, sections, pos, page_cursor = "", [], 0, 1
    for i, (key, heading, text, raw, extra) in enumerate(parts):
        if heading and key != "category":
            block_head = heading + "\n"
        else:
            block_head = ""
        sep = "" if not content else "\n\n" if key in {k for k, _ in SECTION_KEYS} else "\n"
        content += sep
        content += block_head
        start = len(content)
        content += text
        end = len(content)
        pg = page_of_heading(heading or (raw.split("\n")[0] if raw else ""), pages, page_cursor) if (heading or key in ("reference_line",)) else None
        if key == "title":
            pg = sections[-1]["page_start"] if sections else 1
        if pg is None and key != "reference_line":
            pg = page_cursor
        if pg:
            page_cursor = pg
        sections.append(OrderedDict([
            ("section_id", f"{doc['source_id']}#{key}"), ("order", i), ("key", key), ("heading", heading if key != "category" else None),
            ("page_start", pg), ("page_end", pg), ("char_start", start), ("char_end", end),
            ("text", text), ("text_raw", raw), ("char_count", len(text)), ("word_count", len(_words(text)))] +
            ([("printed_url", extra)] if extra else [])))
    if any(s["page_start"] is None for s in sections):
        doc["extraction_error"] = "could not assign a page to a section"
        return doc, ops
    for s in sections:                                          # offsets must address the section text inside content
        assert content[s["char_start"]:s["char_end"]] == s["text"], s["section_id"]
    doc["content"] = content
    doc["sections"] = sections
    doc["provenance"] = OrderedDict([
        ("source_id", doc["source_id"]), ("source_number", num), ("filename", m["filename"]), ("sha256", m["pdf_sha256"]),
        ("title", m["title"]), ("category", m["category"]), ("status", m["status"]), ("authoritative_source", m["authoritative_source"]),
        ("citation", f"[{m['id']}] {m['title']} ({m['filename']}, sha256:{m['pdf_sha256'][:12]})")])
    doc["stats"] = OrderedDict([("chars", len(content)), ("words", len(_words(content))), ("sections", len(sections)),
                                ("raw_chars_extracted", sum(len(p) for p in pages))])
    doc["extraction_status"] = "extracted"
    doc["normalisation"] = OrderedDict(sorted(ops.items()))
    return doc, ops


# ----------------------------------------------------------------------------- outputs
def load_corrections(path: Path) -> Dict[int, Dict[str, Any]]:
    if not path.is_file():
        return {}
    d = json.loads(path.read_text(encoding="utf-8-sig"))
    return {int(c["topic_id"]): c for c in d.get("corrections", [])}


def build(manifest_path: Path, pdf_dir: Path, corrections_path: Path) -> Dict[str, Any]:
    bsm = _load_manifest_module()
    mbytes = manifest_path.read_bytes()
    manifest = json.loads(mbytes.decode("utf-8-sig"))["documents"]
    corrections = load_corrections(corrections_path)
    docs, total_ops = [], Ops()
    for m in sorted(manifest, key=lambda x: (int(x["id"]), x["filename"])):
        d, ops = build_document(m, pdf_dir, corrections, bsm)
        docs.append(d)
        total_ops.update(ops)
    ok = [d for d in docs if d["extraction_status"] == "extracted"]
    corpus = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("description", "Normalised (mechanical artefacts only) text of the 29 SAP Utilities M2C source-reference PDFs. Source of record: data/source_manifest.json."),
        ("manifest_sha256", sha256_bytes(mbytes)),
        ("corrections_sha256", sha256_bytes(corrections_path.read_bytes()) if corrections_path.is_file() else None),
        ("document_count", len(docs)),
        ("extracted_count", len(ok)),
        ("failed_count", len(docs) - len(ok)),
        ("sap_pages_externally_verified", 0),
        ("normalisation_operations", OrderedDict(sorted(total_ops.items()))),
        ("content_fingerprint", sha256_bytes("\n".join(f"{d['source_id']}:{d['sha256']}:{sha256_bytes(d['content'].encode('utf-8'))}" for d in docs).encode("utf-8"))),
        ("documents", docs)])
    return corpus


def write_markdown(path: Path, corpus: Dict[str, Any]) -> None:
    L = ["# Source corpus (normalised) - SAP Utilities Meter-to-Cash references 01-29", "",
         "Generated by `scripts/build_source_corpus.py` from `data/source_manifest.json` and the PDFs; offline, deterministic. "
         "Only mechanical extraction artefacts were normalised (see `data/source_corpus_validation_report.md`). "
         "`status` is the manifest status; it does not mean the SAP page was externally verified.", "",
         f"* documents: **{corpus['document_count']}**   extracted: **{corpus['extracted_count']}**   failed: **{corpus['failed_count']}**   "
         f"manifest sha256 `{corpus['manifest_sha256'][:16]}`   content fingerprint `{corpus['content_fingerprint'][:16]}`", ""]
    for d in corpus["documents"]:
        L += [f"## {d['source_number']:02d} - {d['title']}", "",
              f"* file: `{d['filename']}`   pages: {d['page_count']}   sha256: `{d['sha256']}`",
              f"* category: {d['category']}   manifest status: **{d['status']}**   extraction: **{d['extraction_status']}**   SAP page externally verified: **no**",
              f"* source URL (manifest, unchanged): `{d['authoritative_source']}` ({d['review']['source_url_status']})"]
        if d["review"]["review_reasons"]:
            L.append("* review flags: " + "; ".join(d["review"]["review_reasons"]))
        if d["source_correction"]:
            L.append(f"* source correction (metadata only, content unchanged): card guide `{d['source_correction']['card_guide_id']}` -> "
                     f"`{d['source_correction']['resolved_guide_id']}`; see `data/topic_corrections.json`")
        if d["external_finding"]:
            L.append(f"* external finding (not a correction): {d['external_finding']['note']}")
        if d["extraction_error"]:
            L.append(f"* **EXTRACTION ERROR:** {d['extraction_error']}")
        L += ["", "~~~~text", d["content"], "~~~~", ""]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_report(path: Path, corpus: Dict[str, Any], test_summary: Optional[str]) -> None:
    docs = corpus["documents"]
    ok = [d for d in docs if d["extraction_status"] == "extracted"]
    empty = [d for d in docs if not d["content"].strip()]
    pages = sum(d["page_count"] for d in docs)
    chars = sum(d.get("stats", {}).get("chars", 0) for d in docs)
    words = sum(d.get("stats", {}).get("words", 0) for d in docs)
    ver = [d for d in docs if d["status"] == "verified"]
    rev = [d for d in docs if d["status"] != "verified"]
    L = ["# Source corpus validation report (Phase 2)", "",
         "Generated by `scripts/build_source_corpus.py` (offline, deterministic, no LLM, no network).", "",
         "## Three different things - do not conflate", "",
         "| Term | Meaning here | Count |", "|---|---|--:|",
         f"| `verified` (manifest `status`) | phase-1: PDF extracted, fields complete, number/filename/title consistent, URL without review flag | {len(ver)} |",
         f"| extracted successfully | THIS stage read the PDF, matched sha256/pages/title/category to the manifest and passed the word-preservation check | {len(ok)} |",
         "| SAP page externally verified | an SAP Help page was actually opened and checked. **No network access was used; none were.** | 0 |", "",
         "## Totals", "",
         f"* total documents: **{len(docs)}**   extracted: **{len(ok)}**   failed: **{len(docs) - len(ok)}**   empty content: **{len(empty)}**",
         f"* total pages: **{pages}**   extracted (normalised) characters: **{chars}**   words: **{words}**",
         f"* manifest sha256: `{corpus['manifest_sha256']}`", f"* content fingerprint: `{corpus['content_fingerprint']}`", "",
         "## Normalisation operations performed (all documents)", ""]
    ops = corpus["normalisation_operations"]
    L += ["| Operation | Count |", "|---|--:|"] + [f"| `{k}` | {v} |" for k, v in ops.items()]
    if not ops:
        L.append("| (none) | 0 |")
    L += ["", "Not done on purpose: no paraphrase/summary/correction, no word merging or splitting, no hyphen-break joining (candidates are counted "
          "above and preserved), no URL changes, no document merging. `text_raw` of every section keeps the text exactly as extracted.", "",
          "## Per-document status", "",
          "| # | File | Pages | Chars | Words | Manifest status | Extraction | URL status | Externally verified |", "|--:|---|--:|--:|--:|---|---|---|---|"]
    for d in docs:
        L.append(f"| {d['source_number']:02d} | `{d['filename']}` | {d['page_count']} | {d.get('stats', {}).get('chars', 0)} | {d.get('stats', {}).get('words', 0)} | "
                 f"{d['status']} | {d['extraction_status']}{(' - ' + d['extraction_error']) if d['extraction_error'] else ''} | {d['review']['source_url_status']} | no |")
    L += ["", "## Review items (preserved, NOT resolved)", ""]
    shown = False
    for d in docs:
        bits = []
        if d["review"]["review_reasons"]:
            bits.append("manifest review: " + "; ".join(d["review"]["review_reasons"]))
        if d["source_correction"]:
            c = d["source_correction"]
            bits.append(f"source_correction (metadata only): card guide `{c['card_guide_id']}` -> `{c['resolved_guide_id']}`")
        if d["external_finding"]:
            bits.append("external finding (not a correction): " + d["external_finding"]["note"])
        if bits:
            shown = True
            L.append(f"* **{d['source_number']:02d}** `{d['filename']}`")
            L += [f"  * {b}" for b in bits]
            L.append(f"  * source of record kept as: `{d['authoritative_source']}`")
    if not shown:
        L.append("none")
    L += ["", "## Chunking readiness", "",
          "Each document carries `provenance` (source id/number, filename, sha256, title, category, status, source URL, citation) and each section "
          "carries `section_id`, `page_start`/`page_end`, and `char_start`/`char_end` offsets into `content`, so any future chunk can be traced to its "
          "original PDF, page and section without ambiguity.", "", "## Test results", ""]
    L.append(test_summary if test_summary else "Not recorded by this run. Run `python -m pytest tests -q` (tests: `tests/test_source_corpus.py`, plus all earlier suites).")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(ROOT / "data" / "source_manifest.json"))
    ap.add_argument("--pdf-dir", default=str(ROOT))
    ap.add_argument("--corrections", default=str(ROOT / "data" / "topic_corrections.json"))
    ap.add_argument("--out-dir", default=str(ROOT / "data"))
    ap.add_argument("--test-summary", default=None, help="text copied verbatim into the report's 'Test results' section")
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    corpus = build(Path(a.manifest), Path(a.pdf_dir), Path(a.corrections))
    (out / "source_corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(out / "source_corpus.md", corpus)
    write_report(out / "source_corpus_validation_report.md", corpus, a.test_summary)
    docs = corpus["documents"]
    chars = sum(d.get("stats", {}).get("chars", 0) for d in docs)
    words = sum(d.get("stats", {}).get("words", 0) for d in docs)
    print(f"documents: {corpus['document_count']}   extracted: {corpus['extracted_count']}   failed: {corpus['failed_count']}   "
          f"empty: {sum(1 for d in docs if not d['content'].strip())}")
    print(f"pages: {sum(d['page_count'] for d in docs)}   chars: {chars}   words: {words}   manifest status verified: "
          f"{sum(d['status'] == 'verified' for d in docs)}   SAP pages externally verified: 0")
    print("normalisation ops:", dict(corpus["normalisation_operations"]))
    for d in docs:
        if d["extraction_error"]:
            print(f"FAILED {d['filename']}: {d['extraction_error']}")
    print(f"wrote {out / 'source_corpus.json'}, source_corpus.md, source_corpus_validation_report.md")
    return 0 if corpus["failed_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
