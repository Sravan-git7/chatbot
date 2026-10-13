#!/usr/bin/env python3
"""Versioned LF writer adapter around the sealed Phase-3 chunk algorithm.

The pinned producer is unmodified. This command writes ONLY to a new scratch
output directory and can reproduce the three committed JSON hashes on Windows.
It does not replace/rebaseline the frozen producer's legacy tests. Adopting it in
that checkpoint requires a separately reviewed migration.
"""
import argparse
from pathlib import Path
import build_chunk_candidates as sealed


class LFPath(type(Path())):
    def write_text(self, data, encoding=None, errors=None, newline=None):
        if newline not in (None, "\n"):
            raise ValueError("Portable artifacts require LF")
        # Explicit bytes bypass native Windows text-mode newline translation.
        self.write_bytes(data.encode(encoding or "utf-8", errors or "strict"))
        return len(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    out = a.out_dir.resolve()
    if out.exists():
        ap.error("Use a NEW scratch directory; existing output is never overwritten")
    if out == sealed.ROOT.resolve() or (sealed.ROOT / "data").resolve() in out.parents:
        ap.error("Output cannot be inside repository data/; preserve historical artifacts")
    rc, _ = sealed.run(sealed.ROOT / "data/source_corpus.json", sealed.ROOT,
                       LFPath(out), sealed.DEFAULT_MAX_CHARS, sealed.DEFAULT_SMALL_CHARS,
                       sealed.DEFAULT_LARGE_CHARS, None)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
