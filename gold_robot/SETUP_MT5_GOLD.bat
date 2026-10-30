@echo off
REM QTS Gold unified Windows MT5 installer. READ ONLY until Strategy Tester.
REM Invoke PowerShell directly instead of chaining nested batch files;
REM the old nested CALL could return "The system cannot find the path specified".
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_SETUP_DIR=%~dp0"
set "QTS_ONE_INSTALL=%QTS_SETUP_DIR%mt5_robot\Install_MT5_Canonical.ps1"
set "QTS_EA_INSTALL=%QTS_SETUP_DIR%mt5_robot\Install_QTS_Gold_Robot.ps1"
set "QTS_BROKER_INSTALL=%QTS_SETUP_DIR%mt5_robot\Install_Broker_Preflight.ps1"
set "QTS_EA_SOURCE=%QTS_SETUP_DIR%mt5_robot\QTS_Gold_Robot.mq5"
set "QTS_POLICY_SOURCE=%QTS_SETUP_DIR%mt5_robot\ExecutionPolicy.mqh"
set "QTS_STRUCTURE_SOURCE=%QTS_SETUP_DIR%mt5_robot\StructureResearch.mqh"
set "QTS_OPPORTUNITY_SOURCE=%QTS_SETUP_DIR%mt5_robot\OpportunityResearch.mqh"
set "QTS_ADAPTIVE_SOURCE=%QTS_SETUP_DIR%mt5_robot\AdaptiveResearch.mqh"
set "QTS_SMC_SOURCE=%QTS_SETUP_DIR%mt5_robot\SmcResearch.mqh"
set "QTS_SCALP_SOURCE=%QTS_SETUP_DIR%mt5_robot\ScalpResearch.mqh"
set "QTS_BROKER_SOURCE=%QTS_SETUP_DIR%research\QTS_Broker_Preflight.mq5"
set "QTS_MANIFEST=%QTS_SETUP_DIR%docs\SOURCE_CHECKSUMS.json"
set "QTS_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
echo.
echo ===========================================================
echo  QTS GOLD - Windows MT5 source installer and broker preflight
echo ===========================================================
echo  WMMarkets XAUUSD@ ^| LIVE LOCKED ^| No automatic orders
echo  Source directory: "%QTS_SETUP_DIR%"
echo.
if not exist "%QTS_ONE_INSTALL%" goto MISSING_ONE_INSTALL
if not exist "%QTS_EA_INSTALL%" goto MISSING_EA_INSTALL
if not exist "%QTS_BROKER_INSTALL%" goto MISSING_BROKER_INSTALL
if not exist "%QTS_EA_SOURCE%" goto MISSING_EA_SOURCE
if not exist "%QTS_SCALP_SOURCE%" goto MISSING_SCALP
if not exist "%QTS_SMC_SOURCE%" goto MISSING_SMC
if not exist "%QTS_ADAPTIVE_SOURCE%" goto MISSING_ADAPTIVE
if not exist "%QTS_OPPORTUNITY_SOURCE%" goto MISSING_OPPORTUNITY
if not exist "%QTS_STRUCTURE_SOURCE%" goto MISSING_STRUCTURE
if not exist "%QTS_POLICY_SOURCE%" goto MISSING_POLICY
if not exist "%QTS_BROKER_SOURCE%" goto MISSING_BROKER_SOURCE
if not exist "%QTS_MANIFEST%" goto MISSING_MANIFEST
if not exist "%QTS_POWERSHELL%" goto MISSING_POWERSHELL

REM CI-only path probe: validates a real cmd.exe invocation with no account access.
if /I "%QTS_SETUP_VALIDATE_ONLY%"=="1" (
  echo QTS_SETUP_PATHS_OK: all required files found; no installer was run.
  exit /b 0
)

echo The same MT5 data folder and compiler will be used for both components.
"%QTS_POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%QTS_ONE_INSTALL%"
set "QTS_RC=%ERRORLEVEL%"
if not "%QTS_RC%"=="0" (
  echo ERROR: Canonical one-target installer failed with exit code %QTS_RC%.
  echo Review the error above; the broker account and Algo Trading are unchanged.
  exit /b %QTS_RC%
)
echo.
echo SUCCESS: EA and broker preflight verified in ONE MT5 terminal.
echo Native compiler evidence is local. This does not validate trading profit.
exit /b 0

:MISSING_ONE_INSTALL
echo ERROR [MISSING_ONE_INSTALL]: "%QTS_ONE_INSTALL%"
goto BAD_PACKAGE
:MISSING_EA_INSTALL
echo ERROR [MISSING_EA_INSTALL]: "%QTS_EA_INSTALL%"
goto BAD_PACKAGE
:MISSING_BROKER_INSTALL
echo ERROR [MISSING_BROKER_INSTALL]: "%QTS_BROKER_INSTALL%"
goto BAD_PACKAGE
:MISSING_POLICY
echo ERROR [MISSING_POLICY]: "%QTS_POLICY_SOURCE%"
goto BAD_PACKAGE
:MISSING_STRUCTURE
echo ERROR [MISSING_STRUCTURE]: "%QTS_STRUCTURE_SOURCE%"
goto BAD_PACKAGE
:MISSING_OPPORTUNITY
echo ERROR [MISSING_OPPORTUNITY]: "%QTS_OPPORTUNITY_SOURCE%"
goto BAD_PACKAGE
:MISSING_ADAPTIVE
echo ERROR [MISSING_ADAPTIVE]: "%QTS_ADAPTIVE_SOURCE%"
goto BAD_PACKAGE
:MISSING_SMC
echo ERROR [MISSING_SMC]: "%QTS_SMC_SOURCE%"
goto BAD_PACKAGE
:MISSING_SCALP
echo ERROR [MISSING_SCALP]: "%QTS_SCALP_SOURCE%"
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
