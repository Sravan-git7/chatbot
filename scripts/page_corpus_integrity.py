"""Read-only admission/fingerprint precondition for page-store construction.

A directory glob is not an admission decision. Never silently drop stray files or
change the manifest to make a build work; fail before loading a model/opening a
store. Corpus serialization bytes and historical identities remain untouched.
"""
import hashlib


def validate_records(records, manifest):
    admitted = {}
    for card in manifest["cards"]:
        if card["corpus_status"] == "ingested":
            admitted.setdefault(card["doc_id"], set()).add(card["source_id"])
    ids = [r["doc_id"] for r in records]
    problems = []
    if len(ids) != len(set(ids)):
        problems.append("duplicate page doc_ids")
    extra, missing = sorted(set(ids) - set(admitted)), sorted(set(admitted) - set(ids))
    if extra:
        problems.append(f"unadmitted page doc_ids: {extra}")
    if missing:
        problems.append(f"missing admitted page doc_ids: {missing}")
    actual_hashes = {}
    for record in records:
        doc = record["doc_id"]
        if doc != f"{record['guide_id']}/{record['page_id']}":
            problems.append(f"page identity fields disagree: {doc}")
        if doc in admitted and set(record["source_ids"]) != admitted[doc]:
            problems.append(f"page source_ids disagree with admission manifest: {doc}")
        actual = hashlib.sha256(record["text"].encode("utf-8")).hexdigest()
        actual_hashes[doc] = actual
        if actual != record["text_sha256"]:
            problems.append(f"page text_sha256 mismatch: {doc}")
    fingerprint = hashlib.sha256("\n".join(f"{d} {actual_hashes[d]}" for d in sorted(actual_hashes)).encode("utf-8")).hexdigest()
    if fingerprint != manifest["corpus_sha256"]:
        problems.append("page corpus fingerprint differs from manifest")
    if problems:
        raise ValueError("Page corpus integrity failed; no store was opened or changed: " + "; ".join(problems))
    return fingerprint
