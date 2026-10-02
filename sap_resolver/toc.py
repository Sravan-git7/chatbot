"""In-memory model of one SAP Help guide TOC (the ``fullToc`` of a ``pagecontent``
response fetched with ``deliverableInfo=1``, as saved in master_data.json).

Nodes are keyed by their TOC ``file_path`` (unique per node). SAP re-uses one
topic under several parents by appending ``-NN`` to the file name; such nodes are
*aliases* of the same ``page_id``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .urls import split_page_file


class TocError(ValueError):
    pass


@dataclass
class TocNode:
    file_path: str               # e.g. 4371ce53....html or 4371ce53...-35.html
    page_id: str                 # 32-hex without alias suffix
    alias_suffix: str            # "" for primary node, "-35" for re-used node
    title: str
    order: int                   # document order in the TOC (0-based)
    depth: int                   # 0 = top level
    parent: Optional[str]        # parent file_path or None
    children: List[str] = field(default_factory=list)
    toc_path: Tuple[str, ...] = ()   # titles from the top level down to and including this node

    @property
    def is_alias(self) -> bool:
        return bool(self.alias_suffix)


class TocTree:
    def __init__(self, guide_id: str, title: str, version: str, language: str,
                 landing_page: str, map_root_page_id: str, nodes: List[TocNode]):
        self.guide_id = guide_id.lower()
        self.title = title
        self.version = version
        self.language = language
        self.landing_page = landing_page
        self.map_root_page_id = (map_root_page_id or "").lower()
        self.pageless_headings: List[str] = []
        self.nodes: Dict[str, TocNode] = {}
        self._by_page: Dict[str, List[TocNode]] = {}
        for n in nodes:
            if n.file_path in self.nodes:
                raise TocError(f"duplicate TOC file_path {n.file_path}")
            self.nodes[n.file_path] = n
            self._by_page.setdefault(n.page_id, []).append(n)

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_pagecontent_response(cls, data: Dict[str, Any]) -> "TocTree":
        try:
            d = data["data"]["deliverable"]
            toc = d["fullToc"]
            guide_id = d["loio"]
        except (KeyError, TypeError) as e:
            raise TocError(f"not a pagecontent?deliverableInfo=1 response: missing {e}") from e
        nodes: List[TocNode] = []
        skipped_headings: List[str] = []

        def walk(items, parent: Optional[TocNode], path: Tuple[str, ...], depth: int):
            for item in items:
                fp = item.get("u") or ""
                if not fp:
                    # Real SAP TOCs contain page-less *heading* nodes (u == "", only a
                    # title and children). They are not pages: keep the title in the
                    # TOC path / depth of the children but do not make a node of them.
                    skipped_headings.append(item.get("t", ""))
                    walk(item.get("c") or [], parent, path + (item.get("t", ""),), depth + 1)
                    continue
                page_id, alias = split_page_file(fp)
                node = TocNode(file_path=fp, page_id=page_id, alias_suffix=alias,
                               title=item.get("t", ""), order=len(nodes), depth=depth,
                               parent=parent.file_path if parent else None,
                               toc_path=path + (item.get("t", ""),))
                nodes.append(node)
                if parent:
                    parent.children.append(fp)
                walk(item.get("c") or [], node, node.toc_path, depth + 1)

        walk(toc, None, (), 0)
        tree = cls(guide_id=guide_id, title=d.get("title", ""), version=d.get("version", ""),
                   language=d.get("languageCode", ""), landing_page=d.get("landingPage", ""),
                   map_root_page_id=d.get("buildableMapLoio", ""), nodes=nodes)
        tree.pageless_headings = skipped_headings
        return tree

    @classmethod
    def from_file(cls, path: Path) -> "TocTree":
        with open(path, encoding="utf-8") as f:
            return cls.from_pagecontent_response(json.load(f))

    # ------------------------------------------------------------------ queries
    def __len__(self) -> int:
        return len(self.nodes)

    def find_page(self, page_id: str) -> List[TocNode]:
        """All nodes for a page id; primary (non-alias) node first, then document order."""
        return sorted(self._by_page.get(page_id.lower(), []), key=lambda n: (n.is_alias, n.order))

    def parent_of(self, node: TocNode) -> Optional[TocNode]:
        return self.nodes.get(node.parent) if node.parent else None

    def children_of(self, node: TocNode) -> List[TocNode]:
        return [self.nodes[c] for c in node.children]

    def descendants(self, node: TocNode, max_depth: Optional[int] = None) -> Iterator[TocNode]:
        """Depth-first, document order, excluding ``node``. ``max_depth`` is relative
        to ``node`` (1 = direct children only)."""
        def rec(n: TocNode, d: int):
            for c in self.children_of(n):
                if max_depth is not None and d + 1 > max_depth:
                    continue
                yield c
                yield from rec(c, d + 1)
        yield from rec(node, 0)

    def is_map_root(self, page_id: str) -> bool:
        return bool(self.map_root_page_id) and page_id.lower() == self.map_root_page_id
