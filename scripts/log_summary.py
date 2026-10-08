"""Deterministic structured log summary utility for SURA observability.

Computes request counts, route counts, error counts, latency percentiles, and abstention rate.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_vals[int(k)], 2)
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return round(d0 + d1, 2)


def summarize_logs(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize a sequence of structured JSON log records."""
    total_requests = 0
    error_count = 0
    route_counts: Dict[str, int] = {}
    latencies: List[float] = []
    abstentions = 0
    answered_count = 0

    for rec in records:
        if not isinstance(rec, dict):
            continue
        total_requests += 1

        status = str(rec.get("status") or "")
        http_status = int(rec.get("http_status") or 200)

        if http_status >= 400 or status == "error" or rec.get("error"):
            error_count += 1
            route = rec.get("route") or "error"
            route_counts[route] = route_counts.get(route, 0) + 1
            lat = rec.get("latency_ms")
            if lat is not None:
                try:
                    latencies.append(float(lat))
                except (ValueError, TypeError):
                    pass
            continue

        route = str(rec.get("route") or "unknown")
        route_counts[route] = route_counts.get(route, 0) + 1

        if status in ("unable_to_verify", "out_of_scope", "documentation_unavailable"):
            abstentions += 1
        elif status == "answered":
            answered_count += 1

        lat = rec.get("latency_ms")
        if lat is None and isinstance(rec.get("latency_per_stage"), dict):
            lat = rec["latency_per_stage"].get("total_ms")
        if lat is not None:
            try:
                latencies.append(float(lat))
            except (ValueError, TypeError):
                pass

    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)

    completed = abstentions + answered_count
    abstention_rate = round(abstentions / completed, 4) if completed > 0 else 0.0

    return {
        "request_count": total_requests,
        "route_counts": dict(sorted(route_counts.items())),
        "error_count": error_count,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "abstention_rate": abstention_rate,
    }


def parse_log_lines(lines: Iterable[str]) -> List[Dict[str, Any]]:
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Summarize structured JSON logs.")
    ap.add_argument("log_file", nargs="?", default=None, help="Path to JSONL log file (stdin if omitted)")
    a = ap.parse_args(argv)

    if a.log_file:
        p = Path(a.log_file)
        if not p.is_file():
            print(f"Error: {p} does not exist", file=sys.stderr)
            return 1
        with open(p, "r", encoding="utf-8") as f:
            records = parse_log_lines(f)
    else:
        records = parse_log_lines(sys.stdin)

    summary = summarize_logs(records)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
