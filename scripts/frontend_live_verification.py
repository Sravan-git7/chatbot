#!/usr/bin/env python3
"""Run the entire component suite including its real-HTTP UI workflow (jsdom, NOT a browser).
Starts a private local backend at port 8000 and stops it after the tests. Never overwrites
historical reports. Use the current Python venv and the installed web/node_modules.
"""
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = "http://127.0.0.1:8000"
    # Never mistake another server on this port for the server under test.
    import socket
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 8000))
        except OSError:
            print("BLOCKED: port 8000 is already in use; stop the existing local backend first.")
            return 2
    env = dict(os.environ, RAG_ENABLE_DEBUG="0", SURA_LOG_QUERIES="0", RAG_GENERATOR="extractive")
    server = subprocess.Popen([sys.executable, "scripts/rag_api.py", "--host", "127.0.0.1", "--port", "8000",
                               "--generator", "extractive"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if server.poll() is not None:
                print("BLOCKED: backend exited before readiness")
                return 2
            try:
                if httpx.get(base + "/ready", timeout=2).status_code == 200:
                    break
            except httpx.RequestError:
                pass
            time.sleep(0.3)
        else:
            print("BLOCKED: backend readiness deadline expired")
            return 2
        # Native fetch inside the LIVE_BACKEND test calls the real service. Other tests keep their explicit mocks.
        command = ["npm.cmd" if sys.platform == "win32" else "npm", "test"]
        return subprocess.run(command, cwd=ROOT / "web", env=dict(env, LIVE_BACKEND="1"), timeout=180).returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
