"""Shared parser for explicit ``[S#]`` citation markers.

This module is deliberately dependency-free so answer gates, offline evaluators, and tests
can share the same syntax and marker-only-line policy without importing a service or store.
"""
from __future__ import annotations

import re
from typing import List, Tuple

_COMPOUND_MARKER = re.compile(r"\[(S\d+(?:[\s,/\-–]+(?:and\s+)?S?\d+)*)\]")
_SINGLE_MARKER = re.compile(r"\[S(\d+)\]")
_MARKER_LIKE = re.compile(r"\[S[^\]\n]*(?:\]|$)", re.I)
_VALID_MARKER = re.compile(r"^S[1-9]\d*$")


def parse_citation_line(line: str, *, allow_compound: bool = True) -> Tuple[List[str], List[str], str]:
    """Return expanded marker names, malformed marker spellings, and marker-stripped line body.

    ``[S0]`` is syntactically marker-like but invalid; malformed compound references are
    reported as such. The stripped body is shared by all consumers for detecting a citation
    that has no accompanying claim.
    """
    text = str(line or "")
    marker_re = _COMPOUND_MARKER if allow_compound else _SINGLE_MARKER
    markers: List[str] = []
    for match in marker_re.finditer(text):
        payload = match.group(1)
        numbers = re.findall(r"\d+", payload) if allow_compound else [payload]
        markers.extend(f"S{number}" for number in numbers)
    malformed = [match.group(0) for match in _MARKER_LIKE.finditer(text)
                 if marker_re.fullmatch(match.group(0)) is None]
    malformed.extend(f"[{marker}]" for marker in markers if not _VALID_MARKER.fullmatch(marker))
    body = _MARKER_LIKE.sub("", text).strip()
    return markers, malformed, body


def has_claim_body(body: str) -> bool:
    """Whether non-marker text contains at least one alphanumeric/underscore character."""
    return bool(re.search(r"\w", str(body or ""), flags=re.UNICODE))


def is_marker_only_line(line: str, *, allow_compound: bool = True) -> bool:
    """True when a line contains a citation-like marker but no claim body."""
    markers, malformed, body = parse_citation_line(line, allow_compound=allow_compound)
    return bool(markers or malformed) and not has_claim_body(body)


def valid_marker(marker: str) -> bool:
    return isinstance(marker, str) and bool(_VALID_MARKER.fullmatch(marker))
