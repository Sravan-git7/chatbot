#!/usr/bin/env python3
"""Phase 7G - the mode boundary between the legacy chatbot and the M2C card-routing layer.

This is a boundary, not a RAG implementation. It offers exactly two modes of the Phase 6 specification (section 5, 7C/7G):

``legacy`` (default)
    Runs the existing chatbot unchanged: it calls ``rag_chat.main()`` with no arguments. Nothing else happens.

``route_only``
    query -> M2C card router (dense, one vector per card, ``min_cosine = None``) -> page identity -> citation metadata.
    No LLM is called, no answer is generated, no SAP page is fetched or retrieved, no page text is used and the legacy
    pipeline is not imported. The output says which topic card ranked first and what is known about its page. A card is a
    topic pointer, not SAP Help content; ``used_as_answer_text`` is always false and a card URL is shown byte-identical.

The specification's other two modes, ``shadow`` and ``routed``, answer with an LLM over page chunks. There is no page corpus
and no answer generation yet, so they are specified but NOT implemented: asking for them is an explicit error, never a
silent fallback to another mode.

Rank is not confidence. Phase 7F found that in-domain and out-of-domain rank-1 scores overlap (AUROC 0.87), so no threshold is
applied and a far-away card is still returned. ``route_only`` therefore reports the rank-1 and rank-2 cosine similarity and
distance (kept as separate numbers) and says that the match is a rank, not a confidence.

    python scripts/rag_modes.py                                   # legacy (same as python scripts/rag_chat.py)
    python scripts/rag_modes.py --mode legacy
    python scripts/rag_modes.py --mode route_only --question "How are dunning notices created?"
    python scripts/rag_modes.py --mode route_only --question "..." --json
    python scripts/rag_modes.py --mode route_only                 # interactive, route_only only

``rag_chat.py`` itself is untouched. To make ``rag_chat.py --mode`` the entry point later, call ``rag_modes.main`` from it.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_citations as cit  # noqa: E402
import m2c_common as C  # noqa: E402
import m2c_page_identity as pid  # noqa: E402
import m2c_router as rt  # noqa: E402
from m2c_orchestrator import route_to_page  # noqa: E402

MODE_LEGACY = "legacy"
MODE_ROUTE_ONLY = "route_only"
IMPLEMENTED_MODES = (MODE_LEGACY, MODE_ROUTE_ONLY)
SPECIFIED_NOT_IMPLEMENTED = ("shadow", "routed")
DEFAULT_MODE = MODE_LEGACY
DEFAULT_TOP_K = 5
MIN_COSINE: Optional[float] = None            # Phase 7F: no threshold is justified; this module never applies one
EXIT_WORDS = {"exit", "quit"}

STATUS_ROUTER_UNAVAILABLE = "router_unavailable"

RANK_NOT_CONFIDENCE = ("Rank, not confidence: no similarity threshold is applied (Phase 7F found no justified threshold), so the "
                       "closest card is returned even for a question the cards do not cover.")


class ModeError(ValueError):
    """An unknown, unimplemented or misused mode. The message says what to do instead."""


def parse_mode(value: Any) -> str:
    """Validate a mode name. Exact, case-sensitive; no aliases and no fallback."""
    if value in IMPLEMENTED_MODES:
        return value
    if value in SPECIFIED_NOT_IMPLEMENTED:
        raise ModeError(f"mode {value!r} is specified (data/phase6_next_phase_spec.md) but not implemented: it needs an LLM answer over SAP page "
                        f"chunks, and there is no page corpus or answer pipeline yet. Use one of: {', '.join(IMPLEMENTED_MODES)}.")
    raise ModeError(f"unknown mode {value!r}. Valid modes: {', '.join(IMPLEMENTED_MODES)} (default: {DEFAULT_MODE}).")


# ------------------------------------------------------------------------------------------------------ route_only


@dataclass(frozen=True)
class RouteOnlyResult:
    question: str
    status: str                       # identity status of the selected card, no_card_candidate, or router_unavailable
    message: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.payload)


def _candidate_rows(candidates: Sequence[Any]) -> List[Dict[str, Any]]:
    return [{"rank": c.rank, "source_id": c.source_id, "title": c.title,
             "cosine_similarity": round(1.0 - c.distance, 6), "cosine_distance": round(c.distance, 6)} for c in candidates]


def describe(card_entry: Dict[str, Any]) -> str:
    """The one-sentence statement. It names the card and its URL as stored; it never presents card text as SAP content."""
    ident = card_entry["identity"]
    where = f"(source: {card_entry['url']})" if card_entry["url"] else f"(no URL: {card_entry['url_flag']})"
    s = f"Closest topic card: {card_entry['title']} {where}."
    if ident["local_page_available"]:
        s += " A local page record exists for it, but route_only mode does not retrieve or use page text."
    else:
        s += " The page content is not available locally."
    if ident["status"] == pid.CONFLICTING_IDENTITY:
        s += " The card's page identity is conflicting: no effective page is chosen."
    if card_entry["review_flag"]:
        s += " The card is flagged for review."
    return s


def route_only(question: str, backend: Any, ctx: Any = None, top_k: int = DEFAULT_TOP_K) -> RouteOnlyResult:
    """Route one question. Pure apart from what ``backend`` reads; makes no LLM call and no network request."""
    ctx = ctx or pid.IdentityContext.from_root(C.ROOT)
    outcome = route_to_page(question, backend, ctx.page_index, top_k=top_k)       # default selector: rank 1, no threshold
    citations = cit.cite_outcome(outcome, ctx)
    base: Dict[str, Any] = {
        "mode": MODE_ROUTE_ONLY, "question": question, "min_cosine": MIN_COSINE, "rank_is_not_confidence": RANK_NOT_CONFIDENCE,
        "answer_generated": False, "llm_called": False, "page_text_used": False, "network_used": False,
        "candidates": _candidate_rows(outcome.candidates),
        "fallback_reason": outcome.fallback_reason, "citations": citations.to_dict(),
    }
    if outcome.selected_card is None:
        base.update({"status": pid.NO_CARD_CANDIDATE, "selected": None})
        msg = f"No topic card was selected ({outcome.fallback_reason}). No answer is generated in route_only mode."
        base["message"] = msg
        return RouteOnlyResult(question, pid.NO_CARD_CANDIDATE, msg, base)
    entry = citations.sources[0]
    assert entry["origin"] == cit.ORIGIN_CARD_ROUTE and entry["used_as_answer_text"] is False
    status = entry["identity"]["status"]
    msg = describe(entry)
    base.update({"status": status, "message": msg, "selected": {
        "source_id": entry["source_id"], "title": entry["title"], "url": entry["url"], "url_flag": entry["url_flag"], "citation": entry["citation"],
        "review_flag": entry["review_flag"], "review_reasons": entry["review_reasons"], "identity_status": status,
        "page_content_available": outcome.page_content_available, "join_state": outcome.state,
        "origin": entry["origin"], "used_as_answer_text": False}})
    return RouteOnlyResult(question, status, msg, base)


def render_text(res: RouteOnlyResult) -> str:
    p = res.payload
    lines = ["", "Routing result (route_only: topic identification only, no answer generated):", res.message, ""]
    if p["candidates"]:
        lines.append("Closest cards (cosine similarity and distance are separate numbers; distance = 1 - similarity):")
        for c in p["candidates"]:
            lines.append(f"{c['rank']}. {c['title']} ({c['source_id']}) | similarity={c['cosine_similarity']:.4f} | distance={c['cosine_distance']:.4f}")
        lines.append("")
    lines.append(RANK_NOT_CONFIDENCE)
    cs = cit.CitationSet(p["citations"]["query"], p["citations"]["route_state"], p["citations"]["label"], p["citations"]["sources"],
                         p["citations"]["fallback_reason"], p["citations"]["notes"])
    # 7D's label says "provided to the model"; no model is involved in route_only, so the heading is restated here (the JSON keeps 7D's label)
    block = cit.format_sources(cs).rstrip("\n").split("\n")
    block[1] = "Sources (card route only: topic identification; no page text; no model involved):"
    lines.append("\n".join(block))
    for n in cs.notes:
        lines.append(f"note: {n}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------------ CLI


def run_legacy() -> None:
    """Delegate to the existing chatbot, unchanged (imported only here, so route_only never loads it)."""
    import rag_chat
    rag_chat.main()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rag_modes.py", description="Choose the legacy chatbot (default) or the route_only card-routing mode.")
    ap.add_argument("--mode", type=_mode_arg, default=DEFAULT_MODE, help=f"one of {', '.join(IMPLEMENTED_MODES)} (default: {DEFAULT_MODE})")
    ap.add_argument("--question", default=None, help="route_only: route this question once and exit (otherwise interactive)")
    ap.add_argument("--top-k", type=int, default=None, help=f"route_only: number of cards to list (default {DEFAULT_TOP_K})")
    ap.add_argument("--json", action="store_true", help="route_only: print the result as JSON")
    ap.add_argument("--vector-dir", default=str(C.VECTOR_DIR), help="route_only: card vector store (default data/vector_store)")
    return ap


def _mode_arg(value: str) -> str:
    try:
        return parse_mode(value)
    except ModeError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _emit(res: RouteOnlyResult, as_json: bool) -> None:
    print(json.dumps(res.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) if as_json else render_text(res))


def main(argv: Optional[Sequence[str]] = None, backend: Any = None, ctx: Any = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.mode == MODE_LEGACY:
        used = [n for n, v in (("--question", args.question), ("--top-k", args.top_k), ("--json", args.json or None)) if v is not None]
        if used:
            ap.error(f"{', '.join(used)}: these options only apply to --mode route_only (legacy mode is the interactive chatbot, unchanged)")
        run_legacy()
        return 0

    top_k = args.top_k if args.top_k is not None else DEFAULT_TOP_K
    if top_k < 1:
        ap.error("--top-k must be at least 1")
    try:
        if backend is None:
            backend = rt.ChromaCardBackend(vector_dir=Path(args.vector_dir))
        ctx = ctx or pid.IdentityContext.from_root(C.ROOT)
        if args.question is not None:
            _emit(route_only(args.question, backend, ctx, top_k), args.json)
            return 0
        print("route_only mode: topic identification only (no LLM, no answer). Type 'exit' to quit.")
        while True:
            try:
                q = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                return 0
            if q.lower() in EXIT_WORDS:
                print("Goodbye!")
                return 0
            if q:
                _emit(route_only(q, backend, ctx, top_k), args.json)
    except rt.RouterError as e:                       # missing store/collection, bad metadata: a defined failure, never a legacy fallback
        print(f"Error ({STATUS_ROUTER_UNAVAILABLE}): {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
