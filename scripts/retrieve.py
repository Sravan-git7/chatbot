import re
import chromadb
from sentence_transformers import SentenceTransformer

DB_DIR = "chroma_db"
COLLECTION_NAME = "sap_docs"

# Retrieval configuration
CANDIDATE_K = 10
TOP_K = 5

# Maximum allowed cosine distance
MAX_DISTANCE = 1.0

print("Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path=DB_DIR)
collection = client.get_collection(COLLECTION_NAME)

print(f"Loaded {collection.count()} chunks.")


def search(query, top_k=TOP_K):

    query = query.strip()

    if not query:
        return []

    # --------------------------------------------------
    # 1. Create normalized query embedding
    # --------------------------------------------------

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    ).tolist()

    # --------------------------------------------------
    # 2. Retrieve candidate documents
    # --------------------------------------------------

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=CANDIDATE_K,
        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    candidates = []

    # --------------------------------------------------
    # 3. Convert distance → similarity score
    # --------------------------------------------------

    for doc, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):

        if distance > MAX_DISTANCE:
            continue

        similarity = 1 - distance

        title = metadata.get("title", "")
        url = metadata.get("url", "")

        candidates.append({
            "document": doc,
            "metadata": metadata,
            "distance": distance,
            "score": similarity
        })

    # --------------------------------------------------
    # 4. Remove duplicate documents
    # --------------------------------------------------

    seen = set()
    unique = []

    for item in candidates:

        metadata = item["metadata"]

        title = metadata.get("title", "").strip().lower()
        url = metadata.get("url", "").strip()

        # Prefer URL as the document identity
        if url:
            key = url
        else:
            key = title

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    # --------------------------------------------------
    # 5. Sort by similarity
    # --------------------------------------------------

    unique.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # --------------------------------------------------
    # 6. Return strongest results
    # --------------------------------------------------

    return unique[:top_k]


if __name__ == "__main__":

    query = input("Ask: ").strip()

    if not query:
        print("Please enter a question.")
        raise SystemExit

    results = search(query)

    print(f"\nFound {len(results)} relevant results.")

    for i, result in enumerate(results, start=1):

        metadata = result["metadata"]

        print(f"\n--- Result {i} ---")

        print(
            "Title:",
            metadata.get("title", "Unknown")
        )

        print(
            "Distance:",
            round(result["distance"], 4)
        )

        print(
            "Score:",
            round(result["score"], 4)
        )

        print(
            "URL:",
            metadata.get("url", "")
        )

        print()

        print(result["document"])