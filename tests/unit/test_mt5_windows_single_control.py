"""Regression contracts for the canonical Windows MT5 research launchers.

No MT5 connection or broker trade is needed for these static safety checks.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_single_operator_menu_preserves_legacy_diagnostics() -> None:
    menu = (ROOT / "START_HERE.bat").read_text(encoding="utf-8")
    assert "choice /C 1234567" in menu
    assert "QTS_AUTO_TEST.bat\" champions" in menu
    assert "QTS_AUTO_TEST.bat\"" in menu
    assert ":ADVANCED" in menu
    assert "choice /C 123456789A" in menu
    assert ":VERIFY_SETUP" in menu
    assert "QTS_SETUP_VALIDATE_ONLY=1" in menu


def test_research_runner_pins_evidence_to_this_run() -> None:
    script = (ROOT / "QTS_AUTO_TEST.bat").read_text(encoding="utf-8")
    assert "set \"QTS_RUN_DIR=" in script
    assert "-OutputDirectory \"%QTS_RUN_DIR%\"" in script
    assert "if not \"%RC%\"==\"0\" goto RUN_FINISHED" in script
    assert "if exist \"%QTS_RUN_DIR%\" (" in script
    assert "if errorlevel 1" in script
    pack_commands = [
        line for line in script.splitlines()
        if "PackTradeEvidence.ps1" in line and " -File " in line
    ]
    assert len(pack_commands) == 2
    for command in pack_commands:
        assert '-RunDirectory "%QTS_RUN_DIR%" -NoOpen' in command


def test_candidates_are_sandboxed_to_native_tester() -> None:
    script = (ROOT / "QTS_AUTO_TEST.bat").read_text(encoding="utf-8")
    assert "set \"QTS_STYLE_ARGS=-OnlyStyles 1,3\"" in script
    assert "LIVE LOCKED" in script
    assert "RunAutomaticTester.ps1" in script
    assert "EnableDemoForwardOrders=true" not in script
    assert "order_send(" not in script

