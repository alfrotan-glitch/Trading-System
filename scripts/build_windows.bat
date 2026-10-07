@echo off
REM QTS Trading System -- Build Windows EXE (PyInstaller)
REM Requires: .venv with QTS installed, pyinstaller
REM Output: dist\QTS.exe
setlocal
cd /d "%~dp0.."

if not exist .venv\Scripts\python.exe (
  echo ERROR: .venv not found. Run scripts\setup_windows.bat first.
  pause
  exit /b 1
)

echo === QTS -- Building QTS.exe ===

.venv\Scripts\python.exe -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
  echo Installing pyinstaller ...
  .venv\Scripts\python.exe -m pip install pyinstaller
  if errorlevel 1 (
    echo ERROR: pyinstaller install failed
    pause
    exit /b 1
  )
)

REM Verify spec exists
if not exist packaging\qts.spec (
  echo ERROR: packaging\qts.spec not found
  pause
  exit /b 1
)

REM Verify UI assets
if not exist src\qts\desktop\ui\index.html (
  echo ERROR: src\qts\desktop\ui\index.html missing
  pause
  exit /b 1
)

echo Running PyInstaller ...
.venv\Scripts\pyinstaller packaging\qts.spec --clean --noconfirm
if errorlevel 1 (
  echo ERROR: PyInstaller build failed
  pause
  exit /b 1
)

if not exist dist\QTS.exe (
  if not exist dist\QTS\QTS.exe (
    echo ERROR: dist\QTS.exe not found after build. Check dist\
    dir dist 2>&1
    pause
    exit /b 1
  ) else (
    echo Build produced dist\QTS\QTS.exe (onedir mode^)
    echo Verifying CLI...
    dist\QTS\QTS.exe --help >nul 2>&1
    if errorlevel 1 echo WARNING: QTS.exe --help returned nonzero
  )
) else (
  echo Build succeeded: dist\QTS.exe
  echo Verifying health...
  .venv\Scripts\python.exe -m qts health
)

echo.
echo === Build Complete ===
echo Launch with: dist\QTS.exe  or  dist\QTS\QTS.exe
echo Note: First launch may trigger Windows SmartScreen -- allow
pause
endlocal
