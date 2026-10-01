"""Page/TOC acquisition and storage.

Two fetchers implement the same interface:

* ``LegacyLocalFetcher``  - serves pages already saved in ``sap_pages/`` (guide
  e52c8ee6... / numeric 40374631 only). Offline; used to validate the pipeline.
* ``SapHelpApiFetcher``   - the *same* HTTP mechanism as ``fetch_sap_pages.py``:
      GET https://help.sap.com/http.svc/pagecontent
          ?deliverableInfo=1&deliverable_id=<numeric>&buildNo=<n>&file_path=<page>.html
  It needs the guide's numeric deliverable id AND build number from the registry.
  If either is unknown it raises ``UnresolvedGuideError`` - it never guesses, and
  never tries the 32-hex loio in the numeric slot (untested assumption).
  Network is OFF unless ``allow_network=True``. NOTE: help.sap.com/robots.txt has
  ``Disallow: /`` for generic agents; enabling network is a deliberate, human decision.

``ingest_plan`` writes one JSON per page at ``<out_dir>/<storage_key>``.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import events as ev
from .plan import IngestPlan, PlanEntry, assert_safe_out_dir
from .registry import GuideRegistry, LEGACY_PAGES_DIR

API_URL = "https://help.sap.com/http.svc/pagecontent"
USER_AGENT = "sap-m2c-rag-resolver/0.1 (local student research prototype)"


class FetchError(Exception):
    """Base class."""


class UnresolvedGuideError(FetchError):
    pass


class NetworkDisabledError(FetchError):
    pass


class PageNotAvailableLocally(FetchError):
    pass


class HttpApiError(FetchError):
    def __init__(self, msg: str, status: Optional[int] = None):
        super().__init__(msg)
        self.status = status


class PageParseError(FetchError):
    pass


class GuideMismatchError(FetchError):
    """The response belongs to a different guide/page than requested (never substituted silently)."""


class FetchAborted(FetchError):
    """Circuit breaker: too many consecutive failures; remaining pages are not attempted."""


@dataclass
class FetchedPage:
    text: str
    current_page: Optional[Dict[str, Any]]
    fetched_via: str
    retrieved_at: Optional[str] = None      # ISO-8601 UTC for live fetches; None for local copies
    source_type: str = "sap_help_api"       # sap_help_api | legacy_local_copy


def _html_to_text(body: str) -> str:
    from bs4 import BeautifulSoup   # same flattening as fetch_sap_pages.py
    return BeautifulSoup(body, "html.parser").get_text("\n", strip=True)


class LegacyLocalFetcher:
    """Reads pages from the legacy sap_pages/ folder, keyed by TOC file_path."""

    name = "legacy_local"

    def __init__(self, repo_root: Path, registry: GuideRegistry):
        self.repo_root = Path(repo_root)
        self.registry = registry
        self._index: Dict[str, Path] = {}
        for p in sorted((self.repo_root / LEGACY_PAGES_DIR).glob("*.json")):
            try:
                fp = json.loads(p.read_text(encoding="utf-8")).get("file_path")
            except (OSError, ValueError):
                continue
            if fp:
                self._index.setdefault(fp, p)

    def fetch_page(self, entry: PlanEntry) -> FetchedPage:
        g = self.registry.get(entry.guide_id) or {}
        if g.get("fetch_identifiers_status") != "verified" or not g.get("toc_file"):
            raise PageNotAvailableLocally(
                f"legacy pages are only bound to the verified guide; {entry.guide_id} is not")
        path = self._index.get(entry.file_path)
        if path is None:
            raise PageNotAvailableLocally(f"{entry.file_path} not present in {LEGACY_PAGES_DIR}/")
        d = json.loads(path.read_text(encoding="utf-8"))
        return FetchedPage(text=d["text"], current_page=d.get("current_page"),
                           fetched_via=f"{self.name}:{LEGACY_PAGES_DIR}/{path.name}",
                           retrieved_at=None, source_type="legacy_local_copy")


TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_transient(exc: Exception, status: Optional[int]) -> bool:
    """Retry timeouts, connection resets and 408/425/429/5xx. NOT retried: other 4xx (incl. 401/403/404)
    and TLS failures (a closed TLS handshake is an access policy, not a blip)."""
    try:
        import requests
        if isinstance(exc, requests.exceptions.SSLError):
            return False
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True
    except ImportError:  # pragma: no cover
        pass
    return status is not None and (status in TRANSIENT_STATUS or status >= 500)


class SapHelpApiFetcher:
    name = "sap_help_api"

    def __init__(self, registry: GuideRegistry, log: Optional[ev.EventLog] = None,
                 allow_network: bool = False, session=None, delay_s: float = 1.0, timeout_s: int = 30,
                 max_retries: int = 3, backoff_s: float = 2.0, max_backoff_s: float = 60.0, sleep=time.sleep):
        self.registry, self.log = registry, log or ev.EventLog()
        self.allow_network, self.delay_s, self.timeout_s = allow_network, delay_s, timeout_s
        self.max_retries, self.backoff_s, self.max_backoff_s, self._sleep = max_retries, backoff_s, max_backoff_s, sleep
        self._session = session
        self._last = 0.0

    def _ids(self, guide_id: str):
        g = self.registry.get(guide_id) or {}
        did, build = g.get("numeric_deliverable_id"), g.get("build_no")
        if not did or not build:
            raise UnresolvedGuideError(
                f"guide {guide_id}: numeric deliverable id / build number unknown "
                "(not derivable from local evidence); refusing to guess")
        return str(did), str(build)

    def request_params(self, guide_id: str, file_path: str) -> Dict[str, str]:
        did, build = self._ids(guide_id)
        return {"deliverableInfo": "1", "deliverable_id": did, "buildNo": build, "file_path": file_path}

    def _backoff(self, attempt: int, resp) -> float:
        wait = min(self.backoff_s * (2 ** (attempt - 1)), self.max_backoff_s)
        ra = getattr(resp, "headers", None) and resp.headers.get("Retry-After")
        if ra and str(ra).isdigit():
            wait = min(max(wait, float(ra)), self.max_backoff_s)
        return wait

    def _get_json(self, guide_id: str, file_path: str) -> Dict[str, Any]:
        return self._request(self.request_params(guide_id, file_path), guide_id, file_path)

    def fetch_raw(self, numeric_id: str, build_no: str, file_path: str) -> Dict[str, Any]:
        """Replay ONE captured request (ids taken verbatim from a browser-captured URL). Same retry / TLS /
        network-opt-in rules as every other request; the caller must verify what the response says."""
        params = {"deliverableInfo": "1", "deliverable_id": str(numeric_id), "buildNo": str(build_no), "file_path": file_path}
        return self._request(params, f"captured:{numeric_id}", file_path)

    def _request(self, params: Dict[str, str], guide_id: str, file_path: str) -> Dict[str, Any]:
        if not self.allow_network:
            raise NetworkDisabledError("network access is disabled (pass allow_network=True / --allow-network)")
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers["User-Agent"] = USER_AGENT
        attempt = 0
        while True:
            attempt += 1
            wait = self.delay_s - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            resp = None
            try:
                resp = self._session.get(API_URL, params=params, timeout=self.timeout_s)
                resp.raise_for_status()
                break
            except Exception as e:      # requests exceptions, incl. HTTPError / Timeout / ConnectionError
                status = getattr(getattr(e, "response", None), "status_code", None) or getattr(resp, "status_code", None)
                will_retry = _is_transient(e, status) and attempt <= self.max_retries
                self.log.emit(ev.HTTP_ERROR, guide_id=guide_id, file_path=file_path, status=status,
                              attempt=attempt, will_retry=will_retry, error=f"{type(e).__name__}: {e}")
                if not will_retry:
                    raise HttpApiError(f"{type(e).__name__}: {e} (after {attempt} attempt(s))", status) from e
                self._sleep(self._backoff(attempt, getattr(e, "response", None) or resp))
        try:
            return resp.json()
        except ValueError as e:
            raise PageParseError(f"response is not JSON: {e}") from e

    def fetch_page(self, entry: PlanEntry) -> FetchedPage:
        data = self._get_json(entry.guide_id, entry.file_path)
        d = data.get("data") if isinstance(data, dict) else None
        body = (d or {}).get("body")
        if not body:
            raise PageParseError("response has no data.body")
        # Never silently accept another guide/page than requested.
        loio = ((d.get("deliverable") or {}).get("loio") or "").lower()
        if loio and loio != entry.guide_id.lower():
            raise GuideMismatchError(f"requested guide {entry.guide_id} but the API answered for guide {loio}; "
                                     "registered numeric id / build number do not belong to this guide")
        cur = (d.get("currentPage") or {}).get("loio")
        if cur and not entry.file_path[32:].startswith("-") and cur.lower() != entry.page_id.lower():
            raise GuideMismatchError(f"requested page {entry.page_id} but the API answered for page {cur}")
        return FetchedPage(text=_html_to_text(body), current_page=d.get("currentPage"), fetched_via=self.name,
                           retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           source_type="sap_help_api")

    def fetch_toc_response(self, guide_id: str, any_page_file: str) -> Dict[str, Any]:
        """One request per guide (any page, deliverableInfo=1) returns the guide's fullToc -
        this is how master_data.json was obtained. Caller stores it and registers it."""
        data = self._get_json(guide_id, any_page_file)
        deliv = (data.get("data") or {}).get("deliverable") or {}
        if not deliv.get("fullToc"):
            raise PageParseError("response has no data.deliverable.fullToc")
        if (deliv.get("loio") or "").lower() != guide_id.lower():
            raise GuideMismatchError(f"requested guide {guide_id} but the API answered for {deliv.get('loio')}")
        return data


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def ingest_plan(plan: IngestPlan, fetcher, repo_root: Path, out_dir: Optional[Path] = None,
                log: Optional[ev.EventLog] = None, overwrite: bool = False,
                dry_run: bool = False) -> Dict[str, Any]:
    """Fetch every planned page and store it. Never touches ChromaDB or sap_pages/."""
    log = log or ev.EventLog()
    out = assert_safe_out_dir(out_dir or plan.config.out_dir, repo_root)
    stats = {"planned": len(plan.entries), "stored": 0, "skipped_existing": 0, "failed": 0,
             "duplicate_content": 0, "dry_run": dry_run, "out_dir": str(out)}
    seen_hash: Dict[str, str] = {}
    index_path = out / "ingest_index.json"
    index: Dict[str, Any] = {}
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8")).get("pages", {})
    for e in plan.entries:
        target = out / e.storage_key
        if dry_run:
            continue
        if target.is_file() and not overwrite:
            stats["skipped_existing"] += 1
            log.emit(ev.PAGE_SKIPPED, guide_id=e.guide_id, page_id=e.page_id, reason="already stored")
            try:
                h = json.loads(target.read_text(encoding="utf-8")).get("text_sha256")
                if h:
                    seen_hash.setdefault(h, e.storage_key)
            except (OSError, ValueError):
                pass
            continue
        try:
            fp = fetcher.fetch_page(e)
        except HttpApiError:
            stats["failed"] += 1      # HTTP_ERROR already emitted by the fetcher
            continue
        except FetchError as ex:
            stats["failed"] += 1
            log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, file_path=e.file_path,
                     error_type=type(ex).__name__, error=str(ex))
            continue
        h = hashlib.sha256(fp.text.encode("utf-8")).hexdigest()
        dup_of = seen_hash.get(h)
        if dup_of and dup_of != e.storage_key:
            stats["duplicate_content"] += 1
            log.emit(ev.DUPLICATE_CONTENT, guide_id=e.guide_id, page_id=e.page_id, duplicate_of=dup_of,
                     text_sha256=h)
        seen_hash.setdefault(h, e.storage_key)
        record = {
            "guide_id": e.guide_id, "page_id": e.page_id, "file_path": e.file_path, "title": e.title,
            "canonical_url": e.canonical_url, "toc_path": e.toc_path, "parent_page_id": e.parent_page_id,
            "depth": e.depth, "topic_roles": {str(k): v for k, v in sorted(e.topic_roles.items())},
            "alias_file_paths": e.alias_file_paths, "current_page": fp.current_page,
            "fetched_via": fp.fetched_via, "text_sha256": h, "duplicate_content_of": dup_of if dup_of != e.storage_key else None,
            "text": fp.text,
        }
        try:
            _atomic_write_json(target, record)
        except OSError as ex:
            stats["failed"] += 1
            log.emit(ev.PAGE_FAILED, guide_id=e.guide_id, page_id=e.page_id, error_type="OSError", error=str(ex))
            continue
        index[e.storage_key] = {"title": e.title, "text_sha256": h, "topic_ids": e.topic_ids,
                                "duplicate_content_of": record["duplicate_content_of"]}
        stats["stored"] += 1
        log.emit(ev.PAGE_STORED, guide_id=e.guide_id, page_id=e.page_id, storage_key=e.storage_key,
                 chars=len(fp.text), topic_ids=e.topic_ids)
    if not dry_run and index:
        _atomic_write_json(index_path, {"pages": dict(sorted(index.items()))})
    return stats
