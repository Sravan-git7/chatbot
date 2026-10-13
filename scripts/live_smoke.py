#!/usr/bin/env python3
"""Private local HTTP smoke through the documented CLI. Never downloads/deploys anything.
Uses stdlib subprocess and httpx; writes a new result path, never historical outputs.
"""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    import httpx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator", choices=("extractive", "ollama"), default="extractive")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, "scripts/rag_api.py", "--host", "127.0.0.1", "--port", str(port),
                             "--generator", args.generator], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = {"generator": args.generator, "status": "FAIL", "checks": []}
    code = 1
    try:
        with httpx.Client(base_url=base, timeout=90) as client:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("Backend exited before health check")
                try:
                    if client.get("/health", timeout=2).status_code == 200:
                        break
                except httpx.RequestError:
                    time.sleep(0.3)
            else:
                raise TimeoutError("Backend startup deadline expired")
            ready = client.get("/ready")
            result["readiness"] = {"http": ready.status_code, "body": ready.json()}
            if args.generator == "ollama" and ready.status_code == 503:
                # Verify outage behavior, but never count it as a successful real-model round trip.
                outage = client.post("/api/chat", json={"message": "How does billing work in SAP Utilities?"})
                result["outage_response"] = {"http": outage.status_code, "body": outage.json()}
                assert outage.status_code == 502, outage.text
                assert outage.json()["error"]["code"] == "generator_failed"
                result.update(status="BLOCKED", reason="Real Ollama/model unavailable; outage contract verified, inference NOT verified.")
                code = 2
            else:
                assert ready.status_code == 200, ready.text
                checks = [
                    ("billing", "How does billing work in SAP Utilities?", "answered", "smoke-billing"),
                    ("followup", "elaborate", "answered", "smoke-billing"),
                    ("unsupported", "What is the weather in Berlin today?", "out_of_scope", "smoke-other"),
                    ("missing_evidence", "What is the exact license price of transaction code EL31?", "unable_to_verify", "smoke-missing"),
                    ("M2C18", "Tell me about the Contract Account Business Object page.", "documentation_unavailable", "smoke-identity"),
                ]
                for label, message, expected, cid in checks:
                    response = client.post("/api/chat", json={"message": message, "conversation_id": cid})
                    body = response.json()
                    assert response.status_code == 200 and body["status"] == expected, (label, response.text)
                    if expected == "answered":
                        assert body["metadata"]["grounded"] and body["sources"], (label, body)
                    else:
                        assert not body["metadata"]["grounded"] and not body["sources"], (label, body)
                    result["checks"].append({"workflow": label, "http": response.status_code, "status": body["status"],
                                             "sources": body["sources"], "grounded": body["metadata"]["grounded"]})
                for label, content, expected in (("malformed", b'{"message":', 422),
                                                 ("empty", b'{"message":" "}', 422),
                                                 ("oversized", b"x" * 17000, 413)):
                    response = client.post("/api/chat", content=content, headers={"Content-Type": "application/json"})
                    assert response.status_code == expected, response.text
                    assert "error" in response.json()
                    result["checks"].append({"workflow": label, "http": expected, "error": response.json()["error"]["code"]})
                debug = client.post("/api/chat", json={"message": "billing", "debug": True})
                assert debug.status_code == 403
                ui = client.get("/")
                assert ui.status_code == 200 and "text/html" in ui.headers.get("content-type", "")
                assert "frame-ancestors 'none'" in ui.headers.get("content-security-policy", "")
                assert ui.headers.get("x-content-type-options") == "nosniff"
                result["checks"].append({"workflow": "served_ui_security", "http": ui.status_code, "debug_http": debug.status_code})
                result["status"] = "PASS"
                result["real_ollama_round_trip"] = args.generator == "ollama"
                code = 0
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "checks": len(result["checks"]), "reason": result.get("reason")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
