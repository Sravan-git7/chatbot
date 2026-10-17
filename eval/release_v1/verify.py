"""Versioned API observation package, NOT an independent SAP semantic oracle.

No downloads, no store creation, no output overwrites. Without --url, run offline
resource preflight. Even a complete API observation run needs independent review;
identity/quote matches are candidates, not substantive semantic certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Sequence
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = str(ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from citation_markers import is_marker_only_line, parse_citation_line, valid_marker  # noqa: E402
from claim_review_contract import validate_claim_review_metadata  # noqa: E402

_HEX64 = re.compile(r"^[0-9a-f]{64}$", re.I)
_PROTECTED_STORE_INPUTS = frozenset({
    "data/vector_store/chroma.sqlite3",
    "data/vector_store/page_collection/chroma.sqlite3",
})
_LIMITATION = "The selected evidence does not establish a complete step-by-step procedure."

# PROPOSED chunk/tokenizer pin contract — pending explicit owner approval.
# These values were inferred from the current implementation and artifacts; they make
# regeneration deterministic but are NOT an owner-approved release baseline. The page-corpus
# manifest independently pins the page records/captures; it does not approve these constants.
_RELEASE_CHUNK_STRATEGY = "B_heading_200"
_RELEASE_CHUNK_CONFIG = {
    "name": "B_heading_200", "strategy": "heading", "max_chars": 1000,
    "target_tokens": 200, "max_tokens": 250, "min_tokens": 24,
    "overlap_sentences": 1, "embed_prefix": True,
}
_RELEASE_TOKENIZER_NAME = "all-MiniLM-L6-v2 WordPiece (tokenizers)"
_RELEASE_TOKENIZER_SHA256 = "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"
_RELEASE_TOKENIZERS_VERSION = "0.23.3"
_RELEASE_MODEL_PACKAGE = "gt-all-minilm-l6-v2"
_RELEASE_MODEL_PACKAGE_VERSION = "0.1.0"
_RELEASE_CHUNKER_SOURCE_SHA256 = "cf487b96d87fd06328be2987f1f5bf622a5365f97210426b2ef0c9e9d2701fd7"
_RELEASE_EXTRACTOR_SOURCE_SHA256 = "34a5a0b7d154e8c40fa7c847427fc9375648eab5be4cfc406abd142fedd481f9"
_PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS = "PROPOSED_PENDING_OWNER_APPROVAL"

# The response surface must use a fixed, non-substantive message for policy/abstention cases.
# This list is an evaluation contract, not semantic gold and not a case-ID shortcut.
_SAFE_NONANSWER_TEXTS = frozenset({
    "I found the relevant topic, but the underlying SAP Help page is not currently available in the local knowledge base.",
    "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail.",
    "This question doesn't appear to match the SAP Utilities documentation available to me.",
    "I couldn't verify the relevant documentation.",
    "That's all the additional detail I could verify from the available documentation.",
})
_CLARIFICATION_TEXTS = frozenset({
    "Please clarify which payment process you mean, including the payment type or channel."
})
_REQUIRED_CATEGORIES = {
    "positive": "identity_and_quote_candidate_only",
    "negative": "no_substantive_answer",
    "ambiguous": "clarification_or_safe_abstention",
    "navigation": "no_navigation_only_factual_answer",
    "wrong_guide": "no_wrong_guide_answer",
    "version_conflict": "no_unverified_version_answer",
    "insufficient_evidence": "no_substantive_answer",
    "adversarial": "no_unsupported_answer",
}


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_dataset(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    if not isinstance(data, dict):
        raise ValueError("case dataset root must be a JSON object")
    return data


def validate_case_dataset(dataset: Any) -> Dict[str, Any]:
    """Return structured validation errors for malformed case data; never hash unchecked values."""
    errors: List[str] = []
    if not isinstance(dataset, Mapping):
        return {"ok": False, "errors": ["case dataset root must be an object"], "expected_ids": [],
                "duplicate_expected_ids": []}
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        return {"ok": False, "errors": ["cases must be a non-empty list"], "expected_ids": [],
                "duplicate_expected_ids": []}
    ids: List[str] = []
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append(f"case[{index}] must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id != case_id.strip():
            errors.append(f"case[{index}] has no canonical non-empty id")
            case_id = None
        else:
            ids.append(case_id)
        category = case.get("category")
        if not isinstance(category, str) or category not in _REQUIRED_CATEGORIES:
            errors.append(f"case {case_id!r} has unknown category {category!r}")
        else:
            if case.get("machine_policy") != _REQUIRED_CATEGORIES[category]:
                errors.append(f"case {case_id!r} has missing or unexpected machine_policy for {category!r}")
            if category == "positive":
                doc_id = case.get("reference_doc_id")
                quotes = case.get("reference_quotes")
                if not isinstance(doc_id, str) or not re.fullmatch(r"[0-9a-f]{32}/[0-9a-f]{32}", doc_id, re.I):
                    errors.append(f"case {case_id!r} lacks a valid reference_doc_id")
                if not isinstance(quotes, list) or not quotes or not all(isinstance(q, str) and q.strip() for q in quotes):
                    errors.append(f"case {case_id!r} lacks non-empty reference_quotes")
        question = case.get("question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"case {case_id!r} lacks a question")
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        errors.append("duplicate case ids: " + ", ".join(duplicates))
    return {"ok": not errors, "errors": errors, "expected_ids": ids, "duplicate_expected_ids": duplicates}


def validate_observation_ids(expected_cases: Any, observations: Any) -> Dict[str, Any]:
    """Require exactly one observed row for every expected case; malformed inputs fail closed."""
    expected_valid = isinstance(expected_cases, Sequence) and not isinstance(expected_cases, (str, bytes))
    observations_valid = isinstance(observations, Sequence) and not isinstance(observations, (str, bytes))
    expected_rows = list(expected_cases) if expected_valid else []
    observation_rows = list(observations) if observations_valid else []
    expected = [case.get("id") if isinstance(case, Mapping) and isinstance(case.get("id"), str) else ""
                for case in expected_rows]
    observed = [row.get("id") if isinstance(row, Mapping) and isinstance(row.get("id"), str) else ""
                for row in observation_rows]
    expected_set, observed_set = set(expected), set(observed)
    duplicate_expected = sorted({case_id for case_id in expected if expected.count(case_id) > 1})
    duplicate_observed = sorted({case_id for case_id in observed if observed.count(case_id) > 1})
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    empty_expected = [index for index, case_id in enumerate(expected) if not case_id]
    empty_ids = [index for index, case_id in enumerate(observed) if not case_id]
    malformed_input = not expected_valid or not observations_valid
    ok = not (malformed_input or duplicate_expected or duplicate_observed or missing or unexpected or empty_expected or empty_ids)
    return {"ok": ok, "expected_count": len(expected), "observed_count": len(observed),
            "missing_ids": missing, "duplicate_expected_ids": duplicate_expected,
            "duplicate_observed_ids": duplicate_observed, "unexpected_ids": unexpected,
            "empty_expected_id_rows": empty_expected, "empty_id_rows": empty_ids,
            "malformed_input": malformed_input}


def _safe_input(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("unsafe source hash path")
    rel = PurePosixPath(name)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError("unsafe source hash path")
    if rel.as_posix() in _PROTECTED_STORE_INPUTS:
        raise ValueError("protected persistent-store database paths are excluded")
    root_real = root.resolve(strict=True)
    current = root_real
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink source hash path")
    target = current.resolve(strict=True)
    target.relative_to(root_real)
    if not target.is_file():
        raise ValueError("source hash path is not a regular file")
    return target


def validate_inputs(dataset: Any, root: Path = ROOT) -> List[str]:
    failures: List[str] = []
    if not isinstance(dataset, Mapping):
        return ["source_hashes"]
    hashes = dataset.get("source_hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        return ["source_hashes"]
    for name, digest in hashes.items():
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            failures.append(str(name))
            continue
        try:
            target = _safe_input(Path(root), name)
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except (OSError, ValueError, TypeError):
            failures.append(str(name))
            continue
        if actual != digest.lower():
            failures.append(str(name))
    return failures


@lru_cache(maxsize=1)
def _pinned_page_source_manifest() -> Dict[str, Any]:
    """Load the non-protected corpus manifest only when it matches the release package's pinned file hash."""
    path = ROOT / "data/page_corpus/manifest.json"
    cases_path = ROOT / "eval/release_v1/cases.json"
    try:
        raw = path.read_bytes()
        cases = load_dataset(cases_path)
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    hashes = cases.get("source_hashes")
    expected = hashes.get("data/page_corpus/manifest.json") if isinstance(hashes, Mapping) else None
    if (not isinstance(manifest, Mapping) or not isinstance(expected, str) or not _HEX64.fullmatch(expected)
            or hashlib.sha256(raw).hexdigest() != expected.lower()
            or not isinstance(manifest.get("cards"), list)
            or not _HEX64.fullmatch(str(manifest.get("corpus_sha256") or ""))):
        return {}
    return dict(manifest)


@lru_cache(maxsize=1)
def _pinned_page_manifest() -> Dict[str, List[Dict[str, Any]]]:
    """Index only admitted pages from the hash-pinned source manifest; never read a vector store."""
    manifest = _pinned_page_source_manifest()
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for entry in manifest.get("cards", []) if manifest else []:
        if isinstance(entry, Mapping) and isinstance(entry.get("doc_id"), str):
            by_doc.setdefault(entry["doc_id"].lower(), []).append(dict(entry))
    return by_doc


def _valid_pinned_sap_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname == "help.sap.com"
                and parsed.username is None and parsed.password is None and parsed.port in (None, 443)
                and bool(parsed.path))
    except ValueError:
        return False


def _record_structure_check(record: Mapping[str, Any], extracted: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare every chunking input with independent extraction using type-strict JSON equality."""
    pairs = (("title", "title"), ("html_title", "html_title"), ("blocks", "blocks"),
             ("headings", "headings"), ("text", "text"), ("structure", "stats"))

    def same_json_value(left: Any, right: Any) -> bool:
        try:
            return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == \
                   json.dumps(right, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return False

    mismatches = [record_key for record_key, extracted_key in pairs
                  if not same_json_value(record.get(record_key), extracted.get(extracted_key))]
    return {"ok": not mismatches, "mismatches": mismatches,
            "reason": "record_chunk_structure_mismatch" if mismatches else None}


def _pinned_admitted_source(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    admitted = {check.get("file") for row in rows
                for check in (row.get("source_checks") or [])
                if isinstance(check, Mapping) and check.get("outcome") == "admitted"
                and isinstance(check.get("file"), str)}
    acquisition_types = {row.get("acquisition_type") for row in rows
                         if isinstance(row.get("acquisition_type"), str)}
    if len(admitted) != 1 or len(acquisition_types) != 1:
        return {"ok": False, "reason": "pinned_admitted_source_ambiguous"}
    return {"ok": True, "file": next(iter(admitted)), "type": next(iter(acquisition_types))}


def _authoritative_page_extraction(record: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                                   source_manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Rebuild record structure from the release-pinned capture, or from pinned flat text for legacy M2C-17."""
    source = _pinned_admitted_source(rows)
    if not source.get("ok"):
        return source
    acquisition = record.get("acquisition")
    if not isinstance(acquisition, Mapping):
        return {"ok": False, "reason": "page_acquisition_missing"}
    source_file = source["file"]
    if acquisition.get("file") != source_file or acquisition.get("type") != source["type"]:
        return {"ok": False, "reason": "page_acquisition_not_bound_to_pinned_admission"}
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    try:
        import page_extract as PE
        extractor_path = _safe_input(ROOT, "scripts/page_extract.py")
        if hashlib.sha256(extractor_path.read_bytes()).hexdigest() != _RELEASE_EXTRACTOR_SOURCE_SHA256:
            return {"ok": False, "reason": "release_page_extractor_contract_mismatch"}
        if source["type"] == "saved_sap_help_pagecontent_response":
            capture_pins = (source_manifest.get("inputs", {}).get("captures")
                            if isinstance(source_manifest.get("inputs"), Mapping) else None)
            expected_file_hash = capture_pins.get(source_file) if isinstance(capture_pins, Mapping) else None
            if not isinstance(expected_file_hash, str) or not _HEX64.fullmatch(expected_file_hash):
                return {"ok": False, "reason": "admitted_capture_not_pinned"}
            capture_path = _safe_input(ROOT, source_file)
            raw_capture = capture_path.read_bytes()
            actual_file_hash = hashlib.sha256(raw_capture).hexdigest()
            if actual_file_hash != expected_file_hash.lower() or acquisition.get("file_sha256") != expected_file_hash.lower():
                return {"ok": False, "reason": "admitted_capture_hash_mismatch"}
            envelope = json.loads(raw_capture.decode("utf-8"), object_pairs_hook=_strict_object)
            data = envelope.get("data") if isinstance(envelope, Mapping) else None
            if (not isinstance(data, Mapping) or envelope.get("status") != "OK"
                    or bool(data.get("fallback"))):
                return {"ok": False, "reason": "admitted_capture_envelope_invalid"}
            current_page = data.get("currentPage")
            deliverable = data.get("deliverable")
            if not isinstance(current_page, Mapping) or not isinstance(deliverable, Mapping):
                return {"ok": False, "reason": "admitted_capture_identity_missing"}
            captured_page = str(current_page.get("loio") or "").lower().removesuffix(".html")
            captured_guide = str(deliverable.get("loio") or "").lower()
            body = data.get("body")
            expected_doc = str(record.get("doc_id") or "").lower()
            if (not isinstance(body, str) or not body.strip()
                    or expected_doc != f"{captured_guide}/{captured_page}"):
                return {"ok": False, "reason": "admitted_capture_identity_or_body_mismatch"}
            if (acquisition.get("envelope_status") != "OK"
                    or acquisition.get("body_sha256") != hashlib.sha256(body.encode("utf-8")).hexdigest()
                    or acquisition.get("html_chars") != len(body)
                    or acquisition.get("fallback_page") is not False):
                return {"ok": False, "reason": "page_acquisition_metadata_mismatch"}
            extracted = PE.extract_html(body)
            validation = PE.validate_extraction(extracted)
            if not validation.get("ok") or record.get("validation") != validation:
                return {"ok": False, "reason": "pinned_capture_extraction_invalid"}
        elif source["type"] == "legacy_local_copy":
            # The historical local file has no independent file digest in the release
            # package. Its flat text is pinned by the page-manifest text_sha256; derive
            # the only admissible chunk blocks from that pinned text rather than trusting
            # the legacy record's independently mutable block array.
            text = record.get("text")
            if not isinstance(text, str) or not text.strip():
                return {"ok": False, "reason": "pinned_legacy_text_missing"}
            lines = [line for line in text.splitlines() if line.strip()]
            title = lines[0] if lines else None
            if record.get("title") != title:
                return {"ok": False, "reason": "pinned_legacy_title_mismatch"}
            extracted = PE.extract_flat_text(text, title)
            validation = PE.validate_extraction(extracted)
            if not validation.get("ok") or record.get("validation") != validation:
                return {"ok": False, "reason": "pinned_legacy_extraction_invalid"}
        else:
            return {"ok": False, "reason": "unsupported_pinned_page_source_type"}
    except (ImportError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": f"authoritative_page_reconstruction_failed:{type(exc).__name__}"}
    structure = _record_structure_check(record, extracted)
    if not structure["ok"]:
        return structure
    return {"ok": True, "origin": source["type"], "source_file": source_file,
            "extracted": extracted}


@lru_cache(maxsize=64)
def _pinned_page_record(doc_id: str) -> Dict[str, Any]:
    """Load one admitted page record and bind identity, text hash, and URL to the pinned manifest."""
    normalized_doc_id = str(doc_id or "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}/[0-9a-f]{32}", normalized_doc_id):
        return {"ok": False, "reason": "invalid_doc_id"}
    rows = [row for row in _pinned_page_manifest().get(normalized_doc_id, [])
            if row.get("corpus_status") == "ingested"]
    record_paths = {row.get("record") for row in rows if isinstance(row.get("record"), str)}
    hashes = {str(row.get("text_sha256")).lower() for row in rows if row.get("text_sha256")}
    expected_source_urls: Dict[str, str] = {}
    for row in rows:
        source_id = row.get("source_id")
        card_url = row.get("card_url")
        if (not isinstance(source_id, str) or not source_id.strip() or not _valid_pinned_sap_url(card_url)
                or (source_id in expected_source_urls and expected_source_urls[source_id] != card_url)):
            return {"ok": False, "reason": "manifest_source_or_url_invalid"}
        expected_source_urls[source_id] = card_url
    if (not rows or any(not isinstance(row.get("record"), str) or not _HEX64.fullmatch(str(row.get("text_sha256") or ""))
                        for row in rows) or len(record_paths) != 1 or len(hashes) != 1 or not expected_source_urls):
        return {"ok": False, "reason": "manifest_record_or_hash_ambiguous"}
    try:
        path = _safe_input(ROOT / "data/page_corpus", next(iter(record_paths)))
        record = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"ok": False, "reason": "page_record_unavailable_or_unsafe"}
    if not isinstance(record, Mapping):
        return {"ok": False, "reason": "page_record_not_object"}
    guide_id, page_id = normalized_doc_id.split("/", 1)
    text = record.get("text")
    expected_hash = next(iter(hashes))
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if isinstance(text, str) else ""
    record_source_ids = record.get("source_ids")
    expected_source_ids = set(expected_source_urls)
    record_url = record.get("source_url")
    if (str(record.get("doc_id") or "").lower() != normalized_doc_id
            or str(record.get("guide_id") or "").lower() != guide_id
            or str(record.get("page_id") or "").lower() != page_id
            or actual_hash != expected_hash or str(record.get("text_sha256") or "").lower() != expected_hash
            or not isinstance(record_source_ids, list)
            or not all(isinstance(value, str) for value in record_source_ids)
            or len(record_source_ids) != len(set(record_source_ids))
            or set(record_source_ids) != expected_source_ids
            or not _valid_pinned_sap_url(record_url)
            or record_url not in set(expected_source_urls.values())):
        return {"ok": False, "reason": "page_record_identity_hash_or_pinned_url_mismatch"}
    source_manifest = _pinned_page_source_manifest()
    authority = _authoritative_page_extraction(record, rows, source_manifest)
    if not authority.get("ok"):
        return {"ok": False, "reason": authority.get("reason", "page_record_structure_unverified")}
    return {"ok": True, "doc_id": normalized_doc_id, "guide_id": guide_id, "page_id": page_id,
            "text": text, "text_sha256": actual_hash, "source_url": record_url,
            "source_ids": list(record_source_ids), "source_urls": dict(expected_source_urls),
            "record": dict(record), "source_authority": {"origin": authority["origin"], "file": authority["source_file"]}}


def _chunk_manifest_contract_errors(chunk_manifest: Any, corpus_hash: str,
                                    admitted_doc_ids: Sequence[str], page_count: int) -> List[str]:
    """Check the mutable collection manifest against the proposed owner-pending contract; it is corroboration, not a trust root."""
    errors: List[str] = []
    if not isinstance(chunk_manifest, Mapping):
        return ["chunk manifest must be an object"]
    if chunk_manifest.get("embedding_model") != "all-MiniLM-L6-v2":
        errors.append("embedding model differs from the release contract")
    if chunk_manifest.get("chunk_strategy") != _RELEASE_CHUNK_STRATEGY:
        errors.append("chunk strategy differs from the release contract")
    actual_config = chunk_manifest.get("chunk_config")
    config_matches = (isinstance(actual_config, Mapping)
                      and set(actual_config) == set(_RELEASE_CHUNK_CONFIG)
                      and all(type(actual_config[key]) is type(expected)
                              and actual_config[key] == expected
                              for key, expected in _RELEASE_CHUNK_CONFIG.items()))
    if not config_matches:
        errors.append("chunk configuration differs from the release contract")
    if chunk_manifest.get("corpus_sha256") != corpus_hash:
        errors.append("corpus fingerprint differs from the pinned page records")
    if chunk_manifest.get("page_doc_ids") != list(admitted_doc_ids):
        errors.append("page inventory differs from the pinned page records")
    if type(chunk_manifest.get("pages")) is not int or chunk_manifest.get("pages") != page_count:
        errors.append("page count differs from the pinned page records")
    token_counter = chunk_manifest.get("token_counter")
    if (not isinstance(token_counter, Mapping) or token_counter.get("exact") is not True
            or token_counter.get("tokenizer") != _RELEASE_TOKENIZER_NAME):
        errors.append("token counter differs from the release contract")
    provenance = chunk_manifest.get("embedding_model_provenance")
    files = provenance.get("files_sha256") if isinstance(provenance, Mapping) else None
    if (not isinstance(provenance, Mapping) or provenance.get("model_name") != "all-MiniLM-L6-v2"
            or not isinstance(files, Mapping)
            or files.get("tokenizer.json") != _RELEASE_TOKENIZER_SHA256):
        errors.append("tokenizer asset differs from the release contract")
    return errors


def _fixed_chunker_components() -> Dict[str, Any]:
    """Load the proposed version-controlled chunker/tokenizer pin, pending owner approval; never trust the collection manifest to select it."""
    try:
        for relative, expected in (("scripts/page_chunker.py", _RELEASE_CHUNKER_SOURCE_SHA256),
                                   ("scripts/page_extract.py", _RELEASE_EXTRACTOR_SOURCE_SHA256)):
            path = _safe_input(ROOT, relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return {"ok": False, "reason": f"release_transformation_source_mismatch:{relative}"}
        if _SCRIPTS not in sys.path:
            sys.path.insert(0, _SCRIPTS)
        import page_chunker as PK
        config = PK.STRATEGIES.get(_RELEASE_CHUNK_STRATEGY)
        if config is None or config.to_dict() != _RELEASE_CHUNK_CONFIG:
            return {"ok": False, "reason": "release_chunk_config_mismatch"}
        if version("tokenizers") != _RELEASE_TOKENIZERS_VERSION:
            return {"ok": False, "reason": "release_tokenizers_version_mismatch"}
        if version(_RELEASE_MODEL_PACKAGE) != _RELEASE_MODEL_PACKAGE_VERSION:
            return {"ok": False, "reason": "release_tokenizer_model_package_version_mismatch"}
        from m2c_common import resolve_model
        model_dir, model_info = resolve_model()
        if not isinstance(model_info, Mapping) or model_info.get("model_name") != "all-MiniLM-L6-v2":
            return {"ok": False, "reason": "release_tokenizer_model_identity_mismatch"}
        tokenizer_path = Path(str(model_dir)) / "tokenizer.json"
        if hashlib.sha256(tokenizer_path.read_bytes()).hexdigest() != _RELEASE_TOKENIZER_SHA256:
            return {"ok": False, "reason": "release_tokenizer_asset_hash_mismatch"}
        counter, counter_info = PK.make_token_counter(str(model_dir))
        if (not counter_info.get("exact") or counter_info.get("tokenizer") != _RELEASE_TOKENIZER_NAME):
            return {"ok": False, "reason": "exact_release_tokenizer_unavailable"}
        return {"ok": True, "module": PK, "config": config, "counter": counter}
    except (ImportError, OSError, KeyError, TypeError, ValueError, PackageNotFoundError) as exc:
        return {"ok": False, "reason": f"release_chunker_contract_unavailable:{type(exc).__name__}"}


def _chunks_fingerprint(chunks: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda row: str(row.get("chunk_id") or "")):
        embedding_text = chunk.get("embedding_text")
        content_hash = chunk.get("content_hash")
        if not isinstance(embedding_text, str) or not isinstance(content_hash, str):
            return ""
        embedding_hash = hashlib.sha256(embedding_text.encode("utf-8")).hexdigest()
        digest.update(f"{chunk['chunk_id']}\t{content_hash}\t{embedding_hash}\n".encode("utf-8"))
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _pinned_canonical_chunks() -> Dict[str, Any]:
    """Rebuild the admitted canonical chunk index from pinned page records, without opening any store."""
    source_manifest = _pinned_page_source_manifest()
    if not source_manifest:
        return {"ok": False, "reason": "pinned_page_manifest_invalid"}
    page_by_doc = _pinned_page_manifest()
    admitted_doc_ids = sorted(doc_id for doc_id, rows in page_by_doc.items()
                              if any(row.get("corpus_status") == "ingested" for row in rows))
    page_records: List[Dict[str, Any]] = []
    for doc_id in admitted_doc_ids:
        page = _pinned_page_record(doc_id)
        if not page.get("ok") or not isinstance(page.get("record"), Mapping):
            return {"ok": False, "reason": f"pinned_page_record_invalid:{doc_id}"}
        page_records.append(page["record"])
    corpus_hash = hashlib.sha256("\n".join(
        f"{record['doc_id']} {record['text_sha256']}" for record in sorted(page_records, key=lambda row: row["doc_id"])
    ).encode("utf-8")).hexdigest()
    if corpus_hash != str(source_manifest.get("corpus_sha256") or "").lower():
        return {"ok": False, "reason": "pinned_corpus_fingerprint_mismatch"}

    manifest_path = ROOT / "data/page_collection_manifest.json"
    try:
        chunk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"ok": False, "reason": "page_chunk_manifest_unavailable_or_invalid"}
    components = _fixed_chunker_components()
    if not components.get("ok"):
        return {"ok": False, "reason": components.get("reason", "fixed_chunker_contract_invalid")}
    manifest_errors = _chunk_manifest_contract_errors(chunk_manifest, corpus_hash,
                                                       admitted_doc_ids, len(page_records))
    if manifest_errors:
        return {"ok": False, "reason": "page_chunk_manifest_contract_mismatch",
                "details": manifest_errors}
    try:
        chunks = components["module"].chunk_corpus(
            page_records, components["config"], components["counter"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"canonical_chunk_rebuild_failed:{type(exc).__name__}"}

    by_id: Dict[str, Dict[str, Any]] = {}
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        doc_id = f"{chunk.get('guide_id')}/{chunk.get('page_id')}"
        page = _pinned_page_record(doc_id)
        text = chunk.get("text")
        chunk_index = chunk.get("chunk_index")
        expected_chunk_id = f"{doc_id}/{chunk_index:03d}" if type(chunk_index) is int and chunk_index >= 0 else ""
        expected_chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if isinstance(text, str) else ""
        chunk_source_ids = [value for value in str(chunk.get("source_ids") or "").split(",") if value]
        if (not page.get("ok") or chunk.get("doc_id", doc_id) != doc_id
                or chunk.get("chunk_id") != expected_chunk_id
                or chunk.get("content_hash") != expected_chunk_hash
                or chunk.get("guide_id") != page.get("guide_id")
                or chunk.get("page_id") != page.get("page_id")
                or chunk_source_ids != page.get("source_ids")
                or chunk.get("source_url") != page.get("source_url")):
            return {"ok": False, "reason": f"canonical_chunk_identity_or_hash_mismatch:{doc_id}"}
        enriched = dict(chunk)
        enriched.update({"doc_id": doc_id, "page_text_sha256": page["text_sha256"]})
        if chunk["chunk_id"] in by_id:
            return {"ok": False, "reason": "duplicate_canonical_chunk_id"}
        by_id[chunk["chunk_id"]] = enriched
        by_doc.setdefault(doc_id, []).append(enriched)
    for doc_chunks in by_doc.values():
        doc_chunks.sort(key=lambda row: row["chunk_index"])
    if (len(chunks) != chunk_manifest.get("vector_count")
            or _chunks_fingerprint(chunks) != chunk_manifest.get("chunks_fingerprint")):
        return {"ok": False, "reason": "canonical_chunk_fingerprint_mismatch"}
    return {"ok": True, "by_id": by_id, "by_doc": by_doc, "fingerprint": _chunks_fingerprint(chunks),
            "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS}


def _citation_contract(body: Mapping[str, Any], pinned_page: Mapping[str, Any],
                       canonical_chunks: Mapping[str, Any]) -> Dict[str, Any]:
    answer = body.get("answer")
    sources = body.get("sources")
    metadata = body.get("metadata")
    if (not isinstance(answer, str) or not answer.strip() or not isinstance(sources, list)
            or not isinstance(metadata, Mapping) or pinned_page.get("ok") is not True
            or canonical_chunks.get("ok") is not True):
        return {"ok": False, "reason": "missing answer, source list, metadata, pinned page, or canonical chunks",
                "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS}
    marker_names: List[str] = []
    malformed: List[str] = []
    duplicates: List[str] = []
    marker_only_lines: List[str] = []
    for line in answer.splitlines():
        line_markers, line_malformed, body = parse_citation_line(line, allow_compound=False)
        marker_names.extend(line_markers)
        malformed.extend(line_malformed)
        duplicates.extend(sorted({marker for marker in line_markers if line_markers.count(marker) > 1}))
        if is_marker_only_line(line, allow_compound=False):
            marker_only_lines.append(line)
    source_markers = [source.get("marker") for source in sources if isinstance(source, Mapping)]
    invalid_sources = [source for source in sources if not isinstance(source, Mapping)]
    duplicate_sources = sorted({marker for marker in source_markers if isinstance(marker, str)
                                 and source_markers.count(marker) > 1})
    canonical_by_id = canonical_chunks.get("by_id")
    expected_source_ids = pinned_page.get("source_ids")
    expected_source_urls = pinned_page.get("source_urls")
    if (not isinstance(canonical_by_id, Mapping) or not isinstance(expected_source_ids, list)
            or not isinstance(expected_source_urls, Mapping)):
        return {"ok": False, "reason": "canonical page/source index is malformed",
                "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS}
    valid_sources = True
    source_by_marker: Dict[str, Mapping[str, Any]] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        marker = source.get("marker")
        guide_id = source.get("guide_id")
        page_id = source.get("page_id")
        source_doc_id = source.get("doc_id")
        source_id = source.get("source_id")
        source_ids = source.get("source_ids")
        chunk_id = source.get("chunk_id")
        page_hash = source.get("page_text_sha256")
        canonical = canonical_by_id.get(chunk_id) if isinstance(chunk_id, str) else None
        canonical_text = canonical.get("text") if isinstance(canonical, Mapping) else None
        recomputed_chunk_hash = (hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
                                 if isinstance(canonical_text, str) else "")
        canonical_source_ids = ([value for value in str(canonical.get("source_ids") or "").split(",") if value]
                                if isinstance(canonical, Mapping) else [])
        expected_url = expected_source_urls.get(source_id) if isinstance(source_id, str) else None
        source_valid = (
            source.get("type") == "page"
            and valid_marker(marker)
            and isinstance(guide_id, str) and bool(re.fullmatch(r"[0-9a-f]{32}", guide_id, re.I))
            and isinstance(page_id, str) and bool(re.fullmatch(r"[0-9a-f]{32}", page_id, re.I))
            and isinstance(source_doc_id, str)
            and source_doc_id.lower() == f"{pinned_page.get('guide_id')}/{pinned_page.get('page_id')}"
            and guide_id.lower() == pinned_page.get("guide_id")
            and page_id.lower() == pinned_page.get("page_id")
            and isinstance(chunk_id, str) and isinstance(canonical, Mapping)
            and canonical.get("doc_id") == source_doc_id.lower()
            and canonical.get("chunk_id") == chunk_id
            and isinstance(source_id, str) and source_id in expected_source_ids
            and isinstance(source_ids, list) and all(isinstance(value, str) for value in source_ids)
            and len(source_ids) == len(set(source_ids))
            and source_ids == canonical_source_ids == expected_source_ids
            and bool(re.fullmatch(r"[0-9a-f]{64}", recomputed_chunk_hash, re.I))
            and canonical.get("content_hash") == recomputed_chunk_hash
            and isinstance(source.get("content_hash"), str)
            and source.get("content_hash").lower() == recomputed_chunk_hash
            and isinstance(page_hash, str) and page_hash.lower() == pinned_page.get("text_sha256")
            and canonical.get("page_text_sha256") == pinned_page.get("text_sha256")
            and isinstance(expected_url, str) and source.get("url") == expected_url
            and _valid_pinned_sap_url(source.get("url"))
            and source.get("url_status") == "VERIFIED"
        )
        if not source_valid:
            valid_sources = False
        if isinstance(marker, str):
            source_by_marker[marker] = source
    claim_grounding = metadata.get("claim_grounding")
    review_valid, _review_errors = validate_claim_review_metadata(claim_grounding, answer)
    line_citations_valid = not marker_only_lines
    for line in answer.splitlines():
        line_markers, line_malformed, clean = parse_citation_line(line, allow_compound=False)
        if not clean:
            continue
        if clean.casefold() == _LIMITATION.casefold():
            continue
        if not line_markers or line_malformed:
            line_citations_valid = False
    answer_set = set(marker_names)
    source_set = {marker for marker in source_markers if isinstance(marker, str)}
    source_marker_values_valid = all(valid_marker(marker) for marker in source_markers)
    ok = (not malformed and not duplicates and not duplicate_sources and not invalid_sources
          and valid_sources and source_marker_values_valid and review_valid and line_citations_valid
          and bool(answer_set) and answer_set == source_set)
    return {"ok": ok, "answer_markers": sorted(answer_set), "source_markers": sorted(source_set),
            "malformed_markers": malformed, "duplicate_answer_markers": duplicates,
            "duplicate_source_markers": duplicate_sources, "line_citations_valid": line_citations_valid,
            "source_objects_valid": valid_sources and not invalid_sources,
            "claim_review_valid": review_valid,
            "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS,
            "semantic_entailment": "NOT_ASSESSED"}


def _reference_candidate(case: Mapping[str, Any], status_code: int, body: Mapping[str, Any]) -> Dict[str, Any]:
    raw_doc_id = case.get("reference_doc_id")
    raw_quotes = case.get("reference_quotes")
    if (not isinstance(raw_doc_id, str) or not isinstance(raw_quotes, list)
            or not raw_quotes or not all(isinstance(quote, str) and quote.strip() for quote in raw_quotes)):
        return {"http_status": status_code, "machine_status": "FAIL",
                "reason": "positive case lacks a valid pinned identity or quote list",
                "substantive_semantic_correctness": None,
                "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS,
                "independent_review_required": True}
    doc_id = raw_doc_id.lower()
    normalize = lambda value: " ".join(value.casefold().split())
    normalized_quotes = [normalize(quote) for quote in raw_quotes]
    raw_answer = body.get("answer")
    answer = normalize(raw_answer) if isinstance(raw_answer, str) else ""
    quote_match = any(quote in answer for quote in normalized_quotes)
    page_record = _pinned_page_record(doc_id)
    canonical_chunks = _pinned_canonical_chunks()
    pinned_text = normalize(page_record.get("text")) if page_record.get("ok") else ""
    quote_in_page = bool(page_record.get("ok")) and any(quote in pinned_text for quote in normalized_quotes)
    raw_sources = body.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    identities = {f"{str(source.get('guide_id') or '').lower()}/{str(source.get('page_id') or '').lower()}"
                  for source in sources if isinstance(source, Mapping)}
    citations = _citation_contract(body, page_record, canonical_chunks)
    source_by_marker = {source.get("marker"): source for source in sources
                        if isinstance(source, Mapping) and isinstance(source.get("marker"), str)}
    canonical_by_id = canonical_chunks.get("by_id", {}) if canonical_chunks.get("ok") else {}
    quote_in_cited_chunk = False
    if isinstance(raw_answer, str) and isinstance(canonical_by_id, Mapping):
        for line in raw_answer.splitlines():
            line_markers, _line_malformed, _line_body = parse_citation_line(line, allow_compound=False)
            line_quotes = [quote for quote, normalized in zip(raw_quotes, normalized_quotes)
                           if normalized in normalize(line)]
            if not line_quotes:
                continue
            for marker in line_markers:
                source = source_by_marker.get(marker)
                chunk_id = source.get("chunk_id") if isinstance(source, Mapping) else None
                chunk = canonical_by_id.get(chunk_id) if isinstance(chunk_id, str) else None
                chunk_text = chunk.get("text") if isinstance(chunk, Mapping) else None
                if isinstance(chunk_text, str):
                    normalized_chunk = normalize(chunk_text)
                    if any(normalized in normalized_chunk for normalized in line_quotes):
                        quote_in_cited_chunk = True
    metadata = body.get("metadata") if isinstance(body.get("metadata"), Mapping) else {}
    candidate = (status_code == 200 and body.get("status") == "answered" and doc_id in identities
                 and bool(identities) and identities == {doc_id} and page_record.get("ok") is True
                 and canonical_chunks.get("ok") is True and quote_match and quote_in_page
                 and quote_in_cited_chunk and citations["ok"] and metadata.get("grounded") is True)
    return {"http_status": status_code,
            "machine_status": "CANDIDATE" if candidate else "FAIL",
            "substantive_semantic_correctness": None,
            "reference_identity_match": doc_id in identities and identities == {doc_id},
            "reference_quote_match": quote_match,
            "reference_quote_in_pinned_page": quote_in_page,
            "reference_quote_in_cited_chunk": quote_in_cited_chunk,
            "pinned_source_record_valid": page_record.get("ok") is True,
            "canonical_chunk_index_valid": canonical_chunks.get("ok") is True,
            "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS,
            "citation_contract": citations,
            "independent_review_required": True}


def _policy_response(case: Mapping[str, Any], status_code: int, body: Mapping[str, Any]) -> Dict[str, Any]:
    category = case.get("category")
    status = body.get("status")
    answer = body.get("answer")
    metadata = body.get("metadata")
    sources = body.get("sources")
    if category == "ambiguous":
        content_ok = isinstance(answer, str) and answer in _CLARIFICATION_TEXTS
        clarification_ok = isinstance(metadata, Mapping) and metadata.get("clarification_required") is True
        content_ok = content_ok and clarification_ok
    else:
        content_ok = isinstance(answer, str) and answer in _SAFE_NONANSWER_TEXTS
    nonanswer_markers, nonanswer_malformed, _nonanswer_body = parse_citation_line(
        answer if isinstance(answer, str) else "", allow_compound=True)
    candidate = (status_code == 200 and status != "answered" and content_ok
                 and isinstance(metadata, Mapping) and metadata.get("grounded") is False
                 and isinstance(sources, list) and len(sources) == 0
                 and not nonanswer_markers and not nonanswer_malformed)
    return {"http_status": status_code,
            "machine_status": "REVIEW_REQUIRED" if candidate else "FAIL",
            "substantive_semantic_correctness": None,
            "non_answer_content_check": content_ok,
            "sources_empty": isinstance(sources, list) and len(sources) == 0,
            "independent_review_required": True}


def observe(case: Any, status_code: int, body: Any) -> Dict[str, Any]:
    """Apply explicit category expectations; malformed case/response values fail as structured observations."""
    if not isinstance(case, Mapping):
        return {"http_status": status_code, "machine_status": "FAIL", "reason": "case is not an object"}
    if not isinstance(body, Mapping):
        return {"http_status": status_code, "machine_status": "FAIL", "reason": "response body is not an object"}
    category = case.get("category")
    if not isinstance(category, str) or category not in _REQUIRED_CATEGORIES:
        return {"http_status": status_code, "machine_status": "FAIL", "reason": "unknown case category"}
    if category == "positive":
        return _reference_candidate(case, status_code, body)
    return _policy_response(case, status_code, body)


def offline_preflight() -> Dict[str, Any]:
    """Check local Python/model resources without reading, statting, or opening any persistent store path."""
    result: Dict[str, Any] = {"packages": {}, "errors": [], "protected_store_access": "NOT_ATTEMPTED_BY_POLICY"}
    for package in ("chromadb", "sentence-transformers", "fastapi", "uvicorn", "pydantic", "httpx", "pytest", "numpy"):
        try:
            result["packages"][package] = version(package)
        except PackageNotFoundError:
            result["errors"].append(f"Missing Python package: {package}")
    try:
        from m2c_common import resolve_model
        _model_dir, model_info = resolve_model()
        result["embedding_model"] = {"model": model_info.get("model_name"),
                                      "origin": model_info.get("origin"),
                                      "files_sha256": model_info.get("files_sha256")}
    except Exception as exc:
        result["errors"].append(f"Local embedding model unavailable: {type(exc).__name__}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Explicit existing private API; never starts/deploys a server")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("Output already exists; choose a new versioned path")
    dataset_path = Path(__file__).with_name("cases.json")
    try:
        dataset = load_dataset(dataset_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "reason": f"invalid case dataset: {type(exc).__name__}"}))
        return 1
    dataset_check = validate_case_dataset(dataset)
    drift = validate_inputs(dataset)
    report: Dict[str, Any] = {
        "schema_version": 1,
        "verifier_version": "1.2",
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "status": "BLOCKED",
        "semantic_certification": False,
        "chunk_tokenizer_contract_status": _PROPOSED_CHUNK_TOKENIZER_CONTRACT_STATUS,
        "case_dataset_validation": dataset_check,
        "input_drift": drift,
        "observations": [],
    }
    code = 2
    if not dataset_check["ok"]:
        report.update(status="FAIL", reason="Case dataset IDs or explicit expectation contract is invalid")
        code = 1
    elif drift:
        report.update(status="FAIL", reason="Frozen reference input drift; no evaluation permitted")
        code = 1
    elif not args.url:
        report["preflight"] = offline_preflight()
        report["reason"] = (
            "Full API observation and independent authoritative adjudication required; offline checks are not quality passes; "
            "protected persistent-store paths were not inspected"
        )
    else:
        import httpx

        token = os.environ.get("SURA_API_TOKEN", "")
        headers = {"Authorization": "Bearer " + token} if token else {}
        # Never include request headers, token, or environment dumps in evidence.
        with httpx.Client(
            base_url=args.url.rstrip("/"), headers=headers, timeout=90, trust_env=False
        ) as client:
            for case in dataset["cases"]:
                try:
                    response = client.post("/api/chat", json={"message": case["question"]})
                    body = response.json()
                    row = observe(case, response.status_code, body)
                except (httpx.HTTPError, ValueError) as exc:
                    row = {"machine_status": "FAIL", "error_type": type(exc).__name__}
                row["id"] = case["id"]
                report["observations"].append(row)
        ids = validate_observation_ids(dataset["cases"], report["observations"])
        report["case_id_validation"] = ids
        failures = [row for row in report["observations"] if row.get("machine_status") == "FAIL"]
        if failures or not ids["ok"]:
            report.update(status="FAIL", reason="API observations or case-ID reconciliation failed; no relabeling permitted")
            code = 1
        else:
            report["reason"] = (
                "Observations meet mechanical expectations only; independent SAP source/version/claim adjudication is still required"
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2)
        target.write("\n")
    print(json.dumps({"status": report["status"], "semantic_certification": False,
                      "case_ids_valid": (report.get("case_id_validation") or {}).get("ok")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
