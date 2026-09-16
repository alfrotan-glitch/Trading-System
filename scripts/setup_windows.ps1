# QTS Trading System — Windows Clean-Clone Setup
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
# Requires: Python 3.11+, git, Windows 10/11
$ErrorActionPreference = "Stop"
Write-Host "=== QTS Trading System — Windows Setup ===" -ForegroundColor Cyan

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# 1. Check Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Fail "Python not found. Install Python 3.11+ from https://www.python.org and add to PATH." }
$ver = python --version 2>&1
Write-Host "Found $ver at $($py.Source)"
python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'; print(f'Python {sys.version} OK')"

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

# 8. Validate install
Write-Host "Verifying qts CLI ..."
& $venvPython -m qts --help | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "qts CLI not working" }
& $venvPython -m qts health 2>&1 | Select-Object -First 20

# 9. Run quick tests
Write-Host "Running quick tests (pytest -q) ..."
& $venvPython -m pytest tests -q --tb=short

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. .\scripts\run_qts.bat    — launch desktop (MOCK, no MT5)"
Write-Host "  2. See docs/desktop_installation_windows.md for MT5 DEMO setup"
Write-Host "  3. docs/mt5_demo_setup.md for demo_forward"
