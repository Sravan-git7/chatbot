"""Phase 7C - deterministic CARD -> SAP PAGE identity resolution (pure, read-only, local files only).

Question answered: given an M2C card, which SAP page does it point to, and do we actually possess usable local content
for that page?

The source-of-truth rules are written down in ``data/m2c_page_identity_rules.md`` (written before this code); this module
implements exactly those rules. In short:

  * card id / URL / guide segment / page id come from the card record (the URL is parsed, never rewritten);
  * a per-topic correction comes only from ``data/topic_corrections.json``; it changes the *effective* guide, never the card;
  * a guide is *verified* only by ``data/guide_registrations.json`` (``response_loio_verified`` + TOC loio check + saved
    response check) or, for guide e52c8ee6 only, by the registry's local-evidence entry;
  * a page is *identified* in a guide only if it is a node of that guide's saved TOC;
  * a page is *local* only if ``data/sap_help/pages/<guide>/<page>.json`` is a valid record with status OK and non-empty text
    (the ``m2c_page_join`` criteria).

Never used as identity evidence: a numeric deliverable id, a page title, a page that also appears in another deliverable, or a
probe response. Never used as content: a URL, an HTTP 200, a saved TOC, a raw ``captured_responses/*.json``, an HTML shell,
a probe, a title. Disagreements between sources are listed, not reconciled.

The module never ingests, fetches, repairs or writes anything (``write_identity_json`` / ``render_report`` are explicit
output helpers used only by ``main``), imports no network library and no LLM, and does not import the legacy pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2c_page_join import (PAGES_DIR, PageContentIndex, parse_source_url)  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# ---- statuses ---------------------------------------------------------------------------------------------------------
RESOLVED_LOCAL_PAGE = "resolved_local_page"
IDENTIFIED_NOT_LOCAL = "identified_not_local"
CORRECTED_IDENTITY = "corrected_identity"
CARD_IDENTITY_ONLY = "card_identity_only"
CONFLICTING_IDENTITY = "conflicting_identity"
UNRESOLVED = "unresolved"
STATUSES = (RESOLVED_LOCAL_PAGE, IDENTIFIED_NOT_LOCAL, CORRECTED_IDENTITY, CARD_IDENTITY_ONLY, CONFLICTING_IDENTITY, UNRESOLVED)
NO_CARD_CANDIDATE = "no_card_candidate"

# ---- resolution bases (stable codes) ----------------------------------------------------------------------------------
B_LOCAL_RECORD = "CARD_PAGE_IN_VERIFIED_GUIDE_TOC_AND_LOCAL_RECORD_PRESENT"
B_TOC_ONLY = "CARD_PAGE_IN_VERIFIED_GUIDE_TOC_NO_LOCAL_RECORD"
B_CORRECTION = "CORRECTION_APPLIED_PAGE_IN_CORRECTED_GUIDE_TOC"
B_CARD_ONLY = "CARD_URL_ONLY_GUIDE_UNVERIFIED"
B_CORRECTION_REJECTED = "CORRECTION_NOT_HONOURED"
B_PAGE_NOT_IN_TOC_OTHER = "PAGE_NOT_IN_CARD_GUIDE_TOC_PAGE_SEEN_ELSEWHERE"
B_PAGE_NOT_IN_TOC = "PAGE_NOT_IN_CARD_GUIDE_TOC"
B_UNVERIFIED_GUIDE_OTHER = "CARD_GUIDE_UNVERIFIED_PAGE_SEEN_UNDER_OTHER_GUIDE"
B_CARD_MISSING = "CARD_MISSING"
B_NO_URL = "NO_SOURCE_URL"
B_URL_NOT_PARSEABLE = "URL_NOT_A_SAP_HELP_PAGE_URL"

# authority labels attached to evidence items
A_CARD = "card_record"
A_CORRECTION = "topic_correction"
A_TOC = "saved_toc_membership"
A_PROBE = "probe_evidence_only"
A_HINT = "non_authoritative_hint"
A_LOCAL = "local_page_record"

_PAGE_FILE = re.compile(r"^(?P<page>[0-9a-fA-F]{32})(?P<alias>-\d+)?\.html$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_VERIFIED = "response_loio_verified"
REGISTRY_ONLY_GUIDE_NOTE = "verified through data/guide_registry.json local-evidence entry (master_data.json); not in guide_registrations.json"


# ---- small helpers ----------------------------------------------------------------------------------------------------
def _field(card: Any, name: str) -> Any:
    if isinstance(card, Mapping):
        return card.get(name)
    return getattr(card, name, None)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _query_of(url: str) -> Optional[str]:
    if not isinstance(url, str) or "?" not in url:
        return None
    return url.split("?", 1)[1].split("#", 1)[0] or None


# ---- saved TOC --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TocInfo:
    guide_id: str           # the guide the file was looked up for
    file: str               # repository-relative path
    loio: str               # the TOC's own deliverable.loio
    title: str
    page_ids: frozenset
    node_count: int
    landing_page: str
    map_root: str

    @property
    def loio_matches(self) -> bool:
        return self.loio == self.guide_id

    def to_dict(self) -> Dict[str, Any]:
        return {"file": self.file, "toc_loio": self.loio, "toc_loio_equals_guide_id": self.loio_matches, "title": self.title,
                "node_count": self.node_count, "unique_page_ids": len(self.page_ids),
                "landing_page": self.landing_page, "map_root_page_id": self.map_root}


def load_toc(path: Path, guide_id: str, root: Path) -> Optional[TocInfo]:
    data = _read_json(path)
    try:
        d = data["data"]["deliverable"]
        full = d["fullToc"]
        loio = str(d["loio"]).lower()
    except (KeyError, TypeError):
        return None
    ids: set = set()
    count = 0

    def walk(items: Sequence[Mapping[str, Any]]) -> None:
        nonlocal count
        for it in items:
            m = _PAGE_FILE.match(it.get("u") or "")
            if m:
                ids.add(m.group("page").lower())
                count += 1
            walk(it.get("c") or [])

    walk(full)
    lp = _PAGE_FILE.match(str(d.get("landingPage") or ""))
    return TocInfo(guide_id=guide_id, file=_rel(path, root), loio=loio, title=str(d.get("title") or ""),
                   page_ids=frozenset(ids), node_count=count, landing_page=lp.group("page").lower() if lp else "",
                   map_root=str(d.get("buildableMapLoio") or "").lower())


# ---- captured responses (evidence only) -------------------------------------------------------------------------------
@dataclass(frozen=True)
class CaptureInfo:
    file: str
    numeric_deliverable_id: str
    response_loio: str
    current_page_id: str
    current_page_title: str
    deliverable_title: str
    toc_nodes_in_response: int


def load_captures(root: Path) -> List[CaptureInfo]:
    out: List[CaptureInfo] = []
    cdir = root / "captured_responses"
    if not cdir.is_dir():
        return out
    for p in sorted(cdir.glob("[0-9]_*.json")):
        data = _read_json(p)
        try:
            d = data["data"]["deliverable"]
            cp = data["data"]["currentPage"]
            loio, page = str(d["loio"]).lower(), str(cp["loio"]).lower()
        except (KeyError, TypeError):
            continue
        m = re.match(r"^\d+_(\d+)_", p.name)
        n = 0

        def walk(items: Sequence[Mapping[str, Any]]) -> None:
            nonlocal n
            for it in items:
                if _PAGE_FILE.match(it.get("u") or ""):
                    n += 1
                walk(it.get("c") or [])

        walk(d.get("fullToc") or [])
        out.append(CaptureInfo(file=_rel(p, root), numeric_deliverable_id=m.group(1) if m else "", response_loio=loio,
                               current_page_id=page, current_page_title=str(cp.get("t") or ""),
                               deliverable_title=str(d.get("title") or ""), toc_nodes_in_response=n))
    return out


# ---- result -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PageIdentity:
    source_id: Optional[str]
    card_title: Optional[str]
    card_url: Optional[str]
    card_guide_id: Optional[str]
    card_page_id: Optional[str]
    effective_guide_id: Optional[str]
    effective_page_id: Optional[str]
    resolution_basis: str
    resolution_status: str
    local_page_path: Optional[str]
    local_page_available: bool
    evidence: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    card_source_status: Optional[str] = None
    card_source_url_status: Optional[str] = None
    disagreements: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def card_needs_review(self) -> bool:
        return "needs_review" in (self.card_source_status, self.card_source_url_status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id, "card_title": self.card_title, "card_url": self.card_url,
            "card_guide_id": self.card_guide_id, "card_page_id": self.card_page_id,
            "card_source_status": self.card_source_status, "card_source_url_status": self.card_source_url_status,
            "card_needs_review": self.card_needs_review,
            "effective_guide_id": self.effective_guide_id, "effective_page_id": self.effective_page_id,
            "resolution_basis": self.resolution_basis, "resolution_status": self.resolution_status,
            "local_page_path": self.local_page_path, "local_page_available": self.local_page_available,
            "disagreements": [dict(d) for d in self.disagreements],
            "evidence": [dict(e) for e in self.evidence],
        }


# ---- context (all local evidence, loaded once) ------------------------------------------------------------------------
class IdentityContext:
    """Every local file the resolver reads. ``from_root`` reads; nothing is written or fetched."""

    def __init__(self, root: Path, topic_manifest: Mapping[int, Mapping[str, Any]], source_manifest: Mapping[int, Mapping[str, Any]],
                 corrections: Mapping[int, Mapping[str, Any]], registrations: Mapping[str, Mapping[str, Any]],
                 registry: Mapping[str, Mapping[str, Any]], tocs: Mapping[str, Optional[TocInfo]],
                 captures: Sequence[CaptureInfo], page_index: PageContentIndex, input_files: Mapping[str, Optional[str]],
                 stale_final_manifest: Optional[Mapping[str, Any]] = None) -> None:
        self.root = Path(root)
        self.topic_manifest = dict(topic_manifest)
        self.source_manifest = dict(source_manifest)
        self.corrections = dict(corrections)
        self.registrations = dict(registrations)
        self.registry = dict(registry)
        self.tocs = dict(tocs)
        self.captures = list(captures)
        self.page_index = page_index
        self.input_files = dict(input_files)
        self.stale_final_manifest = dict(stale_final_manifest or {})
        self._guide_cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def from_root(cls, root: Path = ROOT, pages_dir: Optional[Path] = None) -> "IdentityContext":
        root = Path(root)
        files = {
            "topic_manifest": "data/topic_manifest.json", "source_manifest": "data/source_manifest.json",
            "corrections": "data/topic_corrections.json", "registrations": "data/guide_registrations.json",
            "registry": "data/guide_registry.json", "final_corpus_manifest": "data/final_corpus_manifest.json",
            "retrieval_units": "data/retrieval_units.json",
        }
        raw = {k: _read_json(root / v) for k, v in files.items()}
        topic_manifest = {int(t["topic_id"]): t for t in (raw["topic_manifest"] or {}).get("topics", [])}
        source_manifest = {int(d["id"]): d for d in (raw["source_manifest"] or {}).get("documents", [])}
        corrections = {int(c["topic_id"]): c for c in (raw["corrections"] or {}).get("corrections", [])}
        registrations = {str(r["guide_id"]).lower(): r for r in (raw["registrations"] or {}).get("registrations", [])}
        registry = {str(k).lower(): v for k, v in ((raw["registry"] or {}).get("guides") or {}).items()}

        # Saved TOCs: a registration's toc_file (or data/toc/<guide>.json), else the registry's toc_file.
        tocs: Dict[str, Optional[TocInfo]] = {}
        for gid in sorted(set(registrations) | set(registry)):
            cand: List[str] = []
            if registrations.get(gid, {}).get("toc_file"):
                cand.append(registrations[gid]["toc_file"])
            cand.append(f"data/toc/{gid}.json")
            if registry.get(gid, {}).get("toc_file"):
                cand.append(registry[gid]["toc_file"])
            info = None
            for c in cand:
                p = root / c
                if p.is_file():
                    info = load_toc(p, gid, root)
                    if info is not None:
                        break
            tocs[gid] = info
        index = PageContentIndex.from_directory(pages_dir if pages_dir is not None else root / "data" / "sap_help" / "pages")
        input_files = {v: _sha256(root / v) for v in sorted(files.values())}
        for info in sorted((t for t in tocs.values() if t), key=lambda t: t.file):
            input_files[info.file] = _sha256(root / info.file)
        caps = load_captures(root)
        for c in caps:
            input_files[c.file] = _sha256(root / c.file)
        return cls(root, topic_manifest, source_manifest, corrections, registrations, registry, tocs, caps, index, input_files,
                   raw["final_corpus_manifest"])

    # -- guide verification ---------------------------------------------------------------------------------------------
    def guide_status(self, guide_id: Optional[str]) -> Dict[str, Any]:
        """Explicit verification record for one guide; ``verified`` is True only under the rules in the rules file."""
        gid = (guide_id or "").lower()
        if gid in self._guide_cache:
            return self._guide_cache[gid]
        reg = self.registrations.get(gid)
        rg = self.registry.get(gid)
        toc = self.tocs.get(gid)
        declared = reg.get("verification") if reg else None
        rec: Dict[str, Any] = {
            "guide_id": gid,
            "declared_verification": declared,
            "registry_json_status": rg.get("fetch_identifiers_status") if rg else None,
            "numeric_deliverable_id_declared": (reg or {}).get("numeric_id") or (rg or {}).get("numeric_deliverable_id"),
            "toc_file": toc.file if toc else None,
            "toc_loio_equals_guide_id": toc.loio_matches if toc else None,
            "toc_node_count": toc.node_count if toc else 0,
            "capture_check": None, "verified": False, "verification_basis": None, "reasons": [],
        }
        if reg is not None:
            if declared != _VERIFIED:
                rec["reasons"].append(f"registration verification is {str(declared)[:60]!r}, not {_VERIFIED!r}")
            elif toc is None:
                rec["reasons"].append("no readable saved TOC")
            elif not toc.loio_matches:
                rec["reasons"].append(f"saved TOC loio {toc.loio} differs from the guide id")
            else:
                wanted = {p.lower() for p in reg.get("captured_page_ids") or []}
                hits = [c for c in self.captures if c.response_loio == gid and c.current_page_id in wanted]
                rec["capture_check"] = {"captured_page_ids_declared": sorted(wanted),
                                        "matching_saved_responses": [c.file for c in hits], "passed": bool(hits)}
                if hits:
                    rec["verified"], rec["verification_basis"] = True, "registration_response_loio_verified_and_machine_checked"
                else:
                    rec["reasons"].append("no saved captured response with deliverable.loio == guide id and a declared captured page")
        elif rg is not None and rg.get("fetch_identifiers_status") == "verified" and toc is not None and toc.loio_matches:
            rec["verified"], rec["verification_basis"] = True, "registry_local_evidence_only"
            rec["reasons"].append(REGISTRY_ONLY_GUIDE_NOTE)
        else:
            rec["reasons"].append("no registration and no verified registry entry with a matching saved TOC")
        self._guide_cache[gid] = rec
        return rec

    def known_guides(self) -> List[str]:
        return sorted(set(self.registrations) | set(self.registry))


# ---- card loading -----------------------------------------------------------------------------------------------------
def load_cards(root: Path = ROOT) -> List[Dict[str, Any]]:
    """The 29 card records exactly as the router sees them (``data/retrieval_units.json`` -> ``units``), in source order."""
    data = _read_json(Path(root) / "data" / "retrieval_units.json") or {}
    return sorted((dict(u) for u in data.get("units", [])), key=lambda u: int(u.get("source_number") or 0))


def _card_number(card: Any) -> Optional[int]:
    n = _field(card, "source_number")
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    m = re.search(r"(\d+)\s*$", str(_field(card, "source_id") or ""))
    return int(m.group(1)) if m else None


# ---- resolver ---------------------------------------------------------------------------------------------------------
def _toc_membership(ctx: IdentityContext, guide_id: str, page_id: str) -> Dict[str, Any]:
    toc = ctx.tocs.get(guide_id)
    return {"kind": "toc_membership", "authority": A_TOC, "guide_id": guide_id,
            "toc_file": toc.file if toc else None, "toc_available": toc is not None,
            "page_is_toc_node": bool(toc and page_id in toc.page_ids),
            "page_is_landing_page": bool(toc and toc.landing_page == page_id),
            "toc_node_count": toc.node_count if toc else 0}


def _correction_check(ctx: IdentityContext, corr: Mapping[str, Any]) -> Dict[str, Any]:
    """Re-read the correction's saved_response evidence; the user-reported browser observation is never machine evidence."""
    checks: List[Dict[str, Any]] = []
    for ev in corr.get("evidence", []):
        if ev.get("kind") == "saved_response":
            cap = next((c for c in ctx.captures if c.file == ev.get("file")), None)
            ok = bool(cap and cap.response_loio == str(corr.get("resolved_guide_id")).lower()
                      and cap.current_page_id == str(corr.get("card_page_id")).lower())
            checks.append({"kind": "saved_response", "file": ev.get("file"), "machine_checked": True, "passed": ok,
                           "response_loio": cap.response_loio if cap else None,
                           "current_page_id": cap.current_page_id if cap else None,
                           "numeric_deliverable_id": cap.numeric_deliverable_id if cap else None,
                           "note": ev.get("note")})
        else:
            checks.append({"kind": ev.get("kind"), "machine_checked": False, "passed": None,
                           "machine_verified_declared": ev.get("machine_verified"), "date": ev.get("date"),
                           "observation": ev.get("observation")})
    machine = [c for c in checks if c["machine_checked"]]
    return {"evidence_items": checks, "machine_checked_passed": bool(machine) and all(c["passed"] for c in machine)}


def resolve_identity(card: Any, ctx: IdentityContext) -> PageIdentity:
    source_id = _field(card, "source_id") if card is not None else None
    if card is None or not source_id:
        return PageIdentity(None, None, None, None, None, None, None, B_CARD_MISSING, UNRESOLVED, None, False,
                            ({"kind": "card", "authority": A_CARD, "detail": "no card record"},))
    sid, title = str(source_id), _field(card, "title")
    url = _field(card, "source_url")
    st, ust = _field(card, "source_status"), _field(card, "source_url_status")

    def early(basis: str) -> PageIdentity:
        return PageIdentity(sid, title, url if isinstance(url, str) else None, None, None, None, None, basis, UNRESOLVED, None, False,
                            ({"kind": "card", "authority": A_CARD, "detail": basis},), st, ust)

    if not url or not isinstance(url, str) or not url.strip():
        return early(B_NO_URL)
    ids = parse_source_url(url)
    if ids is None:
        return early(B_URL_NOT_PARSEABLE)
    g, p = ids
    number = _card_number(card)
    evidence: List[Dict[str, Any]] = []
    disagreements: List[Dict[str, Any]] = []

    # 1. card-level cross-checks (recorded, never reconciled)
    sm = ctx.source_manifest.get(number) if number is not None else None
    tm = ctx.topic_manifest.get(number) if number is not None else None
    if sm is not None:
        if sm.get("authoritative_source") != url:
            disagreements.append({"field": "card_url", "a": "router/units source_url", "a_value": url,
                                  "b": "data/source_manifest.json authoritative_source", "b_value": sm.get("authoritative_source")})
    if tm is not None:
        if tm.get("url_as_given") != url:
            disagreements.append({"field": "card_url", "a": "router/units source_url", "a_value": url,
                                  "b": "data/topic_manifest.json url_as_given", "b_value": tm.get("url_as_given")})
        for fld, val in (("guide_id", g), ("page_id", p)):
            if str(tm.get(fld, "")).lower() != val:
                disagreements.append({"field": f"card_{fld}", "a": "parsed from card URL", "a_value": val,
                                      "b": f"data/topic_manifest.json {fld}", "b_value": tm.get(fld)})
    reasons = list((sm or {}).get("source_url_reasons") or [])
    evidence.append({"kind": "card", "authority": A_CARD, "source_number": number, "card_url_query": _query_of(url),
                     "source_status": st, "source_url_status": ust,
                     "source_url_status_reasons": reasons,
                     "topic_manifest_warnings": list((tm or {}).get("warnings") or []),
                     "source_manifest_present": sm is not None, "topic_manifest_present": tm is not None})

    # 2. the card guide's verification + TOC membership
    card_guide = ctx.guide_status(g)
    evidence.append({"kind": "guide_registration", "authority": "guide_registrations.json", "role": "card_guide", **card_guide})
    card_mem = _toc_membership(ctx, g, p)
    evidence.append({**card_mem, "role": "card_guide"})

    # 3. evidence that is never authoritative: captures placing the page under another loio, other TOCs, map roots
    corr = ctx.corrections.get(number) if number is not None else None
    corr_guide = str(corr.get("resolved_guide_id")).lower() if corr else None
    foreign_caps = [c for c in ctx.captures if c.current_page_id == p and c.response_loio != g]
    for c in foreign_caps:
        supports = corr is not None and c.response_loio == corr_guide
        evidence.append({
            "kind": "captured_response", "authority": A_CORRECTION if supports else A_PROBE, "file": c.file,
            "numeric_deliverable_id": c.numeric_deliverable_id, "response_loio": c.response_loio,
            "response_deliverable_title": c.deliverable_title, "current_page_id": c.current_page_id,
            "current_page_title": c.current_page_title, "response_toc_nodes": c.toc_nodes_in_response,
            "response_loio_is_card_guide": False,
            "response_loio_registered_verified": ctx.guide_status(c.response_loio)["verified"],
            "used_as_effective_guide": False,
            "meaning": ("page exists inside that deliverable; it does not prove SAP serves the original card URL from it"
                        + ("; referenced by the topic correction" if supports else ""))})
    other_toc = sorted(i.loio for i in ctx.tocs.values() if i and i.loio != g and p in i.page_ids)
    if other_toc:
        evidence.append({"kind": "page_also_in_other_saved_toc", "authority": A_HINT, "guide_ids": other_toc,
                         "meaning": "a page id in another guide's TOC is not evidence about the card's guide"})
    roots = sorted(i.loio for i in ctx.tocs.values() if i and i.map_root == p)
    if roots:
        evidence.append({"kind": "page_is_map_root_of_saved_toc", "authority": A_HINT, "guide_ids": roots,
                         "meaning": "map root of that guide's saved TOC; card guide segment differs; NOT confirmed"})
    seen_elsewhere = bool(foreign_caps or other_toc)

    eff_g: Optional[str] = None
    eff_p: Optional[str] = None
    status = UNRESOLVED
    basis = B_PAGE_NOT_IN_TOC

    # 4. resolution order (see rules file section 3)
    if corr is not None:
        chk = _correction_check(ctx, corr)
        rgs = ctx.guide_status(corr_guide)
        rmem = _toc_membership(ctx, corr_guide, p)
        match = (str(corr.get("card_guide_id", "")).lower() == g and str(corr.get("card_page_id", "")).lower() == p)
        evidence.append({"kind": "correction", "authority": A_CORRECTION, "topic_id": corr.get("topic_id"),
                         "card_guide_id": corr.get("card_guide_id"), "card_page_id": corr.get("card_page_id"),
                         "resolved_guide_id": corr_guide, "reason": corr.get("reason"),
                         "correction_matches_card_ids": match, "machine_checked_saved_response_passed": chk["machine_checked_passed"],
                         "evidence_items": chk["evidence_items"],
                         "registers_a_guide": False, "card_record_modified": False})
        evidence.append({"kind": "guide_registration", "authority": "guide_registrations.json", "role": "corrected_guide", **rgs})
        evidence.append({**rmem, "role": "corrected_guide"})
        if sm is not None and corr.get("card_url") != sm.get("authoritative_source"):
            disagreements.append({"field": "card_url", "a": "data/topic_corrections.json card_url", "a_value": corr.get("card_url"),
                                  "b": "data/source_manifest.json authoritative_source", "b_value": sm.get("authoritative_source")})
        if match and rgs["verified"] and rmem["page_is_toc_node"] and chk["machine_checked_passed"]:
            status, basis, eff_g, eff_p = CORRECTED_IDENTITY, B_CORRECTION, corr_guide, p
        else:
            why = []
            if not match:
                why.append("CORRECTION_DOES_NOT_MATCH_CARD")
            if not rgs["verified"]:
                why.append("CORRECTED_GUIDE_NOT_VERIFIED")
            if not rmem["page_is_toc_node"]:
                why.append("PAGE_NOT_IN_CORRECTED_GUIDE_TOC")
            if not chk["machine_checked_passed"]:
                why.append("CORRECTION_SAVED_RESPONSE_NOT_CONFIRMED")
            status, basis = CONFLICTING_IDENTITY, B_CORRECTION_REJECTED
            evidence.append({"kind": "conflict", "authority": "resolver", "reasons": why,
                             "meaning": "the correction is not honoured; no identity is chosen"})
    elif card_guide["verified"] and card_mem["page_is_toc_node"]:
        eff_g, eff_p = g, p
        status, basis = IDENTIFIED_NOT_LOCAL, B_TOC_ONLY
    elif card_guide["verified"]:
        if seen_elsewhere:
            status, basis = CONFLICTING_IDENTITY, B_PAGE_NOT_IN_TOC_OTHER
            evidence.append({"kind": "conflict", "authority": "resolver",
                             "reasons": ["PAGE_NOT_A_NODE_OF_CARD_GUIDE_TOC", "PAGE_SEEN_IN_OTHER_DELIVERABLE"],
                             "card_guide_id": g, "other_loios_seen": sorted({c.response_loio for c in foreign_caps} | set(other_toc)),
                             "meaning": "the card's guide TOC does not contain the page; other evidence exists but is not authoritative; "
                                        "no effective identity is chosen"})
        else:
            status, basis = UNRESOLVED, B_PAGE_NOT_IN_TOC
    else:
        if foreign_caps:
            status, basis = CONFLICTING_IDENTITY, B_UNVERIFIED_GUIDE_OTHER
            evidence.append({"kind": "conflict", "authority": "resolver",
                             "reasons": ["CARD_GUIDE_UNVERIFIED", "PAGE_SEEN_UNDER_OTHER_GUIDE", "NO_CORRECTION"],
                             "other_loios_seen": sorted({c.response_loio for c in foreign_caps}),
                             "meaning": "no correction exists; no effective identity is chosen"})
        else:
            status, basis = CARD_IDENTITY_ONLY, B_CARD_ONLY

    # 5. local availability: effective identity only
    local_path: Optional[str] = None
    local_ok = False
    if eff_g is not None and eff_p is not None:
        rec = ctx.page_index.get(eff_g, eff_p)
        if rec is not None:
            evidence.append({"kind": "local_page_record", "authority": A_LOCAL, "counted": rec.usable, "path": rec.path,
                             "status": rec.status, "text_chars": rec.text_chars, "record_topic_ids": list(rec.topic_ids)})
            if rec.usable:
                local_ok, local_path = True, rec.path
    else:
        rec = ctx.page_index.get(g, p)
        if rec is not None:
            evidence.append({"kind": "local_page_record", "authority": A_LOCAL, "counted": False, "path": rec.path,
                             "status": rec.status, "text_chars": rec.text_chars,
                             "meaning": "found under the card's own ids while no effective identity is established; not counted"})
    if local_ok and status == IDENTIFIED_NOT_LOCAL:
        status, basis = RESOLVED_LOCAL_PAGE, B_LOCAL_RECORD
    return PageIdentity(sid, title, url, g, p, eff_g, eff_p, basis, status, local_path, local_ok, tuple(evidence), st, ust,
                        tuple(disagreements))


def resolve_all(ctx: IdentityContext, cards: Optional[Sequence[Any]] = None) -> List[PageIdentity]:
    cards = load_cards(ctx.root) if cards is None else cards
    return [resolve_identity(c, ctx) for c in cards]


# ---- local page validation (M2C-17 style end-to-end check; read-only) ------------------------------------------------
def validate_local_page(identity: PageIdentity, root: Path = ROOT) -> Dict[str, Any]:
    """card -> identity -> local path -> page JSON -> non-empty text. Reads the page; never writes; never returns the text."""
    out: Dict[str, Any] = {"source_id": identity.source_id, "checks": {}, "ok": False}
    c = out["checks"]
    c["identity_says_local"] = identity.local_page_available
    if not identity.local_page_available or not identity.local_page_path:
        return out
    path = Path(root) / identity.local_page_path
    c["path_exists"] = path.is_file()
    rec = _read_json(path) if path.is_file() else None
    c["json_valid"] = isinstance(rec, dict)
    if not isinstance(rec, dict):
        return out
    text = str(rec.get("text") or "")
    c["status_ok"] = rec.get("status") == "OK"
    c["text_non_empty"] = bool(text.strip())
    c["record_guide_id_equals_effective"] = str(rec.get("guide_id", "")).lower() == identity.effective_guide_id
    c["record_page_id_equals_effective"] = str(rec.get("page_id", "")).lower() == identity.effective_page_id
    c["path_matches_ids"] = path.parent.name.lower() == identity.effective_guide_id and path.stem.lower() == identity.effective_page_id
    c["record_guide_id_equals_card_guide"] = str(rec.get("guide_id", "")).lower() == identity.card_guide_id
    c["record_page_id_equals_card_page"] = str(rec.get("page_id", "")).lower() == identity.card_page_id
    tids = rec.get("topic_ids")
    if isinstance(tids, str):
        try:
            tids = json.loads(tids)
        except ValueError:
            tids = []
    c["record_topic_ids_include_card"] = bool(tids) and str(_num(identity.source_id)) in {str(t) for t in tids}
    out["record"] = {"doc_id": rec.get("doc_id"), "status": rec.get("status"), "page_title": rec.get("page_title"),
                     "topic_ids": tids, "source_type": rec.get("source_type"), "fetched_via": rec.get("fetched_via"),
                     "source_url": rec.get("source_url"), "canonical_url": rec.get("canonical_url"),
                     "text_chars": len(text.strip()), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     "file_sha256": _sha256(path)}
    out["ok"] = all(bool(v) for v in c.values())
    return out


def _num(source_id: Optional[str]) -> int:
    m = re.search(r"(\d+)\s*$", str(source_id or ""))
    return int(m.group(1)) if m else -1


# ---- query -> card -> identity (composition; the 7A join and orchestrator are unchanged) ---------------------------------
@dataclass(frozen=True)
class IdentityRoute:
    query: str
    route_state: str                        # the identity status of the selected card, or no_card_candidate
    selected_source_id: Optional[str]
    identity: Optional[PageIdentity]
    page_content_available: bool
    local_page_path: Optional[str]
    fallback_reason: Optional[str]          # None only when route_state == resolved_local_page
    join_state_7a: Optional[str]            # state the unchanged 7A join reports for the same card
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {"query": self.query, "route_state": self.route_state, "selected_source_id": self.selected_source_id,
                "identity": self.identity.to_dict() if self.identity else None,
                "page_content_available": self.page_content_available, "local_page_path": self.local_page_path,
                "fallback_reason": self.fallback_reason, "join_state_7a": self.join_state_7a, "warnings": list(self.warnings)}


def route_to_identity(query: str, backend: Any, ctx: IdentityContext, top_k: Optional[int] = None, selector: Any = None) -> IdentityRoute:
    """query -> card router -> selected card -> page identity. Generates no answer and carries no page text."""
    from m2c_orchestrator import select_top_ranked, route_to_page  # imported lazily: keeps this module importable on its own
    from m2c_router import DEFAULT_TOP_K
    outcome = route_to_page(query, backend, ctx.page_index, top_k=top_k or DEFAULT_TOP_K, selector=selector or select_top_ranked)
    if outcome.selected_card is None:
        return IdentityRoute(query, NO_CARD_CANDIDATE, None, None, False, None, outcome.fallback_reason, None)
    ident = resolve_identity(outcome.selected_card, ctx)
    warns: List[str] = []
    if outcome.page_content_available != ident.local_page_available:
        warns.append("the 7A join (card ids) and the identity layer (effective ids) disagree about local content")
    if ident.resolution_status == CONFLICTING_IDENTITY:
        warns.append("conflicting identity: no effective page is chosen")
    if ident.card_needs_review:
        warns.append("card is marked needs_review")
    reason = None if ident.resolution_status == RESOLVED_LOCAL_PAGE else ident.resolution_basis
    return IdentityRoute(query, ident.resolution_status, ident.source_id, ident, ident.local_page_available, ident.local_page_path,
                         reason, outcome.state, tuple(warns))


# ---- whole-audit document ---------------------------------------------------------------------------------------------
def build_audit(ctx: IdentityContext, cards: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    idents = resolve_all(ctx, cards)
    counts: Dict[str, int] = {s: 0 for s in STATUSES}
    for i in idents:
        counts[i.resolution_status] += 1
    guides = []
    card_guides: Dict[str, List[int]] = {}
    for i in idents:
        if i.card_guide_id:
            card_guides.setdefault(i.card_guide_id, []).append(_num(i.source_id))
    for gid in sorted(set(ctx.known_guides()) | set(card_guides)):
        gs = dict(ctx.guide_status(gid))
        gs["card_topic_ids"] = sorted(card_guides.get(gid, []))
        gs["corrected_topic_ids_resolving_here"] = sorted(t for t, c in ctx.corrections.items() if str(c.get("resolved_guide_id")).lower() == gid)
        toc = ctx.tocs.get(gid)
        gs["toc"] = toc.to_dict() if toc else None
        guides.append(gs)
    fm = ctx.stale_final_manifest
    return {
        "schema_version": 1,
        "rules": "data/m2c_page_identity_rules.md",
        "card_count": len(idents),
        "status_counts": counts,
        "local_usable_page_records_in_index": sum(1 for p in ctx.page_index._pages.values() if p.usable),
        "local_page_records_in_index": len(ctx.page_index),
        "cards_with_local_page": [i.source_id for i in idents if i.local_page_available],
        "local_page_validation": [validate_local_page(i, ctx.root) for i in idents if i.local_page_available],
        "guides": guides,
        "guide_verification_summary": {
            "guides_known": len(guides), "guides_verified": sum(1 for g in guides if g["verified"]),
            "verified_by_registration": sum(1 for g in guides if g["verification_basis"] == "registration_response_loio_verified_and_machine_checked"),
            "verified_by_registry_local_evidence_only": sum(1 for g in guides if g["verification_basis"] == "registry_local_evidence_only"),
            "saved_tocs_readable": sum(1 for g in guides if g["toc"]),
            "saved_tocs_in_data_toc": sum(1 for g in guides if g["toc"] and g["toc"]["file"].startswith("data/toc/")),
        },
        "stale_sources": {
            "data/guide_registry.json": {gs["guide_id"][:8]: gs["registry_json_status"] for gs in guides},
            "data/final_corpus_manifest.json": {"topic_status_counts": fm.get("topic_status_counts"),
                                                "completeness": fm.get("completeness")},
            "note": "recorded as written; superseded by the registrations + saved TOCs; not silently preferred or ignored",
        },
        "inputs_sha256": ctx.input_files,
        "cards": [i.to_dict() for i in idents],
    }


def write_identity_json(audit: Mapping[str, Any], path: Path) -> None:
    Path(path).write_text(json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def render_json(audit: Mapping[str, Any]) -> str:
    return json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _short(x: Optional[str]) -> str:
    return (x[:8] + "\u2026") if x else "\u2014"


def render_report(audit: Mapping[str, Any]) -> str:
    cards = audit["cards"]
    L: List[str] = []
    a = L.append
    sc = audit["status_counts"]
    a("# M2C card -> SAP page identity report (Phase 7C)")
    a("")
    a("Generated by `scripts/m2c_page_identity.py` from local files only (deterministic; no network; no scraping; no ingestion). "
      "Rules: `data/m2c_page_identity_rules.md`. Full ids, every piece of evidence and every disagreement: `data/m2c_page_identity.json`.")
    a("")
    a("## 1. Result")
    a("")
    a(f"* Cards audited: **{audit['card_count']}**.")
    a("* Status counts: " + ", ".join(f"`{k}` {v}" for k, v in sc.items()) + ".")
    a(f"* Usable local page records (valid record, status OK, non-empty text): **{audit['local_usable_page_records_in_index']}** "
      f"({audit['local_page_records_in_index']} record file(s) indexed). Cards with local content: {', '.join(audit['cards_with_local_page']) or 'none'}.")
    g = audit["guide_verification_summary"]
    a(f"* Guides: {g['guides_known']} known, {g['guides_verified']} verified ({g['verified_by_registration']} by registration + machine-checked saved response, "
      f"{g['verified_by_registry_local_evidence_only']} by the registry's local-evidence entry only), {g['guides_known'] - g['guides_verified']} not verified. "
      f"Saved TOCs: {g['saved_tocs_in_data_toc']} in `data/toc/` + {g['saved_tocs_readable'] - g['saved_tocs_in_data_toc']} in `master_data.json`.")
    a("* The earlier \"1 local + 28 not local\" baseline is confirmed for *local content*; the 28 are not one class: "
      f"{sc[IDENTIFIED_NOT_LOCAL]} identified (page is a node of a verified guide's saved TOC), {sc[CORRECTED_IDENTITY]} corrected, "
      f"{sc[CARD_IDENTITY_ONLY]} card-identity-only, {sc[CONFLICTING_IDENTITY]} conflicting.")
    a("")
    a("## 2. All cards")
    a("")
    a("Ids are shortened to 8 characters here (full values in the JSON). `\u2014` = no effective identity established (card_identity_only and conflicting_identity).")
    a("")
    a("| Source | Card title | Card guide | Card page | Effective guide | Effective page | Status | Local content |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in cards:
        loc = "yes: `" + c["local_page_path"] + "`" if c["local_page_available"] else "no"
        flag = " (needs_review)" if c["card_needs_review"] else ""
        a(f"| {c['source_id']} | {c['card_title']}{flag} | {_short(c['card_guide_id'])} | {_short(c['card_page_id'])} | "
          f"{_short(c['effective_guide_id'])} | {_short(c['effective_page_id'])} | `{c['resolution_status']}` | {loc} |")
    a("")

    def section(title: str, status: str, note: str, extra=None) -> None:
        a(f"## {title}")
        a("")
        rows = [c for c in cards if c["resolution_status"] == status]
        a(note)
        a("")
        if not rows:
            a("None.")
        for c in rows:
            a(f"* **{c['source_id']}** {c['card_title']} - basis `{c['resolution_basis']}`; card guide `{c['card_guide_id']}`, page `{c['card_page_id']}`; "
              f"effective guide `{c['effective_guide_id'] or 'none'}`, effective page `{c['effective_page_id'] or 'none'}`.")
            if extra:
                for line in extra(c):
                    a("  * " + line)
        a("")

    def conflict_lines(c: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        for e in c["evidence"]:
            if e["kind"] == "captured_response":
                out.append(f"evidence (`{e['authority']}`): `{e['file']}`, numeric id {e['numeric_deliverable_id']}, response loio `{e['response_loio']}` "
                           f"('{e['response_deliverable_title']}', page title '{e['current_page_title']}'); registered: {e['response_loio_registered_verified']}; "
                           f"used as effective guide: {e['used_as_effective_guide']}.")
            if e["kind"] == "toc_membership" and e.get("role") == "card_guide":
                out.append(f"card guide TOC `{e['toc_file']}` ({e['toc_node_count']} nodes): card page is a node: {e['page_is_toc_node']}.")
            if e["kind"] == "conflict":
                out.append(f"conflict reasons: {', '.join(e['reasons'])}.")
        out.append(f"card_needs_review: {c['card_needs_review']} (source status `{c['card_source_status']}`, URL status `{c['card_source_url_status']}`).")
        return out

    def hint_lines(c: Dict[str, Any]) -> List[str]:
        return [f"hint `{e['kind']}` ({e['authority']}): {[_short(x) for x in e['guide_ids']]} - {e['meaning']}."
                for e in c["evidence"] if e["kind"] in ("page_is_map_root_of_saved_toc", "page_also_in_other_saved_toc")]

    def corr_lines(c: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        for e in c["evidence"]:
            if e["kind"] == "correction":
                out.append(f"correction: card guide `{e['card_guide_id']}` -> `{e['resolved_guide_id']}`; matches card ids: {e['correction_matches_card_ids']}; "
                           f"machine-checked saved response passed: {e['machine_checked_saved_response_passed']}; registers a guide: {e['registers_a_guide']}; "
                           f"card record modified: {e['card_record_modified']}.")
                for it in e["evidence_items"]:
                    out.append(f"correction evidence `{it['kind']}`: machine_checked={it['machine_checked']}, passed={it['passed']}"
                               + (f", file `{it['file']}`" if it.get("file") else "") + (f" (declared machine_verified={it['machine_verified_declared']})" if "machine_verified_declared" in it else ""))
        return out

    section("3. Corrected identities", CORRECTED_IDENTITY,
            "A per-topic correction (`data/topic_corrections.json`) supplies the effective guide. The card record is unchanged, the corrected guide is verified, "
            "and the card's page is a node of its saved TOC. The correction registers nothing.", corr_lines)
    section("4. Conflicting identities", CONFLICTING_IDENTITY,
            "Evidence disagrees with the card and nothing authorises a choice. No effective identity is set; the other evidence is listed, never promoted.",
            conflict_lines)
    section("5. Unresolved", UNRESOLVED, "No usable card or URL, or the card's page is not in a verified guide's TOC and nothing else is known.")
    section("6. URL-only (card identity only)", CARD_IDENTITY_ONLY,
            "The card states a guide and page; the guide has no verified registration and no saved TOC, so nothing confirms that SAP serves the page from it. "
            "No effective identity is set (the card's own ids stay in the card columns); hints below are non-authoritative.", hint_lines)
    section("7. Locally resolved", RESOLVED_LOCAL_PAGE, "The page is a node of a verified guide's saved TOC and a usable local record exists.")
    a("## 8. Local page validation (card -> identity -> path -> JSON -> text)")
    a("")
    for v in audit["local_page_validation"]:
        a(f"* **{v['source_id']}**: ok = {v['ok']}; checks: " + ", ".join(f"{k}={val}" for k, val in v["checks"].items()) + ".")
        r = v.get("record") or {}
        a(f"  * record: doc_id `{r.get('doc_id')}`, title '{r.get('page_title')}', status {r.get('status')}, text {r.get('text_chars')} chars "
          f"(sha256 `{r.get('text_sha256')}`), source_type `{r.get('source_type')}`, fetched_via `{r.get('fetched_via')}`.")
    a("")
    a("## 9. Guides (declared vs stale vs checked)")
    a("")
    a("| Guide | Cards | Registration says | `guide_registry.json` (stale) says | Saved TOC | TOC loio = guide | Saved response check | Verified here | Basis |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for gd in audit["guides"]:
        t = gd["toc"]
        cc = gd["capture_check"]
        decl = (gd["declared_verification"] or "none")
        a(f"| {_short(gd['guide_id'])} | {', '.join(str(x) for x in gd['card_topic_ids'])} | {decl[:34]} | {gd['registry_json_status']} | "
          f"{t['file'] if t else 'none'} ({t['node_count'] if t else 0} nodes) | {t['toc_loio_equals_guide_id'] if t else '-'} | "
          f"{('passed' if cc['passed'] else 'failed') if cc else 'n/a'} | {gd['verified']} | {gd['verification_basis'] or '-'} |")
    a("")
    a("Stale sources recorded as written: `data/final_corpus_manifest.json` topic status counts "
      f"`{audit['stale_sources']['data/final_corpus_manifest.json']['topic_status_counts']}` (written before the registrations/TOCs); "
      "`data/guide_registry.json` marks every guide but e52c8ee6 `unresolved`.")
    a("")
    a("## 10. Preserved discrepancies")
    a("")
    a("| Item | Card | Where it is visible |")
    a("| --- | --- | --- |")
    by = {c["source_id"]: c for c in cards}
    for sid, what in (("M2C-05", "card guide 021b182b vs SAP-resolved guide 2ac7fe29 (correction)"),
                      ("M2C-18", "card guide 94424864 vs probe result e4375c1c (evidence only)"),
                      ("M2C-14", "URL `needs_review`: lower-case product segment (identity unaffected)"),
                      ("M2C-23", "URL `needs_review`: `?version=2025.001` (identity unaffected)")):
        c = by[sid]
        a(f"| {what} | {sid} | status `{c['resolution_status']}`, card_needs_review {c['card_needs_review']}; evidence in JSON |")
    a("")
    return "\n".join(L) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Phase 7C: write data/m2c_page_identity.json and the report (read-only over the repo inputs).")
    ap.add_argument("--out", default=str(ROOT / "data" / "m2c_page_identity.json"))
    ap.add_argument("--report", default=str(ROOT / "data" / "m2c_page_identity_report.md"))
    args = ap.parse_args(argv)
    audit = build_audit(IdentityContext.from_root(ROOT))
    write_identity_json(audit, Path(args.out))
    Path(args.report).write_text(render_report(audit), encoding="utf-8")
    print(f"{audit['card_count']} cards: {audit['status_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
