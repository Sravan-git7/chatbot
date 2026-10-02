"""Phase 7A - routing orchestration (no answer generation, no production integration).

Demonstrates the first half of the intended flow and stops there:

    query -> M2C card router -> card-to-page join -> routing outcome

It does NOT call an LLM, does NOT build a prompt, does NOT generate an answer, does NOT retrieve SAP page chunks, does
NOT import or modify the legacy pipeline (``rag_core`` / ``rag_chat`` / ``retrieve`` / ``evaluate_retrieval``) and does
NOT use the network. The M2C cards only identify *which SAP topic/page is relevant*; answering from SAP page content is a
later stage that this phase does not build.

Outcome states (``RoutingOutcome.state``) - explicit, never guessed:
  resolved_page     : a card was selected and local SAP page content exists for it.
  url_only          : a card was selected and has a valid SAP Help URL, but no local page content exists.
  unresolved        : a card was selected but it has no usable URL (missing / not a SAP Help page URL).
  no_card_candidate : no card was selected (empty query, no candidates, or the caller's selector rejected all of them).

Selection policy
----------------
The router applies no threshold. By default the selected card is the top-ranked candidate (``select_top_ranked``), which
is a statement of rank, not of confidence. A caller that wants a cut-off supplies its own ``selector``; the selector
receives the ranked candidates (each with its cosine ``distance``) and returns one of them or ``None``. No cut-off is
shipped here because none is supported by evidence for the card collection.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_page_join import (RESOLVED_PAGE, UNRESOLVED, URL_ONLY, PageContentIndex, PageResolution,  # noqa: E402
                           resolve_card_page)
from m2c_router import DEFAULT_TOP_K, CardBackend, CardCandidate, route  # noqa: E402

NO_CARD_CANDIDATE = "no_card_candidate"
OUTCOME_STATES = (RESOLVED_PAGE, URL_ONLY, UNRESOLVED, NO_CARD_CANDIDATE)

FALLBACK_EMPTY_QUERY = "EMPTY_QUERY"
FALLBACK_NO_CANDIDATES = "NO_CARD_CANDIDATES_RETURNED"
FALLBACK_SELECTOR_REJECTED = "SELECTOR_REJECTED_ALL_CANDIDATES"

Selector = Callable[[Sequence[CardCandidate]], Optional[CardCandidate]]


def select_top_ranked(candidates: Sequence[CardCandidate]) -> Optional[CardCandidate]:
    """Default selection: the rank-1 candidate, if any. This is rank, not confidence."""
    return candidates[0] if candidates else None


@dataclass(frozen=True)
class RoutingOutcome:
    query: str
    state: str
    candidates: Tuple[CardCandidate, ...]
    selected_card: Optional[CardCandidate]
    resolution: Optional[PageResolution]
    source_url: Optional[str]               # the selected card's source_url when it has a usable URL, else None
    page_content_available: bool
    fallback_reason: Optional[str]          # None only when state == resolved_page
    distance_metric: str

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "state": self.state,
            "candidates": [c.to_dict() for c in self.candidates],
            "selected_card": self.selected_card.to_dict() if self.selected_card else None,
            "resolution": self.resolution.to_dict() if self.resolution else None,
            "source_url": self.source_url,
            "page_content_available": self.page_content_available,
            "fallback_reason": self.fallback_reason,
            "distance_metric": self.distance_metric,
        }


def route_to_page(query: str, backend: CardBackend, page_index: PageContentIndex,
                  top_k: int = DEFAULT_TOP_K, selector: Selector = select_top_ranked) -> RoutingOutcome:
    """query -> card candidates -> selected card -> page resolution. Pure apart from what ``backend`` itself reads."""
    result = route(query, backend, top_k=top_k)
    candidates = result.candidates

    selected = selector(candidates) if candidates else None
    if selected is not None and selected not in candidates:
        raise ValueError("selector returned a card that is not among the router's candidates")

    if selected is None:
        if not query.strip():
            reason = FALLBACK_EMPTY_QUERY
        elif not candidates:
            reason = FALLBACK_NO_CANDIDATES
        else:
            reason = FALLBACK_SELECTOR_REJECTED
        return RoutingOutcome(query=query, state=NO_CARD_CANDIDATE, candidates=candidates, selected_card=None, resolution=None,
                              source_url=None, page_content_available=False, fallback_reason=reason,
                              distance_metric=result.distance_metric)

    resolution = resolve_card_page(selected, page_index)
    return RoutingOutcome(
        query=query, state=resolution.state, candidates=candidates, selected_card=selected, resolution=resolution,
        source_url=resolution.source_url if resolution.url_exists else None,
        page_content_available=resolution.local_page_content, fallback_reason=resolution.reason,
        distance_metric=result.distance_metric)
