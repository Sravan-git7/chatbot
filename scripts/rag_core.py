"""Shared retrieval + generation core for the SAP RAG chatbot.

Before this module existed, ``retrieve.py``, ``rag_chat.py`` and
``evaluate_retrieval.py`` each carried their own copy of the retrieval logic
(and each loaded the embedding model and ChromaDB at import time), and the
three copies behaved differently.  Everything now lives here so that

* the chatbot, the retrieval CLI and the evaluation script test the *same*
  code, and
* several retrieval strategies can be compared side by side
  (``python scripts/evaluate_retrieval.py --strategy ...``).

Strategies
----------
``baseline``  Raw dense top-k straight from ChromaDB - no filtering, no
              reranking, no deduplication.  This is what the original
              ``evaluate_retrieval.py`` measured (Top-1/3/5 = 88/96/100 %).
``current``   The pipeline the chatbot used before this change: distance
              filter -> lexical rerank -> one chunk per *URL*.
``improved``  ``current`` + one chunk per *document content*.  SAP's TOC
              re-uses six topics under a second parent with a ``-NN.html`` URL,
              so URL-based dedup lets identical pages through as "different"
              sources.  Also uses a deterministic tie-break.

A note on distances
-------------------
The ``sap_docs`` collection was created without ``hnsw:space`` so ChromaDB
uses its default, **squared L2**.  Embeddings are unit-length, so
``distance = 2 - 2 * cosine_similarity`` and ranges over [0, 4].  It is *not*
a cosine distance, and ``1 - distance`` is *not* a similarity.  Use
:func:`distance_to_cosine` when a real cosine similarity is needed.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

# ============================================================
# Configuration
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "chroma_db"
COLLECTION_NAME = "sap_docs"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

LLM_MODEL_NAME = "llama3.2:3b"
# Deterministic generation makes the answer-quality evaluation repeatable and
# reduces creative drift away from the supplied context.
LLM_OPTIONS = {"temperature": 0, "seed": 42}

CANDIDATE_K = 10
TOP_K = 3  # chunks passed to the LLM

# Maximum allowed (squared-L2) distance; 1.0 <=> cosine similarity >= 0.5.
MAX_DISTANCE = 1.0

NO_ANSWER_MESSAGE = (
    "I couldn't find this information in the provided SAP documentation."
)

DEFAULT_STRATEGY = "improved"

# ============================================================
# Lazy singletons (model / database are loaded once, on first use)
# ============================================================


@lru_cache(maxsize=1)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


@lru_cache(maxsize=1)
def get_collection():
    import chromadb

    if not DB_DIR.exists():
        raise FileNotFoundError(
            f"ChromaDB directory not found: {DB_DIR}\n"
            "Build it first with: python scripts/create_embeddings.py"
        )

    client = chromadb.PersistentClient(path=str(DB_DIR))

    try:
        return client.get_collection(COLLECTION_NAME)
    except Exception as exc:  # chromadb raises different types per version
        raise RuntimeError(
            f"Collection '{COLLECTION_NAME}' not found in {DB_DIR}. "
            "Rebuild it with: python scripts/create_embeddings.py"
        ) from exc


# ============================================================
# Small helpers
# ============================================================


def distance_to_cosine(distance: float) -> float:
    """Convert ChromaDB squared-L2 distance (unit vectors) to cosine similarity."""
    return 1.0 - distance / 2.0


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_STOP_WORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "for", "how",
    "does", "do", "can", "and", "or", "with", "on", "from",
}


def get_query_terms(query: str) -> set[str]:
    return {
        word
        for word in normalize_text(query).split()
        if word not in _STOP_WORDS and len(word) > 2
    }


def _chunk_index(chunk_id: str) -> int:
    """'chunk_17' -> 17 (falls back to 0 for unexpected ids)."""
    try:
        return int(chunk_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


@lru_cache(maxsize=1)
def _document_fingerprints() -> dict[str, str]:
    """Map each source URL to a hash of the page's full chunk text.

    Two URLs with the same fingerprint are the same page reached through
    different TOC entries.  Computed from the database itself, so the dataset
    and the stored metadata stay untouched.
    """
    data = get_collection().get(include=["documents", "metadatas"])

    pages: dict[str, list[tuple[int, str]]] = {}
    for chunk_id, doc, meta in zip(
        data["ids"], data["documents"], data["metadatas"]
    ):
        pages.setdefault(meta.get("url", ""), []).append(
            (_chunk_index(chunk_id), doc)
        )

    return {
        url: hashlib.sha1(
            "\n".join(doc for _, doc in sorted(parts)).encode("utf-8")
        ).hexdigest()
        for url, parts in pages.items()
    }


def source_key(metadata: dict, mode: str) -> str:
    """Identity used for 'one chunk per source' deduplication."""
    url = metadata.get("url", "")
    title = metadata.get("title", "").strip().lower()

    if mode == "content":
        fingerprint = _document_fingerprints().get(url)
        if fingerprint:
            return fingerprint

    return url or title


# ============================================================
# Retrieval
# ============================================================


def _query_candidates(question: str, n_results: int) -> list[dict]:
    embedding = get_embedding_model().encode(
        [question], normalize_embeddings=True
    ).tolist()

    raw = get_collection().query(
        query_embeddings=embedding,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    return [
        {
            "document": doc,
            "metadata": metadata,
            "distance": distance,
            "cosine": distance_to_cosine(distance),
        }
        for doc, metadata, distance in zip(
            raw["documents"][0], raw["metadatas"][0], raw["distances"][0]
        )
    ]


def rerank_candidates(question: str, candidates: list[dict]) -> list[dict]:
    """Lightweight lexical rerank (unchanged from the original rag_chat.py).

    final = 0.60 * semantic + 0.30 * title-term overlap + 0.10 * body-term overlap

    ``semantic_score`` is ``1 - squared_L2_distance``.  After the
    ``MAX_DISTANCE`` filter this lies in [0, 1] and equals ``2*cos - 1``: a
    monotonic rescale of cosine similarity, not cosine itself.
    """
    query_terms = get_query_terms(question)

    for item in candidates:
        title_words = set(normalize_text(item["metadata"].get("title", "")).split())
        doc_words = set(normalize_text(item["document"]).split())

        semantic = max(0.0, 1.0 - item["distance"])

        if query_terms:
            title_score = sum(t in title_words for t in query_terms) / len(query_terms)
            keyword_score = sum(t in doc_words for t in query_terms) / len(query_terms)
        else:
            title_score = keyword_score = 0.0

        item["semantic_score"] = semantic
        item["title_score"] = title_score
        item["keyword_score"] = keyword_score
        item["final_score"] = (
            0.60 * semantic + 0.30 * title_score + 0.10 * keyword_score
        )

    return candidates


def search_baseline(question: str, top_k: int = 5, **_) -> list[dict]:
    """Raw dense top-k. No filtering, reranking or deduplication."""
    question = question.strip()
    if not question:
        return []

    results = _query_candidates(question, top_k)
    for item in results:
        item["final_score"] = item["cosine"]
    return results


def _search_pipeline(
    question: str,
    top_k: int,
    candidate_k: int,
    max_distance: float,
    dedup: str,
) -> list[dict]:
    question = question.strip()
    if not question:
        return []

    candidates = [
        c
        for c in _query_candidates(question, candidate_k)
        if c["distance"] <= max_distance
    ]

    rerank_candidates(question, candidates)

    if dedup == "content":
        # Rounding + URL/text tie-break: identical duplicate pages score the
        # same (up to float noise), so pick the same one every time and prefer
        # the primary URL (no "-NN.html" suffix).
        candidates.sort(
            key=lambda x: (
                -round(x["final_score"], 5),
                len(x["metadata"].get("url", "")),
                x["metadata"].get("url", ""),
            )
        )
    else:
        candidates.sort(key=lambda x: x["final_score"], reverse=True)

    seen: set[str] = set()
    final: list[dict] = []

    for item in candidates:
        key = source_key(item["metadata"], dedup)
        if key in seen:
            continue
        seen.add(key)
        final.append(item)
        if len(final) >= top_k:
            break

    return final


def search_current(
    question: str,
    top_k: int = TOP_K,
    candidate_k: int = CANDIDATE_K,
    max_distance: float = MAX_DISTANCE,
) -> list[dict]:
    """Pipeline as it behaved in rag_chat.py before this change."""
    return _search_pipeline(question, top_k, candidate_k, max_distance, "url")


def search_improved(
    question: str,
    top_k: int = TOP_K,
    candidate_k: int = CANDIDATE_K,
    max_distance: float = MAX_DISTANCE,
) -> list[dict]:
    """``current`` + content-level source deduplication."""
    return _search_pipeline(question, top_k, candidate_k, max_distance, "content")


STRATEGIES = {
    "baseline": search_baseline,
    "current": search_current,
    "improved": search_improved,
}


def search(question: str, top_k: int = TOP_K, strategy: str = DEFAULT_STRATEGY):
    try:
        fn = STRATEGIES[strategy]
    except KeyError:
        raise ValueError(
            f"Unknown strategy '{strategy}'. Choose from: {', '.join(STRATEGIES)}"
        ) from None
    return fn(question, top_k=top_k)


# ============================================================
# Generation
# ============================================================

PROMPT_TEMPLATE = """
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


def build_context(results: list[dict]) -> str:
    parts = []
    for i, result in enumerate(results, start=1):
        metadata = result["metadata"]
        parts.append(
            f"""
SOURCE {i}

Title: {metadata.get("title", "Unknown")}
URL: {metadata.get("url", "")}

Content:
{result["document"]}
"""
        )
    return "\n".join(parts)


def build_prompt(question: str, results: list[dict]) -> str:
    return PROMPT_TEMPLATE.format(
        context=build_context(results), question=question
    )


def generate_answer(
    question: str,
    strategy: str = DEFAULT_STRATEGY,
    model: str = LLM_MODEL_NAME,
) -> tuple[str, list[dict]]:
    """Retrieve context and ask the local Ollama model.

    Returns ``(answer, results)``.  If no chunk passes the distance filter the
    fixed refusal message is returned without calling the LLM.
    """
    results = search(question, top_k=TOP_K, strategy=strategy)

    if not results:
        return NO_ANSWER_MESSAGE, []

    import ollama

    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": build_prompt(question, results)}],
        options=LLM_OPTIONS,
    )

    return response["message"]["content"], results
