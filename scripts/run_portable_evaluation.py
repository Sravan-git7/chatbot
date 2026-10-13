#!/usr/bin/env python3
"""Run the sealed Phase-5 evaluator with owned-temp-store lifecycle management.

No scores, labels, precision thresholds or frozen code are changed. Outputs MUST
be directed to scratch by --out. The actual evaluator opens a temporary copy.
"""
import argparse
from pathlib import Path
import sys
import tempfile
from chroma_temp import ChromaTemporaryDirectory


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    import evaluate_phase5 as sealed
    out = args.out.resolve()
    if out.exists() or out == sealed.ROOT.resolve() or (sealed.ROOT / "data").resolve() in out.parents:
        ap.error("Use a new scratch output file outside data/; historical outputs are protected")
    out.parent.mkdir(parents=True, exist_ok=True)
    original = tempfile.TemporaryDirectory
    tempfile.TemporaryDirectory = ChromaTemporaryDirectory
    try:
        sealed.run(sealed.UNITS_PATH, sealed.CORPUS_PATH, sealed.QUERIES,
                   sealed.P4_QUESTIONS, sealed.P4_RESULTS, sealed.VECTOR_DIR, out)
    finally:
        tempfile.TemporaryDirectory = original
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
