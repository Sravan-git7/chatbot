"""Read the 29 reference-card PDFs and build the topic manifest.

The PDFs are *index cards*, not SAP documentation. From each we extract only:
topic_id, title, category, the authoritative SAP Help URL and bookkeeping about
the PDF itself. The URL is taken from the PDF link annotation (the visible text is
wrapped mid-id and contains literal ``&#8203;`` entities) and cross-checked against
the visible text. The filename is *not* trusted: topic_id comes from the card text
and is cross-checked against the filename prefix.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import events as ev
from .urls import ParsedHelpUrl, UrlParseError, canonical_help_url, parse_help_url

MANIFEST_SCHEMA_VERSION = 1
_TOPIC_RE = re.compile(r"Source Reference\s+(\d+)")
_CATEGORY_RE = re.compile(r"^Category:\s*(.+?)\s*$", re.M)
_FILE_NO_RE = re.compile(r"^(\d+)_")


class CardError(Exception):
    pass


@dataclass
class TopicCard:
    topic_id: int
    title: str
    category: str
    pdf_file: str
    pdf_sha256: str
    covers: str
    relevance: str
    url_as_given: str
    product: str
    guide_id: str
    page_id: str
    url_version: Optional[str]
    canonical_url: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("&#8203;", "")).strip()


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    return _clean(text[i + len(start):j]) if i >= 0 and j >= 0 else ""


def _link_uris(page) -> List[str]:
    uris = []
    for a in page.get("/Annots") or []:
        obj = a.get_object()
        uri = (obj.get("/A") or {}).get("/URI")
        if uri:
            uris.append(str(uri))
    return uris


def read_card(path: Path) -> TopicCard:
    """Parse one card PDF. Raises CardError if a required field is missing."""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise CardError("pypdf is required to read the reference-card PDFs (pip install pypdf)") from e
    path = Path(path)
    try:
        raw = path.read_bytes()
        reader = PdfReader(str(path))
        if len(reader.pages) < 1:
            raise CardError("PDF has no pages")
        page = reader.pages[0]
        text = page.extract_text() or ""
        meta_title = str((reader.metadata or {}).get("/Title") or "").strip()
        uris = _link_uris(page)
    except CardError:
        raise
    except Exception as e:
        raise CardError(f"cannot parse PDF: {type(e).__name__}: {e}") from e

    warnings: List[str] = []
    if len(reader.pages) != 1:
        warnings.append(f"expected 1 page, found {len(reader.pages)}")

    m = _TOPIC_RE.search(text)
    if not m:
        raise CardError("no 'Source Reference <n>' line found")
    topic_id = int(m.group(1))
    fm = _FILE_NO_RE.match(path.name)
    if not fm:
        warnings.append("filename has no numeric prefix")
    elif int(fm.group(1)) != topic_id:
        warnings.append(f"filename prefix {fm.group(1)} != card topic_id {topic_id}")

    after = text[m.end():]
    lines = [l.strip() for l in after.splitlines() if l.strip()]
    title = lines[0] if lines else ""
    if not title:
        raise CardError("no title line after the reference number")
    if meta_title and _clean(meta_title) != _clean(title):
        warnings.append(f"PDF /Title metadata {meta_title!r} != visible title {title!r}")

    cm = _CATEGORY_RE.search(text)
    if not cm:
        raise CardError("no 'Category:' line found")
    category = cm.group(1)

    covers = _between(text, "What it covers", "Meter-to-Cash")
    relevance = _between(text, "relevance", "Authoritative SAP Help source")

    help_uris = [u for u in uris if "help.sap.com" in u]
    if len(help_uris) != 1:
        raise CardError(f"expected exactly 1 help.sap.com link annotation, found {len(help_uris)}")
    # whitespace first, then the entity: line wraps can split '&#8203;' itself
    visible = re.sub(r"\s+", "", _between(text, "Open this topic on SAP Help Portal", "Library use"))
    visible = visible.replace("&#8203;", "")
    if visible != help_uris[0]:
        warnings.append("visible URL text differs from link annotation (annotation used)")
    try:
        parsed = parse_help_url(help_uris[0])
    except UrlParseError as e:
        raise CardError(f"unparseable SAP Help URL: {e}") from e

    return TopicCard(
        topic_id=topic_id, title=_clean(title), category=_clean(category), pdf_file=path.name,
        pdf_sha256=hashlib.sha256(raw).hexdigest(), covers=covers, relevance=relevance,
        url_as_given=parsed.url_as_given, product=parsed.product, guide_id=parsed.guide_id,
        page_id=parsed.page_id, url_version=parsed.version, warnings=warnings)


def _canonical_products(cards: List[TopicCard]) -> Dict[str, str]:
    """case-insensitive product -> most frequent spelling across all cards."""
    by_lower: Dict[str, Counter] = {}
    for c in cards:
        by_lower.setdefault(c.product.lower(), Counter())[c.product] += 1
    return {k: v.most_common(1)[0][0] for k, v in by_lower.items()}


def load_cards(pdf_dir: Path, log: Optional[ev.EventLog] = None) -> List[TopicCard]:
    log = log or ev.EventLog()
    cards: List[TopicCard] = []
    for path in sorted(Path(pdf_dir).glob("[0-9][0-9]_*.pdf")):
        try:
            cards.append(read_card(path))
        except CardError as e:
            log.emit(ev.PAGE_FAILED, kind="card_pdf", pdf_file=path.name, error=str(e))
    seen: Dict[int, str] = {}
    for c in cards:
        if c.topic_id in seen:
            c.warnings.append(f"duplicate topic_id {c.topic_id} (also {seen[c.topic_id]})")
            log.emit(ev.DUPLICATE_PAGE, kind="topic_id", topic_id=c.topic_id,
                     pdf_file=c.pdf_file, also=seen[c.topic_id])
        seen.setdefault(c.topic_id, c.pdf_file)
    products = _canonical_products(cards)
    for c in cards:
        canon = products[c.product.lower()]
        if canon != c.product:
            c.warnings.append(f"product spelling {c.product!r} normalised to {canon!r}")
            c.product = canon
        if c.url_version:
            c.warnings.append(f"URL carries ?version={c.url_version} (kept as url_version; not part of identity)")
        c.canonical_url = canonical_help_url(c.product, c.guide_id, c.page_id)
    cards.sort(key=lambda c: (c.topic_id, c.pdf_file))
    return cards


def build_topic_manifest(pdf_dir: Path, log: Optional[ev.EventLog] = None) -> Dict[str, Any]:
    cards = load_cards(pdf_dir, log)
    guides: Dict[str, Dict[str, Any]] = {}
    for c in cards:
        g = guides.setdefault(c.guide_id, {"guide_id": c.guide_id, "product": c.product, "topic_ids": []})
        g["topic_ids"].append(c.topic_id)
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_from": "root-level reference-card PDFs (link annotation + card text); no network",
        "note": "PDFs are reference cards / link index records, NOT SAP documentation.",
        "topic_count": len(cards),
        "guide_count": len(guides),
        "guides": sorted(guides.values(), key=lambda g: g["topic_ids"][0]),
        "topics": [c.to_dict() for c in cards],
    }
