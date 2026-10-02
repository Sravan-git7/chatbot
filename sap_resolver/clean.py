"""Deterministic, conservative cleaner for text flattened by ``BeautifulSoup.get_text("\\n")``.

What it does (and ONLY this):
  1. unicode NFC, unify line endings, drop zero-width / soft-hyphen characters, NBSP -> space,
     collapse runs of blanks inside a line, drop empty lines;
  2. collapse the page title that SAP repeats at the top (first lines == page title) to ONE line;
  3. drop consecutive exact duplicate lines of >= 30 characters (accidental duplication);
  4. repair *inline-fragment* breaks (a link/bold/xref that the extractor put on its own line):
       - line starts with lower-case or ``, . ; : ) ] }``           -> join to previous line
       - previous line ends with ``(`` / ``[``, has an unclosed ``(``, or ends in a function word
         (the, of, in, under, and ...)                               -> join to next line
     Section labels (Purpose, Use, Features, ...) and the title line are never joined to body text.
It never rewrites, reorders, summarises or removes words. ``check_faithful`` proves that the letters and digits
of the cleaned text equal those of the raw text minus the explicitly counted dropped lines.
Unlike scripts/clean_sap_pages.py it does not glue headings onto the following paragraph.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List

from .schema import sha256_text

SECTION_LABELS = frozenset(x.lower() for x in (
    "Purpose", "Use", "Features", "Activities", "Integration", "Structure", "Definition", "Example", "Examples",
    "Note", "Notes", "Caution", "Tip", "Recommendation", "Prerequisites", "Procedure", "Result", "Results",
    "Constraints", "Restrictions", "Dependencies", "Standard Settings", "Background", "Overview",
    "More Information", "Related Information"))
FUNCTION_WORDS = frozenset(
    "a an the in on of to for and or by with from at as is are be see under via into than that which whose if "
    "when where this these those its their your".split())
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_SPACES = dict.fromkeys(map(ord, "\u00a0\u202f\u2009\u2002\u2003"), " ")
_NO_SPACE_BEFORE = ",.;:)]}"
MIN_DUP_LINE = 30


@dataclass
class CleanResult:
    text: str
    stats: Dict[str, int] = field(default_factory=dict)
    dropped_lines: List[str] = field(default_factory=list)


def _is_label(line: str) -> bool:
    return line.lower() in SECTION_LABELS


def clean_text(raw: str, page_title: str = "") -> CleanResult:
    t = unicodedata.normalize("NFC", raw or "").replace("\r\n", "\n").replace("\r", "\n")
    t = t.translate(_INVISIBLE).translate(_SPACES)
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in t.split("\n")]
    lines = [l for l in lines if l]
    st = Counter()
    dropped: List[str] = []

    # 2. repeated page title at the top -> one line
    title = (page_title or "").strip()
    while len(lines) >= 2 and lines[0] == lines[1] and (not title or lines[0] == title):
        dropped.append(lines.pop(1))
        st["title_duplicates_removed"] += 1

    # 3. consecutive exact duplicates (long lines only)
    out: List[str] = []
    for l in lines:
        if out and l == out[-1] and len(l) >= MIN_DUP_LINE:
            dropped.append(l)
            st["duplicate_lines_removed"] += 1
            continue
        out.append(l)

    # 4. inline-fragment joins
    joined: List[str] = []
    title_line = out[0] if out else ""
    for i, l in enumerate(out):
        if joined and _should_join(joined[-1], l, is_first_line=(len(joined) == 1 and joined[0] == title_line)):
            prev = joined[-1]
            sep = "" if (l[0] in _NO_SPACE_BEFORE or prev.endswith(("(", "["))) else " "
            joined[-1] = prev + sep + l
            st["fragments_joined"] += 1
        else:
            joined.append(l)
    text = "\n".join(joined)
    st["lines_in"] = len([x for x in (raw or "").splitlines() if x.strip()])
    st["lines_out"] = len(joined)
    return CleanResult(text=text, stats=dict(st), dropped_lines=dropped)


def _should_join(prev: str, cur: str, is_first_line: bool) -> bool:
    if is_first_line or _is_label(prev) or _is_label(cur):
        return False
    if cur[0] in _NO_SPACE_BEFORE or cur[0].islower():
        return True
    if prev.endswith(("(", "[")) or prev.count("(") > prev.count(")"):
        return True
    last = re.sub(r"[^\w]+$", "", prev.split(" ")[-1]).lower()
    return last in FUNCTION_WORDS and not prev.endswith((".", "!", "?", ":", ";"))


def _alnum(s: str) -> Counter:
    return Counter(c for c in unicodedata.normalize("NFC", s).translate(_INVISIBLE) if c.isalnum())


def check_faithful(raw: str, result: CleanResult) -> bool:
    """Letters/digits of cleaned text == letters/digits of raw text minus the counted dropped lines."""
    expected = _alnum(raw)
    expected.subtract(_alnum("\n".join(result.dropped_lines)))
    got = _alnum(result.text)
    return +expected == +got and not any(v < 0 for v in expected.values())


def normalize_for_hash(text: str) -> str:
    """Whitespace/case/unicode-insensitive form used for content de-duplication."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").translate(_INVISIBLE)).strip().casefold()


def content_hash(text: str) -> str:
    return sha256_text(normalize_for_hash(text))
