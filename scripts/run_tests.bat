@echo off
REM QTS Trading System -- Run Tests
setlocal
cd /d "%~dp0.."

if not exist .venv\Scripts\python.exe (
  echo ERROR: .venv not found. Run scripts\setup_windows.bat first.
  pause
  exit /b 1
)

echo === QTS -- Running Tests ===
.venv\Scripts\python.exe -m pytest tests -q
if errorlevel 1 (
  echo Tests FAILED -- see output above
  pause
  exit /b 1
)
echo Tests PASSED
pause
endlocal
