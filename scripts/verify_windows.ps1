param(
    [string]$Python = ".\av\Scripts\python.exe",
    [switch]$InstallPrerequisites,
    [switch]$BuildMissingStores,
    [switch]$Ollama
)
# Run from the safely updated checkout. Never modifies git history, deletes caches,
# replaces a venv, rewrites provenance manifests, or deploys publicly.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE): $Arguments" }
}
if (-not (Test-Path $Python)) { throw "Selected venv missing: $Python. Preserve av; create a separate Python 3.11 venv with py -3.11 -m venv .venv, then pass -Python .\.venv\Scripts\python.exe." }
$Python = (Resolve-Path $Python).Path
$Commit = (git rev-parse HEAD).Trim()
$Results = Join-Path $env:TEMP ("SURA-verification-" + $Commit.Substring(0,7) + "-" + (Get-Date -Format yyyyMMddHHmmss))
New-Item -ItemType Directory -Path $Results | Out-Null
Write-Host "Commit: $Commit; results: $Results; no public deployment."
Run $Python @("scripts/refresh_checkout_bytes.py", "--apply")
if ($InstallPrerequisites) {
    # Existing packages satisfying constraints are not reinstalled. On Python 3.10,
    # use this ranged list, NOT the Linux 3.11 closure. No generative model is pulled.
    Run $Python @("-m", "pip", "install", "-r", "requirements-verification.txt")
}
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:RAG_ENABLE_DEBUG = "0"
$env:SURA_LOG_QUERIES = "0"
$env:RAG_GENERATOR = "extractive"
$env:SURA_OLLAMA_TIMEOUT_SECONDS = "60"
$env:SURA_QUEUE_TIMEOUT_SECONDS = "30"
# M2C_MODEL_DIR is optional; preserve an operator-supplied approved model directory.
# With it unset, the pinned wheel is discovered without a personal cache path.
$env:SURA_PYTHON = $Python
if ($BuildMissingStores) {
    if (-not (Test-Path "data/vector_store/chroma.sqlite3")) {
        Run $Python @("scripts/build_card_collection.py", "--manifest", (Join-Path $Results "card_build.json"))
    }
    if (-not (Test-Path "data/vector_store/page_collection/chroma.sqlite3")) {
        Run $Python @("scripts/build_page_collection.py", "--manifest", (Join-Path $Results "page_build.json"))
    }
}
Run $Python @("scripts/preflight_verification.py")
Run $Python @("-m", "pip", "check")
Push-Location web
try {
    Run "npm.cmd" @("ci", "--no-audit", "--no-fund")
    Run "npm.cmd" @("run", "typecheck")
    Run "npm.cmd" @("test")
    Run "npm.cmd" @("run", "build")
} finally { Pop-Location }
Run $Python @("scripts/frontend_live_verification.py")
Run $Python @("scripts/live_smoke.py", "--out", (Join-Path $Results "live_smoke.json"))
Run $Python @("benchmarks/run_benchmark.py", "--mode", "stages", "--repeat", "100", "--strict", "--out", (Join-Path $Results "stages.json"))
Run $Python @("benchmarks/run_benchmark.py", "--mode", "e2e", "--spawn", "8300", "--repeat", "100", "--concurrency-requests", "200", "--concurrency-levels", "1,4,5,10,20", "--strict", "--out", (Join-Path $Results "e2e.json"))
Run $Python @("benchmarks/run_quality.py", "--source-commit", $Commit, "--out", (Join-Path $Results "quality.json"))
Run $Python @("eval/phase3/runner.py", "--adapter", "A0", "--out", (Join-Path $Results "phase3_a0.json"))
if ($Ollama) {
    # Uses your available configured model; never ollama pull. Reports BLOCKED if unavailable.
    Run $Python @("scripts/live_smoke.py", "--generator", "ollama", "--out", (Join-Path $Results "ollama_smoke.json"))
    Run $Python @("benchmarks/run_benchmark.py", "--mode", "stages", "--generator", "ollama", "--repeat", "100", "--out", (Join-Path $Results "ollama_stages.json"))
    Run $Python @("benchmarks/run_benchmark.py", "--mode", "e2e", "--generator", "ollama", "--spawn", "8301", "--repeat", "100", "--concurrency-levels", "1,5,10,20", "--concurrency-requests", "100", "--out", (Join-Path $Results "ollama_e2e.json"))
}
# Browser smoke creates new results, never overwrites historical Playwright artifacts.
& node "web/e2e/predeployment_smoke.mjs" --out (Join-Path $Results "browser.json")
if ($LASTEXITCODE -eq 2) { Write-Warning "Browser binaries unavailable: E2E BLOCKED (not a pass)." }
elseif ($LASTEXITCODE -ne 0) { throw "Browser E2E failed." }
# Full suite last so test failure does not prevent evidence/benchmark collection.
# Native Windows sealed-artifact failures must be fixed/approved, NOT skipped.
& $Python -m pytest tests/ -q -ra
$SuiteExit = $LASTEXITCODE
Write-Host "Saved results: $Results; backend suite exit: $SuiteExit"
if ($SuiteExit -ne 0) { throw "Full suite failed. Preserve output; see the native Windows sealed-writer caveat." }
Write-Host "Local automated verification completed; deployment remains prohibited until the documented release gate is approved."
