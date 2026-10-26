@echo off
REM QTS Gold unified Windows MT5 installer. READ ONLY until Strategy Tester.
REM Invoke PowerShell directly instead of chaining nested batch files;
REM the old nested CALL could return "The system cannot find the path specified".
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_SETUP_DIR=%~dp0"
set "QTS_EA_INSTALL=%QTS_SETUP_DIR%mt5_robot\Install_QTS_Gold_Robot.ps1"
set "QTS_BROKER_INSTALL=%QTS_SETUP_DIR%mt5_robot\Install_Broker_Preflight.ps1"
set "QTS_EA_SOURCE=%QTS_SETUP_DIR%mt5_robot\QTS_Gold_Robot.mq5"
set "QTS_BROKER_SOURCE=%QTS_SETUP_DIR%research\QTS_Broker_Preflight.mq5"
set "QTS_MANIFEST=%QTS_SETUP_DIR%docs\SOURCE_CHECKSUMS.json"
set "QTS_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
echo.
echo ===========================================================
echo  QTS GOLD - Windows MT5 source installer and broker preflight
echo ===========================================================
echo  WMMarkets XAUUSD@ | LIVE LOCKED | No automatic orders
echo  Source directory: "%QTS_SETUP_DIR%"
echo.
if not exist "%QTS_EA_INSTALL%" goto MISSING_EA_INSTALL
if not exist "%QTS_BROKER_INSTALL%" goto MISSING_BROKER_INSTALL
if not exist "%QTS_EA_SOURCE%" goto MISSING_EA_SOURCE
if not exist "%QTS_BROKER_SOURCE%" goto MISSING_BROKER_SOURCE
if not exist "%QTS_MANIFEST%" goto MISSING_MANIFEST
if not exist "%QTS_POWERSHELL%" goto MISSING_POWERSHELL

REM CI-only path probe: validates a real cmd.exe invocation with no account access.
if /I "%QTS_SETUP_VALIDATE_ONLY%"=="1" (
  echo QTS_SETUP_PATHS_OK: all required files found; no installer was run.
  exit /b 0
)

echo STEP 1/2: Install and compile QTS Gold Robot.
echo  Existing EA files are backed up and restored on compile failure.
"%QTS_POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%QTS_EA_INSTALL%"
set "QTS_RC=%ERRORLEVEL%"
if not "%QTS_RC%"=="0" (
  echo.
  echo ERROR: EA installer failed with exit code %QTS_RC%.
  echo Check the PowerShell or MetaEditor error ABOVE.
  echo Broker preflight has NOT been installed by this run.
  exit /b %QTS_RC%
)
echo.
echo STEP 2/2: Install and compile the READ-ONLY broker preflight.
"%QTS_POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%QTS_BROKER_INSTALL%"
set "QTS_RC=%ERRORLEVEL%"
if not "%QTS_RC%"=="0" (
  echo.
  echo ERROR: Broker preflight installer failed with exit code %QTS_RC%.
  echo The EA was compiled, but no broker readiness is verified.
  exit /b %QTS_RC%
)
echo.
echo SUCCESS: QTS source installed for OBSERVATION / STRATEGY TESTER.
echo In WMMarkets MT5 open XAUUSD@.
echo Navigator - Scripts - Refresh - QTS_Broker_Preflight.
echo Run that READ-ONLY script; then select report option 2 in START_HERE.
echo Live new orders remain LOCKED; no profitable edge validated.
exit /b 0

:MISSING_EA_INSTALL
echo ERROR [MISSING_EA_INSTALL]: "%QTS_EA_INSTALL%"
goto BAD_PACKAGE
:MISSING_BROKER_INSTALL
echo ERROR [MISSING_BROKER_INSTALL]: "%QTS_BROKER_INSTALL%"
goto BAD_PACKAGE
:MISSING_EA_SOURCE
echo ERROR [MISSING_EA_SOURCE]: "%QTS_EA_SOURCE%"
goto BAD_PACKAGE
:MISSING_BROKER_SOURCE
echo ERROR [MISSING_BROKER_SOURCE]: "%QTS_BROKER_SOURCE%"
goto BAD_PACKAGE
:MISSING_MANIFEST
echo ERROR [MISSING_MANIFEST]: "%QTS_MANIFEST%"
goto BAD_PACKAGE
:MISSING_POWERSHELL
echo ERROR [NO_WINDOWS_POWERSHELL]: "%QTS_POWERSHELL%"
goto BAD_PACKAGE
:BAD_PACKAGE
echo INSTALL NOT STARTED. The complete main-branch source is required.
echo Nothing was changed in MetaTrader or your broker account.
exit /b 20
