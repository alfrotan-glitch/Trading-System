# QTS Trading System — Windows Clean-Clone Setup
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
# Requires: Python 3.11+, git, Windows 10/11
$ErrorActionPreference = "Stop"
Write-Host "=== QTS Trading System — Windows Setup ===" -ForegroundColor Cyan

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# 1. Check Python (supported 3.11, 3.12, 3.13 — 3.14 not yet verified)
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Fail "Python not found. Install Python 3.11, 3.12, or 3.13 from https://www.python.org and add to PATH." }
$ver = python --version 2>&1
Write-Host "Found $ver at $($py.Source)"
python -c "import sys; major, minor = sys.version_info[:2]; assert (3,11) <= (major, minor) < (3,14), f'Python {major}.{minor} not supported — supported: 3.11, 3.12, 3.13 (3.14 not yet verified)'; print(f'Python {sys.version} OK')"
if ($LASTEXITCODE -ne 0) { Fail "Python version not supported — install Python 3.11, 3.12, or 3.13 (3.14 not yet verified, see docs/desktop_installation_windows.md)" }

# 2. Check git
try { git --version | Out-Null } catch { Fail "git not found. Install git from https://git-scm.com" }

# 3. Create venv
if (-not (Test-Path ".venv")) {
  Write-Host "Creating virtual environment .venv ..."
  python -m venv .venv
  if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
} else { Write-Host ".venv already exists — reusing" }

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { Fail ".venv Scripts python not found" }

# 4. Upgrade pip
Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip

# 5. Install package
Write-Host "Installing QTS (editable) ..."
& $venvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

# 6. Create required directories
foreach ($d in @("data/raw","data/curated","data/sqlite","data/evidence","logs")) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null; Write-Host "Created $d" }
}

# 7. Create default dev config if missing
if (-not (Test-Path "configs/dev.yaml")) { Write-Host "configs/dev.yaml missing — using default" }
if (-not (Test-Path ".env")) {
  @"
# QTS Environment — set QTS_ENV to development/paper/shadow/demo_forward/live
QTS_ENV=development
QTS_MT5_MODE=MOCK
"@ | Out-File -Encoding utf8 ".env.example"
  Write-Host "Created .env.example — copy to .env and edit for demo_forward/live"
}

# 8. Ensure data (ingest fixture if no versions)
Write-Host "Checking data versions ..."
$hasData = & $venvPython -m qts health 2>&1 | Select-String -Pattern "data_versions"
if (-not (Test-Path "data/manifests/manifest_20260916-010-572728d9.json")) {
  if (Test-Path "data/fixtures/XAUUSD_1H_500.csv") {
    Write-Host "Ingesting fixture XAUUSD_1H_500.csv ..."
    & $venvPython -m qts data ingest --path data/fixtures/XAUUSD_1H_500.csv --instrument XAUUSD --timeframe 1H
  }
}
# Also ensure synthetic for 1m if needed
if (-not (Test-Path "data/raw/synthetic_XAUUSD_1m.csv")) {
  Write-Host "Generating synthetic 1m data ..."
  & $venvPython -m qts data synthetic --rows 2000 --out data/raw/synthetic_XAUUSD_1m.csv
}

# 9. Validate install
Write-Host "Verifying qts CLI ..."
& $venvPython -m qts --help | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "qts CLI not working" }
& $venvPython -m qts health 2>&1 | Select-Object -First 20

# 10. Run quick tests (fail-closed — do not print Setup Complete on failure)
Write-Host "Running quick tests (pytest -q) ..."
& $venvPython -m pytest tests -q --tb=short
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: tests failed (pytest exit $LASTEXITCODE) — see output above. Setup NOT complete." -ForegroundColor Red
  Write-Host "Fix failures and re-run setup_windows.ps1 (idempotent) — see docs/troubleshooting_windows.md" -ForegroundColor Yellow
  exit 1
}
Write-Host "Tests passed ($LASTEXITCODE)" -ForegroundColor Green

Write-Host ""
Write-Host "=== Setup Complete ===`nSecond run is idempotent — re-run to verify." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. .\scripts\run_qts.bat    — launch desktop (MOCK, no MT5)"
Write-Host "  2. See docs/desktop_installation_windows.md for MT5 DEMO setup"
Write-Host "  3. docs/mt5_demo_setup.md for demo_forward"
