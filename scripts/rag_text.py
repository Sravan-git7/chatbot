"""Phase 8 - small deterministic text helpers shared by the lexical gates, the extractive generator and the grounding verifier."""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set

STOPWORDS = frozenset("""a about above after again all also am an and any are as at be because been before being below between both but by can could did do does doing
down during each few for from further had has have having he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on
once only or other our out over own same she should so some such than that the their them then there these they this those through to too under until up very was we
were what when where which while who whom why will with would you your please tell explain describe give need want know sap system using use used""".split())
# "sap", "system", "use" carry no topic information in a corpus that is entirely SAP documentation.

_WORD = re.compile(r"[a-z0-9][a-z0-9_]*")
_CODE = re.compile(r"\b(?=[A-Za-z_]*[0-9_])[A-Za-z0-9_]{3,}\b|\b[A-Z]{2,}[A-Z0-9_]*\b")


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def terms(text: str) -> List[str]:
    return [stem(w) for w in _WORD.findall((text or "").lower().replace("-", " ")) if w not in STOPWORDS and len(w) > 2]


def term_set(text: str) -> Set[str]:
    return set(terms(text))


def coverage(query_terms: Iterable[str], text: str) -> float:
    """Fraction of ``query_terms`` that occur (stemmed) in ``text``. 0.0 for an empty term list."""
    qt = set(query_terms)
    if not qt:
        return 0.0
    return len(qt & term_set(text)) / len(qt)


def code_tokens(text: str) -> Set[str]:
    """Identifiers a language model must not invent: tokens containing digits/underscores or all-caps codes (EL31, FPR1, ISU_AMI_1, IS-U)."""
    return {m.group(0) for m in _CODE.finditer(text or "")}


def split_sentences(text: str) -> List[str]:
    out: List[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“‘\[])", line) if s.strip()]
    return out


_CITED_SENT = re.compile(r'.+?[.!?](?:\s*\[S\d+\])*(?=\s+[A-Z0-9("“‘\-]|\s*$)|.+$')


def split_cited_sentences(text: str) -> List[str]:
    """Like ``split_sentences`` but a trailing ``[S#]`` marker stays with the sentence it follows (the verifier needs that pairing)."""
    out: List[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            out += [m.group(0).strip() for m in _CITED_SENT.finditer(line) if m.group(0).strip()]
    return out
