#!/usr/bin/env python3
"""Phase 8 - command-line entry point of the card-first grounded RAG pipeline (``scripts/rag_pipeline.py``).

    python scripts/rag_answer.py --question "How do I create an installment plan?" --generator extractive
    python scripts/rag_answer.py --question "..." --json            # the full structured answer contract
    python scripts/rag_answer.py --question "..." --debug --json    # + routing, identity, gates, retrieval, context, prompt, grounding
    python scripts/rag_answer.py --generator ollama                 # interactive; needs a local Ollama server with the model of rag_core

``--generator ollama`` (default) is the production design: a LOCAL model (``rag_core.LLM_MODEL_NAME``) through the Ollama client. If Ollama or the
model is missing the command fails with a clear message; it never silently switches to another generator. ``--generator extractive`` is the
deterministic, non-LLM baseline. No network access beyond the local Ollama server is ever attempted. ``rag_chat.py`` and ``rag_modes.py`` are
untouched; this is a separate entry point.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXIT_WORDS = {"exit", "quit"}


def main(argv: Optional[Sequence[str]] = None, pipeline=None) -> int:
    ap = argparse.ArgumentParser(description="Card-first grounded RAG over the ingested SAP Help pages.")
    ap.add_argument("--question", "-q")
    ap.add_argument("--generator", choices=("ollama", "extractive"), default="ollama")
    ap.add_argument("--json", action="store_true", help="print the structured answer")
    ap.add_argument("--debug", action="store_true", help="include the debug block")
    a = ap.parse_args(argv)
    try:
        if pipeline is None:
            import rag_pipeline as RP
            pipeline = RP.build_pipeline(generator=a.generator)
    except Exception as e:                                           # noqa: BLE001
        print(f"cannot start the pipeline: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    import rag_pipeline as RP

    def one(q: str) -> int:
        try:
            ans = pipeline.answer(q, debug=a.debug)
        except Exception as e:                                       # noqa: BLE001 - e.g. Ollama not running; reported, never replaced by another generator
            print(f"generation failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 3
        print(json.dumps(ans, indent=2, ensure_ascii=False) if a.json else RP.format_answer(ans))
        return 0

    if a.question is not None:
        return one(a.question)
    rc = 0
    while True:
        try:
            q = input("\nQuestion (exit to quit): ").strip()
        except EOFError:
            return rc
        if q.lower() in EXIT_WORDS:
            return rc
        if q:
            rc = one(q) or rc


if __name__ == "__main__":
    raise SystemExit(main())
