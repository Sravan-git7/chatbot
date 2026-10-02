"""Phase 8H - answer citations that extend the Phase 7D layer (``m2c_citations`` is reused unchanged).

Rules, all enforced here and tested:

* ``topic_pointer`` is the routed card (7D ``card_route`` entry): topic identification, ``used_as_answer_text`` stays ``False``.
  It is never listed among ``answer_sources`` and is never counted as evidence.
* ``answer_sources`` contains ONLY chunks that (1) were supplied to the generator, (2) are cited by a sentence of the answer, and
  (3) passed the grounding verifier for that sentence. They are built with the 7D ``page_chunk_entry`` (join to the routed card by
  page id and guide relation) and then marked ``provided_as_context`` / ``used_as_answer_text`` / ``verified_used``. Chunks that were
  supplied but not cited are listed separately in ``context_not_cited`` (debug information, not citations).
* If nothing was verified (any status other than ``answered``), ``answer_sources`` is empty. No phantom citation can appear: a marker
  that is not a supplied chunk fails the verifier before this layer runs.
* URLs are copied as stored (the card's ``source_url``); nothing is rewritten, normalised, completed or built from identifiers.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_citations as MC  # noqa: E402
import m2c_page_identity as pid  # noqa: E402

LABEL_ANSWER = "Sources used in the answer (page chunks supplied to the model, cited by the answer and checked against the chunk text)"
LABEL_NONE = "No answer sources: no page text was verified as used"


def _chunk_for(item: Any) -> Dict[str, Any]:
    return {"metadata": {"guide_id": item.guide_id, "page_id": item.page_id, "source_url": item.source_url, "chunk_id": item.chunk_id,
                         "doc_id": f"{item.guide_id}/{item.page_id}", "title": item.title},
            "document": item.text}


def build_citations(card: Any, identity: "pid.PageIdentity", ctx: "pid.IdentityContext", context: Optional[Any] = None,
                    verification: Optional[Any] = None, corpus_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    pairs = MC.recorded_numeric_pairs(ctx)
    pointer = MC.card_route_entry(card, identity, ctx)
    if corpus_entry:
        # The 7C/7D identity status is computed against data/sap_help only. Phase 8 holds page text in data/page_corpus; say so on the pointer
        # (the 7D entry itself is not modified: this is a copy).
        pointer["page_corpus"] = {"status": corpus_entry.get("corpus_status"), "doc_id": corpus_entry.get("doc_id"), "reason": corpus_entry.get("reason")}
        if corpus_entry.get("corpus_status") == "ingested":
            pointer["statement"] = ("Topic identified by the M2C card; this entry is a pointer to the SAP page, not page text. Page text for this topic is held in the "
                                    "Phase 8 page corpus (data/page_corpus); the identity status above is the Phase 7C status, which only looks at data/sap_help")
    notes: List[str] = []
    if identity.resolution_status == pid.CONFLICTING_IDENTITY:
        notes.append("conflicting identity: no effective page is chosen; the conflict is shown, not resolved")
    if identity.card_needs_review:
        notes.append("the card is marked needs_review; it is shown with its flag and reasons, not corrected")
    if identity.effective_guide_id and identity.card_guide_id and identity.effective_guide_id != identity.card_guide_id:
        notes.append(f"corrected identity: the card URL names guide {identity.card_guide_id}, the effective guide is {identity.effective_guide_id} "
                     "(existing correction; the card URL is shown unchanged)")
    answer_sources: List[Dict[str, Any]] = []
    not_cited: List[Dict[str, Any]] = []
    if context is not None:
        cited = set(verification.cited_markers) if (verification is not None and verification.ok and not verification.refusal) else set()
        for item in context.items:
            if item.marker in cited:
                e = MC.page_chunk_entry(_chunk_for(item), identity, pairs)
                e.update({"marker": item.marker, "provided_as_context": True, "used_as_answer_text": True, "verified_used": True,
                          "heading_path": list(item.heading_path), "section_title": item.section_title, "chunk_index": item.chunk_index,
                          "content_hash": item.content_hash, "guide_id": item.guide_id})
                if not e["join"]["joined_to_card"]:
                    notes.append(f"chunk {item.chunk_id} is not joined to the routed card: {e['join']['reason']}")
                answer_sources.append(e)
            else:
                not_cited.append({"marker": item.marker, "chunk_id": item.chunk_id, "heading_path": list(item.heading_path), "provided_as_context": True,
                                  "used_as_answer_text": False, "verified_used": False})
    return {"topic_pointer": pointer, "answer_sources": answer_sources, "context_not_cited": not_cited,
            "label": LABEL_ANSWER if answer_sources else LABEL_NONE, "notes": notes}


def format_answer_sources(cit: Dict[str, Any]) -> str:
    lines = ["", cit["label"] + ":"]
    if not cit["answer_sources"]:
        lines.append("   (none)")
    for s in cit["answer_sources"]:
        where = " > ".join(s["heading_path"]) if s.get("heading_path") else s["title"]
        lines.append(f"[{s['marker']}] {where}")
        lines.append(f"    {s['url'] if s['url'] else '(no URL: ' + str(s['url_flag']) + ')'}")
    p = cit["topic_pointer"]
    flag = " [REVIEW]" if p["review_flag"] else ""
    lines += ["", "Topic pointer (card route - topic identification, NOT answer evidence):",
              f"   {p['title']} ({p['source_id']}){flag} | identity={p['identity']['status']}", f"   {p['url'] if p['url'] else '(no URL: ' + str(p['url_flag']) + ')'}"]
    if p.get("page_corpus"):
        lines.append(f"   page text in the Phase 8 corpus: {p['page_corpus']['status']} (the identity status above is the Phase 7C status for data/sap_help)")
    for r in p["review_reasons"]:
        lines.append(f"   review reason: {r}")
    for n in cit["notes"]:
        lines.append(f"   note: {n}")
    return "\n".join(lines) + "\n"
