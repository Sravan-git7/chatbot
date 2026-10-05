"""Conversational follow-up resolution (additive; the retrieval pipeline itself is untouched).

A message such as "elaborate", "why?" or "simplify that" carries no topic of its own. Asked on its own it routes
nowhere and the lexical topic gate rejects it (``LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC``, public status
``out_of_scope``) even though the conversation plainly has a subject. This module turns exactly those messages into a
standalone, retrieval-ready query built from the previous turn - *before* the existing pipeline sees anything.

It is query resolution and nothing else: it never answers, never adds a fact, never imports routing/retrieval/
reranking/evidence/citation code, and it leaves every other message byte-identical. The resolved query still has to
pass every existing gate (card routing, OOD coverage, EvidenceGuard, grounding, citation verification); if the
documentation does not support the follow-up, the normal abstention / out-of-scope behaviour is unchanged.

Clause vocabulary is deliberately tiny and was measured on the shipped pipeline. Adding content terms perturbs the
query embedding and the lexical coverage gates enough to flip marginal anchors between "unable_to_verify" and
"out_of_scope", so the clauses below add as few new content terms as possible ("explain", "more", "why", "that",
"then" are stopwords of the lexical gates; "example" and "happen" are question-frame words that never become evidence
focus terms). Measured (status + routed card) over six anchors x clause, compared with the anchor asked verbatim:

    "explain this more"        6/6 identical      "in more detail"        5/6
    "explain why"              6/6 identical      "in simple terms"       4/6
    "give an example"          6/6 same status    "what happens next"     2/6
    "what happens after that"  6/6 identical

Only the immediately preceding turns are used: the most recent previous *question that stands on its own* is the topic
anchor (so a chain of follow-ups still resolves against the real subject), with the previous answer's opening sentence
as the fallback when no usable previous question was sent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_text as T  # noqa: E402  shared stopword/stem helpers of the lexical gates (pure text, no retrieval code)

MAX_QUESTIONS = 4                     # how many previous questions a client may send (most recent first)
MAX_QUESTION_CHARS = 600              # per previous question
MAX_ANSWER_CHARS = 4000               # the previous answer is a fallback anchor only
MAX_MESSAGE_CHARS = 2000              # a follow-up is short by nature; anything longer is not resolved
MAX_RESOLVED_CHARS = 900
MAX_ANSWER_ANCHOR_CHARS = 300

CATEGORIES = ("elaborate", "example", "reason", "continuation", "simplify", "reference")

# Built from stopwords / question-frame words only - see the module docstring for the measurements behind this table.
_CLAUSES: Dict[str, str] = {
    "elaborate": "explain this more",
    "example": "give an example",
    "reason": "explain why",
    "continuation": "what happens after that",
    "simplify": "explain this more",
    "reference": "explain this more",
}

# ---------------------------------------------------------------------------------------------------------------- patterns
# Conservative by construction: every pattern must match the *whole* normalised message. A question that names its own
# subject ("How is billing handled?", "What is the capital of France?") matches nothing and is left alone.
_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # ELABORATION / REFERENCE - "say more about the previous turn", no topic of its own
    (r"(?:please\s+)?(?:can|could|would)\s+you\s+(?:elaborate|expand|explain|continue)(?:\s+(?:on\s+)?(?:that|this|it))?(?:\s+(?:in\s+)?(?:more\s+)?detail)?(?:\s+(?:further|more))?(?:\s+please)?", "elaborate"),
    (r"(?:please\s+)?elaborate(?:\s+(?:on\s+(?:that|this|it)))?(?:\s+(?:in\s+)?(?:more\s+)?detail)?(?:\s+(?:further|more))?(?:\s+please)?", "elaborate"),
    (r"(?:please\s+)?(?:expand|elaborate)(?:\s+on\s+(?:that|this|it))?(?:\s+please)?", "elaborate"),
    (r"(?:please\s+)?explain(?:\s+(?:that|this|it|those|these))?(?:\s+(?:in\s+)?(?:more\s+)?detail)?(?:\s+(?:further|more|again))?(?:\s+please)?", "elaborate"),
    (r"(?:please\s+)?(?:tell|show)\s+me\s+more(?:\s+about\s+(?:that|this|it))?(?:\s+please)?", "elaborate"),
    (r"(?:please\s+)?go\s+(?:in|into)?\s*(?:to\s+)?(?:more\s+)?detail(?:s)?(?:\s+please)?", "elaborate"),
    (r"(?:some\s+|a\s+bit\s+|much\s+)?more\s+detail(?:s)?(?:\s+please)?", "elaborate"),
    (r"(?:in\s+)?more\s+detail(?:\s+please)?", "elaborate"),
    (r"(?:please\s+)?(?:continue|go\s+on|keep\s+going|carry\s+on)(?:\s+please)?", "elaborate"),
    (r"(?:and\s+)?what\s+else(?:\s+about\s+(?:that|this|it))?(?:\s+please)?", "elaborate"),
    (r"what\s+(?:more|other)\s+(?:can\s+you\s+tell\s+me|do\s+you\s+know)(?:\s+about\s+(?:that|this|it))?", "elaborate"),
    # EXAMPLE
    (r"(?:please\s+)?(?:can|could|would)\s+you\s+(?:give|show|provide)(?:\s+me)?(?:\s+an?)?\s+example(?:s)?(?:\s+please)?", "example"),
    (r"(?:please\s+)?(?:give|show|provide)(?:\s+me)?(?:\s+an?)?\s+example(?:s)?(?:\s+please)?", "example"),
    (r"(?:an?\s+)?example(?:s)?(?:\s+please)?", "example"),
    (r"for\s+example(?:\s+please)?", "example"),
    # REASON
    (r"(?:and\s+)?why(?:\s+(?:is\s+|are\s+)?(?:that|this|it|so|though|tho))?(?:\s+please)?", "reason"),
    (r"why\s+(?:does|do|did|would|should|is|are)\s+(?:that|this|it|they|those|these)(?:\s+\w+)?", "reason"),
    (r"(?:what|what's|whats)\s+the\s+reason(?:\s+for\s+(?:that|this|it))?(?:\s+please)?", "reason"),
    (r"(?:how\s+come|how\s+so)(?:\s+please)?", "reason"),
    # CONTINUATION
    (r"(?:and\s+)?(?:then|after\s+that|after\s+this)(?:\s+(?:what|then))?(?:\s+please)?", "continuation"),
    (r"what\s+happens\s+(?:next|after\s+(?:that|this)|then|now)(?:\s+please)?", "continuation"),
    (r"what\s+comes\s+next(?:\s+please)?", "continuation"),
    (r"what\s+about\s+(?:the\s+)?(?:next|following|last|previous|other|second|third|first)\s+(?:step|point|part|stage|item|option)(?:\s+please)?", "continuation"),
    (r"(?:the\s+)?next\s+(?:step|point|part|stage)(?:\s+please)?", "continuation"),
    # SIMPLIFY
    (r"(?:please\s+)?simplify(?:\s+(?:that|this|it))?(?:\s+please)?", "simplify"),
    (r"(?:in\s+)?simple(?:r)?\s+terms(?:\s+please)?", "simplify"),
    (r"put\s+(?:that|this|it)\s+(?:simply|in\s+simple\s+terms)(?:\s+please)?", "simplify"),
    (r"explain\s+(?:(?:that|this|it)\s+)?(?:in\s+)?simple(?:r)?\s+terms(?:\s+please)?", "simplify"),
    (r"(?:please\s+)?explain(?:\s+(?:that|this|it))?\s+simply(?:\s+please)?", "simplify"),
    (r"explain\s+like\s+i(?:\s+am|'m|m)?\s+(?:completely\s+|totally\s+|very\s+|quite\s+)?(?:new|a\s+beginner|a\s+novice)(?:\s+to\s+(?:this|that|it))?(?:\s+please)?", "simplify"),
    (r"explain\s+(?:(?:that|this|it)\s+)?in\s+(?:a\s+)?(?:simpler|simple|plain)\s+(?:way|language|words)(?:\s+please)?", "simplify"),
    (r"(?:please\s+)?(?:say|put)\s+(?:that|this|it)\s+in\s+(?:a\s+)?(?:simpler|simple|plain)\s+(?:way|language|words)(?:\s+please)?", "simplify"),
    # REFERENCE (pronouns; some of these carry their own topic words, see _carries_own_topic)
    (r"(?:and\s+)?what\s+about\s+(?:that|this|it|those|these)(?:\s+then)?", "reference"),
    (r"what\s+does\s+(?:that|this|it)\s+mean(?:\s+by\s+that)?", "reference"),
    (r"what\s+do\s+you\s+mean(?:\s+by\s+(?:that|this))?", "reference"),
    (r"how\s+does\s+(?:that|this|it)\s+work(?:\s+exactly)?", "reference"),
    (r"how\s+does\s+(?:that|this|it)\s+(?:relate|connect|link)\s+to\s+.+", "reference"),
    (r"what\s+is\s+the\s+(?:relationship|connection|link)\s+(?:between|with|to)\s+.+", "reference"),
    (r"how\s+is\s+(?:that|this|it)\s+(?:related|connected|linked)\s+to\s+.+", "reference"),
    (r"what\s+is\s+(?:that|this)(?:\s+then)?", "reference"),
    (r"tell\s+me\s+(?:about\s+)?(?:that|this|it)(?:\s+again)?", "reference"),
    (r"explain\s+(?:that|this|it)\s+again", "reference"),
    (r"how(?:\s+exactly)?", "reference"),
)

_COMPILED: Tuple[Tuple[re.Pattern[str], str], ...] = tuple((re.compile(f"^(?:{p})$"), c) for p, c in _PATTERNS)

# Vocabulary that never counts as "the message brings its own topic" (follow-up wording + question-frame words)
_FOLLOWUP_VOCAB = (
    "elaborate", "expand", "explain", "detail", "further", "again", "continue", "example", "simplify", "simple",
    "term", "next", "happen", "mean", "reason", "relate", "related", "connect", "connected", "connection", "link",
    "linked", "relationship", "difference", "work", "workflow", "step", "point", "part",
    "stage", "item", "option", "else", "then", "more", "other",
)
_FOLLOWUP_TERMS = frozenset(T.stem(w) for w in _FOLLOWUP_VOCAB)


def _norm(message: str) -> str:
    """Lower-case, strip quotes/typographic apostrophes, collapse whitespace, drop leading politeness and trailing punctuation."""
    text = (message or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    text = re.sub(r"^(?:ok(?:ay)?|hey|hi|hello|so|well|and|also|but|please)[,\s]+", "", text, flags=re.IGNORECASE).strip()
    text = text.rstrip(".!?,;: ").strip()
    return text.lower()


def classify(message: str) -> Optional[str]:
    """The follow-up category of ``message``, or ``None`` when it stands on its own (the conservative default)."""
    text = _norm(message)
    if not text or len(text) > MAX_MESSAGE_CHARS:
        return None
    for pattern, category in _COMPILED:
        if pattern.match(text):
            return category
    return None


def _carries_own_topic(message: str, anchor: str) -> bool:
    """True when the follow-up names something the anchor does not (e.g. "... relate to a business partner?")."""
    anchor_terms = T.term_set(anchor)
    own = [t for t in T.term_set(message) if t not in anchor_terms and t not in _FOLLOWUP_TERMS]
    return bool(own)


def _usable_question(raw: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()[:MAX_QUESTION_CHARS]
    return text if len(T.terms(text)) >= 1 else None


def _anchor(context: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], str, int]:
    """Pick the topic anchor: the most recent previous question that is itself not a follow-up.

    Returns ``(text, source, index)`` with ``source`` in ``{"previous_question", "previous_answer"}`` (``index`` is the
    position in the sent list, most recent first; ``-1`` for the answer fallback). ``(None, "", -1)`` when the context
    carries nothing usable - the caller then leaves the message untouched.
    """
    if not isinstance(context, Mapping):
        return None, "", -1
    questions = context.get("questions")
    if isinstance(questions, (list, tuple)):
        for i, raw in enumerate(list(questions)[:MAX_QUESTIONS]):
            text = _usable_question(raw)
            if text and classify(text) is None:
                return text, "previous_question", i
    answer = context.get("answer")
    if isinstance(answer, str) and answer.strip():
        first = (T.split_sentences(answer.strip()) or [""])[0]
        first = re.sub(r"\s+", " ", first).strip()[:MAX_ANSWER_ANCHOR_CHARS]
        if len(T.terms(first)) >= 2:                       # a one-word "sentence" anchors nothing
            return first.rstrip(" .!?;:") + ".", "previous_answer", -1
    return None, "", -1


def resolve(message: Any, context: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Resolve ``message`` against ``context`` into a standalone retrieval query.

    Returns ``None`` when the message stands on its own, when no usable context was sent, or when the previous turns
    are themselves follow-ups with nothing to anchor on - in all of those cases the caller keeps the original message.
    The returned dict is debug-only metadata plus the resolved ``query``; it never contains an answer or a fact.
    """
    category = classify(message)
    if category is None:
        return None
    anchor, source, index = _anchor(context)
    if not anchor:
        return None

    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if _carries_own_topic(text, anchor):
        # the follow-up names its own topic ("... how does it relate to a business partner?"): keep the user's words
        query = f"{anchor} {text}"[:MAX_RESOLVED_CHARS]
        form = "message"
    else:
        query = f"{anchor} {_CLAUSES[category]}"[:MAX_RESOLVED_CHARS]
        form = "clause"
    return {
        "category": category,
        "anchor": anchor,
        "anchor_source": source,
        "anchor_index": index,
        "form": form,
        "query": re.sub(r"\s+", " ", query).strip(),
    }


def debug_view(resolved: Optional[Mapping[str, Any]], original: str) -> Optional[Dict[str, Any]]:
    """The resolution as it appears in the debug block (developer view only; never in the public result)."""
    if not resolved:
        return None
    return {"category": resolved["category"], "anchor_source": resolved["anchor_source"], "anchor": resolved["anchor"],
            "message": re.sub(r"\s+", " ", str(original or "")).strip()[:MAX_QUESTION_CHARS],
            "resolved_query": resolved["query"]}
