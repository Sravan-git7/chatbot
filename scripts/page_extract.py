"""Phase 8B - SAP Help page extraction (HTML body -> structured blocks).

Input is the ``body`` HTML of one SAP Help ``pagecontent`` response (DITA-derived markup: ``div.page.topic`` with ``h1.title``,
``section.section > h2.section_title``, ``p``, ``ul/ol``, ``table``, ``aside.note``, ``div.related-links``). Output is an ordered list
of typed blocks that each carry their heading path, so the chunker can respect document structure instead of slicing a flat string.

Removed as page chrome: ``script``, ``style``, ``nav``, ``header``, ``footer``, ``form``, ``button``, ``iframe``, ``svg``, images (the
navigation-path arrows are replaced by ``>``; other images keep their alt text only when it is not an SAP navigation glyph), and
containers whose class marks navigation / cookie / feedback / footer material.

Kept: title, headings, paragraphs, lists (nested), tables (as ``header: value`` rows), notes/warnings (labelled), code, definition lists,
figure captions and "Related Information" links (as text; no URL is rewritten or followed).

Nothing here touches the network or the filesystem.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup, NavigableString, Tag

KIND_PARAGRAPH = "paragraph"
KIND_LIST = "list"
KIND_TABLE = "table"
KIND_NOTE = "note"
KIND_CODE = "code"
KIND_DEFINITIONS = "definitions"
KIND_CAPTION = "caption"
KIND_RELATED = "related"
BLOCK_KINDS = (KIND_PARAGRAPH, KIND_LIST, KIND_TABLE, KIND_NOTE, KIND_CODE, KIND_DEFINITIONS, KIND_CAPTION, KIND_RELATED)

MIN_TEXT_CHARS = 80
ERROR_TITLE_PATTERNS = (r"^(http )?(error )?(40[0-9]|50[0-9])\b", r"not found", r"access denied", r"forbidden", r"^(an? )?(http )?error( [0-9]{3})?[:!. ]*$", r"^error[: ]+[0-9]{3}\b", r"service unavailable", r"bad gateway",
                        r"too many requests")

_DROP_TAGS = ("script", "style", "nav", "header", "footer", "form", "button", "iframe", "svg", "noscript", "link", "meta", "head")
_DROP_CLASS = re.compile(r"(^|[\s_-])(navigation|navbar|breadcrumbs?|cookie|feedback|footer|toolbar|skip-?link|sidebar|toc)([\s_-]|$)", re.I)
_NAV_GLYPH = re.compile(r"(start|next|end) (of the )?navigation", re.I)
_NOTE_LABELS = {"note": "Note", "warning": "Warning", "caution": "Caution", "important": "Important", "tip": "Tip", "attention": "Attention",
                "restriction": "Restriction", "danger": "Danger", "notice": "Notice", "remember": "Remember", "trouble": "Troubleshooting"}
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _inline_text(node: Tag) -> str:
    """Text of an element with navigation paths rendered as ``A > B > C`` and navigation glyph images dropped."""
    clone = BeautifulSoup(str(node), "html.parser")
    for img in clone.find_all("img"):
        alt = ws(img.get("alt") or "")
        if alt and not _NAV_GLYPH.search(alt) and "navigation" not in alt.lower():
            img.replace_with(NavigableString(f" [image: {alt}] "))
        else:
            img.decompose()
    for cascade in clone.select("span.menucascade"):
        parts = [ws(s.get_text(" ")) for s in cascade.select("span.uicontrol")]
        cascade.replace_with(NavigableString(" " + " > ".join(p for p in parts if p) + " "))
    return ws(clone.get_text(" "))


def _list_lines(node: Tag, depth: int = 0) -> List[str]:
    lines: List[str] = []
    ordered = node.name == "ol"
    n = 0
    for li in node.find_all("li", recursive=False):
        n += 1
        own = BeautifulSoup(str(li), "html.parser")
        for nested in own.find_all(["ul", "ol"]):
            nested.decompose()
        text = _inline_text(own)
        if text:
            lines.append(("  " * depth) + (f"{n}. " if ordered else "- ") + text)
        for nested in li.find_all(["ul", "ol"], recursive=False):
            lines += _list_lines(nested, depth + 1)
        for div in li.find_all("div", recursive=False):                      # lists inside wrapper divs
            for nested in div.find_all(["ul", "ol"], recursive=False):
                lines += _list_lines(nested, depth + 1)
    return lines


def _table_text(table: Tag) -> Tuple[str, str]:
    caption = ws(table.find("caption").get_text(" ")) if table.find("caption") else ""
    header: List[str] = []
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        vals = [_inline_text(c) for c in cells]
        if cells and all(c.name == "th" for c in cells) and not header:
            header = vals
        elif any(vals):
            rows.append(vals)
    lines: List[str] = []
    for r in rows:
        if header and len(header) == len(r):
            lines.append("; ".join(f"{h}: {v}" for h, v in zip(header, r) if v))
        else:
            lines.append(" | ".join(v for v in r if v))
    return caption, "\n".join(lines)


class _Walker:
    def __init__(self) -> None:
        self.blocks: List[Dict[str, Any]] = []
        self.title: Optional[str] = None
        self.stack: List[Tuple[int, str]] = []      # (level, heading text) below the page title
        self.removed = {"chrome_elements": 0}

    def path(self) -> List[str]:
        base = [self.title] if self.title else []
        return base + [h for _lvl, h in self.stack]

    def add(self, kind: str, text: str) -> None:
        text = text.strip()
        if text:
            self.blocks.append({"kind": kind, "text": text, "heading_path": self.path()})

    def heading(self, level: int, text: str) -> None:
        text = ws(text)
        if not text:
            return
        if level == 1 and self.title is None:
            self.title = text
            return
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, text))

    def walk(self, node: Tag) -> None:
        for child in list(node.children):
            if isinstance(child, NavigableString):
                t = ws(str(child))
                if t and not t.startswith("<!"):
                    self.add(KIND_PARAGRAPH, t)
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            classes = " ".join(child.get("class", []))
            if name in _DROP_TAGS or (classes and _DROP_CLASS.search(classes) and "related-links" not in classes):
                self.removed["chrome_elements"] += 1
                continue
            if name in _HEADING_TAGS or "section_title" in classes or "sectiontitle" in classes:
                self.heading(_HEADING_TAGS.get(name, 2), _inline_text(child))
            elif name == "p":
                self.add(KIND_PARAGRAPH, _inline_text(child))
            elif name in ("ul", "ol"):
                self.add(KIND_LIST, "\n".join(_list_lines(child)))
            elif name == "table":
                caption, body = _table_text(child)
                if caption:
                    self.add(KIND_CAPTION, caption)
                self.add(KIND_TABLE, body)
            elif name == "aside":
                kind_cls = next((c for c in child.get("class", []) if c in _NOTE_LABELS), "note")
                label = _NOTE_LABELS[kind_cls]
                title_el = child.find(class_="title")
                if title_el is not None:
                    title_txt = ws(title_el.get_text(" "))
                    title_el.extract()
                    label = title_txt or label
                self.add(KIND_NOTE, f"{label}: {_inline_text(child)}")
            elif name in ("pre", "code") and name == "pre":
                self.add(KIND_CODE, child.get_text("\n").strip("\n"))
            elif name == "dl":
                items = []
                for dt in child.find_all("dt"):
                    dd = dt.find_next_sibling("dd")
                    items.append(f"{_inline_text(dt)}: {_inline_text(dd) if dd else ''}".strip())
                self.add(KIND_DEFINITIONS, "\n".join(items))
            elif "related-links" in classes:
                links = [ws(a.get_text(" ")) for a in child.find_all("a")]
                if links:
                    self.blocks.append({"kind": KIND_RELATED, "text": "Related Information: " + "; ".join(l for l in links if l),
                                        "heading_path": self.path()})
            elif name == "figcaption" or "figcap" in classes:
                self.add(KIND_CAPTION, _inline_text(child))
            elif name == "img":
                alt = ws(child.get("alt") or "")
                if alt and not _NAV_GLYPH.search(alt):
                    self.add(KIND_CAPTION, f"[image: {alt}]")
            elif name == "div" and "title" in child.get("class", []) and child.parent is not None and child.parent.name == "div":
                # a bare DITA title div that is not inside an aside: treat as a label paragraph
                self.add(KIND_PARAGRAPH, _inline_text(child))
            else:
                self.walk(child)


def extract_html(body: str) -> Dict[str, Any]:
    """Return ``{title, blocks, headings, text, stats}`` for one page body. Pure function."""
    soup = BeautifulSoup(body or "", "html.parser")
    html_title = ws(soup.title.get_text(" ")) if soup.title else ""
    root = soup.select_one("div.page.topic") or soup.find(id=re.compile(r"^loio[0-9a-f]{32}", re.I)) or soup.body or soup
    w = _Walker()
    w.walk(root)
    title = w.title or html_title or None
    # first block(s) that merely repeat the title are dropped (the title is metadata)
    blocks = [b for b in w.blocks if not (b["kind"] == KIND_PARAGRAPH and b["text"] == title and len(b["heading_path"]) <= 1)]
    seen: List[str] = []
    for b in blocks:
        for h in b["heading_path"]:
            if h not in seen:
                seen.append(h)
    for i, b in enumerate(blocks):
        b["block_index"] = i
    return {"title": title, "html_title": html_title or None, "blocks": blocks, "headings": seen, "text": flatten(title, blocks),
            "stats": {"blocks": len(blocks), "kinds": {k: sum(1 for b in blocks if b["kind"] == k) for k in BLOCK_KINDS if any(b["kind"] == k for b in blocks)},
                      "chrome_elements_removed": w.removed["chrome_elements"], "headings": len(seen)}}


def flatten(title: Optional[str], blocks: Sequence[Dict[str, Any]]) -> str:
    """Readable flat text: title, then each block, with a heading line whenever the heading path changes."""
    out: List[str] = [title] if title else []
    last: List[str] = [title] if title else []
    for b in blocks:
        hp = b["heading_path"]
        if hp != last:
            common = 0
            while common < min(len(hp), len(last)) and hp[common] == last[common]:
                common += 1
            for lvl in range(max(common, 1 if title else 0), len(hp)):
                out.append(hp[lvl])
            last = hp
        out.append(b["text"])
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------- flat-text (legacy local copies)

_HEADING_LINE = re.compile(r"^[A-Z][A-Za-z0-9/&,()\- ]{1,60}$")


def extract_flat_text(text: str, title: Optional[str]) -> Dict[str, Any]:
    """Blocks from a flat cleaned text (the legacy local copy has no markup). Heading detection is a heuristic and is recorded as such:
    a short line with no sentence punctuation that is followed by a longer line is a heading. Lines are never merged across blank lines."""
    lines = [ws(l) for l in (text or "").split("\n")]
    lines = [l for l in lines if l]
    if lines and title and lines[0] == title:
        lines = lines[1:]
    blocks: List[Dict[str, Any]] = []
    heading: List[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        is_heading = bool(_HEADING_LINE.match(line)) and not line.endswith((".", ":", ",", ";")) and len(line.split()) <= 6 and len(nxt) > len(line) + 20
        if is_heading:
            heading = [line]
        else:
            blocks.append({"kind": KIND_PARAGRAPH, "text": line, "heading_path": ([title] if title else []) + heading})
    for i, b in enumerate(blocks):
        b["block_index"] = i
    return {"title": title, "html_title": None, "blocks": blocks, "headings": sorted({h for b in blocks for h in b["heading_path"][1:]}),
            "text": flatten(title, blocks),
            "stats": {"blocks": len(blocks), "kinds": {KIND_PARAGRAPH: len(blocks)}, "chrome_elements_removed": 0, "headings": len({h for b in blocks for h in b["heading_path"][1:]}),
                      "structure": "flat_text_heuristic"}}


# ---------------------------------------------------------------------------------------------------- validation


def validate_extraction(ex: Dict[str, Any]) -> Dict[str, Any]:
    """Reject empty pages and SAP/HTTP error pages. Returns ``{ok, reasons, text_chars}``; never raises."""
    reasons: List[str] = []
    text = ex.get("text") or ""
    chars = len(text.strip())
    if not ex.get("blocks"):
        reasons.append("NO_CONTENT_BLOCKS")
    if chars < MIN_TEXT_CHARS:
        reasons.append("TEXT_TOO_SHORT")
    title = (ex.get("title") or ex.get("html_title") or "").lower()
    if not title:
        reasons.append("NO_TITLE")
    for pat in ERROR_TITLE_PATTERNS:
        if re.search(pat, title):
            reasons.append("ERROR_PAGE_TITLE")
            break
    return {"ok": not reasons, "reasons": reasons, "text_chars": chars}
