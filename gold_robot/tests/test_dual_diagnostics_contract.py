"""Regression contracts for read-only recovery of native MT5 dual failures.

These are source-level checks, not proof that MT5 compiled or ran successfully.
PowerShell AST syntax checks are executed separately by the Windows CI workflow.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_root_launcher_preserves_child_failure_instead_of_generic_refusal():
    source=(ROOT/"QTS_DUAL_RESEARCH.ps1").read_text(encoding="utf-8")
    assert "$childExitCode=[int]$LASTEXITCODE" in source
    assert "$failedChildState=[string]$childFailure.state" in source
    assert "$failedChildMessage=[string]$childFailure.message" in source
    assert "failed_child_message=$failedChildMessage" in source
    assert "failed_child_exit_code=$failedChildExitCode" in source
    assert "QTS_DUAL_FAILURE_EVIDENCE.zip" in source
    assert "current_source_native_compile_verified_here=$false" in source
    assert "live='LOCKED'" in source

def test_existing_failed_run_can_be_diagnosed_without_running_mt5_again():
    source=(ROOT/"QTS_DUAL_DIAGNOSE.ps1").read_text(encoding="utf-8")
    bat=(ROOT/"QTS_DUAL_DIAGNOSE.bat").read_text(encoding="utf-8")
    assert "QTS_DUAL_RESEARCH_STATUS.json" in source
    assert "'FAILED_NO_GO'" in source
    assert "QTS_DUAL_FAILURE_DIAGNOSTIC.json" in source
    assert "OPEN_RESULTS.json" in source
    assert "QTS_DUAL_FAILURE_EVIDENCE.zip" in source
    assert "broker_orders_sent_by_collector=0" in source
    assert "live='LOCKED'" in source
    assert "QTS_DUAL_DIAGNOSE.ps1" in bat
    forbidden=("QTS_DUAL_RESEARCH.bat","QTS_AUTO_TEST.bat","RunAutomaticTester.ps1",
               "Start-Process -FilePath $exe","order_send","OrderSend(",
               "MetaTrader5.initialize(","MetaEditor","-ResearchVariant")
    assert not any(word in source for word in forbidden)

def test_kit_runs_powershell_ast_check_on_reader_and_includes_both_launchers():
    workflow=(ROOT/".github/workflows/gold-research-kit.yml").read_text(encoding="utf-8")
    assert "QTS_DUAL_DIAGNOSE.bat" in workflow
    assert "QTS_DUAL_DIAGNOSE.ps1" in workflow
    assert "test_dual_diagnostics_contract.py" in workflow
