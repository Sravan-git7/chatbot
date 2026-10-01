"""Guide registry: one entry per SAP Help guide (identified by its 32-hex loio).

Why this exists: the legacy scraper hard-codes ``DELIVERABLE_ID=40374631`` and
``BUILD_NO=1779`` for the single guide whose TOC was saved. The cards carry seven
different guide loios; the ``pagecontent`` API used by the scraper takes a *numeric*
deliverable id + build number, and nothing local links those to the other six loios.
The registry therefore stores, per guide:

* ``guide_id``             32-hex loio (from the card URLs; the identity used everywhere)
* ``numeric_deliverable_id`` / ``build_no``   what the API mechanism needs, or ``null``
* ``toc_file``             local saved TOC (pagecontent?deliverableInfo=1 response), or ``null``
* ``fetch_identifiers_status``  ``verified`` | ``unresolved`` (never ``guessed``)
* ``evidence``             why we believe the binding (list of strings)

Numeric ids / build numbers are ONLY ever filled from local evidence or by a human
editing the registry file. ``refresh_registry`` never overwrites a non-null value
and never invents one.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .toc import TocError, TocTree

REGISTRY_SCHEMA_VERSION = 1
LEGACY_SCRAPER = "fetch_sap_pages.py"
LEGACY_TOC = "master_data.json"
LEGACY_PAGES_DIR = "sap_pages"


def _legacy_constants(repo_root: Path) -> Dict[str, str]:
    """Read DELIVERABLE_ID / BUILD_NO from the scraper source without importing it
    (importing would start scraping)."""
    src = (repo_root / LEGACY_SCRAPER)
    if not src.is_file():
        return {}
    out: Dict[str, str] = {}
    for node in ast.parse(src.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("DELIVERABLE_ID", "BUILD_NO") and isinstance(node.value, ast.Constant):
                out[name] = str(node.value.value)
    return out


def _legacy_pages_numeric_ids(repo_root: Path) -> set:
    ids = set()
    for p in sorted((repo_root / LEGACY_PAGES_DIR).glob("*.json")):
        try:
            url = json.loads(p.read_text(encoding="utf-8")).get("source_url", "")
        except (OSError, ValueError):
            continue
        m = re.search(r"/docs/[^/]+/(\d+)/", url)
        if m:
            ids.add(m.group(1))
    return ids


def _landing_text_from_response(data: Dict[str, Any]) -> Optional[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    body = (data.get("data") or {}).get("body")
    return BeautifulSoup(body, "html.parser").get_text("\n", strip=True) if body else None


def discover_local_evidence(repo_root: Path) -> Dict[str, Dict[str, Any]]:
    """Guide bindings that the *local files* actually prove. Returns {loio: entry-fields}."""
    toc_path = repo_root / LEGACY_TOC
    if not toc_path.is_file():
        return {}
    try:
        raw = json.loads(toc_path.read_text(encoding="utf-8"))
        tree = TocTree.from_pagecontent_response(raw)
    except (OSError, ValueError, TocError):
        return {}
    entry: Dict[str, Any] = {
        "title": tree.title, "version": tree.version, "language": tree.language,
        "toc_file": LEGACY_TOC, "toc_node_count": len(tree),
        "landing_page_id": tree.landing_page[:-5] if tree.landing_page.endswith(".html") else tree.landing_page,
        "map_root_page_id": tree.map_root_page_id,
        "numeric_deliverable_id": None, "build_no": None,
        "fetch_identifiers_status": "unresolved", "evidence": [],
    }
    consts = _legacy_constants(repo_root)
    numeric_in_pages = _legacy_pages_numeric_ids(repo_root)
    did, build = consts.get("DELIVERABLE_ID"), consts.get("BUILD_NO")
    if did and did in numeric_in_pages:
        # The scraper iterated exactly this TOC (master_data.json) with these constants and
        # the 81 saved pages carry that numeric id. Check the strongest available proof
        # that numeric id and loio are the same guide: identical landing-page text.
        page1 = repo_root / LEGACY_PAGES_DIR / "001.json"
        same_landing = False
        if page1.is_file():
            landing = _landing_text_from_response(raw)
            same_landing = landing is not None and landing == json.loads(page1.read_text(encoding="utf-8")).get("text")
        if same_landing:
            entry.update(numeric_deliverable_id=did, build_no=build, fetch_identifiers_status="verified")
            entry["evidence"] += [
                f"{LEGACY_SCRAPER}: DELIVERABLE_ID={did}, BUILD_NO={build}; iterates the TOC saved in {LEGACY_TOC}",
                f"{LEGACY_PAGES_DIR}/*.json source_url use numeric id {did}",
                f"{LEGACY_PAGES_DIR}/001.json text is byte-identical to the landing-page body in {LEGACY_TOC} "
                f"(loio {tree.guide_id}) -> numeric {did} and loio {tree.guide_id[:8]}... serve the same content",
            ]
        else:
            entry["evidence"].append(
                f"numeric id {did} found in scraper/pages but landing-page content match could not be shown; left unresolved")
    else:
        entry["evidence"].append("no numeric deliverable id evidence found in local scraper/pages")
    return {tree.guide_id: entry}


def _blank_entry(guide_id: str, product: str) -> Dict[str, Any]:
    return {"guide_id": guide_id, "product": product, "title": None, "version": None,
            "numeric_deliverable_id": None, "build_no": None, "toc_file": None,
            "fetch_identifiers_status": "unresolved",
            "evidence": ["guide id known only from reference-card URL(s); no local TOC and no numeric "
                         "deliverable id / build number in local files"]}


def refresh_registry(topic_manifest: Dict[str, Any], repo_root: Path,
                     existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the registry from the topic manifest + local evidence, preserving any
    non-null value already present in ``existing`` (hand-entered ids win over nothing,
    and are never blanked)."""
    existing_guides = (existing or {}).get("guides", {})
    local = discover_local_evidence(repo_root)
    guides: Dict[str, Dict[str, Any]] = {}
    for g in topic_manifest["guides"]:
        gid = g["guide_id"]
        entry = _blank_entry(gid, g["product"])
        if gid in local:
            entry.update(local[gid])
        prev = existing_guides.get(gid, {})
        for k, v in prev.items():
            if v not in (None, [], "") and k not in ("evidence", "topic_ids") and entry.get(k) in (None, "", "unresolved"):
                entry[k] = v
        if prev.get("evidence"):
            entry["evidence"] = list(dict.fromkeys(entry["evidence"] + prev["evidence"]))
        entry["guide_id"] = gid
        entry["topic_ids"] = list(g["topic_ids"])
        if entry["numeric_deliverable_id"] and entry["build_no"] and entry["fetch_identifiers_status"] != "verified":
            entry["fetch_identifiers_status"] = "manual_unverified"
        guides[gid] = entry
    # guides that exist only in local evidence (not referenced by any card) are still recorded
    for gid, ent in local.items():
        if gid not in guides:
            guides[gid] = {**_blank_entry(gid, ""), **ent, "guide_id": gid, "topic_ids": []}
    return {"registry_schema_version": REGISTRY_SCHEMA_VERSION,
            "note": "numeric_deliverable_id/build_no are never guessed; null = unresolved. "
                    "Edit by hand only with evidence, and add it to 'evidence'.",
            "guides": dict(sorted(guides.items(), key=lambda kv: (kv[1]["topic_ids"] or [999])[0]))}


class GuideRegistry:
    def __init__(self, data: Dict[str, Any], repo_root: Path):
        self.data = data
        self.repo_root = Path(repo_root)
        self.guides: Dict[str, Dict[str, Any]] = data.get("guides", {})

    @classmethod
    def load(cls, path: Path, repo_root: Path) -> "GuideRegistry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), repo_root)

    def get(self, guide_id: str) -> Optional[Dict[str, Any]]:
        return self.guides.get(guide_id.lower())

    def fetch_ready(self, guide_id: str) -> bool:
        g = self.get(guide_id)
        return bool(g and g.get("numeric_deliverable_id") and g.get("build_no"))

    def load_toc(self, guide_id: str) -> TocTree:
        """Load the guide's saved TOC. Raises FileNotFoundError / TocError."""
        g = self.get(guide_id)
        if not g or not g.get("toc_file"):
            raise FileNotFoundError(f"no saved TOC registered for guide {guide_id}")
        p = Path(g["toc_file"])
        p = p if p.is_absolute() else self.repo_root / p
        tree = TocTree.from_file(p)
        if tree.guide_id != guide_id.lower():
            raise TocError(f"TOC file {p.name} is guide {tree.guide_id}, registry says {guide_id}")
        return tree


class RegistrationError(ValueError):
    pass


def register_guide(registry: Dict[str, Any], topic_manifest: Dict[str, Any], toc_response: Dict[str, Any],
                   toc_dest: Path, repo_root: Path, numeric_id: Optional[str] = None,
                   build_no: Optional[str] = None, evidence: str = "") -> Dict[str, Any]:
    """Register a guide from *human-supplied* artifacts (a saved ``pagecontent?deliverableInfo=1``
    response, and optionally the numeric deliverable id + build number taken from the same
    browser/API request). Nothing is discovered or guessed here.

    Safety rules: the TOC's own loio must be one of the manifest's guides; an existing
    non-null numeric id / build number / TOC is never silently replaced by a different value;
    supplied ids are recorded as ``manual_unverified`` (this code cannot prove numeric<->loio).
    """
    tree = TocTree.from_pagecontent_response(toc_response)
    guide_ids = {g["guide_id"] for g in topic_manifest["guides"]}
    if tree.guide_id not in guide_ids:
        raise RegistrationError(f"TOC loio {tree.guide_id} is not a guide referenced by any topic card")
    entry = registry["guides"].setdefault(tree.guide_id, _blank_entry(tree.guide_id, ""))
    for key, new in (("numeric_deliverable_id", numeric_id), ("build_no", build_no)):
        if new is not None:
            if not re.fullmatch(r"\d+", str(new)):
                raise RegistrationError(f"{key} must be digits, got {new!r}")
            old = entry.get(key)
            if old not in (None, "") and str(old) != str(new):
                raise RegistrationError(f"refusing to overwrite {key}={old!r} with {new!r}; edit the registry by hand if intended")
    toc_dest = Path(toc_dest)
    if toc_dest.exists() and json.loads(toc_dest.read_text(encoding="utf-8")) != toc_response:
        raise RegistrationError(f"{toc_dest} already exists with different content; not overwriting")
    toc_dest.parent.mkdir(parents=True, exist_ok=True)
    toc_dest.write_text(json.dumps(toc_response, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    try:
        rel = str(toc_dest.resolve().relative_to(Path(repo_root).resolve()))
    except ValueError:
        rel = str(toc_dest)
    entry.update(title=tree.title, version=tree.version, language=tree.language, toc_file=rel,
                 toc_node_count=len(tree), landing_page_id=tree.landing_page[:-5], map_root_page_id=tree.map_root_page_id)
    if numeric_id is not None:
        entry["numeric_deliverable_id"] = str(numeric_id)
    if build_no is not None:
        entry["build_no"] = str(build_no)
    if entry.get("numeric_deliverable_id") and entry.get("build_no") and entry.get("fetch_identifiers_status") != "verified":
        entry["fetch_identifiers_status"] = "manual_unverified"
    entry["evidence"] = list(dict.fromkeys(entry.get("evidence", []) + [
        f"user-supplied TOC response ({len(tree)} nodes, loio {tree.guide_id}) saved as {rel}"
        + (f"; numeric id {numeric_id}/build {build_no} supplied by user, NOT machine-verified" if numeric_id else "")
        + (f"; note: {evidence}" if evidence else "")]))
    entry["topic_ids"] = [t for g in topic_manifest["guides"] if g["guide_id"] == tree.guide_id for t in g["topic_ids"]]
    return registry


# --------------------------------------------------------------------------------------------------
# Declarative registrations: data/guide_registrations.json
# {"registrations": [{"guide_id": "...", "numeric_id": "123", "build_no": "456", "toc_file": "data/toc/<loio>.json",
#                     "evidence": "where these values came from"}]}
# Applying them is pure (in memory), idempotent and needs NO code change per guide.
# --------------------------------------------------------------------------------------------------
def load_registrations(path: Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    regs = data.get("registrations", [])
    if not isinstance(regs, list):
        raise RegistrationError("'registrations' must be a list")
    return regs


PAGECONTENT_URL_KEYS = {"deliverable_id": "numeric_id", "buildNo": "build_no"}
DEFAULT_TOC_DIR = "data/toc"


def default_toc_path(guide_id: str) -> str:
    return f"{DEFAULT_TOC_DIR}/{guide_id}.json"


def parse_pagecontent_request(url: str) -> Dict[str, str]:
    """Extract numeric deliverable id, build number and page file from a ``.../http.svc/pagecontent?...`` request URL
    copied from the browser. HTML-escaped separators (``&amp;``, as pasted from rendered pages) are accepted.
    Nothing is inferred: all three parameters must be present, ids numeric, file_path ``<32hex>[-N].html``."""
    from html import unescape
    from urllib.parse import parse_qs, urlparse
    from .intake import strip_bom
    q = parse_qs(urlparse(unescape(strip_bom(str(url)).strip())).query)
    out: Dict[str, str] = {}
    for key, name in PAGECONTENT_URL_KEYS.items():
        vals = q.get(key) or []
        if len(vals) != 1 or not re.fullmatch(r"\d+", vals[0]):
            raise RegistrationError(f"pagecontent_url must carry a numeric {key}=<digits> parameter (got {vals!r})")
        out[name] = vals[0]
    fp = (q.get("file_path") or [""])[0]
    out["file_path"] = fp if re.fullmatch(r"[0-9a-f]{32}(-\d+)?\.html", fp, re.I) else ""
    return out


def parse_pagecontent_url(url: str) -> Dict[str, str]:
    """numeric_id + build_no only (see parse_pagecontent_request)."""
    r = parse_pagecontent_request(url)
    return {"numeric_id": r["numeric_id"], "build_no": r["build_no"]}


def normalise_registration(reg: Dict[str, Any]) -> Dict[str, Any]:
    """Accept ``pagecontent_url`` as an alternative to numeric_id + build_no (never both with different values)."""
    r = {k: v for k, v in reg.items() if not str(k).startswith("_")}
    url = r.pop("pagecontent_url", None)
    if url not in (None, ""):
        got = parse_pagecontent_url(url)
        for k, v in got.items():
            if r.get(k) not in (None, "") and str(r[k]) != v:
                raise RegistrationError(f"{k}={r[k]!r} conflicts with pagecontent_url ({v})")
            r[k] = v
    for k in ("numeric_id", "build_no"):
        if r.get(k) not in (None, ""):
            r[k] = str(r[k]).strip()
    return r


def shared_numeric_ids(registry: Dict[str, Any]) -> Dict[str, List[str]]:
    """numeric deliverable id -> guide ids, for ids used by more than one guide. This is LEGITIMATE (one SAP
    deliverable_id can serve pages of several guides): identity is never the numeric id alone but the response
    ``loio`` + requested page, which every TOC/page fetch verifies against the registered guide_id."""
    by: Dict[str, List[str]] = {}
    for g, e in (registry.get("guides") or {}).items():
        if e.get("numeric_deliverable_id"):
            by.setdefault(str(e["numeric_deliverable_id"]), []).append(g)
    return {k: sorted(v) for k, v in by.items() if len(v) > 1}


def apply_registrations(registry: Dict[str, Any], topic_manifest: Dict[str, Any], registrations: List[Dict[str, Any]],
                        repo_root: Path):
    """Backward-compatible wrapper: returns (registry, errors)."""
    registry, errors, _ = apply_registrations_ex(registry, topic_manifest, registrations, repo_root)
    return registry, errors


def apply_registrations_ex(registry: Dict[str, Any], topic_manifest: Dict[str, Any], registrations: List[Dict[str, Any]],
                           repo_root: Path):
    """Returns (registry, errors, pending).

    * invalid registration  -> ``errors`` (reported, skipped; never overwrites a different value, never guesses);
    * empty skeleton / ids without a TOC yet -> ``pending`` (not an error: the guide just stays UNRESOLVED_GUIDE and
      the manifest says exactly what is missing). ``toc_file`` defaults to ``data/toc/<guide_id>.json`` which is
      where ``--allow-network`` saves an acquired TOC.
    """
    errors: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    guide_ids = {g["guide_id"] for g in topic_manifest["guides"]}
    for i, raw_reg in enumerate(registrations):
        try:
            reg = normalise_registration(raw_reg)
            gid = str(reg.get("guide_id", "")).lower()
            if gid not in guide_ids:
                raise RegistrationError(f"guide_id {gid!r} is not referenced by any topic card")
            explicit_toc = reg.get("toc_file")
            toc_file = explicit_toc or default_toc_path(gid)
            numeric, build = reg.get("numeric_id"), reg.get("build_no")
            if (numeric in (None, "")) != (build in (None, "")):
                raise RegistrationError("numeric_id and build_no must be supplied together (or both omitted)")
            for k, v in (("numeric_id", numeric), ("build_no", build)):
                if v not in (None, "") and not re.fullmatch(r"\d+", str(v)):
                    raise RegistrationError(f"{k} must be digits, got {v!r}")
            p = Path(toc_file)
            p = p if p.is_absolute() else Path(repo_root) / p
            entry = registry["guides"].setdefault(gid, _blank_entry(gid, ""))
            for key, new in (("numeric_deliverable_id", numeric), ("build_no", build)):
                old = entry.get(key)
                if new not in (None, "") and old not in (None, "") and str(old) != str(new):
                    raise RegistrationError(f"refusing to overwrite {key}={old!r} with {new!r}")
            has_ids = numeric not in (None, "")
            if not p.is_file():
                if explicit_toc:
                    raise RegistrationError(f"toc_file not found: {toc_file}")
                missing = ["toc"] + ([] if has_ids else ["numeric_id", "build_no"])
                if has_ids:                      # record the ids so the TOC can be acquired (network) - still unresolved
                    entry["numeric_deliverable_id"], entry["build_no"] = str(numeric), str(build)
                    if entry.get("fetch_identifiers_status") != "verified":
                        entry["fetch_identifiers_status"] = "manual_unverified"
                    entry["evidence"] = list(dict.fromkeys(entry.get("evidence", []) + [
                        f"registration #{i}: numeric id {numeric}/build {build} user-supplied, not machine-verified; "
                        f"TOC not saved yet ({toc_file})"]))
                pending.append({"registration_index": i, "guide_id": gid, "missing": missing, "toc_file": toc_file,
                                "numeric_id": numeric if has_ids else None, "build_no": build if has_ids else None,
                                "state": "TOC_NOT_AVAILABLE" if has_ids else "EMPTY_SKELETON"})
                continue
            tree = TocTree.from_file(p)
            if tree.guide_id != gid:
                raise RegistrationError(f"toc_file is guide {tree.guide_id}, registration says {gid}")
            entry.update(title=tree.title, version=tree.version, language=tree.language, toc_file=str(toc_file),
                         toc_node_count=len(tree), landing_page_id=tree.landing_page[:-5],
                         map_root_page_id=tree.map_root_page_id)
            if has_ids:
                entry["numeric_deliverable_id"], entry["build_no"] = str(numeric), str(build)
                if entry.get("fetch_identifiers_status") != "verified":
                    entry["fetch_identifiers_status"] = "manual_unverified"
            note = (f"registration #{i}: toc_file={toc_file} ({len(tree)} nodes)"
                    + (f"; numeric id {numeric}/build {build} user-supplied, not machine-verified" if has_ids else "")
                    + (f"; {reg['evidence']}" if reg.get("evidence") else ""))
            entry["evidence"] = list(dict.fromkeys(entry.get("evidence", []) + [note]))
            entry["topic_ids"] = [t for g in topic_manifest["guides"] if g["guide_id"] == gid for t in g["topic_ids"]]
        except (RegistrationError, TocError, OSError, ValueError) as e:
            errors.append({"registration_index": i, "guide_id": raw_reg.get("guide_id"), "error": str(e)})
    return registry, errors, pending
