#!/usr/bin/env python3
"""SURA latency & performance benchmark harness.

Measures the shipped system against the fixed, versioned workload (CLI default: ``benchmarks/workload_v2.json``; v1 remains preserved).

Two measurement modes (never mixed into one number):

* ``stages``  - in-process through ``rag_service.build_service`` / ``RagService.ask(debug=True)``. Reports the
  pipeline's own per-stage timings (``route_ms`` = routing incl. the single query embedding + card retrieval +
  rerank, ``retrieve_ms`` = page-chunk retrieval, ``context_ms`` = evidence filtering/context assembly,
  ``generate_ms`` = answer generation, plus ``queue_wait_ms`` when the generation semaphore was contended and
  ``total_ms``), and the wall time of the full in-process ``ask()`` call (validation + session + guards included).
* ``e2e``     - HTTP against a running API (``--url``) or one spawned by the harness (``--spawn PORT``). Reports
  wall-clock request latency, throughput, cold-start samples, and a concurrency sweep (default 1/5/10/20 workers).

Every measured response is checked against the workload's explicit status, routed-card, citation-marker, source-identity,
provenance, and claim-review contract. These mechanical checks are NOT SAP semantic certification; semantic correctness
remains unassessed. Mismatches are recorded in ``correctness`` and, with ``--strict``, fail the run. Safe abstentions
are checked against fixed non-substantive responses, not counted as substantive correctness.

Honesty rules baked in:
* No fabricated numbers: everything is measured with ``time.perf_counter`` around the real code path.
* If the requested generator is not usable (e.g. ``ollama`` without a reachable server/model), the run is
  recorded as ``status: BLOCKED`` with the reason - it never silently measures something else.
* Cold start (first requests after process start) is reported separately from warm steady-state samples.
* Percentile method: nearest-rank on the sorted sample list (p = ceil(q/100 * n), 1-based). Sample counts are
  recorded for every statistic.

Usage examples (from the repository root, inside the project venv):
    python benchmarks/run_benchmark.py --mode stages --generator extractive --repeat 100
    python benchmarks/run_benchmark.py --mode e2e --generator extractive --spawn 8300 --repeat 30
    python benchmarks/run_benchmark.py --mode e2e --url http://127.0.0.1:8000 --concurrency-levels 1,5,10,20
    python benchmarks/run_benchmark.py --mode stages --generator ollama        # BLOCKED here without Ollama

Results are written to ``benchmarks/results/<utc>_<commit>_<generator>_<mode>.json`` (machine-readable).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "benchmarks"
RESULTS_DIR = BENCH_DIR / "results"
RUNTIME_ROOT = ROOT
sys.path.insert(0, str(ROOT / "scripts"))
from rag_status import API_STATUSES, WORKLOAD_STATUS_VOCABULARY  # noqa: E402
from citation_markers import is_marker_only_line, parse_citation_line, valid_marker  # noqa: E402
from claim_review_contract import validate_claim_review_metadata  # noqa: E402

GENERATION_TIMEOUT_S = 90.0
ADMISSION_CAP = None


# -------------------------------------------------------------------------------------------- environment

def _pkg_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _mem_total_kb() -> Optional[int]:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _git_state() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, args in (("commit", ["git", "rev-parse", "HEAD"]), ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"])):
        try:
            out[key] = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception as e:  # pragma: no cover
            out[key] = f"<error: {e}>"
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout
        out["dirty"] = bool(dirty.strip())
    except Exception:
        out["dirty"] = None
    return out


def capture_environment(generator: str, workload_sha: str) -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_model": _cpu_model(),
        "cpu_count_logical": os.cpu_count(),
        "mem_total_kb": _mem_total_kb(),
        "cgroup_cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip() if Path("/sys/fs/cgroup/cpu.max").exists() else None,
        "cgroup_memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip() if Path("/sys/fs/cgroup/memory.max").exists() else None,
        "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "packages": {p: _pkg_version(p) for p in
                     ("chromadb", "sentence-transformers", "torch", "fastapi", "uvicorn", "httpx", "ollama", "numpy", "pydantic")},
        "generator": generator,
        "git": _git_state(),
        "workload_sha256": workload_sha,
    }
    # Embedding weights provenance (offline resolution; never downloads)
    try:
        from m2c_common import resolve_model
        model_dir, info = resolve_model(None)
        env["embedding_model"] = {"name": "all-MiniLM-L6-v2", "dir": str(model_dir), "source": info.get("source") if isinstance(info, dict) else str(info)}
    except Exception as e:
        env["embedding_model"] = {"error": str(e)}
    # Corpus identity (runtime inputs actually used)
    try:
        pm = json.loads((ROOT / "data" / "page_collection_manifest.json").read_text(encoding="utf-8"))
        env["corpus"] = {"corpus_sha256": pm.get("corpus_sha256"), "chunks_fingerprint": pm.get("chunks_fingerprint"),
                         "page_vector_count": pm.get("vector_count")}
        cm = json.loads((ROOT / "data" / "card_collection_manifest.json").read_text(encoding="utf-8"))
        env["corpus"]["card_vector_count"] = cm.get("vector_count")
    except Exception as e:
        env["corpus"] = {"error": str(e)}
    if generator == "ollama":
        env["ollama"] = {"model": os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
                         "host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                         "timeout_s_env": os.environ.get("SURA_OLLAMA_TIMEOUT_SECONDS")}
    return env


def _peak_rss_mb() -> Optional[float]:
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


# -------------------------------------------------------------------------------------------- statistics

def pctl(sorted_samples: Sequence[float], q: float) -> Optional[float]:
    """Nearest-rank percentile: index = ceil(q/100 * n), 1-based."""
    n = len(sorted_samples)
    if n == 0:
        return None
    import math
    idx = max(1, min(n, math.ceil(q / 100.0 * n)))
    return sorted_samples[idx - 1]


def summarize(samples: Sequence[float]) -> Dict[str, Any]:
    s = sorted(samples)
    return {
        "n": len(s),
        "p50_ms": pctl(s, 50), "p95_ms": pctl(s, 95), "p99_ms": pctl(s, 99),
        "mean_ms": round(statistics.fmean(s), 2) if s else None,
        "stdev_ms": round(statistics.stdev(s), 2) if len(s) > 1 else None,
        "min_ms": s[0] if s else None, "max_ms": s[-1] if s else None,
    }


# -------------------------------------------------------------------------------------------- workload

def _strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate workload JSON key: {key}")
        result[key] = value
    return result


def load_workload(path=None) -> (Dict[str, Any], str):
    path = Path(path) if path else BENCH_DIR / "workload_v1.json"
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object), hashlib.sha256(raw).hexdigest()


_WORKLOAD_CATEGORIES = frozenset({
    "simple_supported", "complex_supported", "followup", "doc_length_variation",
    "insufficient_evidence", "out_of_scope", "unresolved_identity",
})


def validate_workload(workload: Any) -> Dict[str, Any]:
    """Validate a versioned workload against fixed API/status and case contracts before service construction."""
    errors: List[str] = []
    if not isinstance(workload, Mapping):
        return {"ok": False, "errors": ["workload must be an object"], "expected_ids": []}
    items = workload.get("items")
    if not isinstance(items, list) or not items:
        return {"ok": False, "errors": ["workload must contain a non-empty items list"], "expected_ids": []}
    workload_version = workload.get("workload_version")
    if not isinstance(workload_version, str) or workload_version not in {"v1", "v2"}:
        errors.append("workload_version must be a supported version (v1 or v2)")

    raw_statuses = workload.get("status_vocabulary")
    if (not isinstance(raw_statuses, list) or not raw_statuses
            or not all(isinstance(status, str) and status.strip() for status in raw_statuses)
            or len(raw_statuses) != len(set(raw_statuses))):
        errors.append("status_vocabulary must be a non-empty list of unique status strings")
    elif set(raw_statuses) != WORKLOAD_STATUS_VOCABULARY:
        errors.append("status_vocabulary differs from the authoritative workload vocabulary")

    ids: List[str] = []
    has_single_turn_case = False
    authoritative_statuses = set(API_STATUSES)
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"items[{index}] must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip() or item_id != item_id.strip():
            errors.append(f"items[{index}] has no canonical non-empty id")
        else:
            ids.append(item_id)
        category = item.get("category")
        if not isinstance(category, str) or category not in _WORKLOAD_CATEGORIES:
            errors.append(f"item {item_id!r} has missing or unknown category {category!r}")
        expected = item.get("expected_status")
        if not isinstance(expected, str) or expected not in authoritative_statuses:
            errors.append(f"item {item_id!r} has missing or unknown API expected_status {expected!r}")
        turns = item.get("turns")
        if not isinstance(turns, list) or not turns or any(
                not isinstance(turn, Mapping) or not isinstance(turn.get("message"), str) or not turn["message"].strip()
                for turn in turns):
            errors.append(f"item {item_id!r} has invalid turns")
            continue
        has_single_turn_case = has_single_turn_case or len(turns) == 1
        measured_turn = item.get("measured_turn", len(turns))
        if type(measured_turn) is not int or not 1 <= measured_turn <= len(turns):
            errors.append(f"item {item_id!r} has invalid measured_turn")
        if "expected_card_id" in item and item["expected_card_id"] is not None:
            card_id = item["expected_card_id"]
            if not isinstance(card_id, str) or not re.fullmatch(r"M2C-\d{2}", card_id):
                errors.append(f"item {item_id!r} has invalid expected_card_id")
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        errors.append("duplicate item ids: " + ", ".join(duplicates))
    if len(ids) != len(items):
        errors.append("every workload item must have a unique non-empty case ID")
    if not has_single_turn_case:
        errors.append("workload must contain at least one single-turn case for the concurrency sweep")
    return {"ok": not errors, "errors": errors, "expected_ids": ids, "duplicate_expected_ids": duplicates}


def validate_observation_ids(items: Sequence[Dict[str, Any]], observations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Reconcile exact workload IDs and one summary observation per case; malformed inputs fail closed."""
    items_valid = isinstance(items, Sequence) and not isinstance(items, (str, bytes))
    observations_valid = isinstance(observations, Sequence) and not isinstance(observations, (str, bytes))
    item_rows = list(items) if items_valid else []
    observation_rows = list(observations) if observations_valid else []
    expected = [item.get("id") if isinstance(item, Mapping) and isinstance(item.get("id"), str) else ""
                for item in item_rows]
    observed = [row.get("id") if isinstance(row, Mapping) and isinstance(row.get("id"), str) else ""
                for row in observation_rows]
    expected_set, observed_set = set(expected), set(observed)
    duplicates_expected = sorted({key for key in expected if expected.count(key) > 1})
    duplicates_observed = sorted({key for key in observed if observed.count(key) > 1})
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    empty_expected = [index for index, key in enumerate(expected) if not key]
    empty = [index for index, key in enumerate(observed) if not key]
    malformed_input = not items_valid or not observations_valid
    return {"ok": not (malformed_input or duplicates_expected or duplicates_observed or missing or unexpected
                        or empty_expected or empty),
            "expected_count": len(expected), "observed_count": len(observed), "missing_ids": missing,
            "duplicate_expected_ids": duplicates_expected, "duplicate_observed_ids": duplicates_observed,
            "unexpected_ids": unexpected, "empty_expected_id_rows": empty_expected, "empty_id_rows": empty,
            "malformed_input": malformed_input}


_SAFE_NONANSWER_TEXTS = {
    "I found the relevant topic, but the underlying SAP Help page is not currently available in the local knowledge base.",
    "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.",
    "This question doesn't appear to match the SAP Utilities documentation available to me.",
    "I couldn't verify the relevant documentation.",
    "That's all the additional detail I could verify from the available documentation.",
}
_HASH64 = re.compile(r"^[0-9a-f]{64}$", re.I)
_ID32 = re.compile(r"^[0-9a-f]{32}$", re.I)
_PROCEDURE_LIMITATION = "The selected evidence does not establish a complete step-by-step procedure."


def evaluate_response_contract(item: Dict[str, Any], body: Any, http_status: int = 200) -> Dict[str, Any]:
    """Mechanical response contract, not a semantic correctness judgment."""
    failures: List[str] = []
    if not isinstance(body, dict):
        return {"ok": False, "failures": ["RESPONSE_BODY_NOT_OBJECT"], "semantic_correctness": None}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    status = body.get("status")
    expected_status = item.get("expected_status")
    answer = body.get("answer") if isinstance(body.get("answer"), str) else ""
    sources = body.get("sources") if isinstance(body.get("sources"), list) else None
    if http_status != 200:
        failures.append("HTTP_STATUS_NOT_200")
    if status != expected_status:
        failures.append("STATUS_MISMATCH")
    if "expected_card_id" in item and metadata.get("card_id") != item.get("expected_card_id"):
        failures.append("ROUTED_CARD_MISMATCH")
    if sources is None:
        failures.append("SOURCES_NOT_LIST")
        sources = []
    if expected_status == "answered":
        if metadata.get("grounded") is not True:
            failures.append("NOT_GROUNDED")
        claim_review = metadata.get("claim_grounding")
        claim_review_ok, _claim_review_errors = validate_claim_review_metadata(
            claim_review, answer)
        if not claim_review_ok:
            failures.append("CLAIM_REVIEW_CONTRACT_INVALID")
        marker_refs: List[str] = []
        malformed: List[str] = []
        duplicates: List[str] = []
        for line in answer.splitlines():
            line_markers, line_malformed, body_text = parse_citation_line(line, allow_compound=False)
            marker_refs.extend(line_markers)
            malformed.extend(line_malformed)
            duplicates.extend(sorted({marker for marker in line_markers if line_markers.count(marker) > 1}))
            if is_marker_only_line(line, allow_compound=False):
                failures.append("MARKER_ONLY_CITATION_LINE")
            elif body_text and body_text.casefold() != _PROCEDURE_LIMITATION.casefold() and not line_markers:
                failures.append("UNCITED_ANSWER_LINE")
        if not marker_refs:
            failures.append("NO_CITATION_MARKERS")
        if malformed:
            failures.append("MALFORMED_CITATION_MARKER")
        if duplicates:
            failures.append("DUPLICATE_CITATION_MARKER")
        by_marker: Dict[str, List[Dict[str, Any]]] = {}
        for source in sources:
            if not isinstance(source, dict):
                failures.append("SOURCE_OBJECT_NOT_OBJECT")
                continue
            marker = source.get("marker")
            if not valid_marker(marker):
                failures.append("SOURCE_MARKER_INVALID")
                continue
            by_marker.setdefault(marker, []).append(source)
            guide_id, page_id = source.get("guide_id"), source.get("page_id")
            doc_id, chunk_id = source.get("doc_id"), source.get("chunk_id")
            source_id, source_ids = source.get("source_id"), source.get("source_ids")
            if source.get("type") != "page":
                failures.append("SOURCE_TYPE_INVALID")
            if not isinstance(guide_id, str) or not _ID32.fullmatch(guide_id) or not isinstance(page_id, str) or not _ID32.fullmatch(page_id):
                failures.append("SOURCE_PAGE_ID_INVALID")
            expected_doc_id = f"{guide_id}/{page_id}"
            if doc_id != expected_doc_id or not isinstance(chunk_id, str) or not re.fullmatch(re.escape(expected_doc_id) + r"/\d{3}", chunk_id):
                failures.append("SOURCE_CHUNK_IDENTITY_INVALID")
            expected_card = item.get("expected_card_id")
            if (not isinstance(source_id, str) or not source_id or not isinstance(source_ids, list)
                    or not all(isinstance(value, str) for value in source_ids)
                    or source_id not in source_ids or len(source_ids) != len(set(source_ids))
                    or (expected_card is not None and source_id != expected_card)):
                failures.append("SOURCE_CARD_PROVENANCE_INVALID")
            if not isinstance(source.get("content_hash"), str) or not _HASH64.fullmatch(source.get("content_hash", "")):
                failures.append("SOURCE_CONTENT_HASH_INVALID")
            if not isinstance(source.get("page_text_sha256"), str) or not _HASH64.fullmatch(source.get("page_text_sha256", "")):
                failures.append("SOURCE_PAGE_HASH_INVALID")
            source_url = source.get("url")
            if source_url is not None and (not isinstance(source_url, str)
                                           or not source_url.startswith(("https://", "http://"))
                                           or source.get("url_status") != "VERIFIED"):
                failures.append("UNVERIFIED_SOURCE_URL_EXPOSED")
        duplicate_sources = sorted(marker for marker, rows in by_marker.items() if len(rows) != 1)
        if duplicate_sources:
            failures.append("SOURCE_MARKER_NOT_UNIQUE")
        if set(marker_refs) != set(by_marker):
            failures.append("ANSWER_SOURCE_MARKER_SET_MISMATCH")
        for line in answer.splitlines():
            line_markers, _line_malformed, clean = parse_citation_line(line, allow_compound=False)
            if clean and clean.casefold() != _PROCEDURE_LIMITATION.casefold() and not line_markers:
                failures.append("UNCITED_ANSWER_LINE")
                break
    else:
        if status == "answered":
            failures.append("UNEXPECTED_ANSWERED_STATUS")
        if metadata.get("grounded") is not False:
            failures.append("NONANSWER_MARKED_GROUNDED")
        if sources:
            failures.append("NONANSWER_HAS_SOURCES")
        if answer not in _SAFE_NONANSWER_TEXTS:
            failures.append("NONANSWER_TEXT_NOT_IN_FIXED_SAFE_SET")
        nonanswer_markers, nonanswer_malformed, _nonanswer_body = parse_citation_line(
            answer, allow_compound=True)
        if nonanswer_markers or nonanswer_malformed:
            failures.append("NONANSWER_HAS_CITATION_MARKER")
    return {"ok": not failures, "failures": sorted(set(failures)), "observed_status": status,
            "http_status": http_status, "source_count": len(sources), "semantic_correctness": None,
            "note": "Mechanical identity/citation/status checks only; no SAP semantic adjudication."}


# -------------------------------------------------------------------------------------------- stages mode

def run_stages(generator: str, workload: Dict[str, Any], repeat: int, warmup: int) -> Dict[str, Any]:
    import rag_service as S

    t_build0 = time.perf_counter()
    svc = S.build_service(generator)
    build_s = time.perf_counter() - t_build0

    # Fail-closed preflight for ollama: never "measure" a generator that cannot produce answers here.
    if generator == "ollama":
        try:
            from rag_generate import OllamaClient
            probe = OllamaClient(model=os.environ.get("OLLAMA_MODEL"))
            if not probe.check_available():
                return {"status": "BLOCKED",
                        "blocked_reason": "Ollama server/model not reachable from this environment (check_available() == False); no measurement performed.",
                        "service_build_s": round(build_s, 3)}
        except Exception as e:
            return {"status": "BLOCKED", "blocked_reason": f"Ollama preflight failed: {e}", "service_build_s": round(build_s, 3)}

    # Cold start: the very first ask() in a fresh process (lazy Chroma open, first encode, guard warm-up).
    cold_samples: List[Dict[str, Any]] = []
    first = workload["items"][0]
    t0 = time.perf_counter()
    res = svc.ask(first["turns"][0]["message"], conversation_id="bench-cold", debug=True)
    cold_samples.append({"wall_ms": round((time.perf_counter() - t0) * 1000, 2), "status": res.get("status"),
                         "timings_ms": (res.get("debug") or {}).get("timings_ms")})

    # Warmup (excluded from stats)
    for _ in range(warmup):
        svc.ask(first["turns"][0]["message"], conversation_id="bench-warm", debug=True)

    per_item: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    all_walls = []
    all_stages = {}
    all_statuses = {}
    stage_names = ("validation_ms", "support_chain_ms", "route_ms", "embed_ms", "card_query_ms", "rerank_ms", "retrieve_ms", "context_ms",
                   "generate_ms", "verify_ms", "queue_wait_ms", "total_ms")
    for item in workload["items"]:
        walls: List[float] = []
        pipe_totals: List[float] = []
        by_stage: Dict[str, List[float]] = {k: [] for k in stage_names}
        statuses: Dict[str, int] = {}
        contract_passes = 0
        contract_failure_counts: Dict[str, int] = {}
        conv = 0
        for _ in range(repeat):
            conv += 1
            cid = f"bench-{item['id']}-{conv}"
            measured_turn = item.get("measured_turn", len(item["turns"]))
            result = None
            measured_result = None
            for ti, turn in enumerate(item["turns"], start=1):
                t_wall = time.perf_counter()
                result = svc.ask(turn["message"], conversation_id=cid, debug=True)
                if ti == measured_turn:
                    measured_result = result
                    wall = (time.perf_counter() - t_wall) * 1000
                    walls.append(wall)
                    all_walls.append(wall)
            result = measured_result if measured_result is not None else result
            contract = evaluate_response_contract(item, result, 200)
            if contract["ok"]:
                contract_passes += 1
            for failure in contract["failures"]:
                contract_failure_counts[failure] = contract_failure_counts.get(failure, 0) + 1
            st = result.get("status") if result else None
            statuses[st] = statuses.get(st, 0) + 1
            all_statuses[st] = all_statuses.get(st, 0) + 1
            if not contract["ok"] or st != item["expected_status"]:
                mismatches.append({"item": item["id"], "expected": item["expected_status"], "observed": st,
                                   "contract_failures": contract["failures"]})
            tm = ((result or {}).get("debug") or {}).get("timings_ms") or {}
            for k in stage_names:
                if isinstance(tm.get(k), (int, float)):
                    by_stage[k].append(float(tm[k]))
                    all_stages.setdefault(k, []).append(float(tm[k]))
            if isinstance(tm.get("total_ms"), (int, float)):
                pipe_totals.append(float(tm["total_ms"]))
        per_item.append({
            "id": item["id"], "category": item["category"], "expected_status": item["expected_status"],
            "observed_statuses": statuses,
            "response_contract": {"checked": repeat, "passed": contract_passes,
                                  "failure_counts": contract_failure_counts,
                                  "semantic_correctness": None},
            "wall": summarize(walls),
            "pipeline_total": summarize(pipe_totals),
            "stages": {k: summarize(v) for k, v in by_stage.items() if v},
            "observed_card_id": (result.get("metadata") or {}).get("card_id"),
            "context_chunk_count": len((((result.get("debug") or {}).get("pipeline") or {}).get("context") or {}).get("items", [])),
            "page_char_count": len(svc.pipeline.corpus.page_text((result.get("metadata") or {}).get("card_id")) or "") if (result.get("metadata") or {}).get("card_id") else 0,
        })

    case_id_validation = validate_observation_ids(workload["items"], per_item)
    return {
        "status": "OK" if case_id_validation["ok"] else "INVALID",
        "case_id_validation": case_id_validation,
        "service_build_s": round(build_s, 3),
        "cold_start": cold_samples,
        "per_item": per_item,
        "aggregate_wall": summarize(all_walls),
        "aggregate_stages": {k: summarize(v) for k, v in all_stages.items()},
        "observed_statuses": all_statuses,
        "correctness": {"expected_status_mismatches": mismatches, "mismatch_count": len(mismatches),
                        "substantive_semantic_correctness": None},
        "peak_rss_mb": _peak_rss_mb(),
    }


# -------------------------------------------------------------------------------------------- e2e mode

def _wait_health(base: str, timeout_s: float = 90.0) -> bool:
    import httpx
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=3.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.4)
    return False


def _chat(base: str, client, message: str, cid: str, expected_item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        r = client.post(f"{base}/api/chat", json={"message": message, "conversation_id": cid}, timeout=GENERATION_TIMEOUT_S)
    except Exception as exc:
        failed = {"wall_ms": (time.perf_counter() - t0) * 1000, "http_status": 0, "body_status": None,
                  "error_code": type(exc).__name__, "timeout": isinstance(exc, __import__("httpx").TimeoutException)}
        if expected_item is not None:
            failed["response_contract"] = {"ok": False, "failures": ["REQUEST_FAILED"], "semantic_correctness": None}
        return failed
    wall = (time.perf_counter() - t0) * 1000
    try:
        body = r.json()
    except Exception:
        body = {"_non_json": r.text[:200]}
    result = {"wall_ms": wall, "http_status": r.status_code, "body_status": body.get("status"), "generator": (body.get("metadata") or {}).get("generator"),
              "grounded": (body.get("metadata") or {}).get("grounded"), "source_count": len(body.get("sources") or []), "card_id": (body.get("metadata") or {}).get("card_id"),
              "error_code": (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None}
    if expected_item is not None:
        result["response_contract"] = evaluate_response_contract(expected_item, body, r.status_code)
    return result


def run_e2e(generator: str, workload: Dict[str, Any], repeat: int, warmup: int,
            url: Optional[str], spawn_port: Optional[int], levels: List[int], conc_requests: int) -> Dict[str, Any]:
    import httpx

    spawned = None
    if url:
        base = url.rstrip("/")
    else:
        port = spawn_port or 8300
        base = f"http://127.0.0.1:{port}"
        cmd = [sys.executable, str(RUNTIME_ROOT / "scripts" / "rag_api.py"), "--host", "127.0.0.1", "--port", str(port), "--generator", generator]
        # A benchmark must measure the pipeline, not the admission/rate limiters. The spawned server runs with
        # both limits lifted; the production defaults (60/min per IP, 4 concurrent) are unchanged and are
        # verified by tests/test_concurrency_ratelimit.py and by the e2e contamination guard below.
        spawn_env = dict(os.environ, SURA_RATE_LIMIT_PER_MINUTE="10000000")
        if ADMISSION_CAP is not None:
            spawn_env["SURA_MAX_CONCURRENT_REQUESTS"] = str(ADMISSION_CAP)
        spawned = subprocess.Popen(cmd, cwd=RUNTIME_ROOT, env=spawn_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not _wait_health(base) or spawned.poll() is not None:
            spawned.terminate()
            return {"status": "BLOCKED", "blocked_reason": f"spawned server did not become healthy at {base}"}

    out: Dict[str, Any] = {"status": "OK", "base_url": base, "admission_cap_override": ADMISSION_CAP,
                           "service_concurrency": 4, "cold_start_claim": "fresh process" if spawned else "external server state unknown",
                           "rate_limit_note": ("spawned server: SURA_RATE_LIMIT_PER_MINUTE and SURA_MAX_CONCURRENT_REQUESTS lifted for measurement"
                                               if spawned else "external server: lift SURA_RATE_LIMIT_PER_MINUTE and SURA_MAX_CONCURRENT_REQUESTS or results are INVALID")}
    try:
        # Readiness gate (honest mode reporting)
        r = httpx.get(f"{base}/ready", timeout=10.0)
        out["ready_http_status"] = r.status_code
        try:
            out["ready_body"] = r.json()
        except Exception:
            out["ready_body"] = r.text[:200]
        if generator == "ollama" and r.status_code != 200:
            out["status"] = "BLOCKED"
            out["blocked_reason"] = f"/ready reported {r.status_code} for generator=ollama; no latency measured (fail-closed readiness)."
            return out

        with httpx.Client(headers={"Content-Type": "application/json"}) as client:
            # Cold start: first 3 chat requests against the freshly (re)started server
            out["cold_start"] = [_chat(base, client, workload["items"][0]["turns"][0]["message"], f"bench-cold-{i}") for i in range(3)]

            first = workload["items"][0]
            for _ in range(warmup):
                _chat(base, client, first["turns"][0]["message"], "bench-warm")

            # Sequential per-item latency + correctness
            per_item = []
            all_walls = []
            all_statuses = {}
            mismatches = []
            errors = 0
            for item in workload["items"]:
                samples = []
                http_codes: Dict[int, int] = {}
                contract_passes = 0
                contract_failure_counts: Dict[str, int] = {}
                conv = 0
                for _ in range(repeat):
                    conv += 1
                    cid = f"bench-e2e-{item['id']}-{conv}"
                    measured_turn = item.get("measured_turn", len(item["turns"]))
                    last = None
                    for ti, turn in enumerate(item["turns"], start=1):
                        last = _chat(base, client, turn["message"], cid,
                                     expected_item=item if ti == measured_turn else None)
                        if ti == measured_turn:
                            samples.append(last["wall_ms"])
                            all_walls.append(last["wall_ms"])
                    http_codes[last["http_status"]] = http_codes.get(last["http_status"], 0) + 1
                    all_statuses[last["body_status"]] = all_statuses.get(last["body_status"], 0) + 1
                    if last["http_status"] >= 500 or last["http_status"] == 0:
                        errors += 1
                    response_contract = last.get("response_contract") or {"ok": False, "failures": ["CONTRACT_NOT_CHECKED"]}
                    if response_contract.get("ok"):
                        contract_passes += 1
                    for failure in response_contract.get("failures", []):
                        contract_failure_counts[failure] = contract_failure_counts.get(failure, 0) + 1
                    if (not response_contract.get("ok") or
                        (last.get("generator") != generator and len(item["turns"]) == 1)):
                        mismatches.append({"item": item["id"], "expected": item["expected_status"],
                                           "observed": last["body_status"], "http": last["http_status"],
                                           "contract_failures": response_contract.get("failures"),
                                           "error_code": last["error_code"]})
                per_item.append({"id": item["id"], "category": item["category"],
                                 "expected_status": item["expected_status"], "http_codes": http_codes,
                                 "response_contract": {"checked": repeat, "passed": contract_passes,
                                                       "failure_counts": contract_failure_counts,
                                                       "semantic_correctness": None},
                                 "latency": summarize(samples)})

            # Concurrency sweep on a mixed workload (round-robin over items, single-turn requests)
            sweep = []
            single_turn_items = [it for it in workload["items"] if len(it["turns"]) == 1]
            for level in levels:
                def one(i: int) -> Dict[str, Any]:
                    it = single_turn_items[i % len(single_turn_items)]
                    response = _chat(base, client, it["turns"][0]["message"], f"bench-conc-{level}-{i}", expected_item=it)
                    response["expected_status"] = it["expected_status"]
                    contract = response.get("response_contract") or {"ok": False, "failures": ["CONTRACT_NOT_CHECKED"]}
                    response["correct"] = bool(contract.get("ok")) and (response.get("generator") == generator)
                    return response
                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=level) as ex:
                    results = list(ex.map(one, range(conc_requests)))
                span = time.perf_counter() - t0
                walls = [r["wall_ms"] for r in results]
                errs = sum(1 for r in results if r["http_status"] >= 500 or r["http_status"] == 0)
                rate_limited = sum(1 for r in results if r["http_status"] == 429)
                abst = sum(1 for r in results if r["body_status"] in ("out_of_scope", "unable_to_verify", "documentation_unavailable"))
                answered = sum(1 for r in results if r["body_status"] == "answered")
                accepted = [r for r in results if r["http_status"] == 200]
                rejected = [r for r in results if r["http_status"] == 429]
                correct = sum(bool(r["correct"]) for r in accepted)
                sweep.append({"concurrency": level, "requests": conc_requests, "wall_span_s": round(span, 3),
                              "throughput_rps": round(conc_requests / span, 2) if span > 0 else None,
                              "latency_all_responses": summarize(walls),
                              "latency": summarize([r["wall_ms"] for r in accepted]),
                              "rejection_latency": summarize([r["wall_ms"] for r in rejected]),
                              "accepted": len(accepted), "accepted_correct": correct,
                              "completed_rps": round(len(accepted) / span, 2),
                              "error_rate": errs / conc_requests, "timeout_count": sum(bool(r.get("timeout")) for r in results),
                              "rejection_rate": rate_limited / conc_requests,
                              "abstention_rate": abst / len(accepted) if accepted else None,
                              "http_5xx": errs, "http_429": rate_limited,
                              "answered": answered, "abstentions": abst})
            out["concurrency_sweep"] = sweep
            out["per_item"] = per_item
            out["case_id_validation"] = validate_observation_ids(workload["items"], per_item)
            out["aggregate_wall"] = summarize(all_walls)
            out["observed_statuses"] = all_statuses
            out["correctness"] = {"expected_status_mismatches": mismatches[:50], "mismatch_count": len(mismatches),
                                  "http_5xx_sequential": errors, "substantive_semantic_correctness": None}
            if not out["case_id_validation"]["ok"]:
                out["status"] = "INVALID"
                out["blocked_reason"] = "Per-item observations do not reconcile exactly to workload case IDs."
            # Contamination guard: if the rate limiter (or anything else) turned a meaningful share of responses
            # into 429s, the latency/throughput numbers measure rejection handling, not the pipeline. Refuse to
            # present them as a valid benchmark.
            total_req = sum(sum(it["http_codes"].values()) for it in per_item) + sum(s["requests"] for s in sweep)
            total_429 = sum(c for it in per_item for k, c in it["http_codes"].items() if k == 429) + sum(s["http_429"] for s in sweep)
            out["rate_limit_contamination"] = {"requests": total_req, "http_429": total_429,
                                               "fraction": round(total_429 / total_req, 4) if total_req else None}
            sequential_429 = sum(c for it in per_item for k, c in it["http_codes"].items() if k == 429)
            if sequential_429:
                out["status"] = "INVALID"
                out["blocked_reason"] = (f"{total_429}/{total_req} responses were HTTP 429 (rate limited); latency and "
                                         "throughput numbers would measure rejection handling, not the pipeline. Re-run "
                                         "against a server with SURA_RATE_LIMIT_PER_MINUTE lifted.")
            out["server_peak_rss_mb"] = _proc_rss_mb(spawned.pid) if spawned else None
        out["peak_rss_mb_client"] = _peak_rss_mb()
        return out
    finally:
        if spawned is not None:
            spawned.terminate()
            try:
                spawned.wait(timeout=10)
            except Exception:
                spawned.kill()


def _proc_rss_mb(pid: int) -> Optional[float]:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


# -------------------------------------------------------------------------------------------- main

def _parse_concurrency_levels(value: str) -> List[int]:
    """Parse a non-empty comma-separated list of positive worker counts for the E2E sweep."""
    parts = value.split(",")
    if not parts or any(not part.strip() for part in parts):
        raise argparse.ArgumentTypeError("concurrency levels must be comma-separated positive integers")
    try:
        levels = [int(part.strip()) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "concurrency levels must be comma-separated positive integers") from exc
    if any(level <= 0 for level in levels):
        raise argparse.ArgumentTypeError("concurrency levels must all be positive")
    return levels


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workload", type=Path, default=BENCH_DIR / "workload_v2.json")
    ap.add_argument("--mode", choices=("stages", "e2e"), required=True)
    ap.add_argument("--generator", choices=("extractive", "ollama"), default="extractive")
    ap.add_argument("--repeat", type=int, default=None, help="measured repetitions per workload item (default: stages=100, e2e=30)")
    ap.add_argument("--warmup", type=int, default=None, help="warmup requests excluded from stats (default: stages=10, e2e=5)")
    ap.add_argument("--url", default=None, help="e2e: base URL of an already-running API")
    ap.add_argument("--spawn", type=int, default=None, metavar="PORT", help="e2e: spawn the API on this port (default when --url absent: 8300)")
    ap.add_argument("--concurrency-levels", type=_parse_concurrency_levels, default="1,5,10,20")
    ap.add_argument("--concurrency-requests", type=int, default=100, help="requests per concurrency level")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on expected_status mismatches")
    ap.add_argument("--out", default=None)
    ap.add_argument("--source-root", type=Path, help="optional immutable git-archive source tree for paired baseline")
    ap.add_argument("--source-commit", help="commit used to export --source-root, recorded separately from harness commit")
    ap.add_argument("--admission-cap", type=int, default=None, help="e2e spawned API admission override; default uses production 4")
    a = ap.parse_args(argv)
    if (a.repeat is not None and a.repeat < 1) or (a.warmup is not None and a.warmup < 0):
        ap.error("repeat must be >=1 and warmup >=0")
    if a.concurrency_requests < 1:
        ap.error("concurrency-requests must be >=1")
    if a.admission_cap is not None and a.admission_cap < 1:
        ap.error("admission-cap must be >=1")
    if a.spawn is not None and not 1 <= a.spawn <= 65535:
        ap.error("spawn port must be between 1 and 65535")
    if a.mode != "e2e" and (a.url is not None or a.spawn is not None):
        ap.error("--url and --spawn are only valid with --mode e2e")
    if a.url is not None:
        if not a.url or a.url != a.url.strip() or any(character.isspace() for character in a.url):
            ap.error("url must be a non-empty absolute HTTP(S) URL without whitespace")
        if a.spawn is not None:
            ap.error("choose either --url or --spawn, not both")
        try:
            parsed_url = urlsplit(a.url)
            _url_port = parsed_url.port
        except ValueError:
            ap.error("url has an invalid host or port")
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            ap.error("url must be an absolute HTTP(S) URL with a hostname")
    if a.out and Path(a.out).exists():
        ap.error("Output already exists; choose a new versioned path")

    if a.mode == "e2e" and a.generator == "ollama" and a.url is None and a.spawn is None:
        a.spawn = 8301

    repeat = a.repeat if a.repeat is not None else (100 if a.mode == "stages" else 30)
    warmup = a.warmup if a.warmup is not None else (10 if a.mode == "stages" else 5)
    levels = a.concurrency_levels

    workload_error = None
    try:
        workload, wsha = load_workload(a.workload)
    except (OSError, UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        workload, wsha = None, None
        workload_error = f"{type(exc).__name__}: {exc}"
    if workload_error:
        workload_validation = {"ok": False, "errors": ["workload JSON could not be loaded", workload_error],
                               "expected_ids": []}
    else:
        workload_validation = validate_workload(workload)
    if workload_validation["ok"]:
        global RUNTIME_ROOT, ADMISSION_CAP
        runtime_root = ROOT
        if a.source_root is not None:
            try:
                runtime_root = a.source_root.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                ap.error(f"source-root must be an existing source tree ({type(exc).__name__})")
            if not runtime_root.is_dir() or not (runtime_root / "scripts" / "rag_service.py").is_file():
                ap.error("source-root must contain scripts/rag_service.py")
        RUNTIME_ROOT = runtime_root
        ADMISSION_CAP = a.admission_cap
        if a.source_root is not None:
            sys.path.insert(0, str(RUNTIME_ROOT / "scripts"))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()

    if not workload_validation["ok"]:
        core = {"status": "INVALID", "blocked_reason": "Workload contract is invalid; no service or store was constructed.",
                "workload_validation": workload_validation}
    elif a.mode == "stages":
        core = run_stages(a.generator, workload, repeat, warmup)
    else:
        core = run_e2e(a.generator, workload, repeat, warmup, a.url, a.spawn, levels, a.concurrency_requests)
    core["workload_validation"] = workload_validation

    valid_workload = workload_validation["ok"] is True
    result = {
        "benchmark_version": "1.2",
        "source_commit": a.source_commit or (_git_state()["commit"] if valid_workload else None),
        "source_tree": "immutable git archive" if a.source_root else "working tree (see git dirty flag)",
        "workload_version": workload.get("workload_version") if isinstance(workload, Mapping) else None,
        "workload_sha256": wsha,
        "mode": a.mode,
        "generator": a.generator,
        "started_utc": started,
        "duration_s": round(time.perf_counter() - t0, 1),
        "config": {"repeat_per_item": repeat, "warmup": warmup, "concurrency_levels": levels if a.mode == "e2e" else None,
                   "concurrency_requests_per_level": a.concurrency_requests if a.mode == "e2e" else None,
                   "percentile_method": "nearest-rank (ceil(q/100*n), 1-based)",
                   "generation_timeout_s": GENERATION_TIMEOUT_S},
        "environment": (capture_environment(a.generator, wsha) if valid_workload else
                        {"workload_sha256": wsha, "capture_skipped": True}),
        "results": core,
    }

    commit = (result["environment"].get("git") or {}).get("commit", "nogit")[:7]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(a.out) if a.out else RESULTS_DIR / f"{stamp}_{commit}_{a.generator}_{a.mode}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("x", encoding="utf-8") as target:
        json.dump(result, target, indent=2, sort_keys=False)
        target.write("\n")

    try:
        shown_path = str(out_path.relative_to(ROOT))
    except ValueError:
        shown_path = str(out_path)
    print(json.dumps({"status": core.get("status"), "blocked_reason": core.get("blocked_reason"),
                      "mismatches": (core.get("correctness") or {}).get("mismatch_count"),
                      "results_file": shown_path}, indent=2))
    if core.get("status") in ("BLOCKED", "INVALID"):
        return 2
    if a.strict and ((core.get("correctness") or {}).get("mismatch_count") or
                     any(x.get("accepted_correct") != x.get("accepted") or x.get("http_5xx")
                         for x in core.get("concurrency_sweep", []))):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
