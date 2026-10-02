"""Ingestion plan: which pages to fetch for each RESOLVED topic, and where they go.

Scope is an explicit configuration option (``data/ingest_config.json``):
  * ``page_only``             - just the topic page
  * ``page_and_descendants``  - the topic page plus every TOC descendant (optionally
                                limited by ``max_depth``)
with a ``default_scope`` and per-topic overrides. Pages are de-duplicated on
``(guide_id, page_id)``; TOC alias nodes (``-NN`` files) collapse into their
primary page and are logged as DUPLICATE_PAGE.

Deterministic naming: every page is stored at ``<out_dir>/<guide_id>/<page_id>.json``
so pages of different guides can never overwrite one another, and re-running gives
the same paths. The legacy ``sap_pages/NNN.json`` naming is never used.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import events as ev
from .resolver import RESOLVED, TopicResolution
from .toc import TocNode, TocTree
from .urls import canonical_help_url

DEFAULT_OUT_DIR = "data/sap_help"
PROTECTED_DIRS = ("sap_pages", "chroma_db")   # never write ingestion output here
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


class ScopeMode(str, Enum):
    PAGE_ONLY = "page_only"
    PAGE_AND_DESCENDANTS = "page_and_descendants"


class ConfigError(ValueError):
    pass


@dataclass
class IngestConfig:
    default_scope: ScopeMode = ScopeMode.PAGE_ONLY
    topic_scopes: Dict[int, ScopeMode] = field(default_factory=dict)
    max_depth: Optional[int] = None          # only for page_and_descendants; 1 = direct children
    out_dir: str = DEFAULT_OUT_DIR

    def scope_for(self, topic_id: int) -> ScopeMode:
        return self.topic_scopes.get(topic_id, self.default_scope)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IngestConfig":
        try:
            default = ScopeMode(d.get("default_scope", ScopeMode.PAGE_ONLY.value))
            overrides = {int(k): ScopeMode(v) for k, v in (d.get("topic_scopes") or {}).items()}
        except ValueError as e:
            valid = [m.value for m in ScopeMode]
            raise ConfigError(f"invalid scope value ({e}); valid scopes: {valid}") from e
        md = d.get("max_depth")
        if md is not None and (not isinstance(md, int) or md < 1):
            raise ConfigError("max_depth must be null or an integer >= 1")
        return cls(default, overrides, md, d.get("out_dir", DEFAULT_OUT_DIR))

    @classmethod
    def load(cls, path: Path) -> "IngestConfig":
        p = Path(path)
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else cls()

    def to_dict(self) -> Dict[str, Any]:
        return {"default_scope": self.default_scope.value,
                "topic_scopes": {str(k): v.value for k, v in sorted(self.topic_scopes.items())},
                "max_depth": self.max_depth, "out_dir": self.out_dir}


def storage_key(guide_id: str, page_id: str) -> str:
    """Deterministic, guide-namespaced relative path for a stored page."""
    g, p = guide_id.lower(), page_id.lower()
    if not _HEX32.match(g) or not _HEX32.match(p):
        raise ValueError(f"guide_id/page_id must be 32-hex, got {guide_id!r}/{page_id!r}")
    return f"{g}/{p}.json"


def assert_safe_out_dir(out_dir: Path, repo_root: Path) -> Path:
    out = Path(out_dir)
    out = out if out.is_absolute() else Path(repo_root) / out
    resolved = out.resolve()
    root = Path(repo_root).resolve()
    if resolved == root:
        raise ConfigError("out_dir must not be the repository root")
    for prot in PROTECTED_DIRS:
        pd = (root / prot).resolve()
        if resolved == pd or pd in resolved.parents:
            raise ConfigError(f"refusing to write ingestion output inside protected path '{prot}'")
    return resolved


@dataclass
class PlanEntry:
    guide_id: str
    page_id: str
    file_path: str                     # TOC file name to request (primary node)
    title: str
    canonical_url: str
    toc_path: List[str]
    parent_page_id: Optional[str]
    depth: int                         # depth inside the guide TOC
    storage_key: str
    topic_roles: Dict[int, str] = field(default_factory=dict)   # topic_id -> topic_page | descendant
    alias_file_paths: List[str] = field(default_factory=list)

    @property
    def topic_ids(self) -> List[int]:
        return sorted(self.topic_roles)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["topic_roles"] = {str(k): v for k, v in sorted(self.topic_roles.items())}
        d["topic_ids"] = self.topic_ids
        return d


@dataclass
class IngestPlan:
    config: IngestConfig
    entries: List[PlanEntry]
    skipped_topics: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        per_topic: Dict[int, int] = {}
        for e in self.entries:
            for t in e.topic_ids:
                per_topic[t] = per_topic.get(t, 0) + 1
        return {"config": self.config.to_dict(), "entry_count": len(self.entries),
                "pages_per_topic": {str(k): v for k, v in sorted(per_topic.items())},
                "skipped_topics": self.skipped_topics,
                "entries": [e.to_dict() for e in self.entries]}


def build_plan(resolutions: List[TopicResolution], trees: Dict[str, TocTree], topics_by_id: Dict[int, Dict[str, Any]],
               config: IngestConfig, log: Optional[ev.EventLog] = None) -> IngestPlan:
    log = log or ev.EventLog()
    entries: Dict[tuple, PlanEntry] = {}
    order: List[tuple] = []
    skipped: List[Dict[str, Any]] = []

    def add(tree: TocTree, product: str, node: TocNode, topic_id: int, role: str):
        key = (tree.guide_id, node.page_id)
        primary = tree.find_page(node.page_id)[0]
        if key in entries:
            e = entries[key]
            prev_role = e.topic_roles.get(topic_id)
            log.emit(ev.DUPLICATE_PAGE, kind="plan_dedup", guide_id=tree.guide_id, page_id=node.page_id,
                     topic_id=topic_id, node=node.file_path, already_planned_for=e.topic_ids)
            if node.file_path != e.file_path and node.file_path not in e.alias_file_paths:
                e.alias_file_paths.append(node.file_path)
            # a topic page role beats a descendant role for the same topic
            if prev_role != "topic_page":
                e.topic_roles[topic_id] = role
            return
        parent = tree.parent_of(primary)
        entries[key] = PlanEntry(
            guide_id=tree.guide_id, page_id=node.page_id, file_path=primary.file_path, title=primary.title,
            canonical_url=canonical_help_url(product, tree.guide_id, node.page_id),
            toc_path=list(primary.toc_path), parent_page_id=parent.page_id if parent else None,
            depth=primary.depth, storage_key=storage_key(tree.guide_id, node.page_id),
            topic_roles={topic_id: role},
            alias_file_paths=[n.file_path for n in tree.find_page(node.page_id)[1:]])
        order.append(key)

    for r in resolutions:
        if r.status != RESOLVED:
            skipped.append({"topic_id": r.topic_id, "reason": r.reason})
            continue
        tree = trees[r.guide_id]
        product = topics_by_id[r.topic_id]["product"]
        top = tree.nodes[r.node_file_path]
        add(tree, product, top, r.topic_id, "topic_page")
        if config.scope_for(r.topic_id) is ScopeMode.PAGE_AND_DESCENDANTS:
            for d in tree.descendants(top, config.max_depth):
                if d.page_id == top.page_id:
                    log.emit(ev.DUPLICATE_PAGE, kind="descendant_is_topic_page", topic_id=r.topic_id,
                             guide_id=tree.guide_id, page_id=d.page_id, node=d.file_path)
                    continue
                add(tree, product, d, r.topic_id, "descendant")
    return IngestPlan(config, [entries[k] for k in order], skipped)
