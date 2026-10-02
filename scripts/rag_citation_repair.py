"""Phase 18 (E2) - deterministic in-page citation repair.

Problem (measured in Phases 16/17A, e.g. P12-006, P12-026, P12-049@17A): a 3B model can produce an
answer whose sentence is grounded on the SUPPLIED context but whose [S#] marker names the WRONG chunk
of that page. The lexical grounding verifier passes (>= 0.6 term support against the wrongly cited
chunk), while the citation-evidence criterion fails (no cited chunk contains the gold evidence).

What this module does - and strictly only this:
  * Rule A (verbatim re-point): an answer sentence whose strict-normalised text occurs VERBATIM in the
    text of exactly ONE other supplied chunk (and not in any cited chunk) has its marker list replaced
    by that chunk's marker.
  * Rule B (support-improving add): otherwise, if some uncited chunk supports the sentence by >= 0.6 of
    its content terms AND beats the currently cited support by >= 0.10, that chunk's marker is ADDED to
    the sentence (compound citation).

Safety invariants (why this cannot regress the safety contract):
  * It never adds, removes or rewords answer content - only the marker groups of sentences change.
  * It never leaves the supplied context: re-pointed / added markers always name a chunk that WAS
    provided to the generator (no new evidence, no cross-page, no phantom markers).
  * Rule B is monotone for the verifier (support and token coverage can only improve), and Rule A is
    gated by a mandatory re-run of ``verify_grounding`` on the repaired text: if the repaired text does
    not pass, the ORIGINAL (already verified) answer is kept. Worst case is the status quo.
  * Lexical, deterministic, no model, no network, no question ids, no gold data.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_text as T  # noqa: E402
from rag_generate import _COMPOUND_MARKER, _MARKER  # noqa: E402

RULE_B_MIN_SUPPORT = 0.6     # same floor as MIN_SENTENCE_SUPPORT: the added chunk must actually support the sentence
RULE_B_IMPROVEMENT = 0.10    # strict improvement margin over the currently cited support


def _strict(t: str) -> str:
    """Lowercase, collapse whitespace, and glue punctuation to the preceding word (page text contains
    'goods receipt .' where answers write 'goods receipt.' - the space before the period must not defeat
    the verbatim check)."""
    t = re.sub(r"\s+", " ", (t or "").lower()).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", t)


def _marker_names(line: str, citation_normalization: bool) -> List[str]:
    if citation_normalization:
        names: List[str] = []
        for g in _COMPOUND_MARKER.findall(line):
            for num in re.findall(r"\d+", g):
                m = f"S{num}"
                if m not in names:
                    names.append(m)
        return names
    return [f"S{m}" for m in _MARKER.findall(line)]


def _strip_markers(line: str) -> str:
    if _COMPOUND_MARKER.search(line):
        return _COMPOUND_MARKER.sub("", line).strip()
    return _MARKER.sub("", line).strip()


def _support(body: str, text: str) -> float:
    bt = set(T.terms(body))
    if not bt:
        return 0.0
    return len(bt & T.term_set(text)) / len(bt)


def _render_markers(markers: Sequence[str]) -> str:
    ms = sorted(markers, key=lambda m: int(m[1:]))
    return "[" + "/".join(ms) + "]"


def repair_citations(answer: str, context: Any, citation_normalization: bool = False) -> Tuple[str, Dict[str, Any]]:
    """Return (repaired_text, log). ``repaired_text == answer`` when nothing is repaired.

    ``log`` = {"changed": bool, "lines": [{"line": str, "rule": "A_verbatim" | "B_support",
    "from": [..], "to": [..], "support": float?}]}.
    """
    items = list(context.items)
    valid = {i.marker: i for i in items}
    if not answer or not valid:
        return answer, {"changed": False, "lines": []}

    out_lines: List[str] = []
    changes: List[Dict[str, Any]] = []

    for line in T.split_cited_sentences(answer or ""):
        marker_names = _marker_names(line, citation_normalization)
        good = [m for m in marker_names if m in valid]
        if not good:
            out_lines.append(line)
            continue
        body = _strip_markers(line)
        if not T.terms(body) and not T.code_tokens(body):
            out_lines.append(line)
            continue

        strict_body = _strict(body)
        cited_text = "\n".join(valid[m].text for m in good)

        # already correctly attributed: the sentence is verbatim in one of the cited chunks
        if any(strict_body and strict_body in _strict(valid[m].text) for m in good):
            out_lines.append(line)
            continue

        # Rule A: verbatim in exactly one OTHER supplied chunk
        other_verbatim = [i for i in items if i.marker not in good and strict_body and strict_body in _strict(i.text)]
        if len(other_verbatim) == 1:
            new_markers = [other_verbatim[0].marker]
            changes.append({"line": line[:120], "rule": "A_verbatim", "from": list(good), "to": new_markers})
            out_lines.append(f"{body} {_render_markers(new_markers)}")
            continue

        # Rule B: strictly better support from one uncited chunk
        sup_cited = _support(body, cited_text)
        best: Optional[Tuple[float, str]] = None
        for i in items:
            if i.marker in good:
                continue
            s = _support(body, i.text)
            if s >= RULE_B_MIN_SUPPORT and s > sup_cited + RULE_B_IMPROVEMENT:
                if best is None or s > best[0]:
                    best = (s, i.marker)
        if best is not None:
            new_markers = good + [best[1]]
            changes.append({"line": line[:120], "rule": "B_support", "from": list(good), "to": new_markers, "support": round(best[0], 3)})
            out_lines.append(f"{body} {_render_markers(new_markers)}")
            continue

        out_lines.append(line)

    if not changes:
        return answer, {"changed": False, "lines": []}
    return "\n".join(out_lines), {"changed": True, "lines": changes}
