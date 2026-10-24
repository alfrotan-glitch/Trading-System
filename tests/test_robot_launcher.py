"""The one-click Windows robot menu must retain QTS DEMO execution gates."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_robot_operator_menu_is_explicit_demo_only_and_uses_single_backend():
    text = (ROOT / "ROBOT.bat").read_text(encoding="utf-8").lower()
    assert 'call "scripts\\run_qts.bat"' in text
    assert "choice /c 12" in text
    assert "if errorlevel 2 goto demo_robot" in text
    assert 'set /p "ack=' in text
    assert 'if /i not "%ack%"=="demo"' in text
    assert " -m qts demo verify" in text
    assert " -m qts demo run --confirm --risk-ack" in text
    assert text.index(" -m qts demo verify") < text.index(" -m qts demo run")
    assert text.count("if errorlevel 1") >= 2
    assert "no strategy is validated profitable" in text
    for forbidden in (
        "order_send", "demo enable", "demo arm", "qts_mode=",
        "qts_env=demo_execution", "qts_mt5_mode=real",
        "reg add", "setx", "mt5_login=", "git clean", "rmdir /s",
    ):
        assert forbidden not in text


def test_robot_guide_explains_real_execution_boundary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/robot-operator-windows.md").read_text(encoding="utf-8")
    assert "ROBOT.bat" in readme and "ROBOT.bat" in guide
    assert "not a proven" in readme
    assert "LIVE = LOCKED" in guide
    assert "demo verify" in guide and "authorization" in guide.lower()
