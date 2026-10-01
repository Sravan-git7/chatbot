"""Parsing and canonicalisation of SAP Help Portal document URLs.

Identity of a page is ``(guide_id, page_id)``. Everything else in the URL (product
spelling, ``?version=`` query, ``-NN`` alias suffix) is kept as separate metadata
and never used as identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import parse_qsl, urlsplit

HELP_HOST = "help.sap.com"
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_NUMERIC = re.compile(r"^[0-9]+$")
# file name of a TOC/page: 32-hex loio, optional "-<n>" suffix used by SAP when the
# same topic is re-used under another TOC parent, then ".html"
_PAGE_FILE = re.compile(r"^(?P<page_id>[0-9a-fA-F]{32})(?P<alias>-\d+)?\.html$")


class UrlParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedHelpUrl:
    url_as_given: str
    product: str
    guide_id: str
    guide_id_kind: str      # "loio" (32 hex) or "numeric" (legacy deliverable id)
    page_id: str            # 32 hex, lower case, WITHOUT alias suffix
    alias_suffix: str       # "" or "-35"
    query: Dict[str, str]

    @property
    def file_path(self) -> str:
        return f"{self.page_id}{self.alias_suffix}.html"

    @property
    def version(self) -> Optional[str]:
        return self.query.get("version")


def split_page_file(file_path: str):
    """'<hex32>[-NN].html' -> (page_id, alias_suffix). Raises UrlParseError."""
    m = _PAGE_FILE.match(file_path or "")
    if not m:
        raise UrlParseError(f"not a SAP Help page file name: {file_path!r}")
    return m.group("page_id").lower(), m.group("alias") or ""


def parse_help_url(url: str) -> ParsedHelpUrl:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or parts.netloc.lower() != HELP_HOST:
        raise UrlParseError(f"not a {HELP_HOST} URL: {url!r}")
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) != 4 or segs[0] != "docs":
        raise UrlParseError(f"expected /docs/<product>/<guide>/<page>.html, got {parts.path!r}")
    _, product, guide, page_file = segs
    if _HEX32.match(guide):
        kind, guide = "loio", guide.lower()
    elif _NUMERIC.match(guide):
        kind = "numeric"
    else:
        raise UrlParseError(f"guide segment is neither 32-hex nor numeric: {guide!r}")
    page_id, alias = split_page_file(page_file)
    return ParsedHelpUrl(url_as_given=url, product=product, guide_id=guide, guide_id_kind=kind,
                         page_id=page_id, alias_suffix=alias,
                         query=dict(parse_qsl(parts.query)))


def canonical_help_url(product: str, guide_id: str, page_id: str) -> str:
    """Query-less, alias-less, lower-case-id URL. Deterministic for a (product, guide, page)."""
    return f"https://{HELP_HOST}/docs/{product}/{guide_id.lower()}/{page_id.lower()}.html"
