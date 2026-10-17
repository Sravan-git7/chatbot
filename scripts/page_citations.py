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

import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m2c_citations as MC  # noqa: E402
import m2c_page_identity as pid  # noqa: E402
from citation_markers import valid_marker  # noqa: E402

LABEL_ANSWER = "Sources used in the answer (page chunks supplied to the model, cited by the answer and checked against the chunk text)"
LABEL_NONE = "No answer sources: no page text was verified as used"


def _chunk_for(item: Any) -> Dict[str, Any]:
    return {"metadata": {"guide_id": item.guide_id, "page_id": item.page_id, "source_url": item.source_url, "chunk_id": item.chunk_id,
                         "doc_id": item.doc_id, "title": item.title, "source_ids": list(item.source_ids),
                         "content_hash": item.content_hash, "page_text_sha256": item.page_text_sha256,
                         "chunk_index": item.chunk_index},
            "document": item.text}


_HASH64 = re.compile(r"^[0-9a-f]{64}$", re.I)
_ID32 = re.compile(r"^[0-9a-f]{32}$", re.I)


def validate_context_provenance(context: Any, identity: "pid.PageIdentity", ctx: "pid.IdentityContext",
                                corpus_entry: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Validate each citation marker against one immutable page-chunk object and its page manifest.

    A malformed, duplicated, cross-page, wrong-source, or content-hash-mismatched object is fatal.
    A recorded SAP URL that does not identify the admitted guide/page is retained for audit but is
    explicitly unverified and must not be exposed as a clickable citation. We never repair/build URLs.
    """
    items = list(getattr(context, "items", ()) or ())
    counts: Dict[str, int] = {}
    for item in items:
        marker = str(getattr(item, "marker", "") or "")
        counts[marker] = counts.get(marker, 0) + 1
    expected_guide = str(getattr(identity, "effective_guide_id", None) or "").lower()
    expected_page = str(getattr(identity, "effective_page_id", None) or "").lower()
    expected_source_id = str(getattr(identity, "source_id", None) or "")
    corpus = corpus_entry if isinstance(corpus_entry, Mapping) else {}
    expected_page_hash = str(corpus.get("text_sha256") or "").lower()
    expected_corpus_doc_id = str(corpus.get("doc_id") or "")
    numeric_pairs = MC.recorded_numeric_pairs(ctx)
    checked_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for item in items:
        marker = str(getattr(item, "marker", "") or "")
        guide_id = str(getattr(item, "guide_id", None) or "").lower()
        page_id = str(getattr(item, "page_id", None) or "").lower()
        chunk_id = str(getattr(item, "chunk_id", None) or "")
        doc_id = str(getattr(item, "doc_id", None) or "")
        chunk_index = getattr(item, "chunk_index", None)
        text = getattr(item, "text", None)
        content_hash = str(getattr(item, "content_hash", None) or "").lower()
        page_hash = str(getattr(item, "page_text_sha256", None) or "").lower()
        source_ids = [str(value).strip() for value in (getattr(item, "source_ids", None) or []) if str(value).strip()]
        item_errors: List[str] = []

        if not valid_marker(marker):
            item_errors.append("INVALID_MARKER")
        if counts.get(marker, 0) > 1:
            item_errors.append("DUPLICATE_MARKER")
        if not _ID32.fullmatch(guide_id) or not _ID32.fullmatch(page_id):
            item_errors.append("INVALID_GUIDE_OR_PAGE_ID")
        if corpus.get("corpus_status") != "ingested":
            item_errors.append("CORPUS_ENTRY_NOT_INGESTED")
        if not _HASH64.fullmatch(expected_page_hash):
            item_errors.append("PAGE_MANIFEST_HASH_MISSING_OR_INVALID")
        if (guide_id, page_id) != (expected_guide, expected_page):
            item_errors.append("CONTEXT_IDENTITY_MISMATCH")
        if not expected_source_id or expected_source_id not in source_ids:
            item_errors.append("SOURCE_ID_MISSING_OR_MISMATCHED")
        if len(source_ids) != len(set(source_ids)):
            item_errors.append("DUPLICATE_SOURCE_ID")
        expected_doc_id = f"{guide_id}/{page_id}" if guide_id and page_id else ""
        if not doc_id or doc_id != expected_doc_id:
            item_errors.append("DOC_ID_MISMATCH")
        if not expected_corpus_doc_id or expected_corpus_doc_id != expected_doc_id:
            item_errors.append("CORPUS_DOC_ID_MISMATCH")
        expected_chunk_id = f"{expected_doc_id}/{int(chunk_index):03d}" if type(chunk_index) is int and chunk_index >= 0 else ""
        if not expected_chunk_id or chunk_id != expected_chunk_id:
            item_errors.append("CHUNK_ID_MISMATCH")
        if not isinstance(text, str) or not text:
            item_errors.append("CHUNK_TEXT_MISSING")
        if not _HASH64.fullmatch(content_hash):
            item_errors.append("INVALID_CONTENT_HASH")
        elif isinstance(text, str) and hashlib.sha256(text.encode("utf-8")).hexdigest() != content_hash:
            item_errors.append("CONTENT_HASH_MISMATCH")
        if not _HASH64.fullmatch(page_hash):
            item_errors.append("INVALID_PAGE_TEXT_HASH")
        elif expected_page_hash and page_hash != expected_page_hash:
            item_errors.append("PAGE_TEXT_HASH_MISMATCH")

        raw_url = getattr(item, "source_url", None)
        url_parts = MC._url_parts(raw_url)
        if not isinstance(raw_url, str) or not raw_url.strip():
            url_status = "NO_URL"
        elif url_parts is None:
            url_status = MC.URL_FLAG_NOT_PARSEABLE
        elif url_parts["page_id"] != page_id:
            url_status = "URL_PAGE_ID_MISMATCH"
        elif url_parts["segment_kind"] == "loio" and url_parts["segment"] == guide_id:
            url_status = "VERIFIED"
        elif url_parts["segment_kind"] == "numeric_deliverable" and numeric_pairs.get(url_parts["segment"]) == guide_id:
            url_status = "VERIFIED"
        else:
            url_status = "URL_GUIDE_RELATION_NOT_ESTABLISHED"

        checked = {"marker": marker, "chunk_id": chunk_id, "doc_id": doc_id, "guide_id": guide_id, "page_id": page_id,
                   "source_ids": source_ids, "content_hash": content_hash, "page_text_sha256": page_hash,
                   "source_object_valid": not item_errors, "errors": item_errors,
                   "recorded_url": raw_url if isinstance(raw_url, str) else None,
                   "url_status": url_status, "url_verified": url_status == "VERIFIED",
                   "semantic_entailment": "NOT_ASSESSED"}
        checked_items.append(checked)
        for error in item_errors:
            errors.append({"marker": marker, "kind": error})

    return {"ok": not errors and bool(checked_items), "items": checked_items, "errors": errors,
            "semantic_entailment": "NOT_ASSESSED",
            "note": "Chunk identity and hashes are mechanically checked; SAP semantic entailment is not assessed."}


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
        provenance = validate_context_provenance(context, identity, ctx, corpus_entry)
        provenance_by_marker = {row["marker"]: row for row in provenance["items"]}
        if not provenance["ok"]:
            notes.append("source provenance validation failed; answer sources are withheld")
        cited = (set(verification.cited_markers)
                 if provenance["ok"] and verification is not None and verification.ok and not verification.refusal else set())
        for item in context.items:
            if item.marker in cited:
                e = MC.page_chunk_entry(_chunk_for(item), identity, pairs)
                source_provenance = provenance_by_marker[item.marker]
                e.update({"marker": item.marker, "provided_as_context": True, "used_as_answer_text": True, "verified_used": True,
                          "heading_path": list(item.heading_path), "section_title": item.section_title, "chunk_index": item.chunk_index,
                          "content_hash": item.content_hash, "page_text_sha256": item.page_text_sha256,
                          "guide_id": item.guide_id, "page_id": item.page_id, "doc_id": item.doc_id,
                          "source_ids": list(item.source_ids), "provenance": source_provenance,
                          # Keep the raw recorded URL in the provenance audit, but never expose an unverified URL as a link.
                          "url": e.get("url") if source_provenance["url_verified"] else None,
                          "url_flag": None if source_provenance["url_verified"] else source_provenance["url_status"]})
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
