"""Local SAP documentation chatbot (ChromaDB retrieval + Ollama generation).

Usage (from the repository root):
    python scripts/rag_chat.py
"""

from rag_core import DEFAULT_STRATEGY, generate_answer, get_collection

EXIT_WORDS = {"exit", "quit"}


def print_sources(results):
    # These are the chunks that were *given to* the model as context; the
    # model's own text above says which ones it actually used.
    print()
    print("Retrieved context (sources provided to the model):")

    for i, result in enumerate(results, start=1):
        metadata = result["metadata"]

        print(
            f"{i}. {metadata.get('title', 'Unknown')} "
            f"| distance={result['distance']:.4f} (squared L2, lower=closer) "
            f"| cosine={result['cosine']:.4f} "
            f"| final_score={result['final_score']:.4f}"
        )

        url = metadata.get("url", "")
        if url:
            print(f"   {url}")


def main():
    print("Loading embedding model and ChromaDB...")

    try:
        collection = get_collection()
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(f"Error: {exc}")

    print(f"Loaded {collection.count()} chunks (strategy={DEFAULT_STRATEGY}).")
    print()
    print("SAP RAG Assistant")
    print("Type 'exit' to quit.")
    print()

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if question.lower() in EXIT_WORDS:
            print("Goodbye!")
            break

        if not question:
            continue

        try:
            answer, results = generate_answer(question)
        except Exception as exc:
            print()
            print("Error:", exc)
            print(
                "(If this is a connection or model error, check that Ollama "
                "is running and the model is pulled: `ollama pull llama3.2:3b`.)"
            )
            print()
            continue

        print()
        print("Assistant:")
        print(answer)

        if results:
            print_sources(results)

        print()
        print("-" * 70)
        print()


if __name__ == "__main__":
    main()
