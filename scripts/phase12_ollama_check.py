#!/usr/bin/env python3
"""Phase 12 (C2) - is a REAL local Ollama LLM available? Records the exact state; never installs, downloads or fakes anything.

Checks, in order (a later check is skipped, and recorded as skipped, when an earlier one failed):
  1. ``ollama`` executable on PATH            2. python ``ollama`` package importable (the client ``rag_generate.OllamaClient`` uses)
  3. server answers on 127.0.0.1:11434 (``/api/version``, ``/api/tags``)       4. the configured model (``rag_core.LLM_MODEL_NAME``) is pulled
  5. a real one-token generation round trip with the project's options.
``ready`` is true only if all five pass. Host resources are recorded because they decide whether a 3B model is usable at all.

    python scripts/phase12_ollama_check.py            # writes data/phase12/ollama_environment.json, exit code 0 = ready, 3 = not ready

HTTP is a raw socket to the loopback address only (the repository forbids general HTTP clients outside ``page_fetch``; nothing here leaves the machine).
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "phase12" / "ollama_environment.json"
HOST, PORT = "127.0.0.1", 11434

HttpGet = Callable[[str, float], Tuple[Optional[int], str, Optional[str]]]     # path, timeout -> (status, body, error)


def loopback_get(path: str, timeout: float = 3.0) -> Tuple[Optional[int], str, Optional[str]]:
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(f"GET {path} HTTP/1.0\r\nHost: {HOST}:{PORT}\r\nConnection: close\r\n\r\n".encode())
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        status = int(head.split(b" ", 2)[1]) if head.startswith(b"HTTP/") else None
        return status, body.decode("utf-8", "replace"), None
    except Exception as e:                                                   # noqa: BLE001 - every failure is recorded, none raised
        return None, "", f"{type(e).__name__}: {e}"[:200]


def host_resources() -> Dict[str, Any]:
    out: Dict[str, Any] = {"platform": platform.platform(), "cpu_count": os.cpu_count()}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                out["ram_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        out["ram_gb"] = None
    out["free_disk_gb"] = round(shutil.disk_usage(str(ROOT)).free / 1e9, 1)
    return out


def check(model: Optional[str] = None, which: Callable[[str], Optional[str]] = shutil.which, http_get: HttpGet = loopback_get,
          import_ollama: Optional[Callable[[], Any]] = None, generate: Optional[Callable[[str], str]] = None, now: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")) -> Dict[str, Any]:
    import rag_core
    model = model or rag_core.LLM_MODEL_NAME
    rec: Dict[str, Any] = {"schema_version": 1, "checked_at": now(), "configured_model": model, "options": dict(rag_core.LLM_OPTIONS), "host": host_resources(), "checks": {}}
    checks = rec["checks"]
    blockers = []

    exe = which("ollama")
    checks["executable"] = {"ok": bool(exe), "path": exe}
    if not exe:
        blockers.append("NO_OLLAMA_EXECUTABLE")

    def _imp():
        import ollama  # noqa: F401
        return ollama
    try:
        mod = (import_ollama or _imp)()
        checks["python_package"] = {"ok": True, "version": getattr(mod, "__version__", None)}
    except Exception as e:                                                    # noqa: BLE001
        checks["python_package"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
        blockers.append("NO_PYTHON_OLLAMA_PACKAGE")

    status, body, err = http_get("/api/version", 3.0)
    server_ok = status == 200
    version = None
    if server_ok:
        try:
            version = json.loads(body).get("version")
        except ValueError:
            version = None
    checks["server"] = {"ok": server_ok, "host": f"{HOST}:{PORT}", "http_status": status, "error": err, "version": version}
    if not server_ok:
        blockers.append("OLLAMA_SERVER_NOT_RESPONDING")

    models, model_ok = [], False
    if server_ok:
        status, body, err = http_get("/api/tags", 5.0)
        try:
            models = [m.get("name") or m.get("model") for m in (json.loads(body).get("models") or [])] if status == 200 else []
        except ValueError:
            models = []
        model_ok = any(m == model or (m or "").split(":")[0] == model and ":" not in model for m in models)
        checks["model"] = {"ok": model_ok, "configured": model, "available": models, "http_status": status, "error": err}
        if not model_ok:
            blockers.append("CONFIGURED_MODEL_NOT_PULLED")
    else:
        checks["model"] = {"ok": False, "skipped": "server not responding", "configured": model}

    if checks["python_package"]["ok"] and server_ok and model_ok:
        try:
            if generate is None:
                from rag_generate import OllamaClient
                client = OllamaClient(model=model, options={**rag_core.LLM_OPTIONS, "num_predict": 1})
                generate = client.generate
            text = generate("Reply with one word: ok")
            checks["generation"] = {"ok": bool(str(text).strip()), "sample_chars": len(str(text))}
            if not checks["generation"]["ok"]:
                blockers.append("GENERATION_ROUND_TRIP_FAILED")
        except Exception as e:                                                # noqa: BLE001
            checks["generation"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
            blockers.append("GENERATION_ROUND_TRIP_FAILED")
    else:
        checks["generation"] = {"ok": False, "skipped": "an earlier check failed"}
    rec["blockers"] = blockers
    rec["ready"] = all(c.get("ok") for c in checks.values())
    rec["statement"] = ("REAL Ollama is available: the ollama configurations of evaluate_phase12.py may be run." if rec["ready"] else
                        "REAL Ollama is NOT available in this environment: no LLM result exists; the ollama configurations are BLOCKED, never replaced by the extractive generator.")
    return rec


def main(argv: Optional[list] = None) -> int:
    rec = check()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ready": rec["ready"], "blockers": rec["blockers"]}))
    return 0 if rec["ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
