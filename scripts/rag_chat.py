import re
import chromadb
from sentence_transformers import SentenceTransformer
import ollama

# ============================================================
# Configuration
# ============================================================

DB_DIR = "chroma_db"
COLLECTION_NAME = "sap_docs"

MODEL_NAME = "llama3.2:3b"

CANDIDATE_K = 10
TOP_K = 3

MAX_DISTANCE = 1.0


# ============================================================
# Load embedding model
# ============================================================

print("Loading embedding model...")

embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


# ============================================================
# Connect to ChromaDB
# ============================================================

client = chromadb.PersistentClient(
    path=DB_DIR
)

collection = client.get_collection(
    name=COLLECTION_NAME
)

print(f"Loaded {collection.count()} chunks.")


# ============================================================
# Text helpers
# ============================================================

def normalize_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_query_terms(query):
    words = normalize_text(query).split()

    # Remove common question words.
    stop_words = {
        "what",
        "is",
        "are",
        "the",
        "a",
        "an",
        "of",
        "in",
        "to",
        "for",
        "how",
        "does",
        "do",
        "can",
        "and",
        "or",
        "with",
        "on",
        "from"
    }

    return {
        word
        for word in words
        if word not in stop_words
        and len(word) > 2
    }


# ============================================================
# Lightweight reranking
# ============================================================

def rerank_candidates(question, candidates):

    query_terms = get_query_terms(question)

    reranked = []

    for item in candidates:

        metadata = item["metadata"]

        title = metadata.get(
            "title",
            ""
        )

        document = item["document"]

        normalized_title = normalize_text(title)
        normalized_document = normalize_text(document)

        # ----------------------------------------------------
        # Semantic similarity
        #
        # Chroma distance is lower when the match is stronger.
        # Convert it into a similarity-style score.
        # ----------------------------------------------------

        semantic_score = max(
            0.0,
            1.0 - item["distance"]
        )

        # ----------------------------------------------------
        # Title matching
        #
        # Questions such as:
        # "What is a contract account?"
        #
        # should strongly favor a document titled:
        # "Contract Account"
        # ----------------------------------------------------

        title_matches = 0

        for term in query_terms:

            if term in normalized_title.split():
                title_matches += 1

        if query_terms:
            title_score = (
                title_matches / len(query_terms)
            )
        else:
            title_score = 0.0

        # ----------------------------------------------------
        # Document keyword matching
        # ----------------------------------------------------

        document_words = set(
            normalized_document.split()
        )

        document_matches = sum(
            1
            for term in query_terms
            if term in document_words
        )

        if query_terms:
            keyword_score = (
                document_matches / len(query_terms)
            )
        else:
            keyword_score = 0.0

        # ----------------------------------------------------
        # Final score
        #
        # Semantic similarity remains the main signal.
        # Title match gets a strong boost because SAP pages
        # often have highly descriptive titles.
        # ----------------------------------------------------

        final_score = (
            0.60 * semantic_score
            + 0.30 * title_score
            + 0.10 * keyword_score
        )

        item["semantic_score"] = semantic_score
        item["title_score"] = title_score
        item["keyword_score"] = keyword_score
        item["final_score"] = final_score

        reranked.append(item)

    # Highest score first.
    reranked.sort(
        key=lambda x: x["final_score"],
        reverse=True
    )

    return reranked


# ============================================================
# Retrieve candidates
# ============================================================

def retrieve(question):

    query_embedding = embedding_model.encode(
        [question],
        normalize_embeddings=True
    ).tolist()

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

    for doc, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):

        if distance > MAX_DISTANCE:
            continue

        candidates.append({
            "document": doc,
            "metadata": metadata,
            "distance": distance
        })

    # --------------------------------------------------------
    # Rerank
    # --------------------------------------------------------

    reranked = rerank_candidates(
        question,
        candidates
    )

    # --------------------------------------------------------
    # Remove duplicate URLs
    # --------------------------------------------------------

    seen = set()
    final_results = []

    for item in reranked:

        metadata = item["metadata"]

        title = metadata.get(
            "title",
            ""
        )

        url = metadata.get(
            "url",
            ""
        )

        source_key = url or title

        if source_key in seen:
            continue

        seen.add(source_key)

        final_results.append(item)

        if len(final_results) >= TOP_K:
            break

    return final_results


# ============================================================
# Generate answer
# ============================================================

def generate_answer(question):

    results = retrieve(question)

    if not results:

        return (
            "I couldn't find this information in the provided "
            "SAP documentation.",
            []
        )

    # --------------------------------------------------------
    # Build context
    # --------------------------------------------------------

    context_parts = []

    for i, result in enumerate(
        results,
        start=1
    ):

        metadata = result["metadata"]

        title = metadata.get(
            "title",
            "Unknown"
        )

        url = metadata.get(
            "url",
            ""
        )

        document = result["document"]

        context_parts.append(
            f"""
SOURCE {i}

Title: {title}
URL: {url}

Content:
{document}
"""
        )

    context = "\n".join(context_parts)

    # --------------------------------------------------------
    # Grounded prompt
    # --------------------------------------------------------

    prompt = f"""
You are an SAP documentation assistant.

Answer the user's question ONLY from the SAP documentation
provided below.

STRICT RULES:

1. Do not use outside knowledge.
2. Do not use your pretrained knowledge.
3. Do not invent missing information.
4. Do not make assumptions that are not supported by the
   documentation.
5. If the documentation does not contain enough information,
   say exactly:

"I couldn't find this information in the provided SAP documentation."

6. Prefer the source that directly answers the question.
7. Use additional sources only when they add information
   necessary to answer the question.
8. Do not mention irrelevant retrieved sources.
9. Keep the answer concise.
10. At the end, mention only the source title(s) actually used.

SAP DOCUMENTATION:

{context}

USER QUESTION:

{question}

ANSWER:
"""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    answer = response["message"]["content"]

    return answer, results


# ============================================================
# Chat loop
# ============================================================

print()
print("SAP RAG Assistant")
print("Type 'exit' to quit.")
print()


while True:

    question = input("You: ").strip()

    if question.lower() in {
        "exit",
        "quit"
    }:
        print("Goodbye!")
        break

    if not question:
        continue

    try:

        answer, results = generate_answer(
            question
        )

        print()
        print("Assistant:")
        print(answer)

        print()
        print("Selected sources:")

        for i, result in enumerate(
            results,
            start=1
        ):

            metadata = result["metadata"]

            print(
                f"{i}. "
                f"{metadata.get('title', 'Unknown')} "
                f"| distance={result['distance']:.4f} "
                f"| final_score={result['final_score']:.4f}"
            )

            url = metadata.get(
                "url",
                ""
            )

            if url:
                print(f"   {url}")

        print()
        print("-" * 70)
        print()

    except Exception as e:

        print()
        print("Error:", e)
        print()