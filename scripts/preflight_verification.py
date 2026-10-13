#!/usr/bin/env python3
"""Offline resource preflight; never installs/downloads anything or changes a store."""
import json
import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    result = {"python": sys.version.split()[0], "packages": {}, "errors": [], "warnings": []}
    for package in ("chromadb", "sentence-transformers", "fastapi", "uvicorn", "pydantic", "httpx", "pytest", "lxml", "numpy"):
        try:
            result["packages"][package] = version(package)
        except PackageNotFoundError:
            result["errors"].append(f"Missing {package}; install requirements-verification.txt in the selected venv.")
    try:
        from m2c_common import resolve_model
        _, info = resolve_model()
        result["embedding_model"] = {"model": info["model_name"], "origin": info["origin"],
                                      "files_sha256": info["files_sha256"]}
    except Exception as exc:
        result["errors"].append(str(exc))
    for name in ("data/vector_store/chroma.sqlite3", "data/vector_store/page_collection/chroma.sqlite3"):
        if not (ROOT / name).is_file():
            result["errors"].append(f"Missing {name}; build stores with --manifest directed to a scratch directory (see LOCAL_PRODUCTION_VERIFICATION.md).")
    if sys.version_info[:2] == (3, 10):
        result["warnings"].append("Python 3.10 can use ranged prerequisites, but the verified Linux closure is Python 3.11. Do not install requirements.lock.txt here.")
    if sys.platform == "win32":
        result["warnings"].append("Native Windows sealed chunk generation may produce CRLF. Do not skip its byte-equivalence tests; see the documented pending gate.")
    print(json.dumps(result, indent=2))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
