# SURA local verification — Windows handoff (no public deployment)

Target checkout: `D:\chatbot-phase12`; release branch: `arena/b450cda2-chatbot`.
The user's existing `av` environment is Python 3.10.11. That Windows machine was **not accessible from Arena**.
These commands are a handoff, not a claim that native Windows/Ollama verification has passed.
Current release decision and evidence: `FINAL_RELEASE_REPORT.md`, `PRE_DEPLOYMENT_AUDIT.md`, `LATENCY_RAG_COMPARISON.md`.

## One compact PowerShell sequence

Run in a normal local PowerShell window (Node 20+ required; Node 22 was measured in Arena).
Use the **verified final commit printed in the release handoff** instead of following an unreviewed future tip.

```powershell
Set-Location D:\chatbot-phase12
# Preserve local tracked AND untracked edits. Ignored av/cache/chroma_db directories remain untouched.
if ((git status --porcelain).Length -gt 0) { git stash push -u -m 'pre-hardening-local-backup' }
git fetch origin
if ((git branch --show-current).Trim() -ne 'arena/b450cda2-chatbot') { throw 'Wrong branch: switch safely to the release branch before continuing.' }
git merge --ff-only origin/arena/b450cda2-chatbot
# Check HEAD against the verified release commit from the handoff before executing new code.
git log -1 --oneline
.\scripts\verify_windows.ps1 -Python .\av\Scripts\python.exe -InstallPrerequisites -BuildMissingStores
```

If fast-forward fails, **stop**: inspect `git log --left-right --oneline HEAD...origin/arena/b450cda2-chatbot` and reconcile without a reset or force push. Keep the stash; do not automatically pop it over tested code. If the checkout is on a different branch, with edits safely preserved use `git switch arena/b450cda2-chatbot` (or `git switch --track origin/arena/b450cda2-chatbot` when no local release branch exists), then fast-forward. The Arena working session itself never switches branches.

The script installs only the required ranged prerequisites (existing satisfied packages are not reinstalled), supplies the same MiniLM embedding weights via `gt-all-minilm-l6-v2==0.1.0`, builds **only missing** stores, directs new manifests/results to a timestamped `%TEMP%\SURA-verification-*` directory, runs preflight, pip consistency, frontend checks/build, the entire component suite including the live-API workflow, HTTP smoke, identical versioned benchmarks, independent quality evaluation, cached Phase 3 A0 evaluation, and the **full** backend suite. It never deletes `chroma_db`, overwrites historical corpus/manifests, pulls a generative model, or publicly deploys anything. It exits nonzero on failures; retain the full output.

A fresh machine needs Python and Node installed first. Do not replace the existing `av` venv. For the measured Python line, create a **separate** environment:

```powershell
py -3.11 -m venv .venv
.\scripts\verify_windows.ps1 -Python .\.venv\Scripts\python.exe -InstallPrerequisites -BuildMissingStores
```

The existing Python 3.10 environment uses `requirements-verification.txt`, **not** `requirements.lock.txt`. The lock is a snapshot of the verified Linux/Python 3.11 closure; Linux-only dependencies have platform markers. Neither a fresh Windows wheel closure nor Python 3.10 byte-identical numerical reproduction has been verified here. On a fresh machine the dependencies include substantial native wheels (especially PyTorch); review their size before installing. No new large generative model is downloaded.

## Embedding provisioning and sealed-byte caveat

The pinned MiniLM wheel resolves its weights without a personal cache path. An operator-provided `M2C_MODEL_DIR` remains supported and is preserved. Runtime never downloads from Hugging Face: absent weights produce an explicit preflight/startup error, not a silent alternate model.

`.gitattributes` disables newline conversion (`* -text`) so pinned files retain exact Git blob bytes on Windows. `refresh_checkout_bytes.py --apply` restores **only** newline-converted tracked files and refuses genuine edits/staged changes before writing; private backups, ignored caches, and untracked files are not touched.

This addresses checkout-induced `test_phase7b.py` hash failures. It **does not** fix Python-generated CRLF from the sealed, checkpoint-pinned `build_chunk_candidates.py` writer. Native Windows `test_chunk_candidates.py` may still fail its byte-reproduction assertion. **Do not skip the test, weaken its assertion, regenerate the checkpoint, or overwrite sealed candidates.** The full suite passes on Linux. Until an approved versioned producer/checkpoint migration exists, exact historical reproduction requires Linux/WSL with the measured dependency line. This native Windows gate is pending, not green.

`chroma_db/` is legacy, ignored and inert in the shipped system; preserve it. Current runtime stores are the separate card/page collections under `data/vector_store/`. No operation above deletes an existing collection. For an intentional rebuild, first back up the complete store outside Git and explicitly approve the rebuild; use scratch `--manifest` outputs.

## Real Ollama (use the model already available, never auto-pull)

After extractive verification, choose the locally installed model name shown by `ollama list`:

```powershell
$env:OLLAMA_MODEL = 'llama3.2:3b' # replace only with your actual installed model
$env:SURA_OLLAMA_TIMEOUT_SECONDS = '60'
.\scripts\verify_windows.ps1 -Python .\av\Scripts\python.exe -Ollama
```

This runs a real round trip and a separately labelled Ollama benchmark. An unreachable server/missing model is **BLOCKED**, not an inference pass. The default HTTP timeout is finite (60 s), FIFO queue wait is bounded (30 s), the UI aborts at 60 s, and request-body reception is bounded (10 s). These are queue/network/client bounds, not a hard kill deadline for arbitrary stuck Python/C++ execution; that reliability limitation remains explicit.

Ollama runs can take a long time: 100 samples per workload item, plus a concurrency sweep. Do not combine Ollama and extractive numbers. The production admission cap is four; generation is serialized. Higher-concurrency 429s must remain in the report. The optional extractive `--admission-cap 20` experiment queues rather than rejects, and is not a recommendation to use that setting for an unmeasured LLM/hardware combination.

## Start backend and frontend for local inspection

After the UI build, the backend serves the frontend itself; no separate Vite server is required:

```powershell
$env:RAG_ENABLE_DEBUG = '0'; $env:SURA_LOG_QUERIES = '0'; $env:RAG_GENERATOR = 'extractive'
.\av\Scripts\python.exe scripts\rag_api.py --host 127.0.0.1 --port 8000 --generator extractive
# Open http://127.0.0.1:8000 locally. Health is /health; traffic readiness is /ready.
```

Check grounded billing/source links, `elaborate` staying on the same topic, topic switching, out-of-scope abstention, missing detail, M2C-18 fail-closed, and failure/recovery. `frontend_live_verification.py` automates the actual HTTP/component flow. `web/e2e/predeployment_smoke.mjs` performs an additional real-browser smoke **only if Chromium binaries already exist**; otherwise its JSON result is BLOCKED. Historical browser reports are never overwritten.

## Compare the same workload

The PowerShell helper uses `benchmarks/workload_v2.json` (SHA-256 in every result), 100 measured samples/item after warmup, and 200 requests at concurrency 1/4/5/10/20. Compare `%TEMP%` results with `benchmarks/results/v2_baseline_*` and `v2_final_*`, not with historical Windows latency. Hardware differs: compare categories, errors/abstentions and source correctness first; do not treat Arena timing as your PC's timing.

For a deliberate queued extractive experiment:

```powershell
.\av\Scripts\python.exe benchmarks\run_benchmark.py --mode e2e --spawn 8300 --workload benchmarks\workload_v2.json --repeat 100 --concurrency-requests 200 --concurrency-levels 1,5,10,20 --admission-cap 20 --strict
```

The harness lifts only its spawned server's per-IP limiter for measurement; production defaults are unchanged. Accepted latency/throughput and 429 rejection latency/counts are separate. `--strict` fails incorrect accepted responses. Results are not a public deployment authorization.
