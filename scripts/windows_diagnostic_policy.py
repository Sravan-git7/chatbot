"""Diagnostic classification only; never changes retrieval or frozen acceptance rules."""
from decimal import Decimal
import math


def rounding_evidence(actual, recorded, decimals=4):
    """Explain the existing Python round(float, 4) check without widening it.

    Recorded baselines contain quantized scores, not historical raw floats. A
    delta from that decimal is NOT a measured delta from historical inference.
    """
    actual, recorded = float(actual), float(recorded)
    if not math.isfinite(actual) or not math.isfinite(recorded):
        raise ValueError("Non-finite similarity cannot be evaluated")
    center = Decimal(str(recorded))
    half = Decimal(1).scaleb(-decimals) / 2
    exact = Decimal.from_float(actual)
    low, high = center - half, center + half
    return {"recorded_4dp": recorded, "actual_raw": actual, "actual_hex": actual.hex(),
            "actual_4dp": round(actual, decimals), "strict_4dp_match": round(actual, decimals) == recorded,
            "delta_from_quantized_reference": float(abs(exact - center)),
            "reference_raw_score_available": False,
            "nominal_lower_decimal_boundary": str(low), "nominal_upper_decimal_boundary": str(high),
            "signed_delta_from_upper_boundary": float(exact - high),
            "distance_to_recorded_rounding_boundary": float(min(abs(exact - low), abs(exact - high))),
            "policy": "Python round(float, 4) equality remains mandatory; no tolerance or baseline change"}


def diagnostic_outcome(result):
    """0 = all checks pass, 2 = completed with failed gates, 3 = incomplete/error.

    Child status and original-store immutability are execution prerequisites,
    not integrity assertions that can be ignored to obtain a pass.
    """
    failures, errors = [], []
    for kind in ("page", "card"):
        block = result.get(kind, {})
        if block.get("worker_exit", 0) != 0 or block.get("BLOCKED") or block.get("error"):
            errors.append({"scope": kind, "reason": block.get("BLOCKED") or block.get("error") or "child process failed"})
            continue
        if block.get("original_store_unchanged") is not True:
            errors.append({"scope": kind, "reason": "original store changed or immutability could not be verified"})
        if kind == "page":
            for check, passed in block.get("checks", {}).items():
                if passed is not True:
                    failures.append(f"page.{check}")
            if not block.get("checks") or block.get("all_pass") != all(v is True for v in block.get("checks", {}).values()):
                errors.append({"scope": kind, "reason": "page check results missing or internally inconsistent"})
        else:
            if block.get("single_query_focus_match") is False:
                failures.append("card.single_query_focus_match")
            for check in ("passes_existing_vector_threshold", "ranking_and_4dp_match"):
                if block.get(check) is not True:
                    failures.append(f"card.{check}")
            if block.get("stored_count") != block.get("manifest_count"):
                failures.append("card.count_equals_manifest")
        if block.get("model_files_equal_manifest") is not True:
            failures.append(f"{kind}.model_files_equal_manifest")
    code = 3 if errors else 2 if failures else 0
    return {"status": "ERROR_OR_BLOCKED" if errors else "CHECKS_FAILED" if failures else "PASS",
            "exit_code": code, "failed_checks": failures, "execution_errors": errors,
            "strict_reproduction_policy_unchanged": True}


def trace_extra_chunks(chunks, manifest, snapshot):
    """Classify extra IDs using recorded admission decisions, not guessed mappings.

    This is a provenance trace, not proof of insertion time or creator. Matching a
    capture page identity does not prove the stored vector text matches its body.
    """
    admitted = {c["chunk_id"] for c in chunks}
    originals = {c["text"] for c in chunks}
    unused = {(c.get("guide_id"), c.get("page_id")): c for c in manifest.get("unused_captures", [])}
    rows = []
    import hashlib
    for cid, doc, md in zip(snapshot["ids"], snapshot["documents"], snapshot["metadatas"]):
        if cid in admitted:
            continue
        parts = cid.split("/")
        key = tuple(parts[:2]) if len(parts) == 3 else (None, None)
        capture = unused.get(key)
        details = {"chunk_id": cid, "classification": "UNMANIFESTED_UNKNOWN_ORIGIN", "admitted": False,
                   "duplicate_text_of_admitted_chunk": doc in originals,
                   "stored_document_sha256": hashlib.sha256(doc.encode("utf-8")).hexdigest(),
                   "stored_metadata": md, "metadata_identity_matches_id": bool(md and md.get("guide_id") == key[0] and md.get("page_id") == key[1]),
                   "insertion_time_or_creator_known": False}
        if capture:
            details.update(classification="UNADMITTED_CAPTURE_PAGE_VECTORS", capture_file=capture["file"],
                           numeric_deliverable_id=capture.get("numeric_deliverable_id"),
                           admission_reason=capture.get("reason_not_used"),
                           capture_identity_match_is_not_content_verification=True)
        rows.append(details)
    return rows


def enrich_capture_probes(details, config, count):
    """Re-chunk unused captured HTML in memory for forensic comparison ONLY.

    No effective identity or card source mapping is assigned. Nothing is written,
    embedded, admitted, or inserted into a store.
    """
    if not any(d.get("capture_file") for d in details):
        return details
    import hashlib
    import page_corpus as PC
    import page_chunker as PK
    import page_extract as PE
    captures = {c["file"]: c for c in PC.load_captures()}
    probes = {}
    for detail in details:
        filename = detail.get("capture_file")
        if not filename:
            continue
        cap = captures.get(filename)
        if not cap or not cap.get("ok"):
            detail["capture_probe"] = {"status": "UNAVAILABLE", "admission_changed": False}
            continue
        if filename not in probes:
            ex = PE.extract_html(cap["body"])
            record = {"guide_id": cap["guide_id"], "page_id": cap["page_id"], "source_ids": [], "source_url": "",
                      "title": ex["title"], "blocks": ex["blocks"], "text": ex["text"]}
            candidates = PK.chunk_page(record, config, count)
            probes[filename] = {c["chunk_id"]: c for c in candidates}
        candidates = probes[filename]
        candidate = candidates.get(detail["chunk_id"])
        detail["capture_probe"] = {"status": "COMPARED" if candidate else "NO_MATCHING_CURRENT_PROBE_CHUNK",
                                   "capture_sha256": cap["file_sha256"], "candidate_chunk_ids": sorted(candidates),
                                   "admission_changed": False, "source_mapping_assigned": False,
                                   "stored_document_matches_current_probe": (candidate["content_hash"] == detail["stored_document_sha256"]) if candidate else None,
                                   "candidate_embedding_text_sha256": hashlib.sha256(candidate["embedding_text"].encode()).hexdigest() if candidate else None}
    return details
