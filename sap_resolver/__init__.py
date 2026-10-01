"""Multi-guide SAP Help topic manifest, resolver and ingestion planning.

Isolated from the RAG runtime: nothing in here imports or is imported by
retrieve.py / rag_chat.py / rag_core.py, and nothing writes to ChromaDB or to the
legacy ``sap_pages/`` corpus.
"""

__version__ = "0.1.0"
