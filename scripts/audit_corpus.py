#!/usr/bin/env python3
"""
Phase 0 - Corpus audit for the SAP Utilities M2C reference PDFs.

Features:
  - Parses numbered PDF reference cards.
  - Extracts title/category/summary/relevance.
  - Extracts URLs from PDF link annotations and visible text.
  - Cross-checks URL sources.
  - Validates expected SAP Help URL structure.
  - Detects duplicate topics and URL anomalies.
  - Groups topics by SAP guide/deliverable.
  - Measures repeated boilerplate.
  - Optional network probe for SAP Help URLs.
  - Downloads robots.txt and checks robots permissions.
  - Fails gracefully for individual network errors.

Windows / PowerShell usage:

  python scripts\audit_corpus.py --pdf-dir "D:\chatbot"
  python scripts\audit_corpus.py --pdf-dir "D:\chatbot" --check-urls --delay 2 --limit 3
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pypdf import PdfReader


URL_RE = re.compile(
    r"^https://help\.sap\.com/docs/"
    r"(?P<product>[^/]+)/"
    r"(?P<deliverable>[0-9a-fA-F]{32})/"
    r"(?P<topic>[0-9a-fA-F]{32})\.html"
    r"(?P<query>\?.*)?$"
)

ZWSP_ENTITY = "&#8203;"
USER_AGENT = "sap-m2c-rag-audit/0.1 (student research prototype)"


@dataclass
class Record:
    file: str
    file_no: int | None = None
    ref_no: int | None = None
    title: str = ""
    meta_title: str = ""
    category: str = ""
    covers: str = ""
    relevance: str = ""
    pages: int = 0
    chars: int = 0
    boilerplate_chars: int = 0
    url_annotations: list[str] = field(default_factory=list)
    url_text: str = ""
    url: str = ""
    canonical_url: str = ""
    product: str = ""
    deliverable_id: str = ""
    topic_id: str = ""
    query: str = ""
    anomalies: list[str] = field(default_factory=list)


def squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_url_text(value: str) -> str:
    return re.sub(r"\s+", "", value).replace(ZWSP_ENTITY, "")


def canonicalize_url(url: str) -> str:
    """
    Canonical form for comparison only.

    We preserve query strings because SAP Help may use them to select a
    version. We only normalize the product path segment to uppercase.
    """
    if not url:
        return ""

    parts = urlsplit(url.strip())
    path_parts = parts.path.split("/")

    if len(path_parts) >= 4 and path_parts[1].lower() == "docs":
        path_parts[2] = path_parts[2].upper()

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            "/".join(path_parts),
            parts.query,
            parts.fragment,
        )
    )


def parse_pdf(path: Path) -> Record:
    rec = Record(file=path.name)

    match = re.match(r"(\d+)_", path.name)
    rec.file_no = int(match.group(1)) if match else None

    reader = PdfReader(str(path))
    rec.pages = len(reader.pages)
    rec.meta_title = (
        (reader.metadata.title or "") if reader.metadata else ""
    )

    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    rec.chars = len(text)

    # Prefer the actual clickable PDF link annotation.
    for page in reader.pages:
        for annot in page.get("/Annots", []) or []:
            try:
                obj = annot.get_object()
                action = obj.get("/A")
                if action is None:
                    continue
                action_obj = action.get_object()
                uri = action_obj.get("/URI")
                if uri:
                    rec.url_annotations.append(str(uri))
            except Exception:
                rec.anomalies.append("failed to parse one PDF link annotation")

    def grab(pattern: str) -> str:
        match = re.search(pattern, text, re.S)
        return squash(match.group(1)) if match else ""

    match = re.search(r"Source Reference\s+(\d+)", text)
    rec.ref_no = int(match.group(1)) if match else None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rec.title = lines[1] if len(lines) > 1 else ""

    rec.category = grab(r"Category:\s*(.+?)\n")
    rec.covers = grab(
        r"What it covers\s*(.*?)\s*Meter-to-Cash\s*relevance"
    )
    rec.relevance = grab(
        r"relevance\s*(.*?)\s*Authoritative SAP Help source"
    )

    url_block = re.search(
        r"Open this topic on SAP Help Portal\s*(.*?)\s*Library use",
        text,
        re.S,
    )
    rec.url_text = clean_url_text(url_block.group(1)) if url_block else ""

    boilerplate = re.search(r"Library use.*", text, re.S)
    rec.boilerplate_chars = len(boilerplate.group(0)) if boilerplate else 0

    unique_annotations = list(dict.fromkeys(rec.url_annotations))

    if not unique_annotations:
        rec.anomalies.append("no link annotation")
    elif len(unique_annotations) > 1:
        rec.anomalies.append(
            f"{len(unique_annotations)} distinct link annotations"
        )

    rec.url = (
        unique_annotations[0]
        if unique_annotations
        else rec.url_text
    )

    if rec.url_text and unique_annotations:
        if rec.url_text != unique_annotations[0]:
            rec.anomalies.append(
                "visible-text URL differs from link annotation"
            )

    match = URL_RE.match(rec.url)
    if match:
        rec.product = match["product"]
        rec.deliverable_id = match["deliverable"].lower()
        rec.topic_id = match["topic"].lower()
        rec.query = match["query"] or ""
        rec.canonical_url = canonicalize_url(rec.url)

        if rec.query:
            rec.anomalies.append(
                f"query string present: {rec.query}"
            )
    elif rec.url:
        rec.anomalies.append(
            "URL does not match expected help.sap.com pattern"
        )

    if rec.pages != 1:
        rec.anomalies.append(f"{rec.pages} pages (expected 1)")

    if rec.file_no != rec.ref_no:
        rec.anomalies.append(
            f"filename number {rec.file_no} != reference number {rec.ref_no}"
        )

    if rec.meta_title and squash(rec.meta_title) != squash(rec.title):
        rec.anomalies.append("PDF metadata title differs from printed title")

    for name in ("category", "covers", "relevance"):
        if not getattr(rec, name):
            rec.anomalies.append(f"missing field: {name}")

    return rec


def post_process(records: list[Record]) -> dict:
    by_topic = defaultdict(list)
    by_url = defaultdict(list)

    for record in records:
        if record.topic_id:
            by_topic[
                (record.deliverable_id, record.topic_id)
            ].append(record.file_no)

        if record.canonical_url:
            by_url[record.canonical_url].append(record.file_no)

    duplicate_topics = {
        f"{deliverable}/{topic}": files
        for (deliverable, topic), files in by_topic.items()
        if len(files) > 1
    }

    duplicate_urls = {
        url: files
        for url, files in by_url.items()
        if len(files) > 1
    }

    product_case = Counter(
        record.product for record in records if record.product
    )
    majority = (
        product_case.most_common(1)[0][0]
        if product_case
        else ""
    )

    for record in records:
        if record.product and majority and record.product != majority:
            record.anomalies.append(
                f"product segment case differs "
                f"('{record.product}' vs majority '{majority}')"
            )

    guides = defaultdict(list)
    for record in records:
        guides[record.deliverable_id].append(record)

    return {
        "duplicate_topics": duplicate_topics,
        "duplicate_urls": duplicate_urls,
        "product_case_counts": dict(product_case),
        "canonical_product": majority,
        "guides": {
            guide: [
                (r.file_no, r.title, r.category)
                for r in records_in_guide
            ]
            for guide, records_in_guide in guides.items()
        },
    }


def write_outputs(
    records: list[Record],
    summary: dict,
    out: Path,
) -> None:
    out.mkdir(parents=True, exist_ok=True)

    with open(
        out / "inventory.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow(
            [
                "no",
                "file",
                "title",
                "category",
                "url",
                "canonical_url",
                "deliverable_id",
                "topic_id",
                "pages",
                "chars",
                "boilerplate_chars",
                "anomalies",
            ]
        )

        for record in records:
            writer.writerow(
                [
                    record.file_no,
                    record.file,
                    record.title,
                    record.category,
                    record.url,
                    record.canonical_url,
                    record.deliverable_id,
                    record.topic_id,
                    record.pages,
                    record.chars,
                    record.boilerplate_chars,
                    "; ".join(record.anomalies),
                ]
            )

    (out / "urls.json").write_text(
        json.dumps(
            [asdict(record) for record in records],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    total_chars = sum(record.chars for record in records)
    boilerplate_chars = sum(
        record.boilerplate_chars for record in records
    )
    unique_urls = len(
        {record.canonical_url for record in records if record.canonical_url}
    )

    lines = [
        "# Corpus audit report",
        "",
        (
            f"- PDFs parsed: **{len(records)}** | "
            f"unique canonical URLs: **{unique_urls}** | "
            f"guides: **{len(summary['guides'])}**"
        ),
        (
            f"- Duplicate topic URLs: "
            f"**{len(summary['duplicate_topics'])}**"
        ),
        (
            f"- Duplicate canonical URLs: "
            f"**{len(summary['duplicate_urls'])}**"
        ),
        (
            f"- Product-segment casing: "
            f"{summary['product_case_counts']}"
        ),
        (
            f"- Total extracted text: **{total_chars}** chars; "
            f"Library-use boilerplate estimate: **{boilerplate_chars}** chars "
            f"({100 * boilerplate_chars / max(total_chars, 1):.0f}%)"
        ),
        "",
        "## File inventory",
        "",
        "| # | Title | Category | Chars | Anomalies |",
        "|---|---|---|---:|---|",
    ]

    for record in records:
        lines.append(
            f"| {record.file_no} | {record.title} | "
            f"{record.category} | {record.chars} | "
            f"{'; '.join(record.anomalies) or '-'} |"
        )

    lines += [
        "",
        "## Topics grouped by SAP guide",
        "",
    ]

    for guide, items in summary["guides"].items():
        if not guide:
            continue

        lines.append(f"**{guide}** - {len(items)} topic(s)")
        lines.extend(
            f"- {number}: {title} ({category})"
            for number, title, category in items
        )

    lines += [
        "",
        "## Anomaly summary",
        "",
    ]

    anomalous = [record for record in records if record.anomalies]
    lines.append(
        f"{len(anomalous)} of {len(records)} files have at least one anomaly."
        if anomalous
        else "No anomalies."
    )

    (out / "audit_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def check_urls(
    records: list[Record],
    out: Path,
    delay: float,
    limit: int | None,
) -> None:
    """
    Network probe.

    Important:
      - Network/HTTP failures are captured per URL and do not terminate
        the whole audit.
      - robots.txt failure is also non-fatal.
    """
    import urllib.error
    import urllib.request
    from urllib.robotparser import RobotFileParser

    def get(url: str):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT},
        )
        return urllib.request.urlopen(request, timeout=20)

    result: dict = {
        "user_agent": USER_AGENT,
        "robots": {},
        "urls": [],
    }

    robot_parser = RobotFileParser()

    try:
        with get("https://help.sap.com/robots.txt") as response:
            body = response.read().decode("utf-8", "replace")

        (out / "robots.txt").write_text(
            body,
            encoding="utf-8",
        )

        robot_parser.parse(body.splitlines())

        result["robots"] = {
            "fetched": True,
            "saved_to": "robots.txt",
        }
    except Exception as exc:
        # Non-fatal.
        robot_parser = None
        result["robots"] = {
            "fetched": False,
            "error_type": type(exc).__name__,
            "error": repr(exc),
        }

    todo = [record for record in records if record.url]
    if limit is not None:
        todo = todo[:limit]

    for record in todo:
        entry = {
            "no": record.file_no,
            "title": record.title,
            "url": record.url,
            "canonical_url": record.canonical_url,
            "robots_allows": (
                robot_parser.can_fetch(USER_AGENT, record.url)
                if robot_parser
                else None
            ),
        }

        try:
            with get(record.url) as response:
                body = response.read().decode("utf-8", "replace")

                visible = re.sub(
                    r"<(script|style)\b.*?</\1>",
                    " ",
                    body,
                    flags=re.S | re.I,
                )
                visible = squash(
                    re.sub(r"<[^>]+>", " ", visible)
                )

                entry.update(
                    status=response.status,
                    final_url=response.geturl(),
                    content_type=response.headers.get(
                        "Content-Type"
                    ),
                    html_bytes=len(body.encode("utf-8")),
                    visible_text_chars=len(visible),
                    likely_js_shell=(
                        len(visible) < 500
                        and "<script" in body.lower()
                    ),
                    body_sha256=hashlib.sha256(
                        body.encode("utf-8")
                    ).hexdigest(),
                )

        except urllib.error.HTTPError as exc:
            entry.update(
                status=exc.code,
                error_type=type(exc).__name__,
                error=str(exc),
                deny_reason=(
                    exc.headers.get("x-deny-reason")
                    if exc.headers
                    else None
                ),
            )

        except Exception as exc:
            entry.update(
                error_type=type(exc).__name__,
                error=repr(exc),
            )

        result["urls"].append(entry)

        print(
            f"[{record.file_no:>2}] "
            f"{entry.get('status', 'ERR')}  "
            f"visible_chars={entry.get('visible_text_chars', '-')}  "
            f"{str(entry.get('error', ''))[:100]}"
        )

        time.sleep(delay)

    (out / "network_check.json").write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--pdf-dir",
        required=True,
        type=Path,
        help="Folder containing the 01_... through 29_... PDFs",
    )
    parser.add_argument(
        "--out-dir",
        default=Path("audit_out"),
        type=Path,
        help="Output folder (default: audit_out)",
    )
    parser.add_argument(
        "--check-urls",
        action="store_true",
        help="Probe SAP Help URLs (requires working internet access)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between network requests (default: 2)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Probe only the first N URLs",
    )

    args = parser.parse_args()

    pdf_dir = args.pdf_dir.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()

    if not pdf_dir.exists():
        print(
            f"ERROR: PDF directory does not exist: {pdf_dir}",
            file=sys.stderr,
        )
        return 1

    if not pdf_dir.is_dir():
        print(
            f"ERROR: --pdf-dir is not a directory: {pdf_dir}",
            file=sys.stderr,
        )
        return 1

    pdfs = sorted(
        path
        for path in pdf_dir.glob("*.pdf")
        if re.match(r"^\d+_", path.name)
    )

    if not pdfs:
        print(
            f"ERROR: No numbered PDFs found in {pdf_dir}",
            file=sys.stderr,
        )
        return 1

    try:
        records = [parse_pdf(pdf) for pdf in pdfs]
        summary = post_process(records)
        write_outputs(records, summary, out_dir)

    except Exception as exc:
        print(
            f"ERROR during offline audit: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        f"Parsed {len(records)} PDFs -> {out_dir}"
    )

    if args.check_urls:
        check_urls(
            records,
            out_dir,
            max(0.0, args.delay),
            args.limit,
        )

    print("Audit complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
