"""Interactive retrieval check: show what the chatbot would retrieve.

Usage (from the repository root):
    python scripts/retrieve.py                      # 'improved' strategy
    python scripts/retrieve.py --strategy baseline  # raw dense top-k
"""

import argparse

from rag_core import DEFAULT_STRATEGY, STRATEGIES, search

TOP_K = 5


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strategy", choices=sorted(STRATEGIES), default=DEFAULT_STRATEGY
    )
    parser.add_argument("--top-k", type=int, default=TOP_K)
    args = parser.parse_args()

    query = input("Ask: ").strip()

    if not query:
        print("Please enter a question.")
        raise SystemExit

    results = search(query, top_k=args.top_k, strategy=args.strategy)

    print(f"\nFound {len(results)} relevant results (strategy={args.strategy}).")

    for i, result in enumerate(results, start=1):
        metadata = result["metadata"]

        print(f"\n--- Result {i} ---")
        print("Title:", metadata.get("title", "Unknown"))
        # ChromaDB distance is squared L2 (lower = closer), NOT cosine distance.
        print("Distance (squared L2):", round(result["distance"], 4))
        print("Cosine similarity:", round(result["cosine"], 4))
        if "final_score" in result:
            print("Final score:", round(result["final_score"], 4))
        print("URL:", metadata.get("url", ""))
        print()
        print(result["document"])


if __name__ == "__main__":
    main()
