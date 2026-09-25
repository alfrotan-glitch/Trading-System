# QTS Trading System — Windows Clean-Clone Setup
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
# Requires: Python 3.11-3.14, git, Windows 10/11
#
# This file MUST remain UTF-8 with BOM: Windows PowerShell 5.1 reads BOM-less
# .ps1 files as ANSI (cp1252) and mis-parses the non-ASCII characters below.
# It MUST remain PS 5.1-compatible (no ternary operator, no ?? coalescing).
# Idempotent: safe to re-run; data bootstrap reuses existing usable versions.
$ErrorActionPreference = "Stop"
Write-Host "=== QTS Trading System — Windows Setup ===" -ForegroundColor Cyan

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# --- locate repository root (script may be invoked from anywhere) ---
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host "Repository root: $repoRoot"

# 1. Check Python (3.11 through 3.14). 3.15 is refused.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Fail "Python not found. Install Python 3.11, 3.12, 3.13, or 3.14 from https://www.python.org and add to PATH." }
$pyExe = $py.Source
$ver = & $pyExe --version 2>&1
Write-Host "Found $ver at $pyExe"
& $pyExe -c "import sys; v=sys.version_info; ok=(3,11)<=v[:2]<(3,15); print('Python', v[0], v[1], v[2], 'OK' if ok else 'NOT SUPPORTED'); raise SystemExit(0 if ok else 1)"
if ($LASTEXITCODE -ne 0) { Fail "Python version not supported. Install Python 3.11, 3.12, 3.13, or 3.14. Python 3.15 is not accepted. See docs/desktop_installation_windows.md" }

# 2. Check git (Get-Command is reliable under $ErrorActionPreference=Stop)
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { Fail "git not found. Install git from https://git-scm.com" }

# 3. Create venv (reuse if present — idempotent)
if (-not (Test-Path ".venv")) {
  Write-Host "Creating virtual environment .venv ..."
  & $pyExe -m venv .venv
  if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
} else { Write-Host ".venv already exists — reusing (delete .venv for a fully fresh environment)" }

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { Fail ".venv Scripts python not found at $venvPython" }

# 4. Upgrade pip
Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }

# 5. Install package (editable + dev extras)
Write-Host "Installing QTS (editable) ..."
& $venvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

Write-Host "Installing optional desktop window (pywebview) ..."
& $venvPython -m pip install pywebview
if ($LASTEXITCODE -ne 0) {
  Write-Host "WARNING: pywebview not installed. scripts\run_qts.bat will open the browser instead." -ForegroundColor Yellow
}

# 6. Create required directories
foreach ($d in @("data\raw","data\curated","data\sqlite","data\evidence","logs")) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null; Write-Host "Created $d" }
}

# 7. Create .env.example if missing (informational; QTS reads QTS_ENV from the environment)
if (-not (Test-Path ".env.example")) {
  $envLines = @(
    "# QTS Environment — set QTS_ENV to development/paper/shadow/demo_forward/live",
    "QTS_ENV=development",
    "QTS_MT5_MODE=MOCK"
  )
  Set-Content -Path ".env.example" -Value $envLines -Encoding ASCII
  Write-Host "Created .env.example"
}

# 8. Data bootstrap — deterministic, truthful, idempotent.
#    `qts data bootstrap` verifies a version is USABLE (manifest + curated parquet +
#    readable bars), never trusts a version row alone, ingests the SYNTHETIC fixture
#    with explicit provenance when nothing usable exists, and FAILS (exit 1) rather
#    than fabricating data if the fixture is missing or has zero usable bars.
Write-Host "Bootstrapping data ..."
& $venvPython -m qts data bootstrap
if ($LASTEXITCODE -ne 0) { Fail "data bootstrap failed — no usable dataset could be established (nothing was fabricated). See message above and docs/troubleshooting_windows.md" }

# Synthetic 1m dev CSV (explicitly synthetic, lives in data/raw, never promoted to a version)
if (-not (Test-Path "data\raw\synthetic_XAUUSD_1m.csv")) {
  Write-Host "Generating synthetic 1m dev CSV ..."
  & $venvPython -m qts data synthetic --rows 2000 --out data/raw/synthetic_XAUUSD_1m.csv
  if ($LASTEXITCODE -ne 0) { Fail "synthetic dev CSV generation failed" }
}

# 9. Validate install — CLI must start and report health truthfully
Write-Host "Verifying qts CLI ..."
& $venvPython -m qts --help | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "qts CLI not working" }
& $venvPython -m qts health 2>&1 | Select-Object -First 20
if ($LASTEXITCODE -ne 0) { Fail "qts health check failed" }

# 10. Run full test suite (fail-closed — never print Setup Complete on failure)
Write-Host "Running tests (pytest -q) ..."
& $venvPython -m pytest tests -q --tb=short
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: tests failed (pytest exit $LASTEXITCODE) — see output above. Setup NOT complete." -ForegroundColor Red
  Write-Host "Fix failures and re-run setup_windows.ps1 (idempotent) — see docs/troubleshooting_windows.md" -ForegroundColor Yellow
  exit 1
}
Write-Host "Tests passed" -ForegroundColor Green

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "Second run is idempotent — re-run to verify."
Write-Host "Bootstrap data is SYNTHETIC (fixture, GBM seed=42) — it is NOT real market history"
Write-Host "and never satisfies real-data requirements for demo_forward/live eligibility."
Write-Host "Next steps:"
Write-Host "  1. .\scripts\run_qts.bat    — launch desktop (MOCK, no MT5)"
Write-Host "  2. See docs/desktop_installation_windows.md for MT5 DEMO setup"
Write-Host "  3. docs/mt5_demo_setup.md for demo_forward"
