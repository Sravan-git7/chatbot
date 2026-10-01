"""Phase 7A - card -> SAP page join (pure, read-only, local files only).

Question answered: for an M2C card, what SAP page content is *actually present in this repository*?

Evidence used (nothing else):
  * the card's ``source_url`` -> guide id (32 hex) and page id (32 hex), parsed with a strict pattern;
  * the processed page corpus written by the ingestion pipeline: ``data/sap_help/pages/<guide_id>/<page_id>.json``.
    A page counts as local content only if its record has ``status == "OK"``, matching ``guide_id`` AND ``page_id``, and
    non-empty ``text``.

Explicitly NOT used as evidence of local content (a URL is not content):
  * the URL itself;
  * ``captured_responses/`` (raw, unprocessed HTTP captures; not validated page records);
  * the legacy ``chunks.json`` / ``sap_docs`` (it holds one guide and is keyed by a numeric deliverable id; a guide id is
    never inferred from a numeric id here, and no title matching is done).

The module never ingests, fetches, repairs or writes anything, and imports no network library.

Join states (``PageResolution.state``)
  resolved_page : card exists, its URL parses, and a valid local page record exists for that guide + page.
  url_only      : card exists and its URL parses, but no valid local page record exists (``reason`` says why).
  unresolved    : no card, or the card has no usable URL (missing, or not a recognised SAP Help page URL).

The booleans ``card_exists`` / ``url_exists`` / ``local_page_content`` are reported separately so a caller never has to
infer one from another.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "data" / "sap_help" / "pages"

RESOLVED_PAGE = "resolved_page"
URL_ONLY = "url_only"
UNRESOLVED = "unresolved"
STATES = (RESOLVED_PAGE, URL_ONLY, UNRESOLVED)

# Reasons (stable codes)
REASON_CARD_MISSING = "CARD_MISSING"
REASON_NO_SOURCE_URL = "NO_SOURCE_URL"
REASON_URL_NOT_PARSEABLE = "URL_NOT_A_SAP_HELP_PAGE_URL"
REASON_NO_LOCAL_PAGE = "NO_LOCAL_PAGE_RECORD"
REASON_PAGE_NOT_USABLE = "LOCAL_PAGE_RECORD_NOT_USABLE"

# https://help.sap.com/docs/<product>/<guide loio>/<page id>.html[?query][#fragment]; the product segment is not
# interpreted (one card uses a lower-case spelling) and the URL is never rewritten.
_URL_RE = re.compile(r"^https://help\.sap\.com/docs/(?P<product>[^/?#]+)/(?P<guide>[0-9a-fA-F]{32})/(?P<page>[0-9a-fA-F]{32})\.html(?:[?#].*)?$")


class PageIndexError(Exception):
    """The local page corpus is ambiguous or corrupt (raised, never ignored)."""


def parse_source_url(source_url: Any) -> Optional[Tuple[str, str]]:
    """Return ``(guide_id, page_id)`` (lower-case) for a SAP Help page URL, else ``None``. The URL is not modified."""
    if not isinstance(source_url, str):
        return None
    m = _URL_RE.match(source_url.strip())
    if not m:
        return None
    return m.group("guide").lower(), m.group("page").lower()


@dataclass(frozen=True)
class LocalPage:
    guide_id: str
    page_id: str
    doc_id: str
    path: str                 # relative to the pages directory's repository root when possible, else as given
    status: str
    text_chars: int
    topic_ids: Tuple[int, ...]
    page_title: str

    @property
    def usable(self) -> bool:
        return self.status == "OK" and self.text_chars > 0


class PageContentIndex:
    """Read-only index of local processed page records, keyed by (guide_id, page_id)."""

    def __init__(self, pages: Mapping[Tuple[str, str], LocalPage], pages_dir: Optional[Path] = None) -> None:
        self._pages: Dict[Tuple[str, str], LocalPage] = dict(pages)
        self.pages_dir = pages_dir

    def __len__(self) -> int:
        return len(self._pages)

    def get(self, guide_id: str, page_id: str) -> Optional[LocalPage]:
        return self._pages.get((guide_id.lower(), page_id.lower()))

    @classmethod
    def empty(cls) -> "PageContentIndex":
        return cls({}, None)

    @classmethod
    def from_directory(cls, pages_dir: Path = PAGES_DIR) -> "PageContentIndex":
        """Load ``<pages_dir>/<guide_id>/<page_id>.json``. A missing directory is an empty index (no local content)."""
        pages_dir = Path(pages_dir)
        pages: Dict[Tuple[str, str], LocalPage] = {}
        if not pages_dir.is_dir():
            return cls(pages, pages_dir)
        for path in sorted(pages_dir.glob("*/*.json")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise PageIndexError(f"cannot read page record {path}: {e}") from e
            guide, page = str(rec.get("guide_id", "")).lower(), str(rec.get("page_id", "")).lower()
            if not guide or not page:
                raise PageIndexError(f"{path}: page record has no guide_id/page_id")
            if (path.parent.name.lower(), path.stem.lower()) != (guide, page):
                raise PageIndexError(f"{path}: file location does not match its guide_id/page_id ({guide}/{page})")
            key = (guide, page)
            if key in pages:
                raise PageIndexError(f"duplicate page record for {guide}/{page}")
            topic_ids = tuple(int(t) for t in (rec.get("topic_ids") or []))
            pages[key] = LocalPage(
                guide_id=guide, page_id=page, doc_id=str(rec.get("doc_id", f"{guide}/{page}")),
                path=_rel(path), status=str(rec.get("status", "")), text_chars=len(str(rec.get("text") or "").strip()),
                topic_ids=topic_ids, page_title=str(rec.get("page_title", "")))
        return cls(pages, pages_dir)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class PageResolution:
    state: str                              # resolved_page | url_only | unresolved
    card_exists: bool
    url_exists: bool
    local_page_content: bool
    reason: Optional[str]                   # None only when state == resolved_page
    source_id: Optional[str]
    source_url: Optional[str]               # as stored on the card, unmodified
    guide_id: Optional[str]
    page_id: Optional[str]
    doc_id: Optional[str] = None            # local page record id (only when local_page_content)
    content_path: Optional[str] = None      # local page record path (only when local_page_content)
    content_chars: Optional[int] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["warnings"] = list(self.warnings)
        return d


def _card_field(card: Any, name: str) -> Any:
    if isinstance(card, Mapping):
        return card.get(name)
    return getattr(card, name, None)


def resolve_card_page(card: Any, index: PageContentIndex) -> PageResolution:
    """Resolve one card (a ``CardCandidate`` or a mapping with ``source_id`` / ``source_url``) against the local page index.

    Only ``source_url`` is read for the page identity. A legacy ``url`` key is never consulted.
    """
    source_id = _card_field(card, "source_id") if card is not None else None
    if card is None or not source_id:
        return PageResolution(UNRESOLVED, False, False, False, REASON_CARD_MISSING, None, None, None, None)

    source_url = _card_field(card, "source_url")
    if not source_url or not isinstance(source_url, str) or not source_url.strip():
        return PageResolution(UNRESOLVED, True, False, False, REASON_NO_SOURCE_URL, str(source_id), None, None, None)

    ids = parse_source_url(source_url)
    if ids is None:
        # A string exists, but it is not a page URL we can derive a page identity from: not treated as a usable URL.
        return PageResolution(UNRESOLVED, True, False, False, REASON_URL_NOT_PARSEABLE, str(source_id), source_url, None, None)
    guide_id, page_id = ids

    page = index.get(guide_id, page_id)
    if page is None:
        return PageResolution(URL_ONLY, True, True, False, REASON_NO_LOCAL_PAGE, str(source_id), source_url, guide_id, page_id)
    if not page.usable:
        return PageResolution(URL_ONLY, True, True, False, REASON_PAGE_NOT_USABLE, str(source_id), source_url, guide_id, page_id,
                              warnings=(f"local record {page.path} has status {page.status!r} and {page.text_chars} characters of text",))

    warnings = []
    number = _card_field(card, "source_number")
    if isinstance(number, int) and not isinstance(number, bool) and page.topic_ids and number not in page.topic_ids:
        warnings.append(f"local page record lists topic_ids {list(page.topic_ids)}, which do not include card number {number}")
    return PageResolution(RESOLVED_PAGE, True, True, True, None, str(source_id), source_url, guide_id, page_id,
                          doc_id=page.doc_id, content_path=page.path, content_chars=page.text_chars, warnings=tuple(warnings))
