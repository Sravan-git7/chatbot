"""Resolve every topic card to a page inside a guide TOC.

A topic is RESOLVED only if *all* hold, using local evidence:
  1. its guide (card URL loio) is in the registry with a saved TOC;
  2. that TOC's own loio equals the card's guide id;
  3. the card's page_id is a node of that TOC.
Otherwise it is UNRESOLVED with a machine-readable reason. Nothing is guessed:
e.g. topic 1's page id equals the saved TOC's *map root* id, but its guide id
differs from the saved TOC loio, so it stays unresolved and only carries a
``candidate_note``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from . import events as ev
from .registry import GuideRegistry
from .toc import TocError, TocNode, TocTree
from .urls import canonical_help_url

RESOLVED = "resolved"
UNRESOLVED = "unresolved"

# unresolved reason codes
GUIDE_NOT_IN_REGISTRY = "GUIDE_NOT_IN_REGISTRY"
GUIDE_TOC_NOT_AVAILABLE = "GUIDE_TOC_NOT_AVAILABLE"
TOC_GUIDE_MISMATCH = "TOC_GUIDE_MISMATCH"
TOC_UNREADABLE = "TOC_UNREADABLE"
PAGE_NOT_IN_TOC = "PAGE_NOT_IN_TOC"


@dataclass
class TopicResolution:
    topic_id: int
    title: str
    category: str
    source_pdf: str
    guide_id: str
    page_id: str
    canonical_url: str
    status: str = UNRESOLVED
    reason: Optional[str] = None
    detail: str = ""
    candidate_note: Optional[str] = None
    # populated only when resolved
    node_file_path: Optional[str] = None
    toc_path: List[str] = field(default_factory=list)
    depth: Optional[int] = None
    parent_page_id: Optional[str] = None
    parent_title: Optional[str] = None
    child_page_ids: List[str] = field(default_factory=list)
    direct_child_count: Optional[int] = None
    descendant_count: Optional[int] = None          # TOC nodes, aliases included
    descendant_unique_page_count: Optional[int] = None
    alias_file_paths: List[str] = field(default_factory=list)
    fetch_ready: bool = False                        # numeric id + build no. known for the guide
    card_guide_id: Optional[str] = None              # only when a per-topic correction is in force
    correction: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GuideStatus:
    guide_id: str
    status: str
    reason: Optional[str]
    topic_ids: List[int]
    toc_nodes: int = 0
    fetch_ready: bool = False
    numeric_deliverable_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_trees(registry: GuideRegistry, topics: List[Dict[str, Any]], log: ev.EventLog):
    trees: Dict[str, TocTree] = {}
    statuses: Dict[str, GuideStatus] = {}
    errors: Dict[str, tuple] = {}
    by_guide: Dict[str, List[int]] = {}
    for t in topics:
        by_guide.setdefault(t["guide_id"], []).append(t["topic_id"])
    for gid, tids in by_guide.items():
        st = GuideStatus(gid, UNRESOLVED, None, tids, fetch_ready=registry.fetch_ready(gid),
                         numeric_deliverable_id=(registry.get(gid) or {}).get("numeric_deliverable_id"))
        if registry.get(gid) is None:
            st.reason = GUIDE_NOT_IN_REGISTRY
        else:
            try:
                tree = registry.load_toc(gid)
                trees[gid] = tree
                st.status, st.toc_nodes = RESOLVED, len(tree)
            except FileNotFoundError as e:
                st.reason = GUIDE_TOC_NOT_AVAILABLE
                errors[gid] = (GUIDE_TOC_NOT_AVAILABLE, str(e))
            except TocError as e:
                st.reason = TOC_GUIDE_MISMATCH if "registry says" in str(e) else TOC_UNREADABLE
                errors[gid] = (st.reason, str(e))
        if st.status == RESOLVED:
            log.emit(ev.GUIDE_RESOLVED, guide_id=gid, toc_nodes=st.toc_nodes, topic_ids=tids,
                     fetch_ready=st.fetch_ready)
        else:
            log.emit(ev.GUIDE_UNRESOLVED, guide_id=gid, reason=st.reason, topic_ids=tids,
                     fetch_ready=st.fetch_ready)
        statuses[gid] = st
    return trees, statuses, errors


def resolve_topics(topics: List[Dict[str, Any]], registry: GuideRegistry,
                   log: Optional[ev.EventLog] = None):
    """Returns (resolutions, guide_statuses, trees_by_guide)."""
    log = log or ev.EventLog()
    trees, guide_status, errors = _load_trees(registry, topics, log)
    results: List[TopicResolution] = []
    claimed: Dict[tuple, int] = {}
    for t in sorted(topics, key=lambda x: x["topic_id"]):
        gid, pid = t["guide_id"], t["page_id"]
        r = TopicResolution(topic_id=t["topic_id"], title=t["title"], category=t["category"],
                            source_pdf=t["pdf_file"], guide_id=gid, page_id=pid,
                            canonical_url=t.get("canonical_url") or canonical_help_url(t["product"], gid, pid),
                            fetch_ready=registry.fetch_ready(gid),
                            card_guide_id=t.get("card_guide_id"), correction=t.get("correction"))
        tree = trees.get(gid)
        if tree is None:
            r.reason, r.detail = errors.get(gid, (guide_status[gid].reason, ""))
            r.detail = r.detail or "guide has no saved TOC"
        else:
            nodes = tree.find_page(pid)
            if not nodes:
                r.reason = PAGE_NOT_IN_TOC
                r.detail = f"page {pid} is not a node of the {len(tree)}-node TOC of guide {gid}"
                if tree.is_map_root(pid):
                    r.detail = f"page {pid} is the guide's map root, which is not a TOC node"
            else:
                node = nodes[0]
                parent = tree.parent_of(node)
                desc = list(tree.descendants(node))
                r.status, r.reason = RESOLVED, None
                r.node_file_path = node.file_path
                r.toc_path = list(node.toc_path)
                r.depth = node.depth
                r.parent_page_id = parent.page_id if parent else None
                r.parent_title = parent.title if parent else None
                r.child_page_ids = [c.page_id for c in tree.children_of(node)]
                r.direct_child_count = len(node.children)
                r.descendant_count = len(desc)
                r.descendant_unique_page_count = len({d.page_id for d in desc} - {node.page_id})
                r.alias_file_paths = [n.file_path for n in nodes[1:]]
                if r.alias_file_paths:
                    log.emit(ev.DUPLICATE_PAGE, kind="toc_alias", topic_id=r.topic_id, guide_id=gid,
                             page_id=pid, nodes=[n.file_path for n in nodes])
        key = (gid, pid)
        if key in claimed:
            log.emit(ev.DUPLICATE_PAGE, kind="two_topics_same_page", topic_id=r.topic_id,
                     also_topic_id=claimed[key], guide_id=gid, page_id=pid)
        claimed.setdefault(key, r.topic_id)

        # Unconfirmed hint that must NOT be treated as a resolution.
        if r.status == UNRESOLVED:
            for other_gid, other in trees.items():
                if other_gid != gid and other.is_map_root(pid):
                    r.candidate_note = (
                        f"page id equals the map root of the saved TOC of guide {other_gid} "
                        f"('{other.title}', {len(other)} nodes), but the card's guide id {gid} differs; "
                        "NOT confirmed, therefore left unresolved")
        if r.status == RESOLVED:
            log.emit(ev.PAGE_RESOLVED, topic_id=r.topic_id, title=r.title, guide_id=gid, page_id=pid,
                     toc_path=r.toc_path, canonical_url=r.canonical_url,
                     direct_children=r.direct_child_count, descendants=r.descendant_count)
        else:
            log.emit(ev.TOPIC_UNRESOLVED, topic_id=r.topic_id, title=r.title, guide_id=gid, page_id=pid,
                     reason=r.reason, detail=r.detail, candidate_note=r.candidate_note)
        results.append(r)
    return results, list(guide_status.values()), trees


def summarize(resolutions: List[TopicResolution], guides: List[GuideStatus]) -> Dict[str, Any]:
    res = [r for r in resolutions if r.status == RESOLVED]
    unr = [r for r in resolutions if r.status != RESOLVED]
    reasons: Dict[str, int] = {}
    for r in unr:
        reasons[r.reason or "?"] = reasons.get(r.reason or "?", 0) + 1
    return {
        "topics_total": len(resolutions),
        "topics_resolved": len(res),
        "topics_unresolved": len(unr),
        "resolved_topic_ids": [r.topic_id for r in res],
        "unresolved_topic_ids": [r.topic_id for r in unr],
        "unresolved_reasons": dict(sorted(reasons.items())),
        "guides_total": len(guides),
        "guides_resolved": sum(g.status == RESOLVED for g in guides),
        "guides_unresolved": sum(g.status != RESOLVED for g in guides),
        "guides_fetch_ready": sum(g.fetch_ready for g in guides),
    }
