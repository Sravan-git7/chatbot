"""Retrieval evaluation against data/evaluation_questions.json.

Usage (from the repository root):
    python scripts/evaluate_retrieval.py                       # baseline (original numbers)
    python scripts/evaluate_retrieval.py --strategy improved   # what the chatbot uses now
    python scripts/evaluate_retrieval.py --compare             # all strategies side by side

Scoring
-------
* ``Top-k``  (loose) - the ORIGINAL metric, kept unchanged so results stay
  comparable: a hit if an expected title is a *substring* of a retrieved title
  (so expected "Contract Account" also accepts "Contract Account Category",
  "Creating Contract Accounts", ...).
* ``Strict`` - a hit only if the retrieved title *equals* an expected title.
* The 5 out-of-domain questions have no expected title and are excluded from
  retrieval scoring; their nearest distances are listed for reference.
"""

import argparse
import json
from pathlib import Path

from rag_core import (
    DB_DIR,
    REPO_ROOT,
    STRATEGIES,
    get_collection,
    search,
    source_key,
)

EVALUATION_FILE = REPO_ROOT / "data" / "evaluation_questions.json"
TOP_K_VALUES = [1, 3, 5]
MAX_K = max(TOP_K_VALUES)


# -----------------------------
# Matching
# -----------------------------

def is_match(metadata, expected_titles):
    """Original (loose) rule: expected title is a substring of the title."""
    if not expected_titles:
        return False

    title = metadata.get("title", "").strip().lower()
    return any(expected.lower() in title for expected in expected_titles)


def is_strict_match(metadata, expected_titles):
    """Exact (case-insensitive) title equality."""
    title = metadata.get("title", "").strip().lower()
    return any(expected.strip().lower() == title for expected in expected_titles)


# -----------------------------
# Evaluation
# -----------------------------

def run_strategy(questions, strategy):
    results = []

    for item in questions:
        retrieved = search(item["question"], top_k=MAX_K, strategy=strategy)[:MAX_K]
        metadatas = [r["metadata"] for r in retrieved]
        expected = item["expected_titles"]

        doc_keys = [source_key(m, "content") for m in metadatas]

        results.append({
            "id": item["id"],
            "question": item["question"],
            "category": item["category"],
            "expected_titles": expected,
            "retrieved_titles": [m.get("title", "") for m in metadatas],
            "retrieved_urls": [m.get("url", "") for m in metadatas],
            "distances": [round(r["distance"], 6) for r in retrieved],
            "match_ranks": [
                rank for rank, m in enumerate(metadatas, start=1)
                if is_match(m, expected)
            ],
            "strict_match_ranks": [
                rank for rank, m in enumerate(metadatas, start=1)
                if is_strict_match(m, expected)
            ],
            "distinct_documents": len(set(doc_keys)),
        })

    return results


def scored(results):
    """Questions with expected titles (out-of-domain excluded)."""
    return [r for r in results if r["expected_titles"]]


def hits_at(results, k, field):
    rows = scored(results)
    return sum(any(rank <= k for rank in r[field]) for r in rows), len(rows)


def repeated_document_questions(results):
    """How many scored questions have the same document twice in their top-5."""
    rows = scored(results)
    return (
        sum(r["distinct_documents"] < len(r["retrieved_titles"]) for r in rows),
        len(rows),
    )


def mean_strict_mrr(results):
    rows = scored(results)
    total = sum(1 / r["strict_match_ranks"][0] for r in rows if r["strict_match_ranks"])
    return total / len(rows) if rows else 0.0


# -----------------------------
# Reporting
# -----------------------------

def fmt(hit, total):
    return f"{hit}/{total} ({hit / total * 100:.1f}%)" if total else "n/a"


def print_report(results, strategy):
    print("\n")
    print("=" * 60)
    print(f"RETRIEVAL EVALUATION (strategy: {strategy})")
    print("=" * 60)

    for k in TOP_K_VALUES:
        print(f"Top-{k}: {fmt(*hits_at(results, k, 'match_ranks'))}")

    print("\nSTRICT TITLE MATCH (exact title equality)")
    print("-" * 60)
    for k in TOP_K_VALUES:
        print(f"Top-{k}: {fmt(*hits_at(results, k, 'strict_match_ranks'))}")
    print(f"MRR:   {mean_strict_mrr(results):.3f}")

    repeated, total = repeated_document_questions(results)
    print(
        f"\nQuestions whose top-{MAX_K} repeat the same document: "
        f"{repeated}/{total}"
    )

    print("\n")
    print("CATEGORY BREAKDOWN (Top-5, loose)")
    print("-" * 60)

    for category in sorted({r["category"] for r in results}):
        if category == "out_of_domain":
            continue
        rows = [r for r in results if r["category"] == category]
        hit = sum(any(rank <= 5 for rank in r["match_ranks"]) for r in rows)
        print(f"{category:15} {fmt(hit, len(rows))}")

    ood = [r for r in results if r["category"] == "out_of_domain"]
    if ood:
        print("\nOUT-OF-DOMAIN nearest distances (squared L2; chatbot refuses "
              "when all > MAX_DISTANCE):")
        for r in ood:
            nearest = min(r["distances"]) if r["distances"] else None
            shown = f"{nearest:.3f}" if nearest is not None else "no result"
            print(f"  {shown:>9}  {r['question']}")

    print("\n")
    print("=" * 60)
    print("RETRIEVAL FAILURES (no expected title in Top-5, loose)")
    print("=" * 60)

    failures = [
        r for r in scored(results)
        if not any(rank <= 5 for rank in r["match_ranks"])
    ]

    if not failures:
        print("No retrieval failures in Top-5.")

    for r in failures:
        print("\nQuestion:")
        print(r["question"])
        print("\nExpected:")
        print(r["expected_titles"])
        print("\nRetrieved:")
        for rank, (title, distance) in enumerate(
            zip(r["retrieved_titles"], r["distances"]), start=1
        ):
            print(f"{rank}. {title} (distance={distance:.4f})")

    strict_misses = [
        r for r in scored(results)
        if not r["strict_match_ranks"] or r["strict_match_ranks"][0] > 1
    ]
    print(f"\nQuestions where the exact expected page is not ranked #1: "
          f"{len(strict_misses)}")
    for r in strict_misses:
        first = r["strict_match_ranks"][0] if r["strict_match_ranks"] else "not in top-5"
        print(f"  {r['id']} (rank {first}): {r['question']}")


def print_comparison(all_results):
    print("\n" + "=" * 100)
    print("STRATEGY COMPARISON")
    print("=" * 100)
    print(
        f"{'strategy':10} | {'loose Top-1/3/5':17} | {'strict Top-1/3/5':17} | "
        f"{'strict MRR':10} | repeated-doc questions"
    )
    print("-" * 100)

    for strategy, results in all_results.items():
        loose = "/".join(str(hits_at(results, k, "match_ranks")[0]) for k in TOP_K_VALUES)
        strict = "/".join(
            str(hits_at(results, k, "strict_match_ranks")[0]) for k in TOP_K_VALUES
        )
        total = hits_at(results, 1, "match_ranks")[1]
        repeated, _ = repeated_document_questions(results)
        print(
            f"{strategy:10} | {loose + ' of ' + str(total):17} | "
            f"{strict + ' of ' + str(total):17} | "
            f"{mean_strict_mrr(results):10.3f} | {repeated}/{total}"
        )


def save(results, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\nDetailed results saved to:")
    print(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strategy", choices=sorted(STRATEGIES), default="baseline",
        help="retrieval strategy to evaluate (default: baseline)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="evaluate every strategy and print a comparison table (no files written)",
    )
    parser.add_argument(
        "--output", help="results JSON path (default depends on strategy)"
    )
    args = parser.parse_args()

    try:
        collection = get_collection()
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(f"Error: {exc}")

    with open(EVALUATION_FILE, encoding="utf-8") as f:
        questions = json.load(f)

    print(f"Loaded {collection.count()} chunks from {DB_DIR.name}.")
    print(f"Loaded {len(questions)} evaluation questions.")

    if args.compare:
        print_comparison({s: run_strategy(questions, s) for s in STRATEGIES})
        return

    results = run_strategy(questions, args.strategy)
    print_report(results, args.strategy)

    default_name = (
        "retrieval_results.json"
        if args.strategy == "baseline"
        else f"retrieval_results_{args.strategy}.json"
    )
    save(results, args.output or REPO_ROOT / "data" / default_name)


if __name__ == "__main__":
    main()
