"""Standalone helper (Python 3 standard library only - copy this single file anywhere and run it).

Replays SAP Help ``pagecontent`` requests YOU captured in the browser (read-only GET, one per URL, 1 s apart, no
cookies, no auth, no retries beyond a single polite one) and saves each response, so the guide identity can be read
from the response itself instead of guessed:

    python capture_responses.py                                   # uses data/captured_pagecontent_urls.txt if present
    python capture_responses.py --urls-file my_urls.txt --out-dir captured_responses

For every URL it prints: HTTP status, deliverable_id, buildNo, requested page, the response's deliverable.loio,
currentPage.loio, guide title, number of top-level TOC nodes and whether the requested page is in the TOC.
Files: <out-dir>/<n>_<deliverable_id>_<page32>.json (raw response) and <out-dir>/summary.json.

Then, inside the project branch:
    python scripts/guide_intake.py capture --responses-dir captured_responses
    python scripts/build_corpus.py --allow-network --require-complete
Note: help.sap.com/robots.txt has "Disallow: /" for generic agents; running this is your decision.
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "sap-m2c-rag-capture/0.1 (local student research prototype; replays browser-captured URLs)"


_INVISIBLE = "\ufeff\u200b\u200c\u200d\u2060\u00a0"
_MOJIBAKE_BOMS = ("\u00ef\u00bb\u00bf", "\u00ff\u00fe", "\u00fe\u00ff", "\u00c3\u00af\u00c2\u00bb\u00c2\u00bf")


def strip_bom(text):
    """Leading U+FEFF and its mojibake forms ('ï»¿'), applied BEFORE any URL parsing."""
    changed = True
    while changed:
        changed = False
        text = text.lstrip(_INVISIBLE + " \t\r\n")
        for m in _MOJIBAKE_BOMS:
            if text.startswith(m):
                text, changed = text[len(m):], True
    return text


def read_urls(path):
    """BOM / UTF-16 / zero-width / NBSP / quote / markdown-link tolerant URL reader (no manual clean-up needed)."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw[3:].decode("utf-8", "replace")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", "replace")
    elif len(raw) >= 2 and raw[1:2] == b"\x00" and raw[0:1] != b"\x00":
        text = raw.decode("utf-16-le", "replace")
    else:
        text = raw.decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        t = strip_bom(line)
        m = re.search(r"\]\((https?://[^)\s]+)\)", t)
        t = m.group(1) if m else t
        t = "".join(ch for ch in strip_bom(t.strip("\"'<>`")) if ch not in _INVISIBLE and not ch.isspace())
        t = html.unescape(t)
        if t and not t.startswith("#"):
            out.append(t)
    return out


def _saved(out, n, num, fp):
    """A previously saved, parseable response for this URL (any run number prefix)."""
    for p in sorted(Path(out).glob(f"*_{num}_{fp[:32].lower()}.json")):
        try:
            json.loads(p.read_text(encoding="utf-8"))
            return p
        except ValueError:
            continue
    return None


def toc_pages(nodes, acc=None):
    acc = set() if acc is None else acc
    for n in nodes or []:
        acc.add(str(n.get("u", ""))[:32].lower())
        toc_pages(n.get("c"), acc)
    return acc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--urls-file", default="data/captured_pagecontent_urls.txt")
    ap.add_argument("--out-dir", default="captured_responses")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--refresh", action="store_true", help="fetch again even if a valid saved response already exists (default: reuse it)")
    a = ap.parse_args(argv)
    urls = read_urls(a.urls_file)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "summary.json").is_file():       # never lose an earlier summary
        (out / "summary.previous.json").write_bytes((out / "summary.json").read_bytes())
    summary, bad = [], 0
    print(f"{'#':>2} {'http':>4} {'deliverable_id':>14} {'build':>5} {'page':8} {'response loio':32} {'currentPage':8} {'toc':>4} in_toc  title")
    for n, url in enumerate(urls, 1):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        num, build, fp = (q.get(k, [""])[0] for k in ("deliverable_id", "buildNo", "file_path"))
        row = {"n": n, "url": url, "deliverable_id": num, "buildNo": build, "file_path": fp, "http": None}
        if not (re.fullmatch(r"\d+", num) and re.fullmatch(r"\d+", build) and re.fullmatch(r"[0-9a-fA-F]{32}(-\d+)?\.html", fp)):
            row["error"] = "URL lacks numeric deliverable_id / buildNo or a <32hex>.html file_path"
            bad += 1
        elif not a.refresh and _saved(out, n, num, fp):
            body = _saved(out, n, num, fp).read_bytes()        # keep what was captured earlier; no request made
            data = json.loads(body.decode("utf-8"))
            d = data.get("data") or {}
            dv = d.get("deliverable") or {}
            row.update(http="saved", loio=(dv.get("loio") or "").lower(), title=dv.get("title"), version=dv.get("version"),
                       current_page=((d.get("currentPage") or {}).get("loio") or "").lower(), toc_top_nodes=len(dv.get("fullToc") or []),
                       page_in_toc=fp[:32].lower() in toc_pages(dv.get("fullToc")))
            continue_delay = False
        else:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    row["http"] = r.status
                data = json.loads(body.decode("utf-8"))
                d = data.get("data") or {}
                dv = d.get("deliverable") or {}
                row.update(loio=(dv.get("loio") or "").lower(), title=dv.get("title"), version=dv.get("version"),
                           current_page=((d.get("currentPage") or {}).get("loio") or "").lower(), toc_top_nodes=len(dv.get("fullToc") or []),
                           page_in_toc=fp[:32].lower() in toc_pages(dv.get("fullToc")))
                (out / f"{n}_{num}_{fp[:32].lower()}.json").write_bytes(body)
            except urllib.error.HTTPError as e:
                row.update(http=e.code, error=f"HTTP {e.code}")
                bad += 1
            except Exception as e:                      # TLS/connection/JSON problems are reported, never worked around
                row["error"] = f"{type(e).__name__}: {e}"
                bad += 1
        summary.append(row)
        print(f"{n:>2} {str(row.get('http')):>4} {num:>14} {build:>5} {fp[:8]:8} {row.get('loio', '-'):32} {row.get('current_page', '-')[:8]:8} "
              f"{str(row.get('toc_top_nodes', '-')):>4} {str(row.get('page_in_toc', '-')):6}  {row.get('title') or row.get('error', '')}")
        if n < len(urls) and row.get("http") != "saved":
            time.sleep(a.delay)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    by = {}
    for r in summary:
        if r.get("loio"):
            by.setdefault(r["deliverable_id"], set()).add(r["loio"])
    for k, v in by.items():
        if len(v) > 1:
            print(f"!! deliverable_id {k} answered with {len(v)} different loios: {sorted(v)}")
    print(f"saved {len(urls) - bad}/{len(urls)} responses to {out}/")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
