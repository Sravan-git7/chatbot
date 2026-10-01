"""Per-topic card->guide corrections, kept SEPARATE from (and never editing) the card records.

A card (PDF link) names a guide; SAP may serve that page from a different deliverable. A correction says, for
ONE topic, "the card names guide X, but SAP resolves the original URL to guide Y", and carries the evidence.

Rules (nothing is guessed):
  * the correction must quote the card's own guide id and page id; if they do not match the card it is rejected;
  * it needs evidence; a saved response that is present is machine-checked
    (``deliverable.loio == resolved_guide_id`` and ``currentPage.loio == card_page_id``), a mismatch rejects it;
  * it does not register a guide and does not confirm anything: the topic is RESOLVED only if the normal resolver finds the
    card's page id in the verified TOC of ``resolved_guide_id``; otherwise it stays unresolved (PAGE_NOT_IN_TOC / no TOC);
  * the original card values stay in the topic as ``card_guide_id`` / ``card_url`` and the correction is echoed in the manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .intake import strip_bom
from .urls import canonical_help_url

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
EVIDENCE_KINDS = {"saved_response", "user_reported_browser"}


class CorrectionError(ValueError):
    pass


def load_corrections(path: Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    d = json.loads(strip_bom(p.read_text(encoding="utf-8-sig")))
    c = d.get("corrections", [])
    if not isinstance(c, list):
        raise CorrectionError("'corrections' must be a list")
    return c


def _check_evidence(c: Dict[str, Any], root: Path) -> List[str]:
    """-> list of problems (empty = fine)."""
    ev = c.get("evidence")
    if not isinstance(ev, list) or not ev:
        return ["no evidence records"]
    problems: List[str] = []
    for i, e in enumerate(ev):
        if e.get("kind") not in EVIDENCE_KINDS:
            problems.append(f"evidence[{i}]: unknown kind {e.get('kind')!r}")
            continue
        if e["kind"] == "saved_response":
            f = Path(root) / str(e.get("file", ""))
            if not f.is_file():
                e["_file_present"] = False              # not a failure: a clean checkout may lack the untracked file
                continue
            try:
                d = json.loads(strip_bom(f.read_text(encoding="utf-8-sig")))["data"]
                loio, cur = d["deliverable"]["loio"].lower(), d["currentPage"]["loio"].lower()
            except (ValueError, KeyError, TypeError) as ex:
                problems.append(f"evidence[{i}]: {f.name} unreadable: {ex}")
                continue
            if loio != c["resolved_guide_id"]:
                problems.append(f"evidence[{i}]: response loio {loio[:8]} != resolved_guide_id {c['resolved_guide_id'][:8]}")
            if cur != c["card_page_id"]:
                problems.append(f"evidence[{i}]: response currentPage {cur[:8]} != card_page_id {c['card_page_id'][:8]}")
            e["_file_present"] = True
    return problems


def apply_corrections(topics: List[Dict[str, Any]], corrections: List[Dict[str, Any]], root: Path
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """-> (topics with corrections applied (copies), applied records, rejected [{topic_id, errors}])."""
    by_id = {t["topic_id"]: t for t in topics}
    out = {k: dict(v) for k, v in by_id.items()}
    applied, rejected, seen = [], [], set()
    for c in corrections:
        tid, errs = c.get("topic_id"), []
        t = by_id.get(tid)
        for k in ("card_guide_id", "card_page_id", "resolved_guide_id"):
            if not _HEX32.match(str(c.get(k, ""))):
                errs.append(f"{k} is not 32 lower-case hex")
        if t is None:
            errs.append(f"unknown topic {tid}")
        if tid in seen:
            errs.append("duplicate correction for this topic")
        seen.add(tid)
        if not errs:
            if t["guide_id"] != c["card_guide_id"] or t["page_id"] != c["card_page_id"]:
                errs.append("card_guide_id/card_page_id do not match the card record of this topic")
            if c["resolved_guide_id"] == c["card_guide_id"]:
                errs.append("resolved_guide_id equals the card's guide; nothing to correct")
            errs += _check_evidence(c, root)
        if errs:
            rejected.append({"topic_id": tid, "errors": errs})
            continue
        rec = {k: v for k, v in c.items()}
        new = out[tid]
        new["card_guide_id"], new["card_url"] = t["guide_id"], t.get("url_as_given") or t["canonical_url"]
        new["card_canonical_url"] = t["canonical_url"]
        new["guide_id"] = c["resolved_guide_id"]
        new["canonical_url"] = canonical_help_url(t["product"], c["resolved_guide_id"], t["page_id"])
        new["correction"] = rec
        applied.append(rec)
    return [out[t["topic_id"]] for t in topics], applied, rejected
