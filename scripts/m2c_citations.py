"""Phase 7D - citation flow (sources list with provenance). Pure, read-only, local files only.

Specification: ``data/phase6_next_phase_spec.md`` section 5, "7D - Citation flow". Scope kept to exactly that:

  * every answer-side ``sources`` list has entries with ``title``, ``url`` (the SAP page), ``origin`` in
    {``page_chunk``, ``card_route``}; routed items also carry the card's ``citation``, ``source_id``, ``source_status`` and
    ``review_flag`` (and the recorded review reasons);
  * URLs are never rewritten: a chunk URL and a card URL are reported as stored; where their shape differs (numeric deliverable
    vs loio) both are shown and the join is recorded by page id, never by string conversion;
  * a ``needs_review`` card (#14, #18, #23) carries its flag and reasons; nothing is dropped or corrected;
  * the list is labelled "sources provided to the model" (retrieved), never "sources used": usage is not verified;
  * no fabricated citation: a ``card_route`` entry is never presented as text used for an answer
    (``used_as_answer_text`` is always ``False``; ``verified_used`` is always ``False``).

What this module does NOT do: generate an answer, call an LLM, retrieve page chunks (the caller supplies legacy-shaped chunk
results if it has them), fetch or ingest any page, change the card router, the page join or the identity layer, or use the network.

Provenance carried for a card (card -> page identity -> guide/page -> content -> source URL/evidence): the card's stored URL and
ids; the identity status/basis from ``m2c_page_identity`` (``resolved_local_page``, ``identified_not_local``,
``corrected_identity``, ``card_identity_only``, ``conflicting_identity``, ``unresolved`` are passed through unchanged); the
correction summary (#05), the conflict reasons and probe evidence (#18; evidence only, never an effective guide); and, when a
usable local record exists, that record's own ``source_type`` / ``fetched_via`` / hashes. Local evidence is reported with its
recorded origin and is never relabelled as a fresh network fetch.

A page chunk is *joined* to the routed card only when (a) the page ids are equal, (b) the routed card has an effective
identity (never for ``conflicting_identity`` / ``card_identity_only`` / ``unresolved``), and (c) the guide relation is
established: the chunk metadata names the same guide id, or the chunk URL's numeric deliverable id has a recorded, unique pair
with the effective guide in ``guide_registrations.json`` / ``guide_registry.json``. Equal page ids alone are not enough (the same
page id occurs in two saved TOCs, e.g. #14/#15).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_page_identity as pid  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

ORIGIN_PAGE_CHUNK = "page_chunk"
ORIGIN_CARD_ROUTE = "card_route"
ORIGINS = (ORIGIN_PAGE_CHUNK, ORIGIN_CARD_ROUTE)

LABEL_PROVIDED = "Sources provided to the model (page_chunk = retrieved context, not verified as used; card_route = topic pointer, not page text)"
LABEL_ROUTE_ONLY = "Sources provided to the model: card route only (topic identification; no page text was provided)"

URL_FLAG_NO_URL = "NO_URL"
URL_FLAG_NOT_PARSEABLE = "URL_NOT_A_SAP_HELP_PAGE_URL"

JOIN_ESTABLISHED_GUIDE_ID = "guide_id_equal"
JOIN_ESTABLISHED_RECORDED_PAIR = "numeric_deliverable_recorded_pair"
JOIN_NOT_ESTABLISHED = "guide_relation_not_established"

# https://help.sap.com/docs/<product>/<guide loio | numeric deliverable>/<page id>[-NN].html[?query]; the URL is only read, never rebuilt.
_URL_RE = re.compile(r"^https://help\.sap\.com/docs/(?P<product>[^/?#]+)/(?P<seg>[0-9A-Za-z]+)/(?P<page>[0-9a-fA-F]{32})(?P<alias>-\d+)?\.html(?:[?#].*)?$")


# ---- recorded numeric-deliverable <-> guide pairs ---------------------------------------------------------------------
def recorded_numeric_pairs(ctx: "pid.IdentityContext") -> Dict[str, str]:
    """numeric deliverable id -> guide id, only where the repository records the pair for a verified guide and the numeric id
    belongs to exactly one guide in every recorded source. An ambiguous numeric id yields no pair."""
    by_numeric: Dict[str, set] = {}
    for gid, reg in ctx.registrations.items():
        n = reg.get("numeric_id")
        if n:
            by_numeric.setdefault(str(n), set()).add(gid)
    for gid, rg in ctx.registry.items():
        n = rg.get("numeric_deliverable_id")
        if n:
            by_numeric.setdefault(str(n), set()).add(str(gid).lower())
    # A numeric id that any recorded source lists for more than one guide is ambiguous and never paired (40374657: the #05 trap).
    shared = ((ctx.stale_final_manifest or {}).get("shared_numeric_ids") or {})
    ambiguous = {str(n) for n, gs in shared.items() if len(set(gs)) > 1}
    out: Dict[str, str] = {}
    for n, gids in sorted(by_numeric.items()):
        if len(gids) == 1 and n not in ambiguous:
            g = next(iter(gids))
            if ctx.guide_status(g)["verified"]:
                out[n] = g
    return out


# ---- helpers ----------------------------------------------------------------------------------------------------------
def _get(card: Any, name: str) -> Any:
    if isinstance(card, Mapping):
        return card.get(name)
    return getattr(card, name, None)


def _url_parts(url: Any) -> Optional[Dict[str, str]]:
    if not isinstance(url, str):
        return None
    m = _URL_RE.match(url.strip())
    if not m:
        return None
    return {"segment": m.group("seg").lower(), "page_id": m.group("page").lower(), "alias_suffix": m.group("alias") or "",
            "segment_kind": "loio" if re.fullmatch(r"[0-9a-fA-F]{32}", m.group("seg")) else "numeric_deliverable"}


def _evidence(identity: "pid.PageIdentity", kind: str) -> List[Mapping[str, Any]]:
    return [e for e in identity.evidence if e.get("kind") == kind]


def _review_reasons(identity: "pid.PageIdentity") -> List[str]:
    reasons: List[str] = []
    for e in _evidence(identity, "card"):
        reasons += [str(r) for r in e.get("source_url_status_reasons") or []]
        reasons += [str(r) for r in e.get("topic_manifest_warnings") or []]
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _identity_block(identity: "pid.PageIdentity", ctx: "pid.IdentityContext") -> Dict[str, Any]:
    """The identity layer's answer, passed through: status, basis, ids, correction / conflict / probe evidence, local record."""
    blk: Dict[str, Any] = {
        "status": identity.resolution_status, "basis": identity.resolution_basis,
        "card_guide_id": identity.card_guide_id, "card_page_id": identity.card_page_id,
        "effective_guide_id": identity.effective_guide_id, "effective_page_id": identity.effective_page_id,
        "local_page_available": identity.local_page_available, "local_page_path": identity.local_page_path,
        "correction": None, "conflict": None, "probe_evidence": [], "hints": [], "disagreements": [dict(d) for d in identity.disagreements],
        "local_content": None,
    }
    for e in _evidence(identity, "correction"):
        blk["correction"] = {
            "card_guide_id": e.get("card_guide_id"), "resolved_guide_id": e.get("resolved_guide_id"),
            "card_page_id": e.get("card_page_id"), "matches_card_ids": e.get("correction_matches_card_ids"),
            "machine_checked_saved_response_passed": e.get("machine_checked_saved_response_passed"),
            "user_reported_browser_observation_machine_verified": False,
            "registers_a_guide": False, "card_record_modified": False}
    for e in _evidence(identity, "conflict"):
        blk["conflict"] = {"reasons": list(e.get("reasons") or []), "other_loios_seen": list(e.get("other_loios_seen") or [])}
    for e in _evidence(identity, "captured_response"):
        if e.get("authority") == pid.A_PROBE:
            blk["probe_evidence"].append({
                "authority": e["authority"], "file": e.get("file"), "numeric_deliverable_id": e.get("numeric_deliverable_id"),
                "response_loio": e.get("response_loio"), "response_loio_registered_verified": e.get("response_loio_registered_verified"),
                "used_as_effective_guide": False})
    for e in _evidence(identity, "page_is_map_root_of_saved_toc") + _evidence(identity, "page_also_in_other_saved_toc"):
        blk["hints"].append({"kind": e["kind"], "authority": e.get("authority"), "guide_ids": list(e.get("guide_ids") or [])})
    if identity.local_page_available:
        v = pid.validate_local_page(identity, ctx.root)
        rec = v.get("record") or {}
        blk["local_content"] = {
            "record_path": identity.local_page_path, "validated": bool(v.get("ok")), "record_status": rec.get("status"),
            "text_chars": rec.get("text_chars"), "text_sha256": rec.get("text_sha256"),
            "record_source_type": rec.get("source_type"), "record_fetched_via": rec.get("fetched_via"),
            "record_source_url": rec.get("source_url"), "record_canonical_url": rec.get("canonical_url"),
            "is_legacy_local_copy": rec.get("source_type") == "legacy_local_copy",
            "fresh_network_fetch_claimed": False,
            "note": "content origin is the record's own source_type/fetched_via; it is not relabelled as a network fetch"}
    return blk


# ---- entries ----------------------------------------------------------------------------------------------------------
def card_route_entry(card: Any, identity: "pid.PageIdentity", ctx: "pid.IdentityContext") -> Dict[str, Any]:
    """One ``card_route`` source: the routed card and what the repository knows about its page. It is topic identification only."""
    url = _get(card, "source_url")
    has_url = isinstance(url, str) and bool(url.strip())
    needs_review = identity.card_needs_review
    flags: List[str] = []
    if not has_url:
        flags.append(URL_FLAG_NO_URL)
    elif _url_parts(url) is None:
        flags.append(URL_FLAG_NOT_PARSEABLE)
    if identity.resolution_status != pid.RESOLVED_LOCAL_PAGE:
        flags.append(f"PAGE_{identity.resolution_status.upper()}")
    entry = {
        "origin": ORIGIN_CARD_ROUTE,
        "title": _get(card, "title"),
        "url": url if has_url else None,                       # the card's stored URL, byte-identical
        "url_flag": None if (has_url and _url_parts(url) is not None) else (URL_FLAG_NO_URL if not has_url else URL_FLAG_NOT_PARSEABLE),
        "citation": _get(card, "citation"),
        "source_id": _get(card, "source_id"),
        "source_status": _get(card, "source_status"),
        "source_url_status": _get(card, "source_url_status"),
        "review_flag": bool(needs_review or not has_url),
        "review_reasons": _review_reasons(identity),
        "rank": _get(card, "rank"),
        "distance": _get(card, "distance"),                    # the router's cosine distance as stored; no derived confidence
        "distance_metric": _get(card, "distance_metric"),
        "provided_as_context": False,
        "used_as_answer_text": False,
        "verified_used": False,
        "identity": _identity_block(identity, ctx),
        "flags": flags,
        "statement": ("Topic identified by the M2C card; this entry is a pointer to the SAP page, not page text"
                      + ("" if identity.local_page_available else "; the page content is not available locally")),
    }
    return entry


def page_chunk_entry(chunk: Any, identity: Optional["pid.PageIdentity"], pairs: Mapping[str, str]) -> Dict[str, Any]:
    """One ``page_chunk`` source from a legacy-shaped retrieval result (``{"metadata": {...}, "document": ...}``) or a bare chunk dict.

    The chunk text is not copied. The URL is reported as stored. The join to the routed card is by page id with the guide relation
    recorded separately; it is never built from a string conversion of the URL.
    """
    meta = chunk.get("metadata") if isinstance(chunk, Mapping) and isinstance(chunk.get("metadata"), Mapping) else chunk
    meta = meta if isinstance(meta, Mapping) else {}
    url = meta.get("url") or meta.get("source_url") or meta.get("canonical_url")
    has_url = isinstance(url, str) and bool(url.strip())
    parts = _url_parts(url) if has_url else None
    meta_guide = str(meta.get("guide_id") or "").lower() or None
    meta_page = str(meta.get("page_id") or "").lower() or None
    page_id = meta_page or (parts["page_id"] if parts else None)
    url_seg = parts["segment"] if parts else None
    seg_kind = parts["segment_kind"] if parts else None

    join: Dict[str, Any] = {"joined_to_card": False, "card_source_id": identity.source_id if identity else None, "by": "page_id",
                            "chunk_page_id": page_id, "card_page_id": identity.card_page_id if identity else None,
                            "chunk_url_segment": url_seg, "chunk_url_segment_kind": seg_kind,
                            "guide_relation": JOIN_NOT_ESTABLISHED, "reason": None}
    if identity is None:
        join["reason"] = "NO_ROUTED_CARD"
    elif page_id is None:
        join["reason"] = "CHUNK_HAS_NO_PAGE_ID"
    elif identity.effective_page_id is None or identity.effective_guide_id is None:
        join["reason"] = f"CARD_HAS_NO_EFFECTIVE_IDENTITY_{identity.resolution_status.upper()}"
    elif page_id != identity.effective_page_id:
        join["reason"] = "PAGE_ID_DIFFERS"
    else:
        eg = identity.effective_guide_id
        if meta_guide is not None and meta_guide == eg:
            join["guide_relation"] = JOIN_ESTABLISHED_GUIDE_ID
        elif seg_kind == "loio" and url_seg == eg:
            join["guide_relation"] = JOIN_ESTABLISHED_GUIDE_ID
        elif seg_kind == "numeric_deliverable" and pairs.get(url_seg) == eg:
            join["guide_relation"] = JOIN_ESTABLISHED_RECORDED_PAIR
        if join["guide_relation"] == JOIN_NOT_ESTABLISHED:
            join["reason"] = "PAGE_ID_EQUAL_GUIDE_NOT_ESTABLISHED"
        else:
            join["joined_to_card"] = True
            join["reason"] = None
    text = chunk.get("document") if isinstance(chunk, Mapping) else None
    return {
        "origin": ORIGIN_PAGE_CHUNK,
        "title": meta.get("title"),
        "url": url if has_url else None,
        "url_flag": None if parts is not None else (URL_FLAG_NO_URL if not has_url else URL_FLAG_NOT_PARSEABLE),
        "page_id": page_id, "alias_suffix": parts["alias_suffix"] if parts else None,
        "chunk_id": meta.get("chunk_id"), "doc_id": meta.get("doc_id"),
        "provided_as_context": True,
        "used_as_answer_text": None,                     # unknown: the legacy code does not verify usage
        "verified_used": False,
        "chunk_chars": len(text) if isinstance(text, str) else None,
        "join": join,
        "card_url": identity.card_url if identity else None,   # shown next to the chunk URL when the shapes differ
    }


# ---- result -----------------------------------------------------------------------------------------------------------
class CitationSet:
    """``sources`` for one routed question. Generated from a 7A ``RoutingOutcome`` (card) plus caller-supplied page chunks."""

    def __init__(self, query: str, route_state: str, label: str, sources: Sequence[Dict[str, Any]], fallback_reason: Optional[str],
                 notes: Sequence[str]) -> None:
        self.query = query
        self.route_state = route_state
        self.label = label
        self.sources = tuple(sources)
        self.fallback_reason = fallback_reason
        self.notes = tuple(notes)

    def to_dict(self) -> Dict[str, Any]:
        return {"query": self.query, "route_state": self.route_state, "label": self.label, "sources": [dict(s) for s in self.sources],
                "fallback_reason": self.fallback_reason, "notes": list(self.notes)}


def cite_card(card: Any, ctx: "pid.IdentityContext", page_chunks: Sequence[Any] = (), query: str = "") -> CitationSet:
    """Sources for one routed card (a ``CardCandidate`` or a mapping with the card metadata) and optional page chunks."""
    identity = pid.resolve_identity(card, ctx)
    pairs = recorded_numeric_pairs(ctx)
    entries: List[Dict[str, Any]] = [card_route_entry(card, identity, ctx)]
    entries += [page_chunk_entry(c, identity, pairs) for c in page_chunks]
    notes: List[str] = []
    if identity.resolution_status == pid.CONFLICTING_IDENTITY:
        notes.append("conflicting identity: no effective page is chosen; the conflict and probe evidence are shown, not resolved")
    if identity.card_needs_review:
        notes.append("the card is marked needs_review; it is shown with its flag and reasons, not corrected")
    for e in entries[1:]:
        if not e["join"]["joined_to_card"]:
            notes.append(f"chunk {e.get('chunk_id') or e.get('url')} is not joined to the routed card: {e['join']['reason']}")
    label = LABEL_PROVIDED if page_chunks else LABEL_ROUTE_ONLY
    reason = None if identity.resolution_status == pid.RESOLVED_LOCAL_PAGE else identity.resolution_basis
    return CitationSet(query, identity.resolution_status, label, entries, reason, notes)


def cite_outcome(outcome: Any, ctx: "pid.IdentityContext", page_chunks: Sequence[Any] = ()) -> CitationSet:
    """Sources for a 7A ``RoutingOutcome`` (from ``m2c_orchestrator.route_to_page``). No card selected -> no sources, stated."""
    if outcome.selected_card is None:
        return CitationSet(outcome.query, pid.NO_CARD_CANDIDATE, LABEL_ROUTE_ONLY, (), outcome.fallback_reason,
                           ("no card was selected; there is nothing to cite",))
    return cite_card(outcome.selected_card, ctx, page_chunks, query=outcome.query)


def cite_query(query: str, backend: Any, ctx: "pid.IdentityContext", page_chunks: Sequence[Any] = (), top_k: Optional[int] = None,
               selector: Any = None) -> CitationSet:
    from m2c_orchestrator import route_to_page, select_top_ranked
    from m2c_router import DEFAULT_TOP_K
    outcome = route_to_page(query, backend, ctx.page_index, top_k=top_k or DEFAULT_TOP_K, selector=selector or select_top_ranked)
    return cite_outcome(outcome, ctx, page_chunks)


# ---- plain-text rendering (mirrors rag_chat.print_sources semantics; rag_chat is untouched) ---------------------------------
def format_sources(cs: CitationSet) -> str:
    lines = ["", cs.label + ":"]
    if not cs.sources:
        lines.append("   (none)")
    for i, s in enumerate(cs.sources, start=1):
        if s["origin"] == ORIGIN_CARD_ROUTE:
            flag = " [REVIEW]" if s["review_flag"] else ""
            lines.append(f"{i}. [card_route] {s['title']} ({s['source_id']}){flag} | identity={s['identity']['status']}")
            lines.append(f"   {s['url'] if s['url'] else '(no URL: ' + str(s['url_flag']) + ')'}")
            lines.append(f"   {s['citation']}")
            for r in s["review_reasons"]:
                lines.append(f"   review reason: {r}")
        else:
            j = s["join"]
            lines.append(f"{i}. [page_chunk] {s['title']} | joined_to_card={j['joined_to_card']}"
                         + (f" ({j['reason']})" if j["reason"] else f" (by page id; {j['guide_relation']})"))
            lines.append(f"   {s['url'] if s['url'] else '(no URL: ' + str(s['url_flag']) + ')'}")
    return "\n".join(lines) + "\n"


# ---- audit of all 29 cards --------------------------------------------------------------------------------------------
def build_audit(ctx: "pid.IdentityContext", cards: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    """Citation entry for every real card (no router, no store, no page chunks): shows what a routed answer would cite."""
    cards = pid.load_cards(ctx.root) if cards is None else cards
    sets = [cite_card(c, ctx) for c in cards]
    rows = []
    for cs in sets:
        e = cs.sources[0]
        rows.append({k: e[k] for k in ("source_id", "title", "url", "url_flag", "citation", "source_status", "source_url_status",
                                        "review_flag", "review_reasons", "used_as_answer_text", "flags")}
                    | {"identity": e["identity"], "notes": list(cs.notes)})
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["identity"]["status"]] = counts.get(r["identity"]["status"], 0) + 1
    return {"schema_version": 1, "spec": "data/phase6_next_phase_spec.md#7D", "card_count": len(rows),
            "identity_status_counts": dict(sorted(counts.items())),
            "review_flag_cards": [r["source_id"] for r in rows if r["review_flag"]],
            "cards_with_local_content": [r["source_id"] for r in rows if r["identity"]["local_page_available"]],
            "recorded_numeric_pairs": recorded_numeric_pairs(ctx), "cards": rows}


def render_json(audit: Mapping[str, Any]) -> str:
    return json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Phase 7D: write data/m2c_citation_audit.json (read-only over the repo inputs).")
    ap.add_argument("--out", default=str(ROOT / "data" / "m2c_citation_audit.json"))
    args = ap.parse_args(argv)
    audit = build_audit(pid.IdentityContext.from_root(ROOT))
    Path(args.out).write_text(render_json(audit), encoding="utf-8")
    print(f"{audit['card_count']} cards: {audit['identity_status_counts']}; review flags: {audit['review_flag_cards']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
