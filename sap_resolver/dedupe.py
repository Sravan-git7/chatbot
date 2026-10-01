"""Two-level de-duplication.

1. Page identity: ``(guide_id, page_id)`` - done when the plan is built (plan.build_plan folds TOC alias nodes
   and overlapping topics into ONE entry that keeps every topic relationship).
2. Content: documents whose normalised cleaned text hashes equal. One canonical document is kept, the others get
   ``duplicate_of`` + status DUPLICATE_CONTENT and are NOT chunked. No topic relationship is lost: the canonical
   document inherits every topic ref of its duplicates (``via_doc_id`` says where it came from).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import events as ev
from .schema import STATUS_DUPLICATE_CONTENT, STATUS_EMPTY


def primary_topic(topic_refs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic: a direct topic_page relationship beats a descendant one, direct beats inherited, lowest id wins."""
    return sorted(topic_refs, key=lambda r: (r.get("via_doc_id") is not None, r["role"] != "topic_page", r["topic_id"]))[0]


def dedupe_documents(docs: List[Dict[str, Any]], log: Optional[ev.EventLog] = None) -> List[Dict[str, Any]]:
    """``docs`` must be in plan order. Mutates and returns them."""
    log = log or ev.EventLog()
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for d in docs:
        if d["status"] == STATUS_EMPTY:
            continue
        groups.setdefault(d["content_hash"], []).append(d)
    order = {d["doc_id"]: i for i, d in enumerate(docs)}
    for members in groups.values():
        if len(members) < 2:
            continue
        canon = sorted(members, key=lambda d: (not any(r["role"] == "topic_page" for r in d["topic_refs"]),
                                               order[d["doc_id"]]))[0]
        for dup in members:
            if dup is canon:
                continue
            dup["duplicate_of"] = canon["doc_id"]
            dup["status"] = STATUS_DUPLICATE_CONTENT
            canon.setdefault("duplicate_docs", []).append(dup["doc_id"])
            known = {(r["topic_id"], r["role"], r.get("via_doc_id")) for r in canon["topic_refs"]}
            for r in dup["topic_refs"]:
                inherited = {**r, "via_doc_id": r.get("via_doc_id") or dup["doc_id"]}
                key = (inherited["topic_id"], inherited["role"], inherited["via_doc_id"])
                if key not in known:
                    canon["topic_refs"].append(inherited)
                    known.add(key)
            log.emit(ev.DUPLICATE_CONTENT, guide_id=dup["guide_id"], page_id=dup["page_id"], doc_id=dup["doc_id"],
                     duplicate_of=canon["doc_id"], content_hash=dup["content_hash"],
                     topics_inherited_by_canonical=sorted({r["topic_id"] for r in dup["topic_refs"]}))
    for d in docs:
        d["duplicate_docs"] = sorted(d.get("duplicate_docs", []))
        _refresh_topics(d)
    return docs


def _refresh_topics(d: Dict[str, Any]) -> None:
    refs = sorted(d["topic_refs"], key=lambda r: (r["topic_id"], r["role"], r.get("via_doc_id") or ""))
    d["topic_refs"] = refs
    d["topic_ids"] = sorted({r["topic_id"] for r in refs})
    p = primary_topic(refs)
    d["topic_id"], d["topic_title"] = p["topic_id"], p["topic_title"]
