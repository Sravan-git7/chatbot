#!/usr/bin/env python3
"""Refresh ONLY newline-converted tracked files from HEAD; never reset/clean/stash/delete.

Default is a dry run. --apply writes only files whose content differs solely by CRLF/LF
conversion. Any real edit, staged change, missing file or symlink aborts the entire operation
before any writes. Untracked/ignored files and directories are never enumerated or touched.
"""
from __future__ import annotations
import argparse
import os
import subprocess
from pathlib import Path


def inspect(root: Path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)
    if git("diff", "--cached", "--name-only").strip():
        raise ValueError("Staged changes exist; preserve/commit them before refreshing.")
    paths = git("ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0")
    converted = []
    conflicts = []
    for raw in paths:
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        if not path.is_file() or path.is_symlink():
            conflicts.append(name)
            continue
        stored = git("show", f"HEAD:{name}")
        current = path.read_bytes()
        if stored == current:
            continue
        # No whitespace stripping, encoding rewriting or JSON parsing: only CRLF normalization.
        if b"\0" not in stored and current.replace(b"\r\n", b"\n") == stored.replace(b"\r\n", b"\n"):
            converted.append((path, stored))
        else:
            conflicts.append(name)
    if conflicts:
        raise ValueError("Real edits/missing files exist; nothing written: " + ", ".join(conflicts[:20]))
    return converted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        converted = inspect(root)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(f"{len(converted)} newline-converted tracked files; no real edits detected.")
    for path, stored in converted:
        print(path.relative_to(root))
        if args.apply:
            path.write_bytes(stored)
            if path.read_bytes() != stored:
                raise OSError(f"Byte verification failed: {path}")
    return 0 if args.apply or not converted else 1


if __name__ == "__main__":
    raise SystemExit(main())
