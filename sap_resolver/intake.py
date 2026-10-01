"""Guide intake: turn the few human-supplied facts about a guide into a saved TOC + a complete registration.

What is needed per guide (and is NOT derivable from any local file, see data/forensics/findings.md):
    numeric deliverable id + build number   (the ``deliverable_id=`` / ``buildNo=`` parameters of the
                                              ``http.svc/pagecontent`` request the browser makes for that guide)
    + EITHER a saved ``pagecontent?deliverableInfo=1`` response for any page of the guide (``toc_file``)
      OR network permission, in which case ONE request per guide downloads that response.

``acquire_tocs`` performs that single request per guide, through the same fetcher / retry rules as page
fetching, and verifies the answer before anything is stored:
    * the response's ``deliverable.loio`` must equal the registered ``guide_id`` (wrong numeric id/build -> rejected,
      nothing saved, nothing substituted);
    * it must contain a ``fullToc``;
    * an existing ``data/toc/<guide_id>.json`` is never overwritten.
Candidate request pages are the card's own page ids for that guide (from the topic manifest); nothing is invented.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from . import events as ev
from .fetch import (FetchError, GuideMismatchError, HttpApiError, NetworkDisabledError, PageParseError)
from .registry import RegistrationError, default_toc_path, normalise_registration

MAX_TOC_CANDIDATES = 3

_INVISIBLE = "\ufeff\u200b\u200c\u200d\u2060\u00a0"


# A UTF-8 BOM (EF BB BF) that was decoded with the wrong codec shows up as these strings.
MOJIBAKE_BOMS = ("\u00ef\u00bb\u00bf", "\u00ff\u00fe", "\u00fe\u00ff", "\u00c3\u00af\u00c2\u00bb\u00c2\u00bf")


def strip_bom(text: str) -> str:
    """Remove any leading BOM: U+FEFF (repeated), or its mojibake forms (e.g. 'ï»¿'), plus zero-width / NBSP / whitespace in front of it."""
    changed = True
    while changed:
        changed = False
        text = text.lstrip(_INVISIBLE + " \t\r\n")
        for m in MOJIBAKE_BOMS:
            if text.startswith(m):
                text, changed = text[len(m):], True
    return text


def decode_text_file(raw: bytes) -> str:
    """Decode a text file the way Windows tools write it: UTF-8 (with/without BOM), UTF-16 LE/BE with BOM
    (PowerShell ``>`` redirection), else UTF-8 with replacement. The BOM is always removed."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return strip_bom(raw[3:].decode("utf-8", "replace"))
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return strip_bom(raw.decode("utf-16", "replace"))
    if len(raw) >= 2 and raw[1:2] == b"\x00" and raw[0:1] != b"\x00":      # BOM-less UTF-16 LE of ASCII text
        return strip_bom(raw.decode("utf-16-le", "replace"))
    return strip_bom(raw.decode("utf-8", "replace"))


def clean_url_line(line: str) -> str:
    """Programmatic clean-up of one pasted URL: BOM / zero-width / NBSP / whitespace anywhere at the ends (and
    inside the URL), wrapping quotes or <>, a markdown ``[text](url)`` wrapper, and HTML-escaped ``&amp;``."""
    from html import unescape
    t = strip_bom(line)                       # BOM handling happens BEFORE anything is parsed as a URL
    m = re.search(r"\]\((https?://[^)\s]+)\)", t)
    if m:
        t = m.group(1)
    t = strip_bom(t.strip("\"'<>`" + _INVISIBLE + " "))
    t = "".join(ch for ch in t if ch not in _INVISIBLE and not ch.isspace())
    return unescape(t)


def read_url_lines(path: Path) -> List[str]:
    """URLs from a text file: encoding/BOM tolerant, comments (#) and blank lines skipped, every line cleaned."""
    text = decode_text_file(Path(path).read_bytes())
    out = []
    for line in text.splitlines():
        c = clean_url_line(line)
        if c and not c.startswith("#"):
            out.append(c)
    return out


def clean_pasted_url(url: str) -> str:
    """Same cleaning for a single URL given on the command line / in a registration."""
    return clean_url_line(url)


def _save_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def acquirable(registrations: List[Dict[str, Any]], topic_manifest: Dict[str, Any], repo_root: Path) -> List[Dict[str, Any]]:
    """Registrations that carry numeric id + build but whose TOC is not saved yet (and has no explicit toc_file)."""
    guides = {g["guide_id"]: g for g in topic_manifest["guides"]}
    out = []
    for raw in registrations:
        try:
            r = normalise_registration(raw)
        except RegistrationError:
            continue                                  # reported later by apply_registrations
        gid = str(r.get("guide_id", "")).lower()
        if gid not in guides or r.get("toc_file") or not r.get("numeric_id") or not r.get("build_no"):
            continue
        if (Path(repo_root) / default_toc_path(gid)).is_file():
            continue
        pref = [str(x)[:32].lower() for x in (raw.get("captured_page_ids") or [])]
        if raw.get("pagecontent_url"):
            try:
                from .registry import parse_pagecontent_request
                fp = parse_pagecontent_request(raw["pagecontent_url"])["file_path"]
                pref.append(fp[:32].lower()) if fp else None
            except RegistrationError:
                pass
        out.append({"guide_id": gid, "numeric_id": r["numeric_id"], "build_no": r["build_no"], "preferred_pages": pref})
    return out


def acquire_tocs(registrations: List[Dict[str, Any]], topic_manifest: Dict[str, Any], repo_root: Path,
                 toc_fetcher_factory: Callable[[Dict[str, Any]], Any], log: ev.EventLog) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Download + verify + save one TOC per acquirable guide. Returns (acquired, errors)."""
    todo = acquirable(registrations, topic_manifest, repo_root)
    if not todo:
        return [], []
    temp = {"guides": {t["guide_id"]: {"numeric_deliverable_id": t["numeric_id"], "build_no": t["build_no"]} for t in todo}}
    fetcher = toc_fetcher_factory(temp)
    topics_by_guide: Dict[str, List[Dict[str, Any]]] = {}
    for t in topic_manifest["topics"]:
        topics_by_guide.setdefault(t["guide_id"], []).append(t)
    acquired, errors = [], []
    for t in todo:
        gid = t["guide_id"]
        pages = list(dict.fromkeys([f"{p}.html" for p in t.get("preferred_pages", [])] +
                                   [f"{x['page_id']}.html" for x in sorted(topics_by_guide.get(gid, []), key=lambda x: x["topic_id"])]))
        last: Exception | None = None
        for fp in pages[:MAX_TOC_CANDIDATES]:
            try:
                resp = fetcher.fetch_toc_response(gid, fp)
            except GuideMismatchError as e:          # ids belong to another guide: stop, never try to 'fix' it
                last = e
                break
            except NetworkDisabledError as e:
                last = e
                break
            except HttpApiError as e:
                last = e
                if e.status in (404, 400):           # that card page is not addressable; try the next card page
                    continue
                break
            except (PageParseError, FetchError) as e:
                last = e
                continue
            dest = Path(repo_root) / default_toc_path(gid)
            _save_json_atomic(dest, resp)
            n = len((resp.get("data") or {}).get("deliverable", {}).get("fullToc") or [])
            log.emit(ev.TOC_ACQUIRED, guide_id=gid, via_page=fp, toc_file=str(dest.relative_to(Path(repo_root))),
                     top_level_nodes=n)
            acquired.append({"guide_id": gid, "toc_file": default_toc_path(gid), "via_page": fp})
            last = None
            break
        if last is not None or not any(a["guide_id"] == gid for a in acquired):
            errors.append({"guide_id": gid, "error": f"TOC could not be acquired: {type(last).__name__ if last else 'no candidate page'}: {last}"})
    return acquired, errors


# --------------------------------------------------------------------------------------------------
# Captured browser requests  ->  guide identity
# --------------------------------------------------------------------------------------------------
def card_page_matches(page_id: str, topic_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """LOCAL evidence only: which card(s) carry exactly this page id (and therefore which guide they name)."""
    return [{"topic_id": t["topic_id"], "guide_id": t["guide_id"], "title": t["title"]}
            for t in topic_manifest["topics"] if t["page_id"] == page_id.lower()]


def capture_mapping(urls: List[str], topic_manifest: Dict[str, Any], repo_root: Path, fetcher=None,
                    existing_registrations: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """Decide, per captured pagecontent URL, which guide it belongs to - and why. Never forces a mapping.

    Evidence levels:
      * ``response_loio``  (fetcher given): ``data.deliverable.loio`` of the replayed request. Authoritative.
      * ``card_page_id``   (offline): the request's file_path equals the page id of a card URL that names a guide.
        Supporting only; the loio is checked against the guide later, when the TOC is downloaded.
    A numeric deliverable_id claimed for two different guides is AMBIGUOUS and maps to none of them.
    """
    from .registry import RegistrationError, parse_pagecontent_request
    guide_ids = {g["guide_id"] for g in topic_manifest["guides"]}
    rows: List[Dict[str, Any]] = []
    for n, url in enumerate(urls, 1):
        row: Dict[str, Any] = {"n": n, "url": url.strip(), "numeric_id": None, "build_no": None, "file_path": None,
                               "page_id": None, "card_matches": [], "response_loio": None, "response_page_loio": None,
                               "toc_nodes": None, "guide_id": None, "evidence": None, "decision": None, "reason": None}
        try:
            req = parse_pagecontent_request(url)
        except RegistrationError as e:
            row.update(decision="REJECTED", reason=str(e))
            rows.append(row)
            continue
        row.update(numeric_id=req["numeric_id"], build_no=req["build_no"])
        if not req["file_path"]:
            row.update(decision="REJECTED", reason="file_path is not <32hex>.html")
            rows.append(row)
            continue
        row.update(numeric_id=req["numeric_id"], build_no=req["build_no"], file_path=req["file_path"], page_id=req["file_path"][:32].lower())
        row["card_matches"] = card_page_matches(row["page_id"], topic_manifest)
        row["_resp"] = None
        if fetcher is not None:
            try:
                resp = fetcher.fetch_raw(req["numeric_id"], req["build_no"], req["file_path"])
                d = (resp.get("data") or {})
                deliv = d.get("deliverable") or {}
                row["response_loio"] = (deliv.get("loio") or "").lower() or None
                row["response_page_loio"] = ((d.get("currentPage") or {}).get("loio") or "").lower() or None
                row["toc_nodes"] = len(deliv.get("fullToc") or [])
                row["_resp"] = resp
            except FetchError as e:
                row.update(decision="FETCH_FAILED", reason=f"{type(e).__name__}: {e}")
                rows.append(row)
                continue
            loio = row["response_loio"]
            toc_pages = set()

            def _walk(nodes):
                for nd in nodes or []:
                    toc_pages.add(str(nd.get("u", ""))[:32].lower())
                    _walk(nd.get("c"))
            _walk(deliv.get("fullToc"))
            row["page_in_toc"] = row["page_id"] in toc_pages
            row["response_source"] = getattr(fetcher, "name", type(fetcher).__name__)
            card_guides = {m["guide_id"] for m in row["card_matches"]}
            if not loio:
                row.update(decision="REJECTED", reason="response carries no deliverable.loio")
            elif row["response_page_loio"] and row["response_page_loio"] != row["page_id"]:
                row.update(decision="PAGE_MISMATCH", reason=f"requested page {row['page_id']} but the response is for page {row['response_page_loio']}")
            elif loio not in guide_ids:
                row.update(decision="NOT_A_CARD_GUIDE", reason=f"response loio {loio} is not referenced by any of the 29 cards; not registered")
            elif card_guides and loio not in card_guides:
                row.update(decision="CARD_MISMATCH", reason=f"response loio {loio[:8]} but the card(s) carrying this page id "
                           f"{[m['topic_id'] for m in row['card_matches']]} name guide(s) {sorted(g[:8] for g in card_guides)}; "
                           "identity not confirmed, nothing registered for this URL")
            elif not deliv.get("fullToc"):
                row.update(decision="REJECTED", reason="response has no fullToc")
            else:
                row.update(guide_id=loio, evidence="response_loio")
        else:
            gids = sorted({m["guide_id"] for m in row["card_matches"]})
            if len(gids) == 1:
                row.update(guide_id=gids[0], evidence="card_page_id")
            elif not gids:
                row.update(decision="UNMATCHED", reason="page id is on no card; identity can only come from the response loio (--allow-network)")
            else:
                row.update(decision="AMBIGUOUS", reason=f"page id is on cards of several guides {[g[:8] for g in gids]}")
        rows.append(row)
    # build number must be consistent per guide
    by_guide: Dict[str, set] = {}
    for r in rows:
        if r["guide_id"]:
            by_guide.setdefault(r["guide_id"], set()).add((r["numeric_id"], r["build_no"]))
    for r in rows:
        if r["guide_id"] and len(by_guide[r["guide_id"]]) > 1:
            r.update(decision="AMBIGUOUS", reason=f"guide {r['guide_id'][:8]} received different (numeric id, build) pairs {sorted(by_guide[r['guide_id']])}", guide_id=None)
    # already-registered values are never overwritten
    for reg in existing_registrations or []:
        from .registry import normalise_registration
        try:
            e = normalise_registration(reg)
        except RegistrationError:
            continue
        for r in rows:
            if r["guide_id"] and r["guide_id"] == str(e.get("guide_id", "")).lower() and e.get("numeric_id") and \
                    (e["numeric_id"], e.get("build_no")) != (r["numeric_id"], r["build_no"]):
                r.update(decision="CONFLICTS_WITH_EXISTING", guide_id=None,
                         reason=f"guide already registered with numeric {e['numeric_id']}/build {e.get('build_no')}; not overwritten")
    for r in rows:
        if r["guide_id"] and not r["decision"]:
            same = [x for x in rows if x is not r and x["guide_id"] == r["guide_id"] and x["decision"] in (None, "MAPPED")]
            r["decision"] = "MAPPED"
            r["reason"] = (f"response deliverable.loio == {r['guide_id']}, currentPage == requested page"
                           + ("" if r.get("page_in_toc") else " (page not listed in fullToc)")
                           + (f", card(s) {[m['topic_id'] for m in r['card_matches']]} agree" if r["card_matches"] else ", page not on any card")
                           if r["evidence"] == "response_loio" else
                           f"file_path equals the card page id of topic(s) {[m['topic_id'] for m in r['card_matches']]}, "
                           f"whose card URL names guide {r['guide_id']}; loio not yet verified against a response")
            if same:
                r["reason"] += f"; shares guide with captured URL(s) {[x['n'] for x in same]} (same numeric id/build)"
            sharing = sorted({x["guide_id"][:8] for x in rows if x is not r and x["guide_id"] and x["guide_id"] != r["guide_id"]
                              and x["numeric_id"] == r["numeric_id"]})
            if sharing:
                r["reason"] += (f"; numeric id {r['numeric_id']} is also used by guide(s) {sharing} - allowed, identity is "
                                "(response loio + page), verified on every fetch")
    return rows


def capture_markdown(rows: List[Dict[str, Any]], mode: str) -> str:
    L = ["# Captured pagecontent URLs -> guides", "", f"* evidence mode: **{mode}** (`response_loio` = authoritative replay; "
         "`card_page_id` = local card match only, loio check pending)", "",
         "| # | numeric id | build | page id | card match (topic→guide) | response loio | → guide | decision |", "|--:|---|---|---|---|---|---|---|"]
    for r in rows:
        cm = "; ".join(f"#{m['topic_id']}→{m['guide_id'][:8]}" for m in r["card_matches"]) or "-"
        L.append(f"| {r['n']} | {r['numeric_id']} | {r['build_no']} | `{(r['page_id'] or '')[:8]}` | {cm} | "
                 f"{(r['response_loio'] or '-')[:8]} | {(r['guide_id'] or '-')[:8]} | **{r['decision']}** |")
    L += ["", "## Why", ""] + [f"{r['n']}. {r['decision']}: {r['reason']}" for r in rows]
    return "\n".join(L) + "\n"


class SavedResponses:
    """Stand-in for the network: serves previously captured ``pagecontent`` responses from a folder
    (files written by scripts/capture_responses.py, named ``<n>_<numeric>_<page32>.json``).
    Lets the verification run with no network access; evidence level is identical (the response's own loio)."""
    name = "saved_response"

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def fetch_raw(self, numeric_id: str, build_no: str, file_path: str) -> Dict[str, Any]:
        page = file_path[:32].lower()
        hits = sorted(self.folder.glob(f"*_{numeric_id}_{page}*.json"))
        if not hits:
            raise PageParseError(f"no saved response for deliverable_id={numeric_id} page={page} in {self.folder}")
        try:
            return json.loads(strip_bom(hits[0].read_text(encoding="utf-8-sig")))
        except ValueError as e:
            raise PageParseError(f"{hits[0].name} is not valid JSON: {e}") from e
