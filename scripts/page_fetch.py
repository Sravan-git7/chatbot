#!/usr/bin/env python3
"""Phase 8A - OPT-IN fetcher for official SAP Help ``pagecontent`` responses listed in ``data/page_corpus/fetch_plan.json``.

Network is OFF unless ``--allow-network`` is passed, and this is the only Phase 8 module that can use it. Rules (none can be switched off):

* only ``https://help.sap.com/http.svc/pagecontent`` for pages named in the plan, using the numeric deliverable id / build number that a
  saved response of the same guide recorded (never guessed; plan entries without them are skipped and reported);
* ``robots.txt`` is requested first and logged. If it disallows everything for generic agents, nothing is fetched unless the operator
  adds ``--acknowledge-robots-disallow`` (the acknowledgement is written to the log). No other block (HTTP 401/403/429, a TLS reset,
  a captcha page) is worked around: it is logged and counted by the circuit breaker (3 consecutive failures stop the run);
* a fixed delay between requests (default 3 s) and a request cap (default 25);
* a response is saved only if the envelope status is ``OK``, it is not a fallback page, the response's ``currentPage.loio`` equals the
  requested page and its ``deliverable.loio`` equals the planned guide. Anything else is logged and discarded; no content is invented;
* saved files use the same envelope as ``captured_responses/`` so ``page_corpus.py`` ingests them through the same validation.

``--rebuild-after`` re-runs the corpus build. The transport is injectable, which is how the tests exercise every branch without a network.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import page_corpus as PC  # noqa: E402

PLAN_PATH = PC.CORPUS_DIR / "fetch_plan.json"
FETCHED_DIR = PC.CORPUS_DIR / "fetched"
LOG_PATH = PC.CORPUS_DIR / "fetch_log.json"
BASE = "https://help.sap.com"
USER_AGENT = "chatbot-sap-utilities-rag/phase8 (research; contact: repository owner)"
Transport = Callable[[str, float], Tuple[Optional[int], bytes, Optional[str]]]     # url, timeout -> (http status, body, error)


def default_transport(url: str, timeout: float) -> Tuple[Optional[int], bytes, Optional[str]]:
    try:
        import requests
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=timeout, allow_redirects=False)
        return r.status_code, r.content, None
    except Exception as e:                                          # noqa: BLE001 - every transport failure is logged, none is raised
        return None, b"", f"{type(e).__name__}: {e}"[:300]


def robots_disallows_all(robots_txt: str) -> bool:
    """True if the generic ``User-agent: *`` group contains ``Disallow: /`` (whole site)."""
    group_star, disallow_all = False, False
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = (s.strip() for s in line.split(":", 1))
        if k.lower() == "user-agent":
            group_star = v == "*"
        elif k.lower() == "disallow" and group_star and v == "/":
            disallow_all = True
    return disallow_all


def request_url(entry: Mapping[str, Any]) -> str:
    return (f"{BASE}/http.svc/pagecontent?deliverableInfo=1&deliverable_id={entry['numeric_deliverable_id']}"
            f"&buildNo={entry['build_no']}&file_path={entry['page_id']}.html")


def check_response(entry: Mapping[str, Any], status: Optional[int], body: bytes) -> Dict[str, Any]:
    """Validate one HTTP response against the plan entry. Returns ``{ok, reasons, envelope}``."""
    reasons: List[str] = []
    env: Any = None
    if status != 200:
        reasons.append(f"HTTP_STATUS_{status}")
    else:
        try:
            env = json.loads(body.decode("utf-8-sig"))
        except ValueError:
            reasons.append("RESPONSE_NOT_JSON")
    data = env.get("data") if isinstance(env, dict) else None
    if env is not None:
        if not isinstance(env, dict) or env.get("status") != "OK" or not isinstance(data, dict):
            reasons.append("ENVELOPE_NOT_OK")
        else:
            if data.get("fallback"):
                reasons.append("FALLBACK_PAGE")
            if str((data.get("currentPage") or {}).get("loio") or "").lower().removesuffix(".html") != entry["page_id"]:
                reasons.append("RESPONSE_PAGE_ID_DIFFERS_FROM_REQUEST")
            if str((data.get("deliverable") or {}).get("loio") or "").lower() != entry["guide_id"]:
                reasons.append("RESPONSE_GUIDE_ID_DIFFERS_FROM_PLAN")
            if not str(data.get("body") or "").strip():
                reasons.append("EMPTY_BODY")
    return {"ok": not reasons, "reasons": reasons, "envelope": env if not reasons else None}


def fetch_plan(plan: Mapping[str, Any], allow_network: bool, transport: Transport = default_transport, delay_s: float = 3.0, max_requests: int = 25,
               breaker: int = 3, acknowledge_robots: bool = False, only: Optional[Sequence[str]] = None, out_dir: Path = FETCHED_DIR,
               sleep: Callable[[float], None] = time.sleep, now: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
               timeout: float = 20.0) -> Dict[str, Any]:
    log: Dict[str, Any] = {"network_enabled": allow_network, "started_at": now(), "robots": None, "attempts": [], "skipped": [], "saved": [], "stopped_reason": None}
    entries = [e for e in plan.get("pages_to_fetch", []) if not only or e["source_id"] in only]
    todo = []
    for e in entries:
        if e.get("fetchable_with_recorded_ids") and e.get("numeric_deliverable_id") and e.get("build_no"):
            todo.append(e)
        else:
            log["skipped"].append({"source_id": e["source_id"], "reason": e.get("blocker") or "no recorded ids"})
    if not allow_network:
        log["stopped_reason"] = "NETWORK_DISABLED (pass --allow-network to fetch)"
        log["would_fetch"] = [e["source_id"] for e in todo]
        return log
    status, body, err = transport(f"{BASE}/robots.txt", timeout)
    log["robots"] = {"http_status": status, "error": err, "disallow_all_for_generic_agents": None}
    if status == 200:
        log["robots"]["disallow_all_for_generic_agents"] = robots_disallows_all(body.decode("utf-8", "replace"))
    if status != 200:
        log["robots"]["note"] = "robots.txt could not be read; the first content request decides whether the host is reachable at all"
    if log["robots"]["disallow_all_for_generic_agents"] and not acknowledge_robots:
        log["stopped_reason"] = "ROBOTS_DISALLOW_ALL: refusing to fetch without --acknowledge-robots-disallow (an explicit human decision)"
        return log
    if log["robots"]["disallow_all_for_generic_agents"]:
        log["robots"]["operator_acknowledged"] = True
    fails = 0
    for i, e in enumerate(todo):
        if len(log["attempts"]) >= max_requests:
            log["stopped_reason"] = "MAX_REQUESTS_REACHED"
            break
        if fails >= breaker:
            log["stopped_reason"] = f"CIRCUIT_BREAKER_{breaker}_CONSECUTIVE_FAILURES"
            break
        if log["attempts"]:
            sleep(delay_s)
        url = request_url(e)
        status, body, err = transport(url, timeout)
        chk = check_response(e, status, body) if err is None else {"ok": False, "reasons": ["TRANSPORT_ERROR"], "envelope": None}
        att = {"source_id": e["source_id"], "url": url, "http_status": status, "error": err, "ok": chk["ok"], "reasons": chk["reasons"], "at": now()}
        if chk["ok"]:
            fails = 0
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{i + 1}_{e['numeric_deliverable_id']}_{e['page_id']}.json"
            path.write_text(json.dumps(chk["envelope"], ensure_ascii=False, indent=2), encoding="utf-8")
            att["saved_to"] = str(path)
            log["saved"].append(str(path))
        else:
            fails += 1
        log["attempts"].append(att)
    if log["stopped_reason"] is None and fails >= breaker:
        log["stopped_reason"] = f"CIRCUIT_BREAKER_{breaker}_CONSECUTIVE_FAILURES"
    log["finished_at"] = now()
    return log


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Opt-in fetch of planned official SAP Help pages (network OFF by default).")
    ap.add_argument("--allow-network", action="store_true")
    ap.add_argument("--acknowledge-robots-disallow", action="store_true", help="operator decision when robots.txt disallows all generic agents (recorded in the log)")
    ap.add_argument("--only", nargs="*", help="source ids, e.g. M2C-03")
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--max-requests", type=int, default=25)
    ap.add_argument("--plan", default=str(PLAN_PATH))
    ap.add_argument("--log", default=str(LOG_PATH))
    ap.add_argument("--rebuild-after", action="store_true")
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    log = fetch_plan(plan, a.allow_network, delay_s=a.delay, max_requests=a.max_requests, acknowledge_robots=a.acknowledge_robots_disallow, only=a.only)
    Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(Path(a.log).read_text(encoding="utf-8")) if Path(a.log).is_file() else []
    Path(a.log).write_text(json.dumps(history + [log], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"network={'on' if a.allow_network else 'off'} robots={log['robots']} attempts={len(log['attempts'])} saved={len(log['saved'])} stopped={log['stopped_reason']}")
    if a.rebuild_after and log["saved"]:
        PC.build_corpus()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
