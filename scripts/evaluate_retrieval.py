import json
import chromadb
from sentence_transformers import SentenceTransformer

# -----------------------------
# Configuration
# -----------------------------

DB_DIR = "chroma_db"
COLLECTION_NAME = "sap_docs"
EVALUATION_FILE = "data/evaluation_questions.json"

TOP_K_VALUES = [1, 3, 5]

# -----------------------------
# Load models / database
# -----------------------------

print("Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path=DB_DIR)
collection = client.get_collection(COLLECTION_NAME)

with open(EVALUATION_FILE, encoding="utf-8") as f:
    questions = json.load(f)

print(f"Loaded {collection.count()} chunks.")
print(f"Loaded {len(questions)} evaluation questions.")

# -----------------------------
# Retrieval
# -----------------------------

def retrieve(question, top_k=5):

    embedding = model.encode(
        [question],
        normalize_embeddings=True
    ).tolist()

    results = collection.query(
        query_embeddings=embedding,
        n_results=top_k,
        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    return results


# -----------------------------
# Check expected source
# -----------------------------

def is_match(metadata, expected_titles):

    if not expected_titles:
        return False

    title = metadata.get("title", "").strip().lower()

    return any(
        expected.lower() in title
        for expected in expected_titles
    )


# -----------------------------
# Evaluate
# -----------------------------

results = []

for item in questions:

    question = item["question"]
    expected_titles = item["expected_titles"]

    retrieved = retrieve(question, top_k=5)

    metadatas = retrieved["metadatas"][0]
    distances = retrieved["distances"][0]

    ranks = []

    for rank, metadata in enumerate(metadatas, start=1):

        if is_match(metadata, expected_titles):
            ranks.append(rank)

    results.append({
        "id": item["id"],
        "question": question,
        "category": item["category"],
        "expected_titles": expected_titles,
        "retrieved_titles": [
            m.get("title", "")
            for m in metadatas
        ],
        "distances": distances,
        "match_ranks": ranks
    })


# -----------------------------
# Metrics
# -----------------------------

print("\n")
print("=" * 60)
print("RETRIEVAL EVALUATION")
print("=" * 60)

for k in TOP_K_VALUES:

    total = 0
    correct = 0

    for result in results:

        expected = result["expected_titles"]

        # Out-of-domain questions are handled separately.
        if not expected:
            continue

        total += 1

        if any(rank <= k for rank in result["match_ranks"]):
            correct += 1

    if total:
        accuracy = correct / total * 100
        print(
            f"Top-{k}: {correct}/{total} "
            f"({accuracy:.1f}%)"
        )


# -----------------------------
# Category breakdown
# -----------------------------

print("\n")
print("CATEGORY BREAKDOWN")
print("-" * 60)

categories = sorted(
    set(result["category"] for result in results)
)

for category in categories:

    category_results = [
        r for r in results
        if r["category"] == category
    ]

    if category == "out_of_domain":
        continue

    total = len(category_results)

    correct = sum(
        any(rank <= 5 for rank in r["match_ranks"])
        for r in category_results
    )

    accuracy = correct / total * 100 if total else 0

    print(
        f"{category:15} "
        f"{correct}/{total} "
        f"({accuracy:.1f}%)"
    )


# -----------------------------
# Detailed failures
# -----------------------------

print("\n")
print("=" * 60)
print("RETRIEVAL FAILURES")
print("=" * 60)

failures = [
    r for r in results
    if r["expected_titles"]
    and not any(rank <= 5 for rank in r["match_ranks"])
]

if not failures:

    print("No retrieval failures in Top-5.")

else:

    for result in failures:

        print("\nQuestion:")
        print(result["question"])

        print("\nExpected:")
        print(result["expected_titles"])

        print("\nRetrieved:")

        for rank, (title, distance) in enumerate(
            zip(
                result["retrieved_titles"],
                result["distances"]
            ),
            start=1
        ):
            print(
                f"{rank}. {title} "
                f"(distance={distance:.4f})"
            )


# -----------------------------
# Save detailed results
# -----------------------------

with open(
    "data/retrieval_results.json",
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        results,
        f,
        ensure_ascii=False,
        indent=2
    )

print("\nDetailed results saved to:")
print("data/retrieval_results.json")