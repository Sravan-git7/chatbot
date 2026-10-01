"""Structured event logging for resolution / ingestion.

Every event is (a) sent to the standard ``logging`` logger ``sap_resolver``,
(b) kept in memory (``EventLog.events``) so callers and tests can inspect it and
(c) optionally appended to a JSON-lines file.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Required events
PAGE_RESOLVED = "PAGE_RESOLVED"          # topic page found in a guide TOC
TOPIC_UNRESOLVED = "TOPIC_UNRESOLVED"    # topic could not be resolved reliably
PAGE_FAILED = "PAGE_FAILED"              # page/card could not be read, parsed or stored
DUPLICATE_PAGE = "DUPLICATE_PAGE"        # same (guide, page_id) reached more than once
DUPLICATE_CONTENT = "DUPLICATE_CONTENT"  # different page ids, identical text
HTTP_ERROR = "HTTP_ERROR"                # HTTP / API level failure
# Supporting events
GUIDE_RESOLVED = "GUIDE_RESOLVED"
GUIDE_UNRESOLVED = "GUIDE_UNRESOLVED"
PAGE_STORED = "PAGE_STORED"
PAGE_SKIPPED = "PAGE_SKIPPED"
TOPIC_CORRECTED = "TOPIC_CORRECTED"      # per-topic card->guide correction applied (evidence attached)
TOC_ACQUIRED = "TOC_ACQUIRED"            # guide TOC downloaded, verified and saved (network mode)

_LEVELS = {
    PAGE_RESOLVED: logging.INFO,
    GUIDE_RESOLVED: logging.INFO,
    PAGE_STORED: logging.INFO,
    PAGE_SKIPPED: logging.INFO,
    TOC_ACQUIRED: logging.INFO,
    TOPIC_CORRECTED: logging.WARNING,
    TOPIC_UNRESOLVED: logging.WARNING,
    GUIDE_UNRESOLVED: logging.WARNING,
    DUPLICATE_PAGE: logging.WARNING,
    DUPLICATE_CONTENT: logging.WARNING,
    PAGE_FAILED: logging.ERROR,
    HTTP_ERROR: logging.ERROR,
}

logger = logging.getLogger("sap_resolver")
logger.addHandler(logging.NullHandler())   # silent unless the application configures logging


class EventLog:
    def __init__(self, jsonl_path: Optional[Path] = None, truncate: bool = True):
        self.events: List[Dict[str, Any]] = []
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            if truncate:
                self.jsonl_path.write_text("", encoding="utf-8")

    def emit(self, event: str, **fields: Any) -> Dict[str, Any]:
        rec = {"event": event, **fields}
        self.events.append(rec)
        logger.log(_LEVELS.get(event, logging.INFO), "%s %s", event,
                   json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str))
        if self.jsonl_path:
            stamped = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(stamped, ensure_ascii=False, sort_keys=False, default=str) + "\n")
        return rec

    def of(self, event: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]

    def counts(self) -> Dict[str, int]:
        return dict(sorted(Counter(e["event"] for e in self.events).items()))
